"""SQLite schema and helpers for Behavioral Agent Phase 2."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = os.getenv("DB_PATH", str(Path(__file__).parent.parent / "data" / "behavior_agent.db"))

EVENT_COLUMNS: dict[str, str] = {
    "sim_time": "TEXT",
    "event_type": "TEXT",
    "trigger_type": "TEXT",
    "room": "TEXT",
    "front_door_state": "TEXT",
    "camera_presence_state": "TEXT",
    "user_arrival_state": "TEXT",
    "predicted_action": "TEXT",
    "policy_decision": "TEXT",
    "reason_code": "TEXT",
    "feature_snapshot": "TEXT",
}

PREDICTION_COLUMNS: dict[str, str] = {
    "policy_decision": "TEXT",
    "reason_code": "TEXT",
    "feature_snapshot": "TEXT",
}

AGENT_REQUEST_COLUMNS: dict[str, str] = {
    "responded_at": "TEXT",
    "response_source": "TEXT",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = _columns(conn, table)
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_db() -> None:
    """Create/migrate schema idempotently without dropping existing data."""
    conn = get_connection()
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp         TEXT NOT NULL,
                entity_id         TEXT NOT NULL,
                domain            TEXT,
                old_state         TEXT,
                new_state         TEXT,
                hour              INTEGER,
                minute            INTEGER,
                weekday           INTEGER,
                is_weekend        INTEGER,
                temperature       REAL,
                humidity          REAL,
                presence_state    TEXT,
                context_user_id   TEXT,
                source            TEXT DEFAULT 'ha_websocket',
                raw_json          TEXT
            );

            CREATE TABLE IF NOT EXISTS predictions (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp         TEXT NOT NULL,
                entity_id         TEXT NOT NULL,
                predicted_action  TEXT,
                confidence        REAL,
                allowed_by_policy INTEGER,
                executed          INTEGER,
                reason            TEXT
            );

            CREATE TABLE IF NOT EXISTS policy_decisions (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp         TEXT NOT NULL,
                sim_time          TEXT,
                prediction_id     INTEGER,
                entity_id         TEXT NOT NULL,
                requested_action  TEXT,
                decision          TEXT NOT NULL,
                allowed_by_policy INTEGER,
                reason_code       TEXT,
                reason            TEXT,
                confidence        REAL,
                control_level     TEXT,
                risk_level        TEXT,
                room              TEXT,
                context_snapshot  TEXT,
                created_at        TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_requests (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id        TEXT NOT NULL UNIQUE,
                timestamp         TEXT NOT NULL,
                sim_time          TEXT,
                prediction_id     INTEGER,
                entity_id         TEXT NOT NULL,
                requested_action  TEXT NOT NULL,
                reason_code       TEXT,
                reason            TEXT,
                status            TEXT NOT NULL DEFAULT 'pending',
                expires_at        TEXT,
                created_at        TEXT NOT NULL,
                responded_at      TEXT,
                response_source   TEXT
            );

            CREATE TABLE IF NOT EXISTS action_logs (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp         TEXT NOT NULL,
                sim_time          TEXT,
                log_type          TEXT NOT NULL,
                actor             TEXT NOT NULL,
                entity_id         TEXT,
                room              TEXT,
                message           TEXT NOT NULL,
                severity          TEXT DEFAULT 'info',
                metadata          TEXT,
                created_at        TEXT NOT NULL
            );
            """
        )
        _add_missing_columns(conn, "events", EVENT_COLUMNS)
        _add_missing_columns(conn, "predictions", PREDICTION_COLUMNS)
        _add_missing_columns(conn, "agent_requests", AGENT_REQUEST_COLUMNS)
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_events_entity
                ON events(entity_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_events_hour_weekday
                ON events(hour, weekday);
            CREATE INDEX IF NOT EXISTS idx_events_sim_time
                ON events(sim_time);
            CREATE INDEX IF NOT EXISTS idx_predictions_entity
                ON predictions(entity_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_policy_decisions_prediction
                ON policy_decisions(prediction_id);
            CREATE INDEX IF NOT EXISTS idx_policy_decisions_entity
                ON policy_decisions(entity_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_agent_requests_status
                ON agent_requests(status, timestamp);
            CREATE INDEX IF NOT EXISTS idx_action_logs_timestamp
                ON action_logs(timestamp);
            CREATE INDEX IF NOT EXISTS idx_action_logs_type
                ON action_logs(log_type, timestamp);
            """
        )
    conn.close()
    print(f"[db] Schema ready: {DB_PATH}")


def _insert_dynamic(table: str, row: dict[str, Any]) -> int:
    conn = get_connection()
    try:
        columns = _columns(conn, table)
        payload = {key: value for key, value in row.items() if key in columns}
        if not payload:
            raise ValueError(f"No valid columns supplied for {table}")
        names = ", ".join(payload.keys())
        placeholders = ", ".join(f":{key}" for key in payload)
        with conn:
            cursor = conn.execute(f"INSERT INTO {table} ({names}) VALUES ({placeholders})", payload)
            return int(cursor.lastrowid)
    finally:
        conn.close()


def save_event(row: dict[str, Any]) -> int:
    return _insert_dynamic("events", row)


def save_prediction(row: dict[str, Any]) -> int:
    return _insert_dynamic("predictions", row)


def save_policy_decision(row: dict[str, Any]) -> int:
    now = utc_now()
    row.setdefault("timestamp", now)
    row.setdefault("created_at", now)
    return _insert_dynamic("policy_decisions", row)


def save_agent_request(row: dict[str, Any]) -> int:
    now = utc_now()
    row.setdefault("timestamp", now)
    row.setdefault("status", "pending")
    row.setdefault("created_at", now)
    return _insert_dynamic("agent_requests", row)


def update_agent_request_status(request_id: str, status: str, response_source: str = "cli") -> int:
    if status not in {"pending", "accepted", "rejected", "expired", "cancelled"}:
        raise ValueError(f"invalid agent request status: {status}")
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute(
                "UPDATE agent_requests SET status=?, responded_at=?, response_source=? WHERE request_id=?",
                (status, utc_now(), response_source, request_id),
            )
            return int(cursor.rowcount)
    finally:
        conn.close()


def fetch_agent_request(request_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM agent_requests WHERE request_id=?", (request_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_action_log(row: dict[str, Any]) -> int:
    now = utc_now()
    row.setdefault("timestamp", now)
    row.setdefault("created_at", now)
    row.setdefault("severity", "info")
    return _insert_dynamic("action_logs", row)


def fetch_pending_requests(limit: int = 50) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM agent_requests WHERE status='pending' ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_recent_action_logs(limit: int = 20) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM action_logs ORDER BY timestamp DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_events(entity_id: str | None = None, limit: int = 10000) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        if entity_id:
            rows = conn.execute(
                "SELECT * FROM events WHERE entity_id=? ORDER BY timestamp DESC LIMIT ?",
                (entity_id, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM events ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()