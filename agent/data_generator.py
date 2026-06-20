"""Generate deterministic 30-day synthetic Phase 1 Behavioral Agent data."""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.db import get_connection, init_db, save_event
from agent.device_registry import DEVICES, all_entities, domain_for, get_device, room_for

LOCAL_TZ = timezone(timedelta(hours=7))
USER_ID = "user_manual"
DEFAULT_DAYS = 30

CONTROL_ENTITY_INITIAL_STATES = {
    "light.bedroom_light": "off",
    "switch.living_room_ceiling_fan": "off",
    "climate.living_room_ac": "off",
    "climate.bedroom_ac": "off",
    "media_player.living_room_tv": "off",
    "switch.bathroom_water_heater": "off",
}


def _parse_start_date(value: str | None, days: int) -> datetime:
    if value:
        return datetime.fromisoformat(value).replace(tzinfo=LOCAL_TZ, hour=0, minute=0, second=0, microsecond=0)
    return (datetime.now(LOCAL_TZ) - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)


def _dt(day: datetime, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return day.replace(hour=hour, minute=minute, second=second, microsecond=0)


def _random_time(day: datetime, start_minute: int, end_minute: int) -> datetime:
    minute = random.randint(start_minute, end_minute)
    return _dt(day, minute // 60, minute % 60, random.randint(0, 59))


def _base_weather(day: datetime, hour: int, room: str, is_humid_day: bool, is_hot_day: bool) -> tuple[float, float]:
    peak = 34.0 if is_hot_day else 31.0
    base = 26.5 if room == "bedroom" else 27.0
    if 6 <= hour <= 14:
        temp = base + (peak - base) * ((hour - 6) / 8)
    elif 14 < hour <= 22:
        temp = peak - (peak - base + 1.0) * ((hour - 14) / 8)
    else:
        temp = base - 1.5
    if room == "bedroom":
        temp -= 0.4
    humidity = (84 if is_humid_day else 66) - max(0, hour - 8) * 0.7 + random.uniform(-4, 4)
    return round(temp + random.uniform(-0.7, 0.7), 1), round(max(45, min(92, humidity)), 1)


def _event(
    ts: datetime,
    entity_id: str,
    old_state: str | None,
    new_state: str,
    *,
    event_type: str,
    trigger_type: str,
    source: str,
    context: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    device = get_device(entity_id)
    return {
        "timestamp": ts.isoformat(),
        "sim_time": ts.isoformat(),
        "entity_id": entity_id,
        "domain": domain_for(entity_id),
        "room": room_for(entity_id),
        "old_state": old_state,
        "new_state": str(new_state),
        "hour": ts.hour,
        "minute": ts.minute,
        "weekday": ts.weekday(),
        "is_weekend": 1 if ts.weekday() >= 5 else 0,
        "temperature": context.get("living_room_temperature"),
        "humidity": context.get("living_room_humidity"),
        "presence_state": context.get("presence_state", "unknown"),
        "front_door_state": context.get("front_door_state", "closed"),
        "camera_presence_state": context.get("camera_presence_state", "off"),
        "user_arrival_state": context.get("user_arrival_state", "unknown"),
        "event_type": event_type,
        "trigger_type": trigger_type,
        "context_user_id": USER_ID if source == "synthetic" else None,
        "source": source,
        "raw_json": json.dumps({"reason": reason, "device": device.device_type if device else None, **context}, ensure_ascii=False),
    }


def _append_control(events: list[dict[str, Any]], states: dict[str, str], ts: datetime, entity_id: str, desired: str, *, trigger_type: str, context: dict[str, Any], reason: str) -> None:
    old_state = states.get(entity_id, "off")
    if old_state == desired:
        return
    states[entity_id] = desired
    events.append(_event(ts, entity_id, old_state, desired, event_type="user_action", trigger_type=trigger_type, source="synthetic", context=context, reason=reason))


def _daily_context(day: datetime) -> dict[str, Any]:
    return {
        "presence_state": "away",
        "front_door_state": "closed",
        "camera_presence_state": "off",
        "user_arrival_state": "away",
        "bedroom_temperature": 27.0,
        "bedroom_humidity": 70.0,
        "living_room_temperature": 27.0,
        "living_room_humidity": 70.0,
    }


def generate_day(day: datetime, states: dict[str, str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    context = _daily_context(day)
    is_hot_day = random.random() < 0.62
    is_humid_day = random.random() < 0.45
    arrival_minute = random.randint(18 * 60, 19 * 60)
    arrival_overdue = random.random() < 0.18
    actual_arrival_minute = arrival_minute + random.randint(25, 55) if arrival_overdue else arrival_minute
    leave_minute = random.randint(7 * 60, 8 * 60 + 30)

    # Sensor context snapshots every 3 hours.
    for hour in range(0, 24, 3):
        for room in ("bedroom", "living_room"):
            temp, hum = _base_weather(day, hour, room, is_humid_day, is_hot_day)
            context[f"{room}_temperature"] = temp
            context[f"{room}_humidity"] = hum
            events.append(_event(_dt(day, hour, random.randint(0, 12)), f"sensor.{room}_temperature", None, str(temp), event_type="sensor", trigger_type="environment", source="synthetic", context=context, reason="weather_snapshot"))
            events.append(_event(_dt(day, hour, random.randint(13, 25)), f"sensor.{room}_humidity", None, str(hum), event_type="sensor", trigger_type="environment", source="synthetic", context=context, reason="humidity_snapshot"))

    # Leaving home.
    leave_ts = _random_time(day, leave_minute, leave_minute + 10)
    context.update({"presence_state": "away", "front_door_state": "open", "camera_presence_state": "off", "user_arrival_state": "away"})
    events.append(_event(leave_ts, "binary_sensor.front_door_lock", "closed", "open", event_type="presence", trigger_type="door", source="synthetic", context=context, reason="user_left_home"))
    events.append(_event(leave_ts + timedelta(minutes=1), "binary_sensor.front_door_lock", "open", "closed", event_type="presence", trigger_type="door", source="synthetic", context=context, reason="door_closed_after_leave"))

    # Pre-arrival context can create fan comfort action only when not overdue.
    pre_ts = _dt(day, arrival_minute // 60, arrival_minute % 60) - timedelta(minutes=random.randint(10, 15))
    living_temp, living_hum = _base_weather(day, pre_ts.hour, "living_room", is_humid_day, is_hot_day)
    context.update({"living_room_temperature": living_temp, "living_room_humidity": living_hum, "user_arrival_state": "pre_arrival"})
    if not arrival_overdue and living_temp >= 30 and living_hum < 78:
        _append_control(events, states, pre_ts, "switch.living_room_ceiling_fan", "on", trigger_type="pre_arrival_comfort", context=context, reason="hot_before_arrival_fan_preferred")
    elif arrival_overdue:
        context["user_arrival_state"] = "arrival_overdue"
        events.append(_event(pre_ts + timedelta(minutes=30), "binary_sensor.living_room_camera_presence", "off", "off", event_type="context", trigger_type="arrival_overdue", source="synthetic", context=context, reason="arrival_overdue_no_presence"))

    # Arrival signals.
    arrival_ts = _dt(day, actual_arrival_minute // 60, actual_arrival_minute % 60, random.randint(0, 59))
    context.update({"presence_state": "home", "front_door_state": "open", "camera_presence_state": "on", "user_arrival_state": "arrived"})
    events.append(_event(arrival_ts, "binary_sensor.front_door_lock", "closed", "open", event_type="presence", trigger_type="door", source="synthetic", context=context, reason="user_arrived_home"))
    events.append(_event(arrival_ts + timedelta(seconds=30), "binary_sensor.living_room_camera_presence", "off", "on", event_type="presence", trigger_type="camera_presence", source="synthetic", context=context, reason="camera_detected_arrival"))
    events.append(_event(arrival_ts + timedelta(minutes=1), "binary_sensor.front_door_lock", "open", "closed", event_type="presence", trigger_type="door", source="synthetic", context=context, reason="door_closed_after_arrival"))

    # Evening routines based on context.
    if living_temp >= 30 and living_hum < 78:
        _append_control(events, states, arrival_ts + timedelta(minutes=random.randint(1, 8)), "switch.living_room_ceiling_fan", "on", trigger_type="manual_context", context=context, reason="hot_and_not_humid_prefers_fan")
    if living_temp >= 30 and living_hum >= 78:
        _append_control(events, states, arrival_ts + timedelta(minutes=random.randint(3, 12)), "climate.living_room_ac", "on", trigger_type="manual_context", context=context, reason="hot_and_humid_prefers_ac_confirm")
    if living_hum >= 84 and living_temp < 30:
        _append_control(events, states, arrival_ts + timedelta(minutes=random.randint(5, 15)), "climate.living_room_ac", "on", trigger_type="manual_context", context=context, reason="very_humid_dehumidify_context")

    _append_control(events, states, _random_time(day, 18 * 60 + 30, 20 * 60), "light.bedroom_light", "on", trigger_type="routine", context=context, reason="evening_light")
    if random.random() < 0.58:
        _append_control(events, states, _random_time(day, 20 * 60, 22 * 60), "media_player.living_room_tv", "on", trigger_type="routine", context=context, reason="evening_tv_confirm")
    if random.random() < 0.35:
        _append_control(events, states, _random_time(day, 21 * 60, 22 * 60), "switch.bathroom_water_heater", "on", trigger_type="routine", context=context, reason="water_heater_confirm_high_risk")
    if random.random() < 0.35:
        bedroom_temp, bedroom_hum = _base_weather(day, 22, "bedroom", is_humid_day, is_hot_day)
        context.update({"bedroom_temperature": bedroom_temp, "bedroom_humidity": bedroom_hum})
        _append_control(events, states, _random_time(day, 22 * 60, 23 * 60), "climate.bedroom_ac", "on", trigger_type="routine", context=context, reason="bedroom_sleep_comfort_confirm")

    # Turn things off later.
    for entity_id in list(CONTROL_ENTITY_INITIAL_STATES):
        if states.get(entity_id) == "on" and random.random() < 0.82:
            _append_control(events, states, _random_time(day + timedelta(days=1), 0, 90), entity_id, "off", trigger_type="routine", context=context, reason="night_shutdown")

    # Observe-only washing machine status.
    if random.random() < 0.22:
        start = _random_time(day, 9 * 60, 15 * 60)
        events.append(_event(start, "sensor.kitchen_washing_machine_status", "idle", "running", event_type="sensor", trigger_type="appliance_status", source="synthetic", context=context, reason="washing_machine_started"))
        events.append(_event(start + timedelta(minutes=random.randint(45, 95)), "sensor.kitchen_washing_machine_status", "running", "done", event_type="sensor", trigger_type="appliance_status", source="synthetic", context=context, reason="washing_machine_done"))

    # Dirty behavior only for controllable devices.
    if random.random() < 0.18:
        entity_id = random.choice(["light.bedroom_light", "switch.living_room_ceiling_fan"])
        ts = _random_time(day, 19 * 60, 22 * 60)
        first = "off" if states.get(entity_id, "off") == "on" else "on"
        _append_control(events, states, ts, entity_id, first, trigger_type="dirty_behavior", context=context, reason="accidental_toggle")
        _append_control(events, states, ts + timedelta(seconds=random.randint(10, 80)), entity_id, "off" if first == "on" else "on", trigger_type="dirty_behavior", context=context, reason="manual_override_after_accident")

    events.sort(key=lambda row: row["timestamp"])
    return events


def clear_synthetic_events() -> None:
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM events WHERE source = 'synthetic'")
        conn.execute("DELETE FROM predictions")
    conn.close()
    print("[gen] Cleared old synthetic events and predictions")


def generate(days: int = DEFAULT_DAYS, *, clear_old: bool = False, seed: int | None = None, start_date: str | None = None) -> dict[str, Any]:
    if seed is not None:
        random.seed(seed)
    init_db()
    if clear_old:
        clear_synthetic_events()

    start = _parse_start_date(start_date, days)
    states = dict(CONTROL_ENTITY_INITIAL_STATES)
    all_rows: list[dict[str, Any]] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        rows = generate_day(day, states)
        for row in rows:
            save_event(row)
        all_rows.extend(rows)
        print(f"[gen] {day.date()} events={len(rows):3d}")

    summary = {
        "events": len(all_rows),
        "days": days,
        "entities": len({row["entity_id"] for row in all_rows}),
        "event_type": Counter(row.get("event_type") for row in all_rows),
        "source": Counter(row.get("source") for row in all_rows),
        "room": Counter(row.get("room") for row in all_rows),
    }
    print("\n[gen] Summary")
    print(f"  events: {summary['events']}")
    print(f"  days: {summary['days']}")
    print(f"  registry entities: {len(all_entities())}")
    for key in ("event_type", "source", "room"):
        print(f"  {key}: {dict(summary[key])}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--start-date", default=None, help="YYYY-MM-DD or ISO datetime")
    args = parser.parse_args()
    generate(days=args.days, clear_old=args.clear, seed=args.seed, start_date=args.start_date)