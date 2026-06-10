"""
policy.py — Policy Gate: kiểm tra trước khi agent điều khiển thiết bị

Dùng:
    from agent.policy import PolicyGate
    gate = PolicyGate()
    allowed, reason = gate.check(entity_id, domain, confidence, context)
"""

from dataclasses import dataclass, field

ALLOWED_ENTITIES_DEFAULT = [
    "light.bedroom",
    "light.living_room",
    "switch.fan_bedroom",
]

BLOCKED_DOMAINS_DEFAULT = ["lock", "camera", "cover", "water_heater"]


@dataclass
class PolicyGate:
    confidence_threshold: float       = 0.85
    cooldown_seconds:     float       = 300.0
    allowed_entities:     list[str]   = field(default_factory=lambda: list(ALLOWED_ENTITIES_DEFAULT))
    blocked_domains:      list[str]   = field(default_factory=lambda: list(BLOCKED_DOMAINS_DEFAULT))

    def check(self, entity_id: str, domain: str,
              confidence: float, context: dict) -> tuple[bool, str]:
        """
        Trả về (allowed, reason).

        context cần có:
            presence_home           : int  0|1
            recent_toggle_count_2min: int
            recent_toggle_count_5min: int
            time_since_change_s     : float
        """
        if confidence < self.confidence_threshold:
            return False, f"confidence {confidence:.2f} < threshold {self.confidence_threshold}"

        if entity_id not in self.allowed_entities:
            return False, f"entity '{entity_id}' không trong allowed_entities"

        if domain in self.blocked_domains:
            return False, f"domain '{domain}' bị chặn"

        if not context.get("presence_home", 0):
            return False, "không có người ở nhà"

        if context.get("recent_toggle_count_2min", 0) > 0:
            return False, "thiết bị vừa được thao tác trong 2 phút"

        if context.get("recent_toggle_count_5min", 0) >= 2:
            return False, "thiết bị toggle >= 2 lần trong 5 phút"

        if context.get("time_since_change_s", 0) < self.cooldown_seconds:
            elapsed = context["time_since_change_s"]
            return False, f"cooldown chưa hết ({elapsed:.0f}s / {self.cooldown_seconds:.0f}s)"

        return True, "ok"


if __name__ == "__main__":
    gate = PolicyGate()

    # Test cases
    base_ctx = {
        "presence_home":            1,
        "recent_toggle_count_2min": 0,
        "recent_toggle_count_5min": 0,
        "time_since_change_s":      600,
    }

    cases = [
        ("light.bedroom",   "light",  0.91, base_ctx,                                        True),
        ("light.bedroom",   "light",  0.70, base_ctx,                                        False),
        ("lock.front_door", "lock",   0.95, base_ctx,                                        False),
        ("light.bedroom",   "light",  0.91, {**base_ctx, "presence_home": 0},                False),
        ("light.bedroom",   "light",  0.91, {**base_ctx, "recent_toggle_count_2min": 1},     False),
        ("light.bedroom",   "light",  0.91, {**base_ctx, "time_since_change_s": 100},        False),
    ]

    print(f"{'Entity':<22} {'Conf':>5}  {'Expect':>6}  {'Got':>6}  Reason")
    print("-" * 75)
    all_pass = True
    for entity_id, domain, conf, ctx, expected in cases:
        allowed, reason = gate.check(entity_id, domain, conf, ctx)
        ok = "✅" if allowed == expected else "❌"
        if allowed != expected:
            all_pass = False
        print(f"{entity_id:<22} {conf:>5.2f}  {str(expected):>6}  {str(allowed):>6}  {reason}  {ok}")

    print(f"\n{'Tất cả test pass ✅' if all_pass else 'Có test FAIL ❌'}")