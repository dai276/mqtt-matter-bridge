"""
data_collector.py — Home Assistant WebSocket state_changed collector.

This daemon only observes Home Assistant state changes and writes selected
entity events into the Behavioral Agent SQLite database. It does not call
Home Assistant services and does not control devices.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

try:
    import websockets
except ImportError:  # pragma: no cover - exercised only when dependency missing
    websockets = None

from agent.db import get_connection, init_db, save_event

LOG = logging.getLogger("collector")
LOCAL_TZ = ZoneInfo("Asia/Bangkok")
BACKOFF_SECONDS = [1, 2, 5, 10, 30]
DEFAULT_COLLECT_ENTITIES = [
    "light.bedroom",
    "light.living_room",
    "switch.fan_bedroom",
    "climate.bedroom_ac",
    "media_player.living_room_tv",
    "switch.air_purifier",
]
EVENT_ROW_FIELDS = {
    "timestamp",
    "entity_id",
    "domain",
    "old_state",
    "new_state",
    "hour",
    "minute",
    "weekday",
    "is_weekend",
    "temperature",
    "humidity",
    "presence_state",
    "context_user_id",
    "source",
    "raw_json",
}


@dataclass(frozen=True)
class CollectorConfig:
    ha_url: str
    ha_token: str
    collect_entities: set[str]
    temperature_entity: str
    humidity_entity: str
    presence_entity: str


def load_config() -> CollectorConfig:
    """Load collector settings from .env/environment variables."""
    ha_url = os.getenv("HA_URL", "http://localhost:8123").rstrip("/")
    ha_token = os.getenv("HA_TOKEN", "")
    collect_raw = os.getenv("COLLECT_ENTITIES", "")
    collect_entities = {
        item.strip() for item in collect_raw.split(",") if item.strip()
    } or set(DEFAULT_COLLECT_ENTITIES)

    return CollectorConfig(
        ha_url=ha_url,
        ha_token=ha_token,
        collect_entities=collect_entities,
        temperature_entity=os.getenv("TEMPERATURE_ENTITY", "sensor.living_room_temperature"),
        humidity_entity=os.getenv("HUMIDITY_ENTITY", "sensor.living_room_humidity"),
        presence_entity=os.getenv("PRESENCE_ENTITY", "binary_sensor.home_presence"),
    )


def build_ws_url(ha_url: str) -> str:
    """Convert HA HTTP(S) base URL to HA WebSocket API URL."""
    parsed = urlparse(ha_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = "/api/websocket"
    return urlunparse((scheme, parsed.netloc, path, "", "", ""))


def parse_ha_timestamp(value: str | None) -> datetime:
    """Parse Home Assistant ISO timestamp and convert to Asia/Bangkok."""
    if not value:
        LOG.warning("missing time_fired; using current time")
        return datetime.now().astimezone(LOCAL_TZ)

    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt.astimezone(LOCAL_TZ)
    except Exception as exc:
        LOG.warning("cannot parse time_fired=%r: %s; using current time", value, exc)
        return datetime.now().astimezone(LOCAL_TZ)


def normalize_presence(state: str | None) -> str:
    """Normalize Home Assistant presence-like states to home/away/unknown."""
    value = (state or "").strip().lower()
    if value in {"home", "on", "detected"}:
        return "home"
    if value in {"away", "off", "not_home", "clear"}:
        return "away"
    return "unknown"


def parse_float_safe(value: str | None) -> float | None:
    """Parse a float state safely, returning None for invalid sensor states."""
    if value in (None, "", "unknown", "unavailable"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        LOG.warning("cannot parse numeric sensor state=%r", value)
        return None


def get_events_schema_columns() -> set[str]:
    """Return actual SQLite columns in the events table."""
    conn = get_connection()
    try:
        rows = conn.execute("PRAGMA table_info(events)").fetchall()
        return {row["name"] for row in rows}
    finally:
        conn.close()


def filter_row_to_schema(row: dict[str, Any], schema_columns: set[str]) -> dict[str, Any]:
    """Drop keys not present in the current events schema and warn once per row."""
    filtered = {key: value for key, value in row.items() if key in schema_columns}
    dropped = sorted(set(row) - set(filtered))
    if dropped:
        LOG.warning("dropping non-schema event columns: %s", ", ".join(dropped))
    return filtered


def _state_value(state_obj: dict[str, Any] | None) -> str | None:
    if not isinstance(state_obj, dict):
        return None
    value = state_obj.get("state")
    return str(value) if value is not None else None


def _context_user_id(
    event: dict[str, Any],
    new_state_obj: dict[str, Any] | None,
    old_state_obj: dict[str, Any] | None,
) -> str | None:
    candidates = [
        event.get("context", {}) if isinstance(event.get("context"), dict) else {},
        new_state_obj.get("context", {}) if isinstance(new_state_obj, dict) else {},
        old_state_obj.get("context", {}) if isinstance(old_state_obj, dict) else {},
    ]
    for context in candidates:
        user_id = context.get("user_id")
        if user_id:
            return str(user_id)
    return None


def build_event_row(
    event: dict[str, Any],
    context_cache: dict[str, Any],
    schema_columns: set[str],
) -> dict[str, Any]:
    """Build a row compatible with the existing events table schema."""
    data = event.get("data", {})
    entity_id = data.get("entity_id")
    old_state_obj = data.get("old_state")
    new_state_obj = data.get("new_state")
    old_state = _state_value(old_state_obj)
    new_state = _state_value(new_state_obj)
    timestamp = parse_ha_timestamp(event.get("time_fired"))

    row = {
        "timestamp": timestamp.isoformat(),
        "entity_id": entity_id,
        "domain": entity_id.split(".")[0] if isinstance(entity_id, str) and "." in entity_id else None,
        "old_state": old_state,
        "new_state": new_state,
        "hour": timestamp.hour,
        "minute": timestamp.minute,
        "weekday": timestamp.weekday(),
        "is_weekend": 1 if timestamp.weekday() >= 5 else 0,
        "temperature": context_cache.get("temperature"),
        "humidity": context_cache.get("humidity"),
        "presence_state": context_cache.get("presence_state", "unknown"),
        "context_user_id": _context_user_id(event, new_state_obj, old_state_obj),
        "source": "ha_websocket",
        "raw_json": json.dumps(event, ensure_ascii=False),
    }
    unexpected = set(row) - EVENT_ROW_FIELDS
    if unexpected:
        LOG.warning("unexpected event row fields: %s", ", ".join(sorted(unexpected)))
    return filter_row_to_schema(row, schema_columns)


def handle_state_changed(
    message: dict[str, Any],
    config: CollectorConfig,
    context_cache: dict[str, Any],
    schema_columns: set[str],
    *,
    dry_run: bool,
) -> bool:
    """Handle one HA state_changed message. Return True if a target event was accepted."""
    event = message.get("event", {})
    data = event.get("data", {}) if isinstance(event, dict) else {}
    entity_id = data.get("entity_id")
    old_state_obj = data.get("old_state")
    new_state_obj = data.get("new_state")
    old_state = _state_value(old_state_obj)
    new_state = _state_value(new_state_obj)

    if not entity_id:
        LOG.debug("skip state_changed without entity_id")
        return False

    if entity_id == config.temperature_entity:
        context_cache["temperature"] = parse_float_safe(new_state)
        LOG.debug("temperature cache updated: %s", context_cache["temperature"])
    elif entity_id == config.humidity_entity:
        context_cache["humidity"] = parse_float_safe(new_state)
        LOG.debug("humidity cache updated: %s", context_cache["humidity"])
    elif entity_id == config.presence_entity:
        context_cache["presence_state"] = normalize_presence(new_state)
        LOG.debug("presence cache updated: %s", context_cache["presence_state"])

    if old_state == new_state:
        return False

    if new_state in {"unknown", "unavailable"}:
        LOG.warning("%s new_state=%s", entity_id, new_state)

    if entity_id not in config.collect_entities:
        return False

    row = build_event_row(event, context_cache, schema_columns)
    missing = sorted(EVENT_ROW_FIELDS.intersection(schema_columns) - set(row))
    if missing:
        LOG.error("events schema/filter missing required row keys: %s", ", ".join(missing))
        return False

    LOG.info(
        "%s %s → %s presence=%s temp=%s hum=%s",
        row.get("entity_id"),
        row.get("old_state"),
        row.get("new_state"),
        row.get("presence_state"),
        row.get("temperature"),
        row.get("humidity"),
    )

    if dry_run:
        LOG.debug("dry-run row: %s", json.dumps(row, ensure_ascii=False))
    else:
        save_event(row)
    return True


async def _run_once_connection(
    config: CollectorConfig,
    schema_columns: set[str],
    *,
    dry_run: bool,
    once: bool,
    max_events: int | None,
) -> int:
    if websockets is None:
        raise RuntimeError("Missing dependency. Install with: pip install websockets python-dotenv")
    if not config.ha_token:
        raise RuntimeError("HA_TOKEN is required for Home Assistant WebSocket auth")

    ws_url = build_ws_url(config.ha_url)
    context_cache: dict[str, Any] = {
        "temperature": None,
        "humidity": None,
        "presence_state": "unknown",
    }
    accepted = 0

    async with websockets.connect(ws_url) as ws:
        hello = json.loads(await ws.recv())
        LOG.debug("HA websocket hello type=%s", hello.get("type"))
        await ws.send(json.dumps({"type": "auth", "access_token": config.ha_token}))
        auth_response = json.loads(await ws.recv())
        if auth_response.get("type") != "auth_ok":
            raise RuntimeError(f"Home Assistant auth failed: {auth_response.get('type')}")

        await ws.send(json.dumps({
            "id": 1,
            "type": "subscribe_events",
            "event_type": "state_changed",
        }))
        LOG.info("subscribed state_changed from %s dry_run=%s", ws_url, dry_run)

        async for raw in ws:
            message = json.loads(raw)
            if message.get("type") != "event":
                continue
            if handle_state_changed(
                message,
                config,
                context_cache,
                schema_columns,
                dry_run=dry_run,
            ):
                accepted += 1
                if once or (max_events is not None and accepted >= max_events):
                    return accepted
    return accepted


async def collector_loop(
    config: CollectorConfig,
    *,
    dry_run: bool = True,
    once: bool = False,
    max_events: int | None = None,
) -> None:
    """Run collector with reconnect/backoff until stopped or enough events arrive."""
    init_db()
    schema_columns = get_events_schema_columns()
    missing_schema = sorted(EVENT_ROW_FIELDS - schema_columns)
    if missing_schema:
        message = "events table missing columns: " + ", ".join(missing_schema)
        if dry_run:
            LOG.warning("%s; dry-run will omit them", message)
        else:
            raise RuntimeError(message)

    total_accepted = 0
    retry = 0
    while True:
        try:
            accepted = await _run_once_connection(
                config,
                schema_columns,
                dry_run=dry_run,
                once=once,
                max_events=None if max_events is None else max_events - total_accepted,
            )
            total_accepted += accepted
            if once or (max_events is not None and total_accepted >= max_events):
                LOG.info("collector stopped after %d accepted event(s)", total_accepted)
                return
            retry = 0
        except KeyboardInterrupt:
            LOG.info("collector stopped by Ctrl+C")
            return
        except Exception as exc:
            delay = BACKOFF_SECONDS[min(retry, len(BACKOFF_SECONDS) - 1)]
            retry += 1
            LOG.error("connection error: %s; retry=%d backoff=%ss", exc, retry, delay)
            await asyncio.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description="Home Assistant state_changed data collector")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Chỉ log row, không ghi DB (mặc định)")
    parser.add_argument("--live", action="store_true", default=False,
                        help="Ghi DB thật")
    parser.add_argument("--once", action="store_true",
                        help="Nhận 1 event hợp lệ rồi thoát")
    parser.add_argument("--max-events", type=int, default=None,
                        help="Nhận tối đa N event hợp lệ rồi thoát")
    parser.add_argument("--verbose", action="store_true",
                        help="Log chi tiết hơn")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [collector] %(message)s",
        datefmt="%H:%M:%S",
    )

    if websockets is None:
        print("Missing dependency. Install with: pip install websockets python-dotenv", file=sys.stderr)
        raise SystemExit(1)

    config = load_config()
    dry_run = not args.live
    try:
        asyncio.run(collector_loop(
            config,
            dry_run=dry_run,
            once=args.once,
            max_events=args.max_events,
        ))
    except KeyboardInterrupt:
        LOG.info("collector stopped by Ctrl+C")


if __name__ == "__main__":
    main()