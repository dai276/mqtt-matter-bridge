"""Central device registry for Behavioral Agent Phase 1."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


REGISTRY_VERSION = "phase1-2026-06"


@dataclass(frozen=True)
class Device:
    entity_id: str
    room: str
    domain: str
    device_type: str
    protocol: str
    control_level: str  # auto | confirm | observe_only
    risk_level: str     # low | medium | high


DEVICES: tuple[Device, ...] = (
    Device("sensor.bedroom_temperature", "bedroom", "sensor", "temperature", "MQTT", "observe_only", "low"),
    Device("sensor.bedroom_humidity", "bedroom", "sensor", "humidity", "MQTT", "observe_only", "low"),
    Device("climate.bedroom_ac", "bedroom", "climate", "air_conditioner", "HA_SIMULATED", "confirm", "medium"),
    Device("light.bedroom_light", "bedroom", "light", "light", "HA_SIMULATED", "auto", "low"),
    Device("switch.living_room_ceiling_fan", "living_room", "switch", "fan", "HA_SIMULATED", "auto", "low"),
    Device("climate.living_room_ac", "living_room", "climate", "air_conditioner", "HA_SIMULATED", "confirm", "medium"),
    Device("sensor.living_room_temperature", "living_room", "sensor", "temperature", "MQTT", "observe_only", "low"),
    Device("sensor.living_room_humidity", "living_room", "sensor", "humidity", "MQTT", "observe_only", "low"),
    Device("binary_sensor.front_door_lock", "living_room", "binary_sensor", "door_lock", "HA_SIMULATED", "observe_only", "high"),
    Device("media_player.living_room_tv", "living_room", "media_player", "tv", "HA_SIMULATED", "confirm", "medium"),
    Device("binary_sensor.living_room_camera_presence", "living_room", "binary_sensor", "camera_presence", "HA_SIMULATED", "observe_only", "low"),
    Device("switch.bathroom_water_heater", "bathroom", "switch", "water_heater", "HA_SIMULATED", "confirm", "high"),
    Device("sensor.kitchen_washing_machine_status", "kitchen", "sensor", "washing_machine", "HA_SIMULATED", "observe_only", "medium"),
)

_DEVICE_BY_ID = {device.entity_id: device for device in DEVICES}


def sanity_check() -> None:
    required = {"entity_id", "room", "domain", "device_type", "protocol", "control_level", "risk_level"}
    seen: set[str] = set()
    for device in DEVICES:
        data = asdict(device)
        missing = [field for field in required if not data.get(field)]
        if missing:
            raise ValueError(f"Device {device.entity_id} missing metadata: {missing}")
        if device.entity_id in seen:
            raise ValueError(f"Duplicate entity_id in registry: {device.entity_id}")
        seen.add(device.entity_id)
        if device.control_level not in {"auto", "confirm", "observe_only"}:
            raise ValueError(f"Invalid control_level for {device.entity_id}: {device.control_level}")
        if device.risk_level not in {"low", "medium", "high"}:
            raise ValueError(f"Invalid risk_level for {device.entity_id}: {device.risk_level}")


def registry_hash() -> str:
    payload = json.dumps([asdict(device) for device in DEVICES], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def get_device(entity_id: str) -> Device | None:
    return _DEVICE_BY_ID.get(entity_id)


def all_entities() -> list[str]:
    return [device.entity_id for device in DEVICES]


def control_entities() -> list[str]:
    return [device.entity_id for device in DEVICES if device.control_level in {"auto", "confirm"}]


def auto_entities() -> list[str]:
    return [device.entity_id for device in DEVICES if device.control_level == "auto"]


def confirm_entities() -> list[str]:
    return [device.entity_id for device in DEVICES if device.control_level == "confirm"]


def observe_only_entities() -> list[str]:
    return [device.entity_id for device in DEVICES if device.control_level == "observe_only"]


def sensor_entities() -> list[str]:
    return [device.entity_id for device in DEVICES if device.domain == "sensor" or device.device_type in {"temperature", "humidity"}]


def domain_for(entity_id: str) -> str | None:
    device = get_device(entity_id)
    return device.domain if device else (entity_id.split(".", 1)[0] if "." in entity_id else None)


def room_for(entity_id: str) -> str | None:
    device = get_device(entity_id)
    return device.room if device else None


sanity_check()