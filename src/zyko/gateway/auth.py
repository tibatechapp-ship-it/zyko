"""Multi-user gateway authentication (0.7.0) — an identity layer, not just a token.

Roadmap item ("مصادقة متعددة المستخدمين للبوابة") from the pre-broad-production
order in ``docs/STRATEGY.md``: until 0.6 the gateway knew exactly one bearer
token. A :class:`UserStore` turns it into a governed multi-user surface:

* **declarative users file** (YAML) — each user declares a key (plaintext for
  dev, scrypt hash for production), roles, an optional per-user RPM and an
  optional per-user daily USD budget;
* **constant-time verification** — keys are compared with
  :func:`hmac.compare_digest`, and *every* enabled user's key is checked
  before returning, so response timing does not reveal which entry matched;
* **hashed keys by default in production** — ``zyko hash-key`` emits a
  stdlib :func:`hashlib.scrypt` record (``scrypt$n$r$p$salt$hash``) so the
  users file never has to hold a usable secret;
* **governance, not just authn** — per-user rate limiting (token bucket),
  per-user daily budget persisted across restarts (same pattern as the
  policy engine's budget), role scopes (``chat`` for ``/v1/*``, ``admin``),
  and a usage receipt per user inside every response.

Configuration problems raise :class:`~zyko.exceptions.GatewayAuthError`
before the server binds — a broken users file never half-starts a gateway.

Users file::

    name: team-gateway
    users:
      - name: alice
        key: zk-dev-only-plaintext
        roles: [chat]
      - name: ops
        key_hash: scrypt$16384$8$1$9f2c…$51ab…   # zyko hash-key
        roles: [chat, admin]
        rpm: 120
        daily_budget_usd: 5.0
      - name: intern
        key_hash: scrypt$16384$8$1$7c1d…$88ef…
        roles: [chat]
        enabled: false
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zyko.exceptions import GatewayAuthError
from zyko.log import get_logger

log = get_logger("gateway.auth")

ROLES: tuple[str, ...] = ("chat", "admin")
_STATE_FILE = "gateway_users_state.json"


def hash_key(key: str, *, n: int = 16384, r: int = 8, p: int = 1) -> str:
    """Hash an API key with stdlib scrypt → ``scrypt$n$r$p$salt_hex$hash_hex``.

    The salt is fresh per call (``secrets.token_bytes(16)``), so hashing the
    same key twice yields different records — that is correct hash behaviour,
    and verification only needs the record itself.
    """
    if not isinstance(key, str) or not key.strip():
        raise GatewayAuthError("cannot hash an empty key")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(key.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${digest.hex()}"


def verify_key(key: str, stored: str) -> bool:
    """Verify *key* against a plaintext or scrypt record, in constant time.

    Malformed ``scrypt$…`` records verify as False (never raise) — a broken
    entry in the users file must not turn into a 500.
    """
    if not isinstance(key, str) or not isinstance(stored, str):
        return False
    if stored.startswith("scrypt$"):
        try:
            _, n_s, r_s, p_s, salt_hex, hash_hex = stored.split("$")
            digest = hashlib.scrypt(
                key.encode("utf-8"),
                salt=bytes.fromhex(salt_hex),
                n=int(n_s),
                r=int(r_s),
                p=int(p_s),
                dklen=32,
            )
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(digest.hex(), hash_hex)
    return hmac.compare_digest(key, stored)


@dataclass
class GatewayUser:
    """One declared gateway identity (never carries the key in receipts)."""

    name: str
    roles: frozenset[str] = frozenset({"chat"})
    enabled: bool = True
    rpm: int | None = None
    daily_budget_usd: float | None = None
    stored_key: str = ""  # plaintext key or scrypt record — secret material

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    def public(self) -> dict[str, Any]:
        """Receipt-safe projection: identity and limits, never the key."""
        return {
            "name": self.name,
            "roles": sorted(self.roles),
            "enabled": self.enabled,
            "rpm": self.rpm,
            "daily_budget_usd": self.daily_budget_usd,
        }


class _Bucket:
    """Per-user token bucket (thread-safe; same maths as the policy engine)."""

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


class _UsageLedger:
    """Per-user daily usage persisted to one JSON file (survives restarts).

    Shape: ``{user_name: {"date": "YYYY-MM-DD", "spend_usd": float,
    "requests": int, "input_tokens": int, "output_tokens": int}}`` — the same
    day-reset pattern as the policy engine's budget file, one file for all
    users, atomic writes via tmp+rename.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def _today() -> str:
        return time.strftime("%Y-%m-%d")

    def today(self, name: str) -> dict[str, Any]:
        state = self._load().get(name) or {}
        if state.get("date") != self._today():
            return {
                "date": self._today(),
                "spend_usd": 0.0,
                "requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        return state

    def record(
        self,
        name: str,
        *,
        cost_usd: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> dict[str, Any]:
        with self._lock:
            all_state = self._load()
            today = self._today()
            entry = all_state.get(name) or {}
            if entry.get("date") != today:
                entry = {
                    "date": today,
                    "spend_usd": 0.0,
                    "requests": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                }
            entry["spend_usd"] = round(float(entry.get("spend_usd", 0.0)) + max(0.0, cost_usd), 8)
            entry["requests"] = int(entry.get("requests", 0)) + 1
            entry["input_tokens"] = int(entry.get("input_tokens", 0)) + max(0, input_tokens)
            entry["output_tokens"] = int(entry.get("output_tokens", 0)) + max(0, output_tokens)
            all_state[name] = entry
            self._save(all_state)
            return entry


class UserStore:
    """Loads and enforces a declared multi-user gateway configuration."""

    def __init__(self, users: list[GatewayUser], *, state_dir: Path | None = None) -> None:
        if not users:
            raise GatewayAuthError(
                "a users file must declare at least one user",
                hint="add a users: list with name + key (dev) or key_hash (production)",
            )
        names = [u.name for u in users]
        if len(set(names)) != len(names):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise GatewayAuthError(
                f"duplicate user name(s) in users file: {', '.join(dupes)}",
                hint="user names are identity keys for budgets and receipts — they must be unique",
            )
        self._users: dict[str, GatewayUser] = {u.name: u for u in users}
        self._buckets: dict[str, _Bucket] = {u.name: _Bucket(u.rpm) for u in users if u.rpm}
        from zyko.platform.paths import data_dir

        self.ledger = _UsageLedger((state_dir or data_dir(create=True)) / _STATE_FILE)
        log.info("user store loaded: %d user(s): %s", len(users), ", ".join(names))

    # --------------------------------------------------------------- loading
    @classmethod
    def load(
        cls,
        source: str | Path,
        *,
        state_dir: Path | None = None,
    ) -> "UserStore":
        """Load a users YAML file (path, or a name searched like agents).

        Searched un-suffixed, ``.yaml`` and ``.yml`` — same resolution rules
        as ``zk.crew("file")``. Anything malformed raises
        :class:`GatewayAuthError` **before** the gateway binds.
        """
        import yaml

        from zyko.agents.loader import _search_paths

        path = Path(source)
        candidates = [path] if path.is_absolute() else _search_paths(str(source))
        doc: dict[str, Any] | None = None
        for probe in candidates:
            for suffix in ("", ".yaml", ".yml"):
                target = probe if suffix == "" else Path(str(probe) + suffix)
                if target.is_file():
                    try:
                        loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
                    except Exception as exc:  # noqa: BLE001 - surfaced as GatewayAuthError
                        raise GatewayAuthError(f"invalid users file {target}: {exc}") from exc
                    if not isinstance(loaded, dict):
                        raise GatewayAuthError(
                            f"users file {target} must contain a YAML mapping with 'users:'"
                        )
                    doc = loaded
                    break
            if doc is not None:
                break
        if doc is None:
            raise GatewayAuthError(
                f"users file '{source}' not found",
                hint="searched: " + ", ".join(str(p) for p in candidates),
            )
        return cls.from_doc(doc, state_dir=state_dir, source=str(source))

    @classmethod
    def from_doc(
        cls,
        doc: dict[str, Any],
        *,
        state_dir: Path | None = None,
        source: str = "<doc>",
    ) -> "UserStore":
        raw_users = doc.get("users")
        if not isinstance(raw_users, list) or not raw_users:
            raise GatewayAuthError(
                f"users file '{source}' must declare a non-empty 'users:' list",
                hint="each user: name + key (plaintext, dev) or key_hash (scrypt, production)",
            )
        users: list[GatewayUser] = []
        for index, raw in enumerate(raw_users, 1):
            where = f"users[{index}] in '{source}'"
            if not isinstance(raw, dict):
                raise GatewayAuthError(f"{where} must be a mapping")
            name = raw.get("name")
            if not isinstance(name, str) or not name.strip():
                raise GatewayAuthError(f"{where} must declare a non-empty 'name'")
            where = f"user '{name}' in '{source}'"
            key = raw.get("key")
            key_hash = raw.get("key_hash")
            if (key is None) == (key_hash is None):
                raise GatewayAuthError(
                    f"{where} must declare exactly one of 'key' (plaintext) or "
                    f"'key_hash' (scrypt record from `zyko hash-key`)"
                )
            if key is not None and (not isinstance(key, str) or not key.strip()):
                raise GatewayAuthError(f"{where} has an empty 'key'")
            if key_hash is not None and (
                not isinstance(key_hash, str) or not key_hash.startswith("scrypt$")
            ):
                raise GatewayAuthError(
                    f"{where} has an invalid 'key_hash' — expected a scrypt$ record "
                    "from `zyko hash-key`",
                )
            roles_raw = raw.get("roles", ["chat"])
            if not isinstance(roles_raw, list) or not roles_raw:
                raise GatewayAuthError(f"{where} must declare a non-empty 'roles:' list")
            bad = [r for r in roles_raw if r not in ROLES]
            if bad:
                raise GatewayAuthError(
                    f"{where} declares unknown role(s) {bad} — known roles: {list(ROLES)}"
                )
            rpm = raw.get("rpm")
            if rpm is not None and (not isinstance(rpm, int) or isinstance(rpm, bool) or rpm < 1):
                raise GatewayAuthError(f"{where} has an invalid 'rpm' (positive integer)")
            budget = raw.get("daily_budget_usd")
            if budget is not None:
                if isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget <= 0:
                    raise GatewayAuthError(
                        f"{where} has an invalid 'daily_budget_usd' (positive number)"
                    )
                budget = float(budget)
            users.append(
                GatewayUser(
                    name=name,
                    roles=frozenset(roles_raw),
                    enabled=bool(raw.get("enabled", True)),
                    rpm=rpm,
                    daily_budget_usd=budget,
                    stored_key=str(key if key is not None else key_hash),
                )
            )
        return cls(users, state_dir=state_dir)

    # ----------------------------------------------------------- authentication
    def authenticate(self, token: str) -> GatewayUser | None:
        """Return the matching user, or ``None`` — in (near) constant time.

        Every enabled **and** disabled user's stored key is compared with
        :func:`hmac.compare_digest`; the loop never short-circuits on a
        match, so request timing does not leak which entry (or how far down
        the list) matched.
        """
        if not isinstance(token, str) or not token:
            return None
        matched: GatewayUser | None = None
        for user in self._users.values():
            if verify_key(token, user.stored_key):
                matched = user  # keep scanning — no early exit
        return matched

    # --------------------------------------------------------------- governance
    def check_rate(self, user: GatewayUser) -> bool:
        """Take one slot from the user's RPM bucket (True = allowed)."""
        bucket = self._buckets.get(user.name)
        return True if bucket is None else bucket.take()

    def budget_left(self, user: GatewayUser) -> float | None:
        """Remaining daily USD budget, or ``None`` when unlimited."""
        if user.daily_budget_usd is None:
            return None
        spent = float(self.ledger.today(user.name).get("spend_usd", 0.0))
        return max(0.0, user.daily_budget_usd - spent)

    def within_budget(self, user: GatewayUser) -> bool:
        left = self.budget_left(user)
        return left is None or left > 0.0

    def record_usage(
        self,
        user: GatewayUser,
        *,
        cost_usd: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> dict[str, Any]:
        """Persist one request's usage into the user's daily ledger entry."""
        return self.ledger.record(
            user.name,
            cost_usd=cost_usd,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    # ------------------------------------------------------------------- views
    def get(self, name: str) -> GatewayUser | None:
        return self._users.get(name)

    def snapshot(self) -> list[dict[str, Any]]:
        """Receipt-safe view of every declared user (no secrets, ever)."""
        return [u.public() for u in self._users.values()]


__all__ = [
    "GatewayUser",
    "UserStore",
    "hash_key",
    "verify_key",
    "ROLES",
]
