"""
data_generator.py — Sinh synthetic data 30 ngày để test pipeline
Mô phỏng thói quen sử dụng thiết bị thật của người dùng Việt Nam

Kiến trúc sửa lỗi:
  Phase 1: Sinh candidate actions theo routine + dirty behavior
  Phase 2: Sort toàn bộ candidate actions theo timestamp rồi replay bằng device_states
           để old_state/new_state luôn đúng theo dòng thời gian.

Chạy:
  python agent/data_generator.py
  python agent/data_generator.py --clear   # xóa dữ liệu synthetic cũ trước khi sinh lại
"""

import json
import random
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from agent.db import init_db, save_event, get_connection

# ── Config ───────────────────────────────────────────────────────────────────

DAYS = 30
NOISE_RATE = 0.15             # 15% hành vi ngẫu nhiên
PRESENCE_AWAY_PROB = 0.10     # 10% xác suất không có ở nhà cả ngày
DIRTY_BEHAVIOR_PROB = 0.12    # 12% xác suất có thao tác bẩn/ngày
USER_ID = "user_manual"

# Thiết bị và domain
ENTITIES: dict[str, str] = {
    "light.bedroom": "light",
    "light.living_room": "light",
    "switch.fan_bedroom": "switch",
}

# Trạng thái ban đầu tất cả thiết bị là off

def _initial_states() -> dict[str, str]:
    return {entity_id: "off" for entity_id in ENTITIES}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _random_time_between(date: datetime, sh: int, sm: int, eh: int, em: int) -> datetime:
    """Datetime ngẫu nhiên trong khoảng [start, end] của ngày date."""
    start = date.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = date.replace(hour=eh, minute=em, second=0, microsecond=0)

    # Nếu end <= start, hiểu là khoảng thời gian bắc qua ngày hôm sau.
    if end <= start:
        end += timedelta(days=1)

    total = int((end - start).total_seconds())
    return start + timedelta(seconds=random.randint(0, total))


def _noisy(prob: float) -> bool:
    """True nếu hành vi xảy ra, đã tính noise."""
    if random.random() < NOISE_RATE:
        return random.random() < 0.5
    return random.random() < prob


def _temp(hour: int, is_weekend: bool) -> float:
    """Nhiệt độ giả lập theo giờ trong ngày."""
    base = 27.0
    peak = 33.0 if not is_weekend else 32.0

    if 6 <= hour <= 14:
        temp = base + (peak - base) * ((hour - 6) / 8)
    elif 14 < hour <= 20:
        temp = peak - (peak - base) * ((hour - 14) / 6)
    else:
        temp = base - 2 + random.uniform(-1, 1)

    return round(temp + random.uniform(-0.5, 0.5), 1)


def _humidity(hour: int) -> float:
    """Độ ẩm giả lập theo giờ trong ngày."""
    base = 75.0
    delta = 10 * abs(hour - 14) / 14
    return round(base - delta + random.uniform(-3, 3), 1)


def make_action(
    ts: datetime,
    entity_id: str,
    desired_state: str,
    presence: str,
    temperature: float | None = None,
    humidity: float | None = None,
    *,
    required_old_state: str | None = None,
    group_id: str | None = None,
    depends_on_group: bool = False,
    reason: str = "routine",
) -> dict[str, Any]:
    """
    Candidate action, chưa phải event thật.

    required_old_state:
      - Nếu khác None, action chỉ được materialize khi state hiện tại đúng như yêu cầu.
      - Dùng cho dirty behavior để không tạo event sai logic.

    group_id + depends_on_group:
      - Nếu action đầu của group bị skip, action sau trong cùng group cũng bị skip.
      - Ví dụ: tắt nhầm → bật lại. Nếu không thể tạo event tắt nhầm, không tạo event bật lại.
    """
    is_weekend = ts.weekday() >= 5
    return {
        "timestamp": ts,
        "entity_id": entity_id,
        "desired_state": desired_state,
        "presence": presence,
        "temperature": temperature if temperature is not None else _temp(ts.hour, is_weekend),
        "humidity": humidity if humidity is not None else _humidity(ts.hour),
        "required_old_state": required_old_state,
        "group_id": group_id,
        "depends_on_group": depends_on_group,
        "reason": reason,
    }


def _event_from_action(
    action: dict[str, Any],
    old_state: str,
    new_state: str,
) -> dict[str, Any]:
    """Chuyển candidate action đã được replay thành event thật để lưu DB."""
    ts: datetime = action["timestamp"]
    entity_id = action["entity_id"]
    domain = ENTITIES[entity_id]
    is_weekend = ts.weekday() >= 5

    return {
        "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S+07:00"),
        "entity_id": entity_id,
        "domain": domain,
        "old_state": old_state,
        "new_state": new_state,
        "hour": ts.hour,
        "minute": ts.minute,
        "weekday": ts.weekday(),
        "is_weekend": 1 if is_weekend else 0,
        "temperature": action["temperature"],
        "humidity": action["humidity"],
        "presence_state": action["presence"],
        "context_user_id": USER_ID,
        "source": "synthetic",
        "raw_json": json.dumps(
            {
                "entity_id": entity_id,
                "old_state": old_state,
                "new_state": new_state,
                "reason": action.get("reason", "synthetic"),
            },
            ensure_ascii=False,
        ),
    }


# ── Phase 2: materialize candidate actions theo timestamp ─────────────────────

def materialize_actions(
    actions: list[dict[str, Any]],
    device_states: dict[str, str],
) -> list[dict[str, Any]]:
    """
    Sort candidate actions theo timestamp rồi replay bằng device_states.
    Đây là chỗ duy nhất được cập nhật state tracker.
    """
    events: list[dict[str, Any]] = []
    group_success: dict[str, bool] = {}

    # Sort stable: nếu cùng timestamp, giữ thứ tự append ban đầu.
    actions_sorted = sorted(enumerate(actions), key=lambda item: (item[1]["timestamp"], item[0]))

    for _, action in actions_sorted:
        entity_id = action["entity_id"]
        desired_state = action["desired_state"]
        group_id = action.get("group_id")

        # Nếu action này phụ thuộc group trước đó mà group đã fail, skip.
        if action.get("depends_on_group") and group_id and not group_success.get(group_id, False):
            continue

        old_state = device_states.get(entity_id, "off")
        required_old_state = action.get("required_old_state")

        if required_old_state is not None and old_state != required_old_state:
            if group_id:
                group_success[group_id] = False
            continue

        if old_state == desired_state:
            if group_id:
                group_success[group_id] = False
            continue

        event = _event_from_action(action, old_state, desired_state)
        events.append(event)
        device_states[entity_id] = desired_state

        if group_id:
            group_success[group_id] = True

    return events


# ── Phase 1: routine actions ──────────────────────────────────────────────────

def simulate_light_bedroom(date: datetime, presence: str) -> list[dict[str, Any]]:
    """
    Đèn phòng ngủ:
    - Weekday: bật 22:00–22:59, tắt 00:00–00:30 ngày hôm sau
    - Weekend: bật 23:00–23:59, tắt 00:30–01:30 ngày hôm sau
    """
    actions: list[dict[str, Any]] = []
    if presence != "home" or not _noisy(0.90):
        return actions

    is_weekend = date.weekday() >= 5

    if is_weekend:
        ts_on = _random_time_between(date, 23, 0, 23, 59)
        ts_off = _random_time_between(date + timedelta(days=1), 0, 30, 1, 30)
    else:
        ts_on = _random_time_between(date, 22, 0, 22, 59)
        ts_off = _random_time_between(date + timedelta(days=1), 0, 0, 0, 30)

    actions.append(make_action(ts_on, "light.bedroom", "on", presence, reason="routine_bedroom_light_on"))

    if _noisy(0.92):
        actions.append(make_action(ts_off, "light.bedroom", "off", presence, reason="routine_bedroom_light_off"))

    return actions


def simulate_light_living_room(date: datetime, presence: str) -> list[dict[str, Any]]:
    """
    Đèn phòng khách:
    - Weekday: bật 18:00–19:30, tắt 21:00–22:30
    - Weekend: bật 17:00–18:30, tắt 21:30–23:00
    """
    actions: list[dict[str, Any]] = []
    if presence != "home" or not _noisy(0.85):
        return actions

    is_weekend = date.weekday() >= 5

    if is_weekend:
        ts_on = _random_time_between(date, 17, 0, 18, 30)
        ts_off = _random_time_between(date, 21, 30, 23, 0)
    else:
        ts_on = _random_time_between(date, 18, 0, 19, 30)
        ts_off = _random_time_between(date, 21, 0, 22, 30)

    actions.append(make_action(ts_on, "light.living_room", "on", presence, reason="routine_living_light_on"))

    if _noisy(0.88):
        actions.append(make_action(ts_off, "light.living_room", "off", presence, reason="routine_living_light_off"))

    return actions


def simulate_fan_bedroom(date: datetime, presence: str) -> list[dict[str, Any]]:
    """
    Quạt phòng ngủ:
    - Ban ngày: bật khi temp > 28°C lúc 11h, 13h, 15h; tắt sau 1–3 tiếng
    - Ban đêm: bật 22h nếu temp > 27°C; tắt sau 1–3 tiếng
    """
    actions: list[dict[str, Any]] = []
    if presence != "home":
        return actions

    is_weekend = date.weekday() >= 5

    for hour in [11, 13, 15]:
        temp = _temp(hour, is_weekend)
        if temp > 28 and _noisy(0.75):
            ts_on = date.replace(
                hour=hour,
                minute=random.randint(0, 59),
                second=random.randint(0, 59),
                microsecond=0,
            )
            ts_off = ts_on + timedelta(hours=random.randint(1, 3), minutes=random.randint(0, 59))

            actions.append(make_action(ts_on, "switch.fan_bedroom", "on", presence, temp, _humidity(hour), reason="routine_fan_day_on"))
            actions.append(make_action(ts_off, "switch.fan_bedroom", "off", presence, reason="routine_fan_day_off"))

    night_temp = _temp(22, is_weekend)
    if night_temp > 27 and _noisy(0.70):
        ts_on = _random_time_between(date, 22, 0, 22, 59)
        ts_off = ts_on + timedelta(hours=random.randint(1, 3), minutes=random.randint(0, 59))

        actions.append(make_action(ts_on, "switch.fan_bedroom", "on", presence, night_temp, _humidity(22), reason="routine_fan_night_on"))
        actions.append(make_action(ts_off, "switch.fan_bedroom", "off", presence, reason="routine_fan_night_off"))

    return actions


# ── Phase 1: dirty behavior candidates ────────────────────────────────────────

def simulate_accidental_toggle(date: datetime, presence: str) -> list[dict[str, Any]]:
    """
    Lớp 3 — Dirty real-world behavior.
    Sinh candidate actions có required_old_state/group để khi replay theo timestamp
    không tạo event sai logic trạng thái.
    """
    actions: list[dict[str, Any]] = []
    if presence != "home" or random.random() > DIRTY_BEHAVIOR_PROB:
        return actions

    entity_id = random.choice(list(ENTITIES.keys()))
    ts_base = _random_time_between(date, 19, 0, 22, 59)
    scenario = random.choice(["accidental_off_then_on", "accidental_on_then_off", "rapid_toggle"])
    group_id = f"dirty_{scenario}_{date.strftime('%Y%m%d')}_{entity_id}_{random.randint(1000, 9999)}"

    if scenario == "accidental_off_then_on":
        # Chỉ hợp lệ nếu tại thời điểm replay thiết bị đang on.
        ts_off = ts_base
        ts_on = ts_off + timedelta(seconds=random.randint(5, 60))
        actions.append(
            make_action(
                ts_off,
                entity_id,
                "off",
                presence,
                required_old_state="on",
                group_id=group_id,
                reason="dirty_accidental_off_then_on_step1",
            )
        )
        actions.append(
            make_action(
                ts_on,
                entity_id,
                "on",
                presence,
                group_id=group_id,
                depends_on_group=True,
                reason="dirty_accidental_off_then_on_step2",
            )
        )

    elif scenario == "accidental_on_then_off":
        # Chỉ hợp lệ nếu tại thời điểm replay thiết bị đang off.
        ts_on = ts_base
        ts_off = ts_on + timedelta(seconds=random.randint(5, 60))
        actions.append(
            make_action(
                ts_on,
                entity_id,
                "on",
                presence,
                required_old_state="off",
                group_id=group_id,
                reason="dirty_accidental_on_then_off_step1",
            )
        )
        actions.append(
            make_action(
                ts_off,
                entity_id,
                "off",
                presence,
                group_id=group_id,
                depends_on_group=True,
                reason="dirty_accidental_on_then_off_step2",
            )
        )

    else:
        # Rapid toggle: không cần biết state trước. Replay sẽ flip theo trạng thái thực tế.
        ts = ts_base
        current_desired = None
        for i in range(random.randint(2, 3)):
            # Dùng desired_state xen kẽ. Nếu event đầu bị skip do trùng state,
            # các event sau vẫn có thể tạo thay đổi thật, giống thao tác do dự ngoài đời.
            if current_desired is None:
                current_desired = random.choice(["on", "off"])
            else:
                current_desired = "off" if current_desired == "on" else "on"

            actions.append(
                make_action(
                    ts,
                    entity_id,
                    current_desired,
                    presence,
                    reason="dirty_rapid_toggle",
                )
            )
            ts += timedelta(seconds=random.randint(5, 90))

    return actions


# ── DB helpers ────────────────────────────────────────────────────────────────

def clear_synthetic_events() -> None:
    """Xóa dữ liệu synthetic cũ để tránh chạy generator nhiều lần bị duplicate."""
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM events WHERE source = 'synthetic'")
        conn.execute("DELETE FROM predictions")
    conn.close()
    print("[gen] Cleared old synthetic events and predictions")


# ── Main ─────────────────────────────────────────────────────────────────────

def generate(days: int = DAYS, *, clear_old: bool = False) -> int:
    init_db()

    if clear_old:
        clear_synthetic_events()

    total = 0
    device_states = _initial_states()
    start = datetime.now() - timedelta(days=days)

    for day_offset in range(days):
        date = (start + timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        presence = "away" if random.random() < PRESENCE_AWAY_PROB else "home"

        actions: list[dict[str, Any]] = []
        actions += simulate_light_bedroom(date, presence)
        actions += simulate_light_living_room(date, presence)
        actions += simulate_fan_bedroom(date, presence)
        actions += simulate_accidental_toggle(date, presence)

        day_events = materialize_actions(actions, device_states)
        day_events.sort(key=lambda event: event["timestamp"])

        for event in day_events:
            save_event(event)

        total += len(day_events)

        print(
            f"[gen] {date.strftime('%Y-%m-%d')} "
            f"({['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][date.weekday()]}) "
            f"presence={presence:4s}  actions={len(actions):2d}  events={len(day_events):2d}"
        )

    return total


if __name__ == "__main__":
    clear_old = "--clear" in sys.argv
    count = generate(DAYS, clear_old=clear_old)
    print(f"\n✅ Generated {count} events → {os.getenv('DB_PATH', 'data/behavior_agent.db')}")