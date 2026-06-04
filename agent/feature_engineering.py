"""
feature_engineering.py — Chuyển raw events → feature vectors để train model

Logic label:
  Với mỗi event off→on của entity X tại T, nếu không phải correction:
    Tạo positive sample tại T-10, T-5, T-2 phút → label = 1

  Negative sample:
    Chọn thời điểm ngẫu nhiên mà trong 10 phút tiếp theo không có off→on hợp lệ.

Correction bị bỏ qua:
  - tắt nhầm → bật lại trong 120s: off→on ngay sau on→off
  - bật nhầm → tắt lại trong 120s: off→on bị theo sau bởi on→off

Chạy:
  python agent/feature_engineering.py
"""

import sys
import random
import pandas as pd
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))
from agent.db import get_connection, init_db

PREDICTION_WINDOW_MINUTES = 10
NEGATIVE_SAMPLE_RATE = 1.5
CORRECTION_MAX_SECONDS = 120
OBSERVE_OFFSETS = [10, 5, 2]   # T-10, T-5, T-2 phút
LOCAL_TZ = "Asia/Bangkok"      # cùng múi giờ +07 với Việt Nam

ENTITIES = ["light.bedroom", "light.living_room", "switch.fan_bedroom"]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FEATURES_CSV = PROJECT_ROOT / "data" / "features.csv"


# ── Load ──────────────────────────────────────────────────────────────────────

def load_events() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query(
        """
        SELECT * FROM events
        WHERE
            (source IS NULL OR source != 'agent')
            AND (context_user_id IS NULL OR context_user_id NOT IN ('agent', 'behavior_agent'))
        ORDER BY timestamp ASC
        """,
        conn,
    )
    conn.close()

    if df.empty:
        return df

    # Chuẩn hóa timestamp về giờ địa phương để feature hour/weekday không lệch.
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(LOCAL_TZ)
    return df


# ── Snapshot helpers ─────────────────────────────────────────────────────────

def get_device_state_at(df: pd.DataFrame, entity_id: str, t) -> str:
    past = df[(df["entity_id"] == entity_id) & (df["timestamp"] <= t)]
    return past.iloc[-1]["new_state"] if not past.empty else "off"


def get_context_at(df: pd.DataFrame, t) -> dict:
    past = df[df["timestamp"] <= t]

    temp_candidates = past[past["temperature"].notna()]
    hum_candidates = past[past["humidity"].notna()]
    pres_candidates = past[past["presence_state"].notna()]

    return {
        "temperature": round(temp_candidates.iloc[-1]["temperature"], 1) if not temp_candidates.empty else 28.0,
        "humidity": round(hum_candidates.iloc[-1]["humidity"], 1) if not hum_candidates.empty else 75.0,
        "presence_state": pres_candidates.iloc[-1]["presence_state"] if not pres_candidates.empty else "unknown",
    }


def time_since_last_change(df: pd.DataFrame, entity_id: str, t) -> float:
    past = df[(df["entity_id"] == entity_id) & (df["timestamp"] < t)]
    if past.empty:
        return 99999.0
    return float((t - past.iloc[-1]["timestamp"]).total_seconds())


def recent_toggle_count(df: pd.DataFrame, entity_id: str, t, minutes: int) -> int:
    """Số lần thiết bị thay đổi trạng thái trong `minutes` phút trước t."""
    start = t - timedelta(minutes=minutes)
    mask = (
        (df["entity_id"] == entity_id)
        & (df["timestamp"] >= start)
        & (df["timestamp"] <= t)
    )
    return int(mask.sum())


# ── Correction filters ────────────────────────────────────────────────────────

def is_quick_correction(df: pd.DataFrame, entity_id: str, t_on) -> bool:
    """
    True nếu event off→on tại t_on xảy ra trong 120s sau một on→off.
    Đây là tắt nhầm → bật lại, không phải thói quen.
    """
    past = df[(df["entity_id"] == entity_id) & (df["timestamp"] < t_on)]
    if past.empty:
        return False

    last = past.iloc[-1]
    if last["old_state"] == "on" and last["new_state"] == "off":
        return (t_on - last["timestamp"]).total_seconds() <= CORRECTION_MAX_SECONDS

    return False


def followed_by_quick_off(df: pd.DataFrame, entity_id: str, t_on) -> bool:
    """
    True nếu event off→on tại t_on bị theo sau bởi on→off trong 120s.
    Đây là bật nhầm → tắt lại, không phải thói quen.
    """
    window = df[
        (df["entity_id"] == entity_id)
        & (df["timestamp"] > t_on)
        & (df["timestamp"] <= t_on + timedelta(seconds=CORRECTION_MAX_SECONDS))
    ]

    for _, ev in window.iterrows():
        if ev["old_state"] == "on" and ev["new_state"] == "off":
            return True

    return False


def is_valid_turn_on(df: pd.DataFrame, entity_id: str, t_on) -> bool:
    """off→on hợp lệ để train positive sample."""
    if is_quick_correction(df, entity_id, t_on):
        return False
    if followed_by_quick_off(df, entity_id, t_on):
        return False
    return True


# ── Feature vector ────────────────────────────────────────────────────────────

def make_feature_vector(df: pd.DataFrame, entity_id: str, t) -> dict:
    ctx = get_context_at(df, t)
    state = get_device_state_at(df, entity_id, t)
    secs = time_since_last_change(df, entity_id, t)

    related = {}
    for other in ENTITIES:
        if other != entity_id:
            key = other.replace(".", "_")
            related[key] = 1 if get_device_state_at(df, other, t) == "on" else 0

    minute_bucket = (t.hour * 60 + t.minute) // 30

    return {
        "entity_id": entity_id,
        "hour": t.hour,
        "minute_bucket": minute_bucket,
        "weekday": t.weekday(),
        "is_weekend": 1 if t.weekday() >= 5 else 0,
        "temperature": ctx["temperature"],
        "humidity": ctx["humidity"],
        "presence_home": 1 if ctx["presence_state"] == "home" else 0,
        "prev_state": 1 if state == "on" else 0,
        "time_since_change_s": min(secs, 86400),
        "recent_toggle_count_2min": recent_toggle_count(df, entity_id, t, 2),
        "recent_toggle_count_5min": recent_toggle_count(df, entity_id, t, 5),
        **related,
    }


# ── Dataset builder ───────────────────────────────────────────────────────────

def build_dataset_for_entity(df: pd.DataFrame, entity_id: str) -> pd.DataFrame:
    records: list[dict] = []
    entity_events = df[df["entity_id"] == entity_id].copy()

    turn_on_events = entity_events[
        (entity_events["old_state"] == "off")
        & (entity_events["new_state"] == "on")
    ]

    skipped = 0
    valid_turn_on_times = []

    for _, event in turn_on_events.iterrows():
        t_action = event["timestamp"]

        if not is_valid_turn_on(df, entity_id, t_action):
            skipped += 1
            continue

        valid_turn_on_times.append(t_action)

        for offset_min in OBSERVE_OFFSETS:
            t_obs = t_action - timedelta(minutes=offset_min)
            fv = make_feature_vector(df, entity_id, t_obs)
            fv["label"] = 1
            fv["t_observe"] = t_obs.isoformat()
            records.append(fv)

    if skipped:
        print(f"[fe]   → bỏ qua {skipped} correction events cho {entity_id}")

    # Negative samples: cân bằng theo positive hợp lệ, không phải raw turn_on_events.
    n_positive = sum(1 for record in records if record.get("label") == 1)
    n_negative = int(n_positive * NEGATIVE_SAMPLE_RATE)

    if not df.empty and n_negative > 0:
        t_min = df["timestamp"].min()
        t_max = df["timestamp"].max()
        total_seconds = (t_max - t_min).total_seconds()
        generated, attempts = 0, 0

        while generated < n_negative and attempts < n_negative * 20:
            attempts += 1
            t_rand = t_min + timedelta(seconds=random.uniform(0, total_seconds))
            t_end = t_rand + timedelta(minutes=PREDICTION_WINDOW_MINUTES)

            # Không có off→on hợp lệ trong prediction window.
            has_valid_action = any(t_rand <= t_on <= t_end for t_on in valid_turn_on_times)

            if not has_valid_action:
                fv = make_feature_vector(df, entity_id, t_rand)
                fv["label"] = 0
                fv["t_observe"] = t_rand.isoformat()
                records.append(fv)
                generated += 1

    return pd.DataFrame(records)


def build_full_dataset() -> pd.DataFrame:
    init_db()
    df_events = load_events()

    if df_events.empty:
        print("[fe] Không có data trong DB. Chạy data_generator.py trước.")
        return pd.DataFrame()

    print(f"[fe] Loaded {len(df_events)} events từ DB")

    all_ds = []
    for entity_id in ENTITIES:
        ds = build_dataset_for_entity(df_events, entity_id)
        pos = int(ds["label"].sum()) if not ds.empty else 0
        neg = int((ds["label"] == 0).sum()) if not ds.empty else 0
        print(f"[fe] {entity_id}: {len(ds)} samples (+{pos} / -{neg})")
        if not ds.empty:
            all_ds.append(ds)

    if not all_ds:
        print("[fe] Dataset rỗng. Cần thêm event hoặc tăng số ngày synthetic data.")
        return pd.DataFrame()

    combined = pd.concat(all_ds, ignore_index=True)

    if "t_observe" in combined.columns:
        combined = combined.drop(columns=["t_observe"])

    # Fill NaN related device cols.
    rel_cols = [c for c in combined.columns if c.startswith("light_") or c.startswith("switch_")]
    if rel_cols:
        combined[rel_cols] = combined[rel_cols].fillna(0).astype(int)

    # Encode entity_id.
    entity_map = {entity: i for i, entity in enumerate(ENTITIES)}
    combined["entity_id_enc"] = combined["entity_id"].map(entity_map)

    # Đảm bảo tất cả feature columns đều tồn tại.
    for col in get_feature_columns():
        if col not in combined.columns:
            combined[col] = 0

    pos_total = int(combined["label"].sum())
    neg_total = int((combined["label"] == 0).sum())
    print(f"\n[fe] Total: {len(combined)} samples  (+{pos_total} / -{neg_total})")

    return combined


def get_feature_columns() -> list[str]:
    """Danh sách cột feature dùng để train, không gồm label và entity_id gốc."""
    return [
        "entity_id_enc",
        "hour",
        "minute_bucket",
        "weekday",
        "is_weekend",
        "temperature",
        "humidity",
        "presence_home",
        "prev_state",
        "time_since_change_s",
        "recent_toggle_count_2min",
        "recent_toggle_count_5min",
        "light_bedroom",
        "light_living_room",
        "switch_fan_bedroom",
    ]


if __name__ == "__main__":
    dataset = build_full_dataset()
    if not dataset.empty:
        feat_cols = get_feature_columns()
        print("\n=== Sample 3 rows ===")
        print(dataset[feat_cols + ["label"]].head(3).to_string())

        FEATURES_CSV.parent.mkdir(parents=True, exist_ok=True)
        dataset.to_csv(FEATURES_CSV, index=False)
        print(f"\n✅ Saved {len(dataset)} rows → {FEATURES_CSV}")