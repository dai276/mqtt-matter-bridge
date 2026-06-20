"""FastAPI server for Behavioral Agent Phase 3 laptop simulator."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.db import (
    fetch_agent_request,
    fetch_events,
    fetch_pending_requests,
    fetch_recent_action_logs,
    init_db,
    save_action_log,
    save_agent_request,
    save_event,
    save_policy_decision,
    save_prediction,
    update_agent_request_status,
    utc_now,
)
from agent.device_registry import DEVICES, domain_for, get_device, room_for
from agent.policy import PolicyDecision, PolicyGate
from agent.scenarios import get_scenario, scenario_names

DRY_RUN = True
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SIMULATOR_DIR = PROJECT_ROOT / "simulator"

DEFAULT_SIM_CONTEXT: dict[str, Any] = {
    "sim_time": "2026-06-19T18:30:00+07:00",
    "outdoor_temperature": 35.0,
    "outdoor_humidity": 80.0,
    "living_room_temperature": 31.0,
    "living_room_humidity": 75.0,
    "bedroom_temperature": 29.0,
    "bedroom_humidity": 65.0,
    "presence_home": True,
    "arrival_status": "normal",
    "predicted_arrival_minutes": None,
    "minutes_after_expected_arrival": 0,
}

SIM_CONTEXT: dict[str, Any] = dict(DEFAULT_SIM_CONTEXT)

app = FastAPI(title="Behavioral Agent API", version="3.0.0")

# Demo-only CORS. Keep broad origins for local laptop/Pi demos; restrict in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if SIMULATOR_DIR.exists():
    app.mount("/simulator", StaticFiles(directory=str(SIMULATOR_DIR), html=True), name="simulator")


class SimContextPayload(BaseModel):
    sim_time: str
    outdoor_temperature: float
    outdoor_humidity: float
    living_room_temperature: float
    living_room_humidity: float
    bedroom_temperature: float
    bedroom_humidity: float
    presence_home: bool
    arrival_status: Literal["normal", "pre_arrival", "arrival_overdue"] = "normal"
    predicted_arrival_minutes: int | None = None
    minutes_after_expected_arrival: int = 0


class RespondPayload(BaseModel):
    response: Literal["yes", "no"]


class UserActionPayload(BaseModel):
    entity_id: str
    action: Literal["turn_on", "turn_off", "toggle"] = "toggle"
    source: str = "simulator"
    sim_time: str | None = None


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _latest_device_state(entity_id: str) -> str | None:
    rows = fetch_events(entity_id=entity_id, limit=1)
    if rows:
        return rows[0].get("new_state")
    device = get_device(entity_id)
    if not device:
        return None
    if device.device_type == "temperature":
        if device.room == "living_room":
            return str(SIM_CONTEXT.get("living_room_temperature"))
        if device.room == "bedroom":
            return str(SIM_CONTEXT.get("bedroom_temperature"))
    if device.device_type == "humidity":
        if device.room == "living_room":
            return str(SIM_CONTEXT.get("living_room_humidity"))
        if device.room == "bedroom":
            return str(SIM_CONTEXT.get("bedroom_humidity"))
    if device.control_level in {"auto", "confirm"}:
        return "off"
    return "unknown"


def get_devices_state() -> list[dict[str, Any]]:
    """Return simulator-visible device state without invoking FastAPI endpoints."""
    result = []
    for device in DEVICES:
        result.append({
            "entity_id": device.entity_id,
            "room": device.room,
            "domain": device.domain,
            "device_type": device.device_type,
            "control_level": device.control_level,
            "risk_level": device.risk_level,
            "friendly_name": device.entity_id.replace(".", " ").replace("_", " ").title(),
            "current_state": _latest_device_state(device.entity_id),
        })
    return result


def get_sim_context_state() -> dict[str, Any]:
    """Return current in-memory simulation context without invoking an endpoint."""
    return dict(SIM_CONTEXT)


def get_recent_logs(limit: int = 50) -> list[dict[str, Any]]:
    """Fetch recent action logs with a concrete integer limit for SQLite."""
    return fetch_recent_action_logs(limit=int(limit))


def get_pending_requests(limit: int = 50) -> list[dict[str, Any]]:
    """Fetch pending agent requests with a concrete integer limit for SQLite."""
    return fetch_pending_requests(limit=int(limit))


def _policy_context_from_sim_context(entity_id: str, action: str, sim_context: dict[str, Any]) -> dict[str, Any]:
    arrival_status = sim_context.get("arrival_status", "normal")
    predicted = sim_context.get("predicted_arrival_minutes")
    minutes_after = int(sim_context.get("minutes_after_expected_arrival") or 0)
    lr_temp = float(sim_context.get("living_room_temperature") or 0)
    lr_hum = float(sim_context.get("living_room_humidity") or 0)
    br_temp = float(sim_context.get("bedroom_temperature") or 0)
    br_hum = float(sim_context.get("bedroom_humidity") or 0)
    prev_state = 1 if _latest_device_state(entity_id) == "on" else 0
    return {
        "bedroom_temperature": br_temp,
        "bedroom_humidity": br_hum,
        "living_room_temperature": lr_temp,
        "living_room_humidity": lr_hum,
        "is_hot": 1 if max(lr_temp, br_temp) >= 30 else 0,
        "is_humid": 1 if max(lr_hum, br_hum) >= 70 else 0,
        "is_dry": 1 if min(lr_hum, br_hum) <= 55 else 0,
        "presence_home": 1 if sim_context.get("presence_home") else 0,
        "presence_state": "home" if sim_context.get("presence_home") else "away",
        "door_recently_opened": 1 if sim_context.get("presence_home") else 0,
        "camera_recently_detected": 1 if sim_context.get("presence_home") else 0,
        "predicted_arrival_minutes": predicted if predicted is not None else 999,
        "is_before_arrival_window": 1 if arrival_status == "pre_arrival" and predicted is not None and 10 <= int(predicted) <= 15 else 0,
        "is_arrival_overdue": 1 if arrival_status == "arrival_overdue" or minutes_after >= 20 else 0,
        "minutes_after_expected_arrival": minutes_after,
        "prev_state": prev_state,
        "time_since_change_s": 1800,
        "recent_toggle_count_2min": 0,
        "recent_toggle_count_5min": 0,
    }


def _metadata(entity_id: str, action: str, confidence: float, decision: PolicyDecision, context: dict[str, Any], source: str) -> str:
    return _json({
        "source": source,
        "entity_id": entity_id,
        "action": action,
        "confidence": confidence,
        "policy_decision": decision.decision,
        "reason_code": decision.reason_code,
        "context": context,
    })


def _request_id(sim_time: str, prediction_id: int, entity_id: str) -> str:
    clean_entity = entity_id.replace(".", "_")
    clean_time = _parse_dt(sim_time).strftime("%Y%m%d_%H%M%S")
    return f"req_{clean_time}_{prediction_id}_{clean_entity}"


def _request_message(entity_id: str, action: str, confidence: float, decision: PolicyDecision) -> str:
    device = get_device(entity_id)
    action_vi = "bật" if action == "turn_on" else "tắt"
    name = device.device_type if device else entity_id
    room = device.room if device else room_for(entity_id) or "unknown"
    return f"🤖 Agent request: Bạn có muốn {action_vi} {name} ở {room} không? Lý do: {decision.reason}, confidence {confidence:.0%}."


def _save_log(sim_time: str, log_type: str, actor: str, entity_id: str | None, message: str, metadata: dict[str, Any] | str | None = None, severity: str = "info") -> int:
    if isinstance(metadata, dict):
        metadata = _json(metadata)
    return save_action_log({
        "timestamp": utc_now(),
        "sim_time": sim_time,
        "log_type": log_type,
        "actor": actor,
        "entity_id": entity_id,
        "room": room_for(entity_id) if entity_id else None,
        "message": message,
        "severity": severity,
        "metadata": metadata,
    })


def _run_candidate(
    *,
    entity_id: str,
    action: str,
    confidence: float,
    sim_time: str,
    context: dict[str, Any],
    source: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    gate = PolicyGate()
    decision = gate.evaluate(entity_id, action, confidence, context)
    metadata = _metadata(entity_id, action, confidence, decision, context, source)
    _save_log(sim_time, "AGENT_PREDICT", "agent", entity_id, f"{source} candidate {action} confidence={confidence:.2f}", metadata)
    prediction_id = save_prediction({
        "timestamp": utc_now(),
        "entity_id": entity_id,
        "predicted_action": action,
        "confidence": confidence,
        "allowed_by_policy": 1 if decision.allowed else 0,
        "policy_decision": decision.decision,
        "executed": 0,
        "reason": decision.reason,
        "reason_code": decision.reason_code,
        "feature_snapshot": metadata,
    })
    device = get_device(entity_id)
    save_policy_decision({
        "timestamp": utc_now(),
        "sim_time": sim_time,
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
    request_id = None
    if decision.decision == "confirm_required":
        request_id = _request_id(sim_time, prediction_id, entity_id)
        message = _request_message(entity_id, action, confidence, decision)
        save_agent_request({
            "request_id": request_id,
            "timestamp": utc_now(),
            "sim_time": sim_time,
            "prediction_id": prediction_id,
            "entity_id": entity_id,
            "requested_action": action,
            "confidence": confidence,
            "reason_code": decision.reason_code,
            "reason": decision.reason,
            "status": "pending",
            "expires_at": (_parse_dt(sim_time) + timedelta(minutes=30)).isoformat(timespec="seconds"),
        })
        _save_log(sim_time, "AGENT_REQUEST", "agent", entity_id, message, metadata)
    elif decision.decision == "allow":
        _save_log(sim_time, "POLICY_ALLOW", "policy", entity_id, f"Policy allow {action}: {decision.reason_code}", metadata)
        if dry_run:
            _save_log(sim_time, "AGENT_ACTION", "agent", entity_id, f"Dry-run would execute {action}", metadata)
    elif decision.reason_code == "ARRIVAL_OVERDUE":
        _save_log(sim_time, "ARRIVAL_OVERDUE", "policy", entity_id, decision.reason, metadata, severity="warning")
    else:
        _save_log(sim_time, "POLICY_BLOCKED", "policy", entity_id, f"Policy {decision.decision}: {decision.reason_code} - {decision.reason}", metadata, severity="warning")
    return {
        "source": source,
        "entity_id": entity_id,
        "action": action,
        "confidence": confidence,
        "policy_decision": decision.decision,
        "reason_code": decision.reason_code,
        "reason": decision.reason,
        "request_id": request_id,
        "dry_run": dry_run,
    }


def _candidate_from_sim_context() -> tuple[str, str, float, dict[str, Any]]:
    ctx = SIM_CONTEXT
    arrival = ctx.get("arrival_status", "normal")
    predicted = ctx.get("predicted_arrival_minutes")
    minutes_after = int(ctx.get("minutes_after_expected_arrival") or 0)
    presence_home = bool(ctx.get("presence_home"))
    lr_temp = float(ctx.get("living_room_temperature") or 0)
    lr_hum = float(ctx.get("living_room_humidity") or 0)
    sim_time = str(ctx.get("sim_time") or DEFAULT_SIM_CONTEXT["sim_time"])
    if arrival == "arrival_overdue" or minutes_after >= 20:
        entity_id = "switch.living_room_ceiling_fan"
        action = "turn_on"
        confidence = 0.86
    elif arrival == "pre_arrival" and not presence_home and predicted is not None and 10 <= int(predicted) <= 15 and lr_temp >= 30 and lr_hum < 65:
        entity_id = "switch.living_room_ceiling_fan"
        action = "turn_on"
        confidence = 0.88
    elif presence_home and lr_temp >= 30 and lr_hum >= 70:
        entity_id = "climate.living_room_ac"
        action = "turn_on"
        confidence = 0.89
    else:
        hour = _parse_dt(sim_time).hour
        if presence_home and 20 <= hour <= 22:
            entity_id = "media_player.living_room_tv"
            action = "turn_on"
            confidence = 0.84
        else:
            entity_id = "light.bedroom_light"
            action = "turn_on"
            confidence = 0.72
    return entity_id, action, confidence, _policy_context_from_sim_context(entity_id, action, ctx)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    _save_log(str(SIM_CONTEXT["sim_time"]), "SYSTEM", "system", None, "Behavioral Agent API started", {"dry_run": DRY_RUN})


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "behavioral-agent-api", "dry_run": DRY_RUN}


@app.get("/api/devices")
def api_devices() -> list[dict[str, Any]]:
    return get_devices_state()


@app.get("/api/sim-context")
def api_get_sim_context() -> dict[str, Any]:
    return get_sim_context_state()


@app.post("/api/sim-context")
def set_sim_context(payload: SimContextPayload) -> dict[str, Any]:
    SIM_CONTEXT.clear()
    SIM_CONTEXT.update(payload.dict())
    _save_log(
        payload.sim_time,
        "SENSOR_UPDATE",
        "simulator",
        None,
        f"Simulation context updated: outdoor={payload.outdoor_temperature}°C/{payload.outdoor_humidity}%, living={payload.living_room_temperature}°C/{payload.living_room_humidity}%",
        payload.dict(),
    )
    return dict(SIM_CONTEXT)


@app.get("/api/logs")
def api_logs(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    return get_recent_logs(limit)


@app.get("/api/requests")
def api_requests(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    return get_pending_requests(limit)


@app.post("/api/requests/{request_id}/respond")
def respond_request(request_id: str, payload: RespondPayload) -> dict[str, Any]:
    row = fetch_agent_request(request_id)
    if not row:
        raise HTTPException(status_code=404, detail="request not found")
    status = "accepted" if payload.response == "yes" else "rejected"
    update_agent_request_status(request_id, status, response_source="api")
    log_type = "AGENT_REQUEST_ACCEPTED" if status == "accepted" else "AGENT_REQUEST_REJECTED"
    _save_log(row.get("sim_time") or utc_now(), log_type, "user", row.get("entity_id"), f"User {status} request {request_id}", {"request_id": request_id, "status": status})
    return {"request_id": request_id, "status": status, "dry_run": DRY_RUN}


@app.post("/api/scenarios/{scenario_name}")
def run_scenario(scenario_name: str) -> dict[str, Any]:
    if scenario_name not in scenario_names():
        raise HTTPException(status_code=404, detail="scenario not found")
    scenario = get_scenario(scenario_name)
    result = _run_candidate(
        entity_id=scenario["entity_id"],
        action=scenario["action"],
        confidence=float(scenario["confidence"]),
        sim_time=scenario["sim_time"].isoformat(timespec="seconds"),
        context=dict(scenario["context"]),
        source=f"scenario:{scenario_name}",
        dry_run=DRY_RUN,
    )
    result["scenario"] = scenario_name
    return result


@app.post("/api/evaluate-context")
def evaluate_context() -> dict[str, Any]:
    entity_id, action, confidence, context = _candidate_from_sim_context()
    return _run_candidate(
        entity_id=entity_id,
        action=action,
        confidence=confidence,
        sim_time=str(SIM_CONTEXT["sim_time"]),
        context=context,
        source="evaluate_context",
        dry_run=DRY_RUN,
    )


@app.post("/api/user-action")
def user_action(payload: UserActionPayload) -> dict[str, Any]:
    device = get_device(payload.entity_id)
    sim_time = payload.sim_time or str(SIM_CONTEXT["sim_time"])
    if not device:
        raise HTTPException(status_code=404, detail="unknown entity")
    if device.control_level == "observe_only":
        message = f"Manual action blocked: {payload.entity_id} is observe-only"
        _save_log(sim_time, "USER_ACTION", "simulator", payload.entity_id, message, {"warning": "observe_only"}, severity="warning")
        return {"ok": False, "warning": "observe_only device", "entity_id": payload.entity_id}
    old_state = _latest_device_state(payload.entity_id) or "off"
    if payload.action == "toggle":
        new_state = "off" if old_state == "on" else "on"
        action = "turn_off" if old_state == "on" else "turn_on"
    else:
        action = payload.action
        new_state = "on" if action == "turn_on" else "off"
    save_event({
        "timestamp": sim_time,
        "sim_time": sim_time,
        "entity_id": payload.entity_id,
        "domain": domain_for(payload.entity_id),
        "room": room_for(payload.entity_id),
        "old_state": old_state,
        "new_state": new_state,
        "hour": _parse_dt(sim_time).hour,
        "minute": _parse_dt(sim_time).minute,
        "weekday": _parse_dt(sim_time).weekday(),
        "is_weekend": 1 if _parse_dt(sim_time).weekday() >= 5 else 0,
        "presence_state": "home" if SIM_CONTEXT.get("presence_home") else "away",
        "source": payload.source,
        "event_type": "user_action",
        "trigger_type": "simulator_keyboard",
        "raw_json": _json({"action": action, "source": payload.source}),
    })
    _save_log(sim_time, "USER_ACTION", "user", payload.entity_id, f"Manual simulator action {action}: {old_state} → {new_state}", {"old_state": old_state, "new_state": new_state, "action": action})
    return {"ok": True, "entity_id": payload.entity_id, "action": action, "old_state": old_state, "new_state": new_state}


@app.get("/api/state")
def state() -> dict[str, Any]:
    return {
        "devices": get_devices_state(),
        "pending_requests": get_pending_requests(50),
        "recent_logs": get_recent_logs(50),
        "sim_context": get_sim_context_state(),
    }