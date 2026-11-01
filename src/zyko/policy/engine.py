"""Policy-as-Code engine: declarative governance for every AI call.

A policy is a YAML document (schema below) that the engine enforces
*before* any vendor call and on every route attempt::

    version: 1
    name: default
    defaults:
      budget_usd_per_day: 5.0
      max_tokens_per_request: 4096
    models:
      allow: ["*"]
      deny: []
    providers:
      allow: ["*"]
    tools:
      allow: ["*"]
      deny: ["shell"]
    privacy:
      redact: [email, phone, credit_card, iban, ssn]
      custom: []                    # [{pattern: "...", replace: "..."}]
    rate_limit:
      requests_per_minute: 60
    audit:
      enabled: true

Denials raise :class:`PolicyViolation` with the triggering rule; redaction
rewrites message content deterministically so the same input always yields
the same outbound payload — auditable and reproducible.
"""

from __future__ import annotations

import fnmatch
import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zyko.core.response import ChatRequest
from zyko.exceptions import BudgetExceededError, ConfigError, LocalRateLimitError
from zyko.log import get_logger
from zyko.platform.paths import audit_log, policies_search_dirs

log = get_logger("policy")

BUILTIN_PATTERNS: dict[str, tuple[str, str]] = {
    "email": (r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "[EMAIL]"),
    "ssn": (r"\b\d{3}-\d{2}-\d{4}\b", "[SSN]"),
    "iban": (r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b", "[IBAN]"),
    "credit_card": (r"\b(?:\d[ -]?){13,19}\b", "[CREDIT_CARD]"),
    "phone": (r"(?<![\w-])\+?\d[\d\s().\-]{8,}\d(?![\w-])", "[PHONE]"),
}

# Card/IBAN digit runs must be redacted BEFORE the generic phone pattern sees
# them, so pattern application order is fixed regardless of user list order.
_PATTERN_PRIORITY = {"credit_card": 0, "iban": 1, "ssn": 2, "email": 3, "phone": 4}

# Keys the policy schema understands; anything else is almost certainly a
# typo that would otherwise silently disable a control the author believed
# was active ("privcy:", "budget_per_day:", ...).
KNOWN_TOP_LEVEL = {
    "version", "name", "defaults", "models", "providers", "tools",
    "privacy", "rate_limit", "audit",
}
KNOWN_DEFAULTS_KEYS = {"budget_usd_per_day", "max_tokens_per_request"}


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


@dataclass
class Redactor:
    rules: list[tuple[str, str, str]] = field(default_factory=list)  # (compiled, replace, label)

    @classmethod
    def from_doc(cls, privacy: dict[str, Any]) -> "Redactor":
        rules: list[tuple[str, str, str]] = []
        for name in privacy.get("redact") or []:
            if name not in BUILTIN_PATTERNS:
                raise ConfigError(
                    f"unknown builtin redaction pattern '{name}'",
                    hint=f"available: {', '.join(BUILTIN_PATTERNS)}",
                )
            pattern, replace = BUILTIN_PATTERNS[name]
            rules.append((_PATTERN_PRIORITY.get(name, 9), re.compile(pattern), replace, name))
        for custom in privacy.get("custom") or []:
            try:
                rules.append((9, re.compile(custom["pattern"]), custom.get("replace", "[REDACTED]"), "custom"))
            except (KeyError, re.error) as exc:
                raise ConfigError(f"invalid custom redaction rule: {exc}") from exc
        rules.sort(key=lambda r: r[0])
        return cls([(regex, replace, label) for _, regex, replace, label in rules])

    def __bool__(self) -> bool:
        return bool(self.rules)

    def apply(self, text: str) -> tuple[str, list[str]]:
        applied: list[str] = []
        for regex, replace, label in self.rules:
            def _sub(match: re.Match[str], *, _label=label, _replace=replace) -> str:
                if _label == "credit_card":
                    digits = re.sub(r"\D", "", match.group(0))
                    if not (12 <= len(digits) <= 19) or not _luhn_ok(digits):
                        return match.group(0)  # looks like a date/order number
                applied.append(_label)
                return _replace

            text = regex.sub(_sub, text)
        return text, applied


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str = ""
    request: ChatRequest | None = None
    redactions: list[str] = field(default_factory=list)


class _TokenBucket:
    def __init__(self, rpm: int) -> None:
        self.capacity = max(1, rpm)
        self.tokens = float(self.capacity)
        self.refill_per_s = self.capacity / 60.0
        self.updated = time.monotonic()
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.refill_per_s)
            self.updated = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False


class _Budget:
    """Daily USD budget persisted to disk; state survives restarts."""

    def __init__(self, cap_usd: float | None, path: Path) -> None:
        self.cap = cap_usd
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def spent_today(self) -> float:
        state = self._load()
        return float(state.get("spend_usd", 0.0)) if state.get("date") == time.strftime("%Y-%m-%d") else 0.0

    def remaining(self) -> float | None:
        return None if self.cap is None else max(0.0, self.cap - self.spent_today())

    def add(self, cost_usd: float) -> float:
        with self._lock:
            state = self._load()
            today = time.strftime("%Y-%m-%d")
            if state.get("date") != today:
                state = {"date": today, "spend_usd": 0.0}
            state["spend_usd"] = round(float(state.get("spend_usd", 0.0)) + max(0.0, cost_usd), 8)
            self._save(state)
            return float(state["spend_usd"])


class PolicyEngine:
    """Loads a policy document and enforces it on every request."""

    def __init__(self, doc: dict[str, Any], *, state_dir: Path | None = None) -> None:
        if not isinstance(doc, dict):
            raise ConfigError("policy document must be a mapping")
        version = doc.get("version", 1)
        if version != 1:
            raise ConfigError(f"unsupported policy schema version: {version!r} (expected 1)")
        self.doc = doc
        self.name = doc.get("name", "unnamed")
        defaults = doc.get("defaults") or {}
        self.max_tokens = defaults.get("max_tokens_per_request")
        budget_cap = defaults.get("budget_usd_per_day")
        from zyko.platform.paths import data_dir

        base = state_dir or data_dir(create=True)
        self.budget = _Budget(float(budget_cap) if budget_cap is not None else None, base / "budget_state.json")
        self.redactor = Redactor.from_doc(doc.get("privacy") or {})
        rate = (doc.get("rate_limit") or {}).get("requests_per_minute")
        self.bucket = _TokenBucket(int(rate)) if rate else None
        self.audit_enabled = bool((doc.get("audit") or {}).get("enabled", True))
        self.stats = {"requests_allowed": 0, "requests_denied": 0, "redactions": 0, "denied_by_rule": {}}
        self.warnings = self._schema_warnings(doc)

    # ------------------------------------------------------------------ models
    @staticmethod
    def _schema_warnings(doc: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        for key in doc:
            if key not in KNOWN_TOP_LEVEL:
                warnings.append(f"unknown top-level key '{key}' (typo? ignored)")
        defaults = doc.get("defaults") or {}
        if not isinstance(defaults, dict):
            warnings.append("'defaults' must be a mapping")
        else:
            for key in defaults:
                if key not in KNOWN_DEFAULTS_KEYS:
                    warnings.append(f"unknown key 'defaults.{key}' (typo? ignored)")
        privacy = doc.get("privacy")
        if privacy is not None and not isinstance(privacy, dict):
            warnings.append("'privacy' must be a mapping")
        return warnings

    def _matches(self, name: str, patterns: list[str]) -> bool:
        return any(fnmatch.fnmatchcase(name, p) for p in patterns)

    def allows_model(self, provider: str, model: str) -> bool:
        models = self.doc.get("models") or {}
        allow = models.get("allow", ["*"])
        deny = models.get("deny", [])
        qualified = f"{provider}/{model}"
        for candidate in (qualified, model):
            if self._matches(candidate, deny):
                return False
        return self._matches(qualified, allow) or self._matches(model, allow)

    def allows_provider(self, provider: str) -> bool:
        allow = (self.doc.get("providers") or {}).get("allow", ["*"])
        return self._matches(provider, allow)

    def allows_tool(self, tool_name: str) -> bool:
        tools = self.doc.get("tools") or {}
        deny = tools.get("deny", [])
        if self._matches(tool_name, deny):
            return False
        return self._matches(tool_name, tools.get("allow", ["*"]))

    def explicitly_allows_tool(self, tool_name: str) -> bool:
        """True only when *tool_name* is named literally in ``tools.allow``.

        Used for danger tools (e.g. ``shell``): a ``*`` wildcard must never
        unlock them by accident.
        """
        allow = (self.doc.get("tools") or {}).get("allow", [])
        return tool_name in allow

    # ----------------------------------------------------------------- request
    def check_request(self, request: ChatRequest, candidate: Any) -> PolicyDecision:
        """Full pre-flight: provider, model, budget, rate, tokens, redaction."""
        if not self.allows_provider(candidate.provider):
            return self._deny("providers.allow", f"provider '{candidate.provider}' is not allowed")
        if not self.allows_model(candidate.provider, candidate.model):
            return self._deny("models.deny", f"model '{candidate.provider}/{candidate.model}' is not allowed")

        if self.budget.cap is not None and self.budget.remaining() <= 0.0:
            raise BudgetExceededError(
                f"daily budget of ${self.budget.cap:.2f} is exhausted",
                rule="defaults.budget_usd_per_day",
                hint="raise the cap or wait for the daily reset (UTC)",
            )
        if self.bucket and not self.bucket.take():
            raise LocalRateLimitError(
                f"local rate limit of {self.bucket.capacity} requests/minute exceeded",
                rule="rate_limit.requests_per_minute",
            )

        effective = request
        cap = self.max_tokens
        if cap and (request.max_tokens is None or request.max_tokens > cap):
            effective = ChatRequest(
                messages=request.messages,
                model=request.model,
                temperature=request.temperature,
                max_tokens=cap,
                tools=request.tools,
                tool_choice=request.tool_choice,
                metadata=request.metadata,
            )

        applied: list[str] = []
        if self.redactor:
            new_messages = []
            for message in effective.messages:
                if message.content:
                    cleaned, labels = self.redactor.apply(message.content)
                    applied.extend(labels)
                    new_messages.append(message.map_content(lambda _t: cleaned) if labels else message)
                else:
                    new_messages.append(message)
            effective = ChatRequest(
                messages=new_messages,
                model=effective.model,
                temperature=effective.temperature,
                max_tokens=effective.max_tokens,
                tools=effective.tools,
                tool_choice=effective.tool_choice,
                metadata=effective.metadata,
            )
        if applied:
            self.stats["redactions"] += len(applied)
        self.stats["requests_allowed"] += 1
        self._audit("allow", candidate, list(dict.fromkeys(applied)))
        return PolicyDecision(True, "ok", effective, sorted(set(applied)))

    def _deny(self, rule: str, reason: str) -> PolicyDecision:
        self.stats["requests_denied"] += 1
        self.stats["denied_by_rule"][rule] = self.stats["denied_by_rule"].get(rule, 0) + 1
        self._audit("deny", None, [], reason=reason, rule=rule)
        return PolicyDecision(False, reason)

    # ------------------------------------------------------------------ usage
    def record_cost(self, cost_usd: float, candidate: Any, *, estimated: bool = False) -> None:
        """Account spend against the daily budget.

        ``estimated=True`` marks kernel-estimated stream costs (vendor usage
        was unavailable); the audit entry records the accounting source.
        """
        if cost_usd and cost_usd > 0:
            spent = self.budget.add(cost_usd)
            log.debug("policy: +%0.6f USD (day total %.4f, estimated=%s)", cost_usd, spent, estimated)
            self._audit("usage", candidate, [], cost=cost_usd, spent_today=spent, estimated=estimated)

    def record_stream_open(self, candidate: Any) -> None:
        self._audit("stream_open", candidate, [])

    # ------------------------------------------------------------------ misc
    def _audit(self, event: str, candidate: Any, redactions: list[str], **extra: Any) -> None:
        if not self.audit_enabled:
            return
        entry = {
            "ts": time.time(),
            "policy": self.name,
            "event": event,
            "candidate": getattr(candidate, "key", None),
            "redactions": redactions,
            **extra,
        }
        try:
            path = audit_log()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:  # never break a request because auditing failed
            log.warning("audit write failed: %s", exc)

    def snapshot(self) -> dict[str, Any]:
        return {
            "policy": self.name,
            "budget_remaining_usd": self.budget.remaining(),
            "redaction_active": bool(self.redactor),
            "rate_limit_rpm": self.bucket.capacity if self.bucket else None,
            "warnings": list(self.warnings),
            "stats": dict(self.stats),
        }

    def redact_text(self, text: str) -> str:
        cleaned, _ = self.redactor.apply(text) if self.redactor else (text, [])
        return cleaned


def load_policy(name_or_path: str | Path) -> PolicyEngine:
    """Resolve a policy by absolute path, relative path, or name."""
    import yaml

    path = Path(name_or_path)
    candidates = [path] if path.is_absolute() else [Path.cwd() / path, *(d / name_or_path for d in policies_search_dirs())]
    for cand in candidates:
        for suffix in ("", ".yaml", ".yml"):
            probe = cand.with_suffix(cand.suffix) if suffix == "" else Path(str(cand) + suffix)
            if probe.is_file():
                try:
                    doc = yaml.safe_load(probe.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise ConfigError(f"invalid policy file {probe}: {exc}") from exc
                if not isinstance(doc, dict):
                    raise ConfigError(f"policy file {probe} must contain a YAML mapping")
                doc.setdefault("name", probe.stem)
                return PolicyEngine(doc)
    raise ConfigError(
        f"policy '{name_or_path}' not found",
        hint="searched: " + ", ".join(str(d) for d in [Path.cwd(), *policies_search_dirs()]),
    )


def builtin_default_policy() -> dict[str, Any]:
    return {
        "version": 1,
        "name": "default",
        "defaults": {"max_tokens_per_request": 4096},
        "models": {"allow": ["*"], "deny": []},
        "tools": {"allow": ["*"], "deny": []},
        "privacy": {"redact": []},
    }


__all__ = [
    "PolicyEngine",
    "PolicyDecision",
    "Redactor",
    "load_policy",
    "builtin_default_policy",
    "BUILTIN_PATTERNS",
]
