"""Small terminal CLI for Phase 2 agent requests and action logs."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.db import fetch_agent_request, fetch_pending_requests, fetch_recent_action_logs, init_db, save_action_log, update_agent_request_status, utc_now


def _short_time(value: str | None) -> str:
    if not value:
        return "--:--"
    try:
        return datetime.fromisoformat(value).strftime("%H:%M")
    except ValueError:
        return value[:16]


def _metadata_action(metadata: str | None) -> str:
    if not metadata:
        return ""
    try:
        data = json.loads(metadata)
        action = data.get("action")
        confidence = data.get("confidence")
        if action and confidence is not None:
            return f" {action} confidence={float(confidence):.2f}"
    except Exception:
        return ""
    return ""


def pending_requests(limit: int) -> None:
    init_db()
    rows = fetch_pending_requests(limit=limit)
    if not rows:
        print("No pending agent requests.")
        return
    for row in rows:
        print(
            f"[PENDING] {row['request_id']} | {row['entity_id']} | {row['requested_action']} | "
            f"confidence={float(row.get('confidence') or 0):.2f} | reason={row.get('reason_code')} | expires={_short_time(row.get('expires_at'))}"
        )


def recent_logs(limit: int) -> None:
    init_db()
    rows = fetch_recent_action_logs(limit=limit)
    if not rows:
        print("No action logs.")
        return
    for row in rows:
        action_bits = _metadata_action(row.get("metadata"))
        entity = row.get("entity_id") or "-"
        print(f"[{_short_time(row.get('timestamp'))}] {row['log_type']} {entity}{action_bits} | {row['message']}")


def respond(request_id: str, response: str) -> None:
    init_db()
    row = fetch_agent_request(request_id)
    if not row:
        print(f"Request not found: {request_id}")
        raise SystemExit(1)
        
    status = "accepted" if response == "yes" else "rejected"
    updated = update_agent_request_status(request_id, status, response_source="agent_cli")
    
    if updated:
        log_type = "AGENT_REQUEST_ACCEPTED" if status == "accepted" else "AGENT_REQUEST_REJECTED"
        save_action_log({
            "timestamp": utc_now(),
            "sim_time": row.get("sim_time"),
            "log_type": log_type,
            "actor": "user",
            "entity_id": row.get("entity_id"),
            "room": None,
            "message": f"User {status} request {request_id} for {row.get('requested_action')} {row.get('entity_id')}",
            "severity": "info",
            "metadata": json.dumps({"request_id": request_id, "status": status, "response_source": "agent_cli"}, ensure_ascii=False),
        })
        print(f"{request_id} -> {status}")
    else:
        print(f"Request not found: {request_id}")
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Inspect Phase 2 Behavioral Agent requests/logs")
    sub = parser.add_subparsers(dest="command", required=True)
    
    p_pending = sub.add_parser("pending-requests")
    p_pending.add_argument("--limit", type=int, default=50)
    
    p_logs = sub.add_parser("recent-logs")
    p_logs.add_argument("--limit", type=int, default=20)
    
    p_respond = sub.add_parser("respond")
    p_respond.add_argument("request_id")
    p_respond.add_argument("response", choices=["yes", "no"])
    
    args = parser.parse_args(argv)
    
    if args.command == "pending-requests":
        pending_requests(args.limit)
    elif args.command == "recent-logs":
        recent_logs(args.limit)
    elif args.command == "respond":
        respond(args.request_id, args.response)


if __name__ == "__main__":
    main()