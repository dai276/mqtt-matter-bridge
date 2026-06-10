"""
predictor.py — Load model, predict, kiểm tra Policy Gate, log kết quả

Mặc định dry_run=True — KHÔNG điều khiển thiết bị thật.
Muốn thật: python agent/predictor.py --live

Chạy: python agent/predictor.py [--dry-run | --live]
"""

import sys
import json
import pickle
import logging
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.db         import init_db, get_connection, save_prediction
from agent.policy     import PolicyGate
from agent.ha_client  import HAClient
from agent.feature_engineering import (
    load_events, get_feature_columns,
    get_device_state_at, get_context_at,
    time_since_last_change, recent_toggle_count,
)

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [predictor] %(message)s",
                    datefmt="%H:%M:%S")

PROJECT_ROOT = Path(__file__).parent.parent
MODEL_PATH   = PROJECT_ROOT / "models" / "decision_tree.pkl"
META_PATH    = PROJECT_ROOT / "models" / "decision_tree_meta.json"

ENTITIES = ["light.bedroom", "light.living_room", "switch.fan_bedroom"]
DOMAIN_MAP = {
    "light.bedroom":      "light",
    "light.living_room":  "light",
    "switch.fan_bedroom": "switch",
}


# ── Load model ────────────────────────────────────────────────────────────────

def load_model():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Model không tìm thấy tại {MODEL_PATH}. Chạy trainer.py trước.")
    with open(MODEL_PATH, "rb") as f:
        model = pickle.load(f)
    with open(META_PATH)  as f:
        meta  = json.load(f)
    log.info(f"Model loaded  trained_at={meta.get('trained_at','?')}")
    return model, meta


# ── Build feature vector hiện tại ────────────────────────────────────────────

def build_current_features(df, entity_id: str, feat_cols: list[str]) -> list:
    """Tạo feature vector tại thời điểm hiện tại cho entity_id."""
    now = datetime.now().astimezone()

    ctx   = get_context_at(df, now)
    state = get_device_state_at(df, entity_id, now)
    secs  = time_since_last_change(df, entity_id, now)

    related = {}
    for other in ENTITIES:
        if other != entity_id:
            key = other.replace(".", "_")
            related[key] = 1 if get_device_state_at(df, other, now) == "on" else 0

    minute_bucket = (now.hour * 60 + now.minute) // 30

    fv_dict = {
        "entity_id_enc":            ENTITIES.index(entity_id),
        "hour":                     now.hour,
        "minute_bucket":            minute_bucket,
        "weekday":                  now.weekday(),
        "is_weekend":               1 if now.weekday() >= 5 else 0,
        "temperature":              ctx["temperature"],
        "humidity":                 ctx["humidity"],
        "presence_home":            1 if ctx["presence_state"] == "home" else 0,
        "prev_state":               1 if state == "on" else 0,
        "time_since_change_s":      min(secs, 86400),
        "recent_toggle_count_2min": recent_toggle_count(df, entity_id, now, 2),
        "recent_toggle_count_5min": recent_toggle_count(df, entity_id, now, 5),
        **{k: v for k, v in related.items()},
    }

    return [fv_dict.get(col, 0) for col in feat_cols]


# ── Run predictor ─────────────────────────────────────────────────────────────

def run(dry_run: bool = True) -> None:
    init_db()

    model, meta  = load_model()
    feat_cols    = meta["feature_columns"]
    gate         = PolicyGate()
    ha           = HAClient(dry_run=dry_run)
    df           = load_events()

    if df.empty:
        log.warning("Không có events trong DB — không thể predict.")
        return

    now_str = datetime.now().isoformat(timespec="seconds")
    log.info(f"Predicting for {len(ENTITIES)} entities  dry_run={dry_run}")

    for entity_id in ENTITIES:
        domain = DOMAIN_MAP[entity_id]

        # Feature vector hiện tại
        fv = build_current_features(df, entity_id, feat_cols)

        # Predict
        proba      = model.predict_proba([fv])[0]
        confidence = float(proba[1])   # xác suất class=1 (turn_on)

        # Context để Policy Gate kiểm tra
        now = datetime.now().astimezone()
        ctx = {
            "presence_home":            fv[feat_cols.index("presence_home")],
            "recent_toggle_count_2min": fv[feat_cols.index("recent_toggle_count_2min")],
            "recent_toggle_count_5min": fv[feat_cols.index("recent_toggle_count_5min")],
            "time_since_change_s":      fv[feat_cols.index("time_since_change_s")],
        }

        allowed, reason = gate.check(entity_id, domain, confidence, ctx)

        log.info(
            f"{entity_id:<25}  conf={confidence:.2f}  "
            f"{'ALLOW' if allowed else 'BLOCK':5}  {reason}"
        )

        # Thực thi nếu được phép
        executed = 0
        if allowed and not dry_run:
            ok = ha.call_service(domain, "turn_on", entity_id)
            executed = 1 if ok else 0

        # Luôn log vào bảng predictions
        save_prediction({
            "timestamp":        now_str,
            "entity_id":        entity_id,
            "predicted_action": "turn_on",
            "confidence":       confidence,
            "allowed_by_policy": 1 if allowed else 0,
            "executed":         executed,
            "reason":           reason,
        })

    log.info("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Chỉ log, không gọi HA thật (mặc định)")
    parser.add_argument("--live", action="store_true", default=False,
                        help="Gọi HA REST API thật (cần HA_TOKEN trong .env)")
    args = parser.parse_args()

    dry = not args.live
    run(dry_run=dry)