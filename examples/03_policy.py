"""03 — Policy-as-Code: redaction, budgets, allowlists — declaratively."""

from zyko.policy.engine import PolicyEngine

policy = PolicyEngine(
    {
        "version": 1,
        "name": "demo",
        "defaults": {"budget_usd_per_day": 2.0, "max_tokens_per_request": 512},
        "models": {"allow": ["*"], "deny": ["*opus*"]},
        "privacy": {"redact": ["email", "credit_card", "phone"]},
    }
)

# 1) Deterministic redaction — same input, same outbound payload, always.
cleaned = policy.redact_text("invoice for card 4111 1111 1111 1111, mail billing@corp.com")
print("redacted:", cleaned)

# 2) Budget accounting survives restarts (state on disk).
from zyko.router.engine import RouteCandidate

candidate = RouteCandidate("openai", "gpt-4o-mini")
policy.record_cost(0.0031, candidate)
print("budget remaining: $%.4f" % (policy.snapshot()["budget_remaining_usd"] or 0))

# 3) Wire it into ZYKO and every call is governed automatically:
#   zk = Zyko(policy="my-policy")        # from ~/.config/zyko/policies/my-policy.yaml
#   zk = Zyko(policy=policy)             # or pass the engine directly
