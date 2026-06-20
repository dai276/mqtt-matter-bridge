"""Deterministic predictor scenarios for Phase 2.5 smoke testing."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

SCENARIO_BASE_TIME = datetime(2026, 6, 19, 18, 0, tzinfo=timezone.utc)


def _context(**overrides: Any) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "bedroom_temperature": 28.0,
        "bedroom_humidity": 62.0,
        "living_room_temperature": 28.0,
        "living_room_humidity": 62.0,
        "is_hot": 0,
        "is_humid": 0,
        "is_dry": 0,
        "presence_home": 1,
        "presence_state": "home",
        "door_recently_opened": 1,
        "camera_recently_detected": 1,
        "predicted_arrival_minutes": 0,
        "is_before_arrival_window": 0,
        "is_arrival_overdue": 0,
        "minutes_after_expected_arrival": 0,
        "prev_state": 0,
        "time_since_change_s": 1800,
        "recent_toggle_count_2min": 0,
        "recent_toggle_count_5min": 0,
        "fan_on": 0,
        "living_room_ac_on": 0,
        "bedroom_ac_on": 0,
        "bedroom_light_on": 0,
        "water_heater_on": 0,
        "tv_on": 0,
    }
    ctx.update(overrides)
    return ctx


SCENARIOS: dict[str, dict[str, Any]] = {
    "pre-arrival-hot-dry": {
        "sim_time": SCENARIO_BASE_TIME.replace(hour=18, minute=15),
        "entity_id": "switch.living_room_ceiling_fan",
        "action": "turn_on",
        "confidence": 0.88,
        "context": _context(
            living_room_temperature=31.8,
            living_room_humidity=50.0,
            is_hot=1,
            is_humid=0,
            is_dry=1,
            presence_home=0,
            presence_state="away",
            door_recently_opened=0,
            camera_recently_detected=0,
            predicted_arrival_minutes=15,
            is_before_arrival_window=1,
            minutes_after_expected_arrival=0,
            prev_state=0,
            fan_on=0,
        ),
        "description": "Hot/dry living room before arrival; low-risk fan may be auto-allowed.",
    },
    "hot-humid-evening": {
        "sim_time": SCENARIO_BASE_TIME.replace(hour=18, minute=45),
        "entity_id": "climate.living_room_ac",
        "action": "turn_on",
        "confidence": 0.89,
        "context": _context(
            living_room_temperature=32.2,
            living_room_humidity=82.0,
            is_hot=1,
            is_humid=1,
            presence_home=1,
            presence_state="home",
            prev_state=0,
            living_room_ac_on=0,
        ),
        "description": "Hot/humid evening; living room AC should create a confirmation request.",
    },
    "water-heater-routine": {
        "sim_time": SCENARIO_BASE_TIME.replace(hour=21, minute=0),
        "entity_id": "switch.bathroom_water_heater",
        "action": "turn_on",
        "confidence": 0.91,
        "context": _context(
            presence_home=1,
            presence_state="home",
            prev_state=0,
            water_heater_on=0,
        ),
        "description": "Evening bathroom routine; water heater is high-risk and confirm-only.",
    },
    "tv-evening": {
        "sim_time": SCENARIO_BASE_TIME.replace(hour=20, minute=30),
        "entity_id": "media_player.living_room_tv",
        "action": "turn_on",
        "confidence": 0.90,
        "context": _context(
            presence_home=1,
            presence_state="home",
            prev_state=0,
            tv_on=0,
        ),
        "description": "Evening TV routine; TV should create a confirmation request.",
    },
    "arrival-overdue": {
        "sim_time": SCENARIO_BASE_TIME.replace(hour=19, minute=5),
        "entity_id": "switch.living_room_ceiling_fan",
        "action": "turn_on",
        "confidence": 0.87,
        "context": _context(
            living_room_temperature=31.0,
            living_room_humidity=52.0,
            is_hot=1,
            is_humid=0,
            presence_home=0,
            presence_state="away",
            door_recently_opened=0,
            camera_recently_detected=0,
            predicted_arrival_minutes=-35,
            is_before_arrival_window=0,
            is_arrival_overdue=1,
            minutes_after_expected_arrival=35,
            prev_state=0,
            fan_on=0,
        ),
        "description": "Expected arrival is overdue; policy must block additional pre-arrival automation.",
    },
    "observe-only": {
        "sim_time": SCENARIO_BASE_TIME.replace(hour=18, minute=20),
        "entity_id": "binary_sensor.front_door_lock",
        "action": "turn_on",
        "confidence": 0.80,
        "context": _context(
            presence_home=1,
            presence_state="home",
            prev_state=0,
        ),
        "description": "Door lock binary sensor is observe-only and must not be controlled.",
    },
}


def scenario_names() -> list[str]:
    return sorted(SCENARIOS)


def get_scenario(name: str) -> dict[str, Any]:
    if name not in SCENARIOS:
        raise KeyError(f"Unknown scenario: {name}")
    scenario = deepcopy(SCENARIOS[name])
    scenario["name"] = name
    return scenario