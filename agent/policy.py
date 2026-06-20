"""Context-aware Policy Gate for Behavioral Agent Phase 2."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.device_registry import get_device


@dataclass(frozen=True)
class PolicyDecision:
    decision: str  # allow | confirm_required | block | observe_only
    reason_code: str
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"


@dataclass
class PolicyGate:
    confidence_threshold: float = 0.70
    cooldown_seconds: float = 300.0

    def _environment_reason(self, device_type: str, context: dict[str, Any]) -> tuple[str, str]:
        hot = bool(context.get("is_hot", 0))
        humid = bool(context.get("is_humid", 0))
        dry = bool(context.get("is_dry", 0))
        lr_temp = float(context.get("living_room_temperature", 0) or 0)
        lr_hum = float(context.get("living_room_humidity", 0) or 0)
        
        if device_type == "fan" and hot and not humid:
            return "HOT_DRY_FAN", f"Nóng và độ ẩm không cao (living_room={lr_temp:.1f}°C/{lr_hum:.0f}%), quạt trần là lựa chọn hợp lý"
        if device_type == "air_conditioner" and hot and humid:
            return "HOT_HUMID_AC", f"Nóng và ẩm (living_room={lr_temp:.1f}°C/{lr_hum:.0f}%), điều hòa hợp lý nhưng cần xác nhận"
        if device_type == "air_conditioner" and humid:
            return "HUMID_AC", f"Độ ẩm cao ({lr_hum:.0f}%), điều hòa/hút ẩm hợp lý nhưng cần xác nhận"
        if dry:
            return "DRY_CONTEXT", "Độ ẩm thấp; tránh bật thiết bị làm khô thêm nếu không cần"
            
        return "CONTEXT_OK", "Context phù hợp với policy Phase 2"

    def _confirm_reason(self, device_type: str, context: dict[str, Any]) -> tuple[str, str]:
        env_code, env_reason = self._environment_reason(device_type, context)
        
        if device_type == "water_heater":
            return "WATER_HEATER_CONFIRM_REQUIRED", "Bình nước nóng là thiết bị rủi ro cao, luôn cần xác nhận"
        if device_type == "tv":
            return "TV_CONFIRM_REQUIRED", "TV là thiết bị cần xác nhận, không tự động bật/tắt trong Phase 2"
        if device_type == "air_conditioner":
            return "CLIMATE_CONFIRM_REQUIRED", env_reason if env_code in {"HOT_HUMID_AC", "HUMID_AC"} else "Điều hòa cần xác nhận trong Phase 2"
            
        return "HIGH_RISK_DEVICE", "Thiết bị không thuộc nhóm auto low-risk, cần xác nhận"

    def evaluate(self, entity_id: str, action: str, confidence: float, context: dict[str, Any] | None = None) -> PolicyDecision:
        context = context or {}
        device = get_device(entity_id)
        
        if device is None:
            return PolicyDecision("block", "UNKNOWN_ENTITY", f"Unknown entity: {entity_id}")
        if action in {"no_action", "none", None}:
            return PolicyDecision("block", "NO_ACTION", "No device action requested")
        if action not in {"turn_on", "turn_off"}:
            return PolicyDecision("block", "UNSUPPORTED_ACTION", f"Unsupported action: {action}")
        if device.control_level == "observe_only" or device.device_type in {"door_lock", "camera_presence", "temperature", "humidity", "washing_machine"}:
            return PolicyDecision("observe_only", "OBSERVE_ONLY", f"{entity_id} là observe-only, Agent không được điều khiển")

        prev_state = int(context.get("prev_state", 0) or 0)
        if action == "turn_on" and prev_state == 1:
            return PolicyDecision("block", "ALREADY_ON", "Thiết bị đã bật")
        if action == "turn_off" and prev_state == 0:
            return PolicyDecision("block", "ALREADY_OFF", "Thiết bị đã tắt")

        overdue = bool(context.get("is_arrival_overdue", 0)) or float(context.get("minutes_after_expected_arrival", 0) or 0) >= 20 and not int(context.get("presence_home", 0) or 0)
        if action == "turn_on" and overdue:
            return PolicyDecision("block", "ARRIVAL_OVERDUE", "User chưa về sau expected arrival window; không tự động bật thêm thiết bị")

        if confidence < self.confidence_threshold:
            return PolicyDecision("block", "LOW_CONFIDENCE", f"confidence {confidence:.2f} < threshold {self.confidence_threshold:.2f}")

        if context.get("recent_manual_override", 0):
            return PolicyDecision("block", "MANUAL_OVERRIDE_COOLDOWN", "User vừa override thủ công, Agent không can thiệp")
            
        if context.get("recent_toggle_count_2min", 0) > 0 or context.get("recent_toggle_count_5min", 0) >= 2:
            return PolicyDecision("block", "COOLDOWN", "Thiết bị vừa được thao tác gần đây")
            
        elapsed = float(context.get("time_since_change_s", 99999.0) or 0.0)
        if elapsed < self.cooldown_seconds:
            return PolicyDecision("block", "COOLDOWN", f"cooldown active ({elapsed:.0f}s / {self.cooldown_seconds:.0f}s)")

        if device.control_level == "confirm" or device.risk_level == "high" or device.device_type in {"water_heater", "tv", "air_conditioner"}:
            code, reason = self._confirm_reason(device.device_type, context)
            return PolicyDecision("confirm_required", code, reason)

        presence_home = int(context.get("presence_home", 0) or 0)
        pre_arrival = int(context.get("is_before_arrival_window", 0) or 0)
        predicted_arrival = float(context.get("predicted_arrival_minutes", 999) or 999)
        valid_pre_arrival = pre_arrival and 10 <= predicted_arrival <= 15
        
        if action == "turn_on" and not presence_home and not (valid_pre_arrival and device.risk_level == "low"):
            return PolicyDecision("block", "NO_PRESENCE", "User không ở nhà và không nằm trong pre-arrival window hợp lệ")

        if device.control_level == "auto" and device.risk_level == "low" and device.device_type in {"light", "fan"}:
            env_code, env_reason = self._environment_reason(device.device_type, context)
            
            if valid_pre_arrival and action == "turn_on" and device.device_type == "fan":
                return PolicyDecision("allow", "PRE_ARRIVAL_COMFORT_FAN", "Cho phép bật quạt trước giờ về 10–15 phút vì thiết bị low-risk")
                
            if device.device_type == "fan" and action == "turn_on" and env_code not in {"HOT_DRY_FAN", "CONTEXT_OK"}:
                return PolicyDecision("block", "ENVIRONMENT_NOT_SUITABLE", env_reason)
                
            return PolicyDecision("allow", env_code if env_code != "CONTEXT_OK" else "AUTO_LOW_RISK_OK", env_reason)

        return PolicyDecision("confirm_required", "CONFIRM_REQUIRED", "Thiết bị cần xác nhận trước khi thực thi")

    def check(self, entity_id: str, domain: str, action: str, confidence: float, context: dict | None = None) -> tuple[bool, str]:
        decision = self.evaluate(entity_id, action, confidence, context)
        return decision.allowed, decision.reason


if __name__ == "__main__":
    gate = PolicyGate()
    cases = [
        ("switch.living_room_ceiling_fan", "turn_on", 0.90, {"presence_home": 1, "prev_state": 0, "time_since_change_s": 600, "is_hot": 1, "is_humid": 0, "living_room_temperature": 31, "living_room_humidity": 64}, "allow", "HOT_DRY_FAN"),
        ("switch.living_room_ceiling_fan", "turn_on", 0.90, {"presence_home": 0, "is_before_arrival_window": 1, "predicted_arrival_minutes": 12, "prev_state": 0, "time_since_change_s": 600, "is_hot": 1, "is_humid": 0}, "allow", "PRE_ARRIVAL_COMFORT_FAN"),
        ("climate.living_room_ac", "turn_on", 0.92, {"presence_home": 1, "prev_state": 0, "time_since_change_s": 600, "is_hot": 1, "is_humid": 1, "living_room_temperature": 32, "living_room_humidity": 84}, "confirm_required", "CLIMATE_CONFIRM_REQUIRED"),
        ("media_player.living_room_tv", "turn_on", 0.92, {"presence_home": 1, "prev_state": 0, "time_since_change_s": 600}, "confirm_required", "TV_CONFIRM_REQUIRED"),
        ("switch.bathroom_water_heater", "turn_on", 0.92, {"presence_home": 1, "prev_state": 0, "time_since_change_s": 600}, "confirm_required", "WATER_HEATER_CONFIRM_REQUIRED"),
        ("binary_sensor.front_door_lock", "turn_on", 0.99, {"presence_home": 1, "prev_state": 0, "time_since_change_s": 600}, "observe_only", "OBSERVE_ONLY"),
        ("switch.living_room_ceiling_fan", "turn_on", 0.90, {"presence_home": 0, "is_arrival_overdue": 1, "minutes_after_expected_arrival": 25, "prev_state": 0, "time_since_change_s": 600}, "block", "ARRIVAL_OVERDUE"),
        ("light.bedroom_light", "turn_on", 0.90, {"presence_home": 1, "prev_state": 1, "time_since_change_s": 600}, "block", "ALREADY_ON"),
    ]
    
    all_pass = True
    print(f"{'Entity':<38} {'Action':<8} {'Expect':<16} {'Got':<16} Reason")
    print("-" * 112)
    
    for entity_id, action, confidence, context, expected_decision, expected_reason in cases:
        result = gate.evaluate(entity_id, action, confidence, context)
        ok = result.decision == expected_decision and result.reason_code == expected_reason
        all_pass = all_pass and ok
        print(f"{entity_id:<38} {action:<8} {expected_decision:<16} {result.decision:<16} {result.reason_code} {'✅' if ok else '❌'}")
        
    print(f"\n{'Tất cả policy checks pass ✅' if all_pass else 'Có policy check FAIL ❌'}")
    raise SystemExit(0 if all_pass else 1)