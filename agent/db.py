"""
db.py — SQLite schema & helper functions cho Behavioral Agent
Tạo và quản lý 2 bảng: events, predictions
"""

import sqlite3
import os
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", str(Path(__file__).parent.parent / "data" / "behavior_agent.db"))


def get_connection() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # an toàn khi multi-process đọc/ghi
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")

    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Tạo schema nếu chưa tồn tại. Idempotent — gọi nhiều lần không sao."""
    conn = get_connection()
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp         TEXT NOT NULL,
                entity_id         TEXT NOT NULL,
                domain            TEXT,
                old_state         TEXT,
                new_state         TEXT,
                hour              INTEGER,
                minute            INTEGER,
                weekday           INTEGER,       -- 0=Mon, 6=Sun
                is_weekend        INTEGER,       -- 0/1
                temperature       REAL,
                humidity          REAL,
                presence_state    TEXT,          -- 'home' | 'away' | 'unknown'
                context_user_id   TEXT,          -- 'user_manual' | 'agent' | NULL
                source            TEXT DEFAULT 'ha_websocket',
                raw_json          TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_events_entity
                ON events(entity_id, timestamp);

            CREATE INDEX IF NOT EXISTS idx_events_hour_weekday
                ON events(hour, weekday);

            CREATE TABLE IF NOT EXISTS predictions (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp         TEXT NOT NULL,
                entity_id         TEXT NOT NULL,
                predicted_action  TEXT,          -- 'turn_on' | 'turn_off' | ...
                confidence        REAL,
                allowed_by_policy INTEGER,       -- 0/1
                executed          INTEGER,       -- 0/1
                reason            TEXT           -- lý do nếu bị block
            );

            CREATE INDEX IF NOT EXISTS idx_predictions_entity
                ON predictions(entity_id, timestamp);
        """)
    conn.close()
    print(f"[db] Schema ready: {DB_PATH}")


def save_event(row: dict) -> None:
    conn = get_connection()
    with conn:
        conn.execute("""
            INSERT INTO events
                (timestamp, entity_id, domain, old_state, new_state,
                 hour, minute, weekday, is_weekend,
                 temperature, humidity, presence_state,
                 context_user_id, source, raw_json)
            VALUES
                (:timestamp, :entity_id, :domain, :old_state, :new_state,
                 :hour, :minute, :weekday, :is_weekend,
                 :temperature, :humidity, :presence_state,
                 :context_user_id, :source, :raw_json)
        """, row)
    conn.close()


def save_prediction(row: dict) -> None:
    conn = get_connection()
    with conn:
        conn.execute("""
            INSERT INTO predictions
                (timestamp, entity_id, predicted_action,
                 confidence, allowed_by_policy, executed, reason)
            VALUES
                (:timestamp, :entity_id, :predicted_action,
                 :confidence, :allowed_by_policy, :executed, :reason)
        """, row)
    conn.close()


def fetch_events(entity_id: str = None, limit: int = 10000) -> list[dict]:
    conn = get_connection()
    if entity_id:
        rows = conn.execute(
            "SELECT * FROM events WHERE entity_id=? ORDER BY timestamp DESC LIMIT ?",
            (entity_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()