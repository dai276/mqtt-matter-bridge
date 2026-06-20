"""Stdlib feature engineering for Behavioral Agent Phase 1."""

from __future__ import annotations

import csv
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.db import get_connection, init_db
from agent.device_registry import DEVICES, control_entities, get_device, registry_hash

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FEATURES_CSV = PROJECT_ROOT / 'data' / 'features.csv'
FEATURE_META_PATH = PROJECT_ROOT / 'models' / 'feature_metadata.json'

LABELS = ['no_action', 'turn_on', 'turn_off']
LABEL_TO_ID = {v: i for i, v in enumerate(LABELS)}
ID_TO_LABEL = {i: v for v, i in LABEL_TO_ID.items()}

CONTROL_LEVELS = ['auto', 'confirm', 'observe_only']
RISK_LEVELS = ['low', 'medium', 'high']
DEVICE_TYPES = sorted({d.device_type for d in DEVICES})
ROOMS = sorted({d.room for d in DEVICES})
ENTITIES = control_entities()
EXPECTED_ARRIVAL_MINUTE = 18 * 60 + 30
OBSERVE_OFFSETS = [15, 10, 5, 2]
NEGATIVE_SAMPLE_RATE = 1.2

STATE_FEATURES = {
    'fan_on': 'switch.living_room_ceiling_fan',
    'living_room_ac_on': 'climate.living_room_ac',
    'bedroom_ac_on': 'climate.bedroom_ac',
    'bedroom_light_on': 'light.bedroom_light',
    'water_heater_on': 'switch.bathroom_water_heater',
    'tv_on': 'media_player.living_room_tv'
}

BASE_FEATURES = [
    'hour', 'minute_bucket', 'weekday', 'is_weekend',
    'bedroom_temperature', 'bedroom_humidity', 'living_room_temperature', 'living_room_humidity',
    'is_hot', 'is_humid', 'is_dry', 'presence_home', 'door_recently_opened', 'camera_recently_detected',
    'predicted_arrival_minutes', 'is_before_arrival_window', 'is_arrival_overdue', 'minutes_after_expected_arrival',
    'prev_state', 'time_since_change_s', 'recent_toggle_count_2min', 'recent_toggle_count_5min',
    *STATE_FEATURES.keys()
]

ENTITY_FEATURES = [f"entity__{e.replace('.', '_')}" for e in ENTITIES]
ROOM_FEATURES = [f"room__{r}" for r in ROOMS]
CONTROL_FEATURES = [f"control_level__{x}" for x in CONTROL_LEVELS]
RISK_FEATURES = [f"risk_level__{x}" for x in RISK_LEVELS]
TYPE_FEATURES = [f"device_type__{x}" for x in DEVICE_TYPES]

FEATURE_COLUMNS = BASE_FEATURES + ENTITY_FEATURES + ROOM_FEATURES + CONTROL_FEATURES + RISK_FEATURES + TYPE_FEATURES


class FeatureTable(list):
    @property
    def empty(self) -> bool:
        return len(self) == 0

    @property
    def columns(self) -> set[str]:
        return set().union(*(r.keys() for r in self)) if self else set()

    def to_csv(self, path: Path | str, index: bool = False) -> None:
        cols = list(self[0].keys()) if self else []
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(self)


def _parse_ts(s: Any) -> datetime:
    return datetime.fromisoformat(str(s).replace('Z', '+00:00'))


def load_events() -> list[dict[str, Any]]:
    conn = get_connection()
    rows = [
        dict(r) for r in conn.execute(
            "SELECT * FROM events WHERE (source IS NULL OR source!='agent') AND (context_user_id IS NULL OR context_user_id NOT IN ('agent','behavior_agent')) ORDER BY timestamp ASC"
        ).fetchall()
    ]
    conn.close()
    
    for r in rows:
        r['_ts'] = _parse_ts(r['timestamp'])
    return rows


def _state_at(events: list[dict[str, Any]], entity: str, t: datetime) -> str:
    val = 'off'
    for r in events:
        if r['entity_id'] == entity and r['_ts'] <= t:
            val = str(r.get('new_state'))
        if r['_ts'] > t:
            break
    return val


def get_device_state_at(df: list[dict[str, Any]], entity_id: str, t: datetime) -> str:
    return _state_at(df, entity_id, t)


def _num_at(events: list[dict[str, Any]], entity: str, t: datetime, default: float) -> float:
    val = default
    for r in events:
        if r['entity_id'] == entity and r['_ts'] <= t:
            try:
                val = float(r.get('new_state'))
            except Exception:
                pass
        if r['_ts'] > t:
            break
    return val


def _recent(events: list[dict[str, Any]], entity: str, t: datetime, minutes: int, states: set[str] | None = None) -> int:
    start = t - timedelta(minutes=minutes)
    return int(
        any(
            r['entity_id'] == entity and start <= r['_ts'] <= t and (states is None or str(r.get('new_state')) in states)
            for r in events
        )
    )


def get_context_at(df: list[dict[str, Any]], t: datetime) -> dict[str, Any]:
    minute = t.hour * 60 + t.minute
    door = _recent(df, 'binary_sensor.front_door_lock', t, 20, {'open'})
    cam = _recent(df, 'binary_sensor.living_room_camera_presence', t, 20, {'on', 'detected'})
    presence = 1 if door or cam or _state_at(df, 'binary_sensor.living_room_camera_presence', t) in {'on', 'detected'} else 0
    
    brt = _num_at(df, 'sensor.bedroom_temperature', t, 27.0)
    brh = _num_at(df, 'sensor.bedroom_humidity', t, 70.0)
    lrt = _num_at(df, 'sensor.living_room_temperature', t, 28.0)
    lrh = _num_at(df, 'sensor.living_room_humidity', t, 70.0)
    
    return {
        'bedroom_temperature': brt,
        'bedroom_humidity': brh,
        'living_room_temperature': lrt,
        'living_room_humidity': lrh,
        'is_hot': int(max(brt, lrt) >= 30),
        'is_humid': int(max(brh, lrh) >= 78),
        'is_dry': int(min(brh, lrh) <= 55),
        'presence_home': presence,
        'presence_state': 'home' if presence else 'away',
        'door_recently_opened': door,
        'camera_recently_detected': cam,
        'predicted_arrival_minutes': EXPECTED_ARRIVAL_MINUTE - minute,
        'is_before_arrival_window': int(EXPECTED_ARRIVAL_MINUTE - 15 <= minute <= EXPECTED_ARRIVAL_MINUTE - 10),
        'is_arrival_overdue': int(EXPECTED_ARRIVAL_MINUTE + 20 <= minute <= EXPECTED_ARRIVAL_MINUTE + 30 and not presence),
        'minutes_after_expected_arrival': max(0, minute - EXPECTED_ARRIVAL_MINUTE)
    }


def time_since_last_change(df: list[dict[str, Any]], entity: str, t: datetime) -> float:
    last = None
    for r in df:
        if r['entity_id'] == entity and r['_ts'] < t:
            last = r['_ts']
        if r['_ts'] >= t:
            break
    return 99999.0 if last is None else float((t - last).total_seconds())


def recent_toggle_count(df: list[dict[str, Any]], entity: str, t: datetime, minutes: int) -> int:
    start = t - timedelta(minutes=minutes)
    return sum(1 for r in df if r['entity_id'] == entity and start <= r['_ts'] <= t)


def make_feature_vector(df: list[dict[str, Any]], entity_id: str, t: datetime) -> dict[str, Any]:
    d = get_device(entity_id)
    ctx = get_context_at(df, t)
    state = _state_at(df, entity_id, t)
    
    fv = {
        'hour': t.hour,
        'minute_bucket': (t.hour * 60 + t.minute) // 30,
        'weekday': t.weekday(),
        'is_weekend': int(t.weekday() >= 5),
        **{k: v for k, v in ctx.items() if k != 'presence_state'},
        'prev_state': int(state == 'on'),
        'time_since_change_s': min(time_since_last_change(df, entity_id, t), 86400),
        'recent_toggle_count_2min': recent_toggle_count(df, entity_id, t, 2),
        'recent_toggle_count_5min': recent_toggle_count(df, entity_id, t, 5)
    }
    
    for f, e in STATE_FEATURES.items():
        fv[f] = int(_state_at(df, e, t) == 'on')
        
    for e in ENTITIES:
        fv[f"entity__{e.replace('.', '_')}"] = int(e == entity_id)
        
    for r in ROOMS:
        fv[f"room__{r}"] = int(d and d.room == r)
        
    for x in CONTROL_LEVELS:
        fv[f"control_level__{x}"] = int(d and d.control_level == x)
        
    for x in RISK_LEVELS:
        fv[f"risk_level__{x}"] = int(d and d.risk_level == x)
        
    for x in DEVICE_TYPES:
        fv[f"device_type__{x}"] = int(d and d.device_type == x)
        
    return {c: fv.get(c, 0) for c in FEATURE_COLUMNS}


def build_dataset_for_entity(df: list[dict[str, Any]], entity_id: str, seed: int | None = None) -> FeatureTable:
    rng = random.Random(seed)
    records = []
    windows = []
    
    actions = [
        r for r in df 
        if r['entity_id'] == entity_id 
        and r.get('old_state') in ('on', 'off') 
        and r.get('new_state') in ('on', 'off') 
        and r.get('old_state') != r.get('new_state')
    ]
    
    for ev in actions:
        action = 'turn_on' if ev['new_state'] == 'on' else 'turn_off'
        t = ev['_ts']
        windows.append((t - timedelta(minutes=10), t + timedelta(minutes=1)))
        
        for off in OBSERVE_OFFSETS:
            t_obs = t - timedelta(minutes=off)
            row = make_feature_vector(df, entity_id, t_obs)
            row.update({
                'entity_id': entity_id,
                'label_name': action,
                'label': LABEL_TO_ID[action],
                't_observe': t_obs.isoformat()
            })
            records.append(row)
            
    nneg = int(len(records) * NEGATIVE_SAMPLE_RATE)
    
    if df and nneg:
        tmin, tmax = df[0]['_ts'], df[-1]['_ts']
        total = max(1, int((tmax - tmin).total_seconds()))
        gen = 0
        attempts = 0
        
        while gen < nneg and attempts < nneg * 30:
            attempts += 1
            t = tmin + timedelta(seconds=rng.randint(0, total))
            
            if not any(a <= t <= b for a, b in windows):
                row = make_feature_vector(df, entity_id, t)
                row.update({
                    'entity_id': entity_id,
                    'label_name': 'no_action',
                    'label': 0,
                    't_observe': t.isoformat()
                })
                records.append(row)
                gen += 1
                
    return FeatureTable(records)


def build_full_dataset(seed: int | None = None) -> FeatureTable:
    init_db()
    events = load_events()
    
    if not events:
        print('[fe] Không có data trong DB. Chạy data_generator.py trước.')
        return FeatureTable()
        
    print(f'[fe] Loaded {len(events)} events từ DB')
    out = FeatureTable()
    
    for i, e in enumerate(ENTITIES):
        ds = build_dataset_for_entity(events, e, None if seed is None else seed + i)
        counts = {}
        for r in ds:
            counts[r['label_name']] = counts.get(r['label_name'], 0) + 1
        print(f'[fe] {e}: {len(ds)} samples {counts}')
        out.extend(ds)
        
    return out


def get_feature_columns() -> list[str]:
    return list(FEATURE_COLUMNS)


def feature_metadata() -> dict[str, Any]:
    return {
        'feature_columns': get_feature_columns(),
        'labels': LABELS,
        'label_mapping': LABEL_TO_ID,
        'entities': ENTITIES,
        'rooms': ROOMS,
        'control_levels': CONTROL_LEVELS,
        'risk_levels': RISK_LEVELS,
        'device_types': DEVICE_TYPES,
        'device_registry_hash': registry_hash()
    }


if __name__ == '__main__':
    ds = build_full_dataset(seed=42)
    if ds:
        FEATURES_CSV.parent.mkdir(parents=True, exist_ok=True)
        ds.to_csv(FEATURES_CSV, index=False)
        
        FEATURE_META_PATH.parent.mkdir(parents=True, exist_ok=True)
        FEATURE_META_PATH.write_text(
            json.dumps(feature_metadata(), indent=2, ensure_ascii=False), 
            encoding='utf-8'
        )
        
        print('\n=== Sample 3 rows ===')
        for r in ds[:3]:
            print({k: r[k] for k in get_feature_columns()[:8]}, 'label=', r['label_name'])
        print(f'\n✅ Saved {len(ds)} rows → {FEATURES_CSV}')