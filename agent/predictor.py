"""Phase 2 predictor: dry-run by default, with policy audit, requests and action logs."""

from __future__ import annotations

import argparse
import json
import logging
import pickle
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.db import init_db, save_action_log, save_agent_request, save_policy_decision, save_prediction
from agent.device_registry import control_entities, domain_for, get_device, room_for
from agent.feature_engineering import get_context_at, get_feature_columns, get_device_state_at, load_events, make_feature_vector, recent_toggle_count, time_since_last_change
from agent.ha_client import HAClient
from agent.policy import PolicyDecision, PolicyGate
from agent.scenarios import get_scenario, scenario_names

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [predictor] %(message)s", datefmt="%H:%M:%S")

PROJECT_ROOT = Path(__file__).parent.parent
MODEL_PATH = PROJECT_ROOT / "models" / "decision_tree.pkl"
META_PATH = PROJECT_ROOT / "models" / "decision_tree_meta.json"
ACTION_CANDIDATE_THRESHOLD = 0.25


def _now() -> datetime:
    return datetime.now().astimezone()


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def load_model(model_path: Path = MODEL_PATH, meta_path: Path = META_PATH) -> tuple[Any, dict[str, Any]]:
    if not model_path.exists() or not meta_path.exists():
        raise FileNotFoundError(f"Model/meta không tìm thấy. Chạy trainer.py trước: {model_path}, {meta_path}")
    with open(model_path, "rb") as f:
        model = pickle.load(f)
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    log.info("Model loaded trained_at=%s", meta.get("trained_at", "?"))
    return model, meta


def _label_for_class(class_id: int, meta: dict[str, Any]) -> str:
    label = meta.get("id_to_label", {}).get(str(class_id))
    if label is not None:
        return label
    reverse = {int(v): k for k, v in meta.get("label_mapping", {}).items()}
    return reverse.get(class_id, "no_action")


def _prediction_from_proba(model: Any, fv: list[float], meta: dict[str, Any]) -> tuple[str, float, dict[str, float]]:
    proba = list(model.predict_proba([fv])[0])
    classes = list(getattr(model, "classes_", meta.get("classes_", [])))
    labels = [_label_for_class(int(cls), meta) for cls in classes]
    probabilities = {label: float(proba[idx]) for idx, label in enumerate(labels)}
    
    best_idx = max(range(len(proba)), key=lambda idx: proba[idx])
    best_label = labels[best_idx]
    best_conf = float(proba[best_idx])
    
    if best_label == "no_action":
        action_candidates = [(label, probabilities[label]) for label in ("turn_on", "turn_off") if label in probabilities]
        if action_candidates:
            alt_label, alt_conf = max(action_candidates, key=lambda item: item[1])
            if alt_conf >= ACTION_CANDIDATE_THRESHOLD:
                return alt_label, alt_conf, probabilities
    return best_label, best_conf, probabilities


def _policy_context(df: list[dict[str, Any]], entity_id: str, now: datetime) -> dict[str, Any]:
    ctx = get_context_at(df, now)
    ctx.update({
        "prev_state": 1 if get_device_state_at(df, entity_id, now) == "on" else 0,
        "time_since_change_s": min(time_since_last_change(df, entity_id, now), 86400),
        "recent_toggle_count_2min": recent_toggle_count(df, entity_id, now, 2),
        "recent_toggle_count_5min": recent_toggle_count(df, entity_id, now, 5),
    })
    return ctx


def _request_id(now: datetime, prediction_id: int, entity_id: str) -> str:
    clean = entity_id.replace(".", "_")
    return f"req_{now.strftime('%Y%m%d_%H%M%S')}_{prediction_id}_{clean}"


def _request_message(entity_id: str, action: str, confidence: float, decision: PolicyDecision, context: dict[str, Any]) -> str:
    device = get_device(entity_id)
    room = device.room if device else room_for(entity_id) or "unknown"
    action_vi = "bật" if action == "turn_on" else "tắt"
    device_name = device.device_type if device else entity_id
    return (
        f"🤖 Agent request: Bạn có muốn {action_vi} {device_name} ở {room} không? "
        f"Lý do: {decision.reason}, confidence {confidence:.0%}."
    )


def _metadata(entity_id: str, action: str, confidence: float, decision: PolicyDecision, context: dict[str, Any], probabilities: dict[str, float], scenario_name: str | None = None) -> str:
    important_context = {
        "bedroom_temperature": context.get("bedroom_temperature"),
        "bedroom_humidity": context.get("bedroom_humidity"),
        "living_room_temperature": context.get("living_room_temperature"),
        "living_room_humidity": context.get("living_room_humidity"),
        "presence_home": context.get("presence_home"),
        "is_before_arrival_window": context.get("is_before_arrival_window"),
        "is_arrival_overdue": context.get("is_arrival_overdue"),
        "minutes_after_expected_arrival": context.get("minutes_after_expected_arrival"),
    }
    payload = {
        "entity_id": entity_id,
        "action": action,
        "confidence": confidence,
        "reason_code": decision.reason_code,
        "policy_decision": decision.decision,
        "probabilities": probabilities,
        "context": important_context,
    }
    if scenario_name:
        payload["scenario"] = scenario_name
        payload["source"] = "scenario_candidate"
    return _json(payload)


def _save_policy_audit(prediction_id: int, now: datetime, entity_id: str, action: str, confidence: float, decision: PolicyDecision, context: dict[str, Any]) -> int:
    device = get_device(entity_id)
    return save_policy_decision({
        "timestamp": now.isoformat(timespec="seconds"),
        "sim_time": now.isoformat(timespec="seconds"),
        "prediction_id": prediction_id,
        "entity_id": entity_id,
        "requested_action": action,
        "decision": decision.decision,
        "allowed_by_policy": 1 if decision.allowed else 0,
        "reason_code": decision.reason_code,
        "reason": decision.reason,
        "confidence": confidence,
        "control_level": device.control_level if device else None,
        "risk_level": device.risk_level if device else None,
        "room": device.room if device else room_for(entity_id),
        "context_snapshot": _json(context),
    })


def _save_action_log(now: datetime, log_type: str, actor: str, entity_id: str | None, message: str, metadata: str, severity: str = "info") -> int:
    return save_action_log({
        "timestamp": now.isoformat(timespec="seconds"),
        "sim_time": now.isoformat(timespec="seconds"),
        "log_type": log_type,
        "actor": actor,
        "entity_id": entity_id,
        "room": room_for(entity_id) if entity_id else None,
        "message": message,
        "severity": severity,
        "metadata": metadata,
    })


def _maybe_create_request(prediction_id: int, now: datetime, entity_id: str, action: str, confidence: float, decision: PolicyDecision, context: dict[str, Any], metadata: str) -> str | None:
    if decision.decision != "confirm_required":
        return None
    request_id = _request_id(now, prediction_id, entity_id)
    message = _request_message(entity_id, action, confidence, decision, context)
    save_agent_request({
        "request_id": request_id,
        "timestamp": now.isoformat(timespec="seconds"),
        "sim_time": now.isoformat(timespec="seconds"),
        "prediction_id": prediction_id,
        "entity_id": entity_id,
        "requested_action": action,
        "confidence": confidence,
        "reason_code": decision.reason_code,
        "reason": decision.reason,
        "status": "pending",
        "expires_at": (now + timedelta(minutes=30)).isoformat(timespec="seconds"),
    })
    _save_action_log(now, "AGENT_REQUEST", "agent", entity_id, message, metadata)
    return request_id


def _feature_snapshot_for_scenario(scenario: dict[str, Any], decision: PolicyDecision, probabilities: dict[str, float]) -> str:
    return _json({
        "source": "scenario_candidate",
        "scenario": scenario["name"],
        "description": scenario.get("description"),
        "context": scenario["context"],
        "probabilities": probabilities,
        "policy_decision": decision.decision,
        "reason_code": decision.reason_code,
    })


def run_scenario(name: str, dry_run: bool = True) -> None:
    init_db()
    scenario = get_scenario(name)
    now = scenario["sim_time"]
    entity_id = scenario["entity_id"]
    action = scenario["action"]
    confidence = float(scenario["confidence"])
    probabilities = {"no_action": max(0.0, 1.0 - confidence), action: confidence}
    ctx = dict(scenario["context"])
    
    gate = PolicyGate()
    ha = HAClient(dry_run=dry_run)
    decision = gate.evaluate(entity_id, action, confidence, ctx)
    metadata = _metadata(entity_id, action, confidence, decision, ctx, probabilities, scenario_name=name)
    
    print(f"[SCENARIO] {name} source=scenario_candidate")
    print(f"[PREDICT] {entity_id} {action} confidence={confidence:.2f} source=scenario_candidate")
    _save_action_log(now, "AGENT_PREDICT", "agent", entity_id, f"Scenario {name} predicted {action} confidence={confidence:.2f}", metadata)
    
    prediction_id = save_prediction({
        "timestamp": now.isoformat(timespec="seconds"),
        "entity_id": entity_id,
        "predicted_action": action,
        "confidence": confidence,
        "allowed_by_policy": 1 if decision.allowed else 0,
        "policy_decision": decision.decision,
        "executed": 0,
        "reason": decision.reason,
        "reason_code": decision.reason_code,
        "feature_snapshot": _feature_snapshot_for_scenario(scenario, decision, probabilities),
    })
    
    _save_policy_audit(prediction_id, now, entity_id, action, confidence, decision, ctx)
    request_id = _maybe_create_request(prediction_id, now, entity_id, action, confidence, decision, ctx, metadata)
    
    if decision.decision == "allow":
        _save_action_log(now, "POLICY_ALLOW", "policy", entity_id, f"Scenario policy allow {action}: {decision.reason_code}", metadata)
        print(f"[POLICY] allow reason={decision.reason_code}")
        if action != "no_action" and not dry_run:
            ok = ha.call_service(domain_for(entity_id) or entity_id.split(".")[0], action, entity_id)
            _save_action_log(now, "AGENT_ACTION", "agent", entity_id, f"Scenario executed {action}: ok={ok}", metadata, severity="info" if ok else "error")
        elif action != "no_action":
            print(f"[DRY-RUN] would call {(domain_for(entity_id) or entity_id.split('.')[0])}.{action} {entity_id}")
            _save_action_log(now, "AGENT_ACTION", "agent", entity_id, f"Scenario dry-run would execute {action}", metadata)
            
    elif decision.decision == "confirm_required":
        print(f"[POLICY] confirm_required reason={decision.reason_code}")
        print(f"[REQUEST] {request_id} created")
        
    elif decision.reason_code == "ARRIVAL_OVERDUE":
        _save_action_log(now, "ARRIVAL_OVERDUE", "policy", entity_id, decision.reason, metadata, severity="warning")
        print(f"[POLICY] block reason=ARRIVAL_OVERDUE {decision.reason}")
        
    else:
        _save_action_log(now, "POLICY_BLOCKED", "policy", entity_id, f"Scenario policy {decision.decision}: {decision.reason_code} - {decision.reason}", metadata, severity="warning")
        print(f"[POLICY] {decision.decision} reason={decision.reason_code} {decision.reason}")


def run(dry_run: bool = True) -> None:
    init_db()
    model, meta = load_model()
    feat_cols = meta.get("feature_columns", get_feature_columns())
    
    missing = [col for col in feat_cols if col not in get_feature_columns()]
    if missing:
        log.warning("Metadata has unknown feature columns; missing from current feature builder: %s", missing)
        
    entities = [entity for entity in meta.get("entities", control_entities()) if get_device(entity) is not None]
    if not entities:
        entities = control_entities()
        
    ha = HAClient(dry_run=dry_run)
    gate = PolicyGate()
    df = load_events()
    
    if not df:
        log.warning("Không có events trong DB — không thể predict.")
        return
        
    log.info("Predicting for %d entities dry_run=%s", len(entities), dry_run)
    
    for entity_id in entities:
        now = _now()
        fv_dict = make_feature_vector(df, entity_id, now)
        fv = [fv_dict.get(col, 0) for col in feat_cols]
        action, confidence, probabilities = _prediction_from_proba(model, fv, meta)
        ctx = _policy_context(df, entity_id, now)
        decision = gate.evaluate(entity_id, action, confidence, ctx)
        metadata = _metadata(entity_id, action, confidence, decision, ctx, probabilities)
        
        print(f"[PREDICT] {entity_id} {action} confidence={confidence:.2f}")
        _save_action_log(now, "AGENT_PREDICT", "agent", entity_id, f"Model predicted {action} confidence={confidence:.2f}", metadata)
        
        executed = 0
        prediction_id = save_prediction({
            "timestamp": now.isoformat(timespec="seconds"),
            "entity_id": entity_id,
            "predicted_action": action,
            "confidence": confidence,
            "allowed_by_policy": 1 if decision.decision == "allow" else 0,
            "policy_decision": decision.decision,
            "executed": executed,
            "reason": decision.reason,
            "reason_code": decision.reason_code,
            "feature_snapshot": _json({"features": fv_dict, "context": ctx, "probabilities": probabilities}),
        })
        
        _save_policy_audit(prediction_id, now, entity_id, action, confidence, decision, ctx)
        request_id = _maybe_create_request(prediction_id, now, entity_id, action, confidence, decision, ctx, metadata)
        
        if decision.decision == "allow":
            _save_action_log(now, "POLICY_ALLOW", "policy", entity_id, f"Policy allow {action}: {decision.reason_code}", metadata)
            print(f"[POLICY] allow reason={decision.reason_code}")
            
            if action != "no_action" and not dry_run:
                ok = ha.call_service(domain_for(entity_id) or entity_id.split(".")[0], action, entity_id)
                executed = 1 if ok else 0
                _save_action_log(now, "AGENT_ACTION", "agent", entity_id, f"Executed {action} via Home Assistant: ok={ok}", metadata, severity="info" if ok else "error")
            elif action != "no_action":
                print(f"[DRY-RUN] would call {(domain_for(entity_id) or entity_id.split('.')[0])}.{action} {entity_id}")
                _save_action_log(now, "AGENT_ACTION", "agent", entity_id, f"Dry-run would execute {action}", metadata)
                
        elif decision.decision == "confirm_required":
            print(f"[POLICY] confirm_required reason={decision.reason_code}")
            print(f"[REQUEST] {request_id} created")
            
        elif decision.reason_code == "ARRIVAL_OVERDUE":
            _save_action_log(now, "ARRIVAL_OVERDUE", "policy", entity_id, decision.reason, metadata, severity="warning")
            print(f"[POLICY] block reason=ARRIVAL_OVERDUE {decision.reason}")
            
        else:
            log_type = "POLICY_BLOCKED" if decision.decision == "block" else "POLICY_BLOCKED"
            _save_action_log(now, log_type, "policy", entity_id, f"Policy {decision.decision}: {decision.reason_code} - {decision.reason}", metadata, severity="warning" if decision.decision in {"block", "observe_only"} else "info")
            print(f"[POLICY] {decision.decision} reason={decision.reason_code} {decision.reason}")
            
    log.info("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True, help="Chỉ log, không gọi HA thật (mặc định)")
    parser.add_argument("--live", action="store_true", default=False, help="Gọi HA REST API thật (cần HA_TOKEN)")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--scenario", choices=scenario_names(), default=None, help="Run deterministic Phase 2.5 scenario candidate instead of model inference")
    args = parser.parse_args()
    
    dry = not args.live
    if args.scenario:
        run_scenario(args.scenario, dry_run=dry)
    elif args.loop:
        while True:
            run(dry_run=dry)
            print(f"[predictor] Sleeping {args.interval}s...")
            time.sleep(args.interval)
    else:
        run(dry_run=dry)