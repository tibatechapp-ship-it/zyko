"""Response cache — exact-match TTL cache for routed completions.

Competitive parity with LiteLLM / Portkey gateways: identical requests
inside the TTL window are served from memory instead of billing the vendor
again. The cache key is the SHA-256 of the *canonical outbound payload*
(provider, model, messages, temperature, max_tokens, tools, tool_choice),
so a hit is guaranteed to be the same call the vendor would have answered.

Design notes:

- **Policy-gated**: the cache exists only when a policy declares a
  ``cache:`` section (``enabled: true``). No policy, no cache — the
  default behaviour stays identical to previous releases.
- **Per-candidate keys**: keys include the chosen ``provider/model``, so a
  cached ``openai/gpt-4o-mini`` answer is never served for a request that
  routed to ``anthropic/*``.
- **Bounded**: LRU eviction at ``max_entries`` (default 512), TTL expiry
  (default 300 s) on a monotonic clock — immune to wall-clock changes.
- **Agent-safe**: responses carrying ``tool_calls`` are not stored by
  default — replaying tool calls from a cache can desynchronise agent
  loops.
- **Schema-aware keys** (v2 basis): ``response_format`` is part of the key,
  so a cached free-text answer is never served for a structured call.
- **Streaming bypasses the cache** (v1): only ``aroute()`` reads/writes.
- Requests opt out per call via ``metadata={"cache": "bypass"}`` and can
  force a re-validation with ``metadata={"cache": "refresh"}`` (skip the
  read, still store the fresh answer).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any

from zyko.core.messages import messages_to_openai
from zyko.core.response import ChatRequest, ChatResponse
from zyko.log import get_logger

log = get_logger("cache")

DEFAULT_TTL_S = 300.0
DEFAULT_MAX_ENTRIES = 512

# metadata={"cache": ...} request-level overrides
_BYPASS_VALUES = {"bypass", "off", "no", "false"}
_REFRESH_VALUES = {"refresh", "revalidate", "force"}

KNOWN_CACHE_KEYS = {"enabled", "ttl_s", "max_entries"}


class ResponseCache:
    """Thread-safe, bounded, exact-match response cache with TTL expiry."""

    def __init__(
        self, *, ttl_s: float = DEFAULT_TTL_S, max_entries: int = DEFAULT_MAX_ENTRIES
    ) -> None:
        if ttl_s <= 0:
            raise ValueError(f"cache ttl_s must be > 0, got {ttl_s!r}")
        if max_entries <= 0:
            raise ValueError(f"cache max_entries must be > 0, got {max_entries!r}")
        self.ttl_s = float(ttl_s)
        self.max_entries = int(max_entries)
        self._store: OrderedDict[str, tuple[float, ChatResponse]] = OrderedDict()
        self._lock = threading.Lock()
        self.stats: dict[str, int] = {
            "hits": 0,
            "misses": 0,
            "stores": 0,
            "bypasses": 0,
            "expiries": 0,
            "evictions": 0,
        }

    # ------------------------------------------------------------------- key
    @staticmethod
    def key_for(request: ChatRequest, *, provider: str, model: str) -> str:
        """Stable SHA-256 over the canonical outbound payload.

        ``messages_to_openai`` is the same serialisation every OpenAI-compatible
        adapter sends, so the key reflects exactly what would hit the wire.
        """
        basis = {
            "v": 2,
            "provider": provider,
            "model": model,
            "messages": messages_to_openai(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "tools": request.tools or None,
            "tool_choice": request.tool_choice,
            "response_format": request.response_format,
        }
        raw = json.dumps(basis, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # ----------------------------------------------------------- mode switch
    @staticmethod
    def cache_mode(request: ChatRequest) -> str:
        """``"read/write"`` | ``"bypass"`` | ``"refresh"`` from request metadata."""
        value = (request.metadata or {}).get("cache")
        text = str(value).strip().lower() if value is not None else ""
        if text in _BYPASS_VALUES:
            return "bypass"
        if text in _REFRESH_VALUES:
            return "refresh"
        return "read/write"

    # ------------------------------------------------------------------- ops
    def get(self, key: str) -> ChatResponse | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.stats["misses"] += 1
                return None
            stored_at, response = entry
            if time.monotonic() - stored_at > self.ttl_s:
                del self._store[key]
                self.stats["expiries"] += 1
                self.stats["misses"] += 1
                return None
            self._store.move_to_end(key)  # LRU touch
            self.stats["hits"] += 1
            return response

    def set(self, key: str, response: ChatResponse) -> None:
        with self._lock:
            self._store[key] = (time.monotonic(), response)
            self._store.move_to_end(key)
            self.stats["stores"] += 1
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)
                self.stats["evictions"] += 1

    def clear(self) -> int:
        with self._lock:
            count = len(self._store)
            self._store.clear()
            return count

    def size(self) -> int:
        """Current entry count. Deliberately NOT ``__len__`` — an empty cache
        must stay truthy so ``if cache:`` never silently disables caching."""
        with self._lock:
            return len(self._store)

    # ------------------------------------------------------------ visibility
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            lookups = self.stats["hits"] + self.stats["misses"]
            return {
                "enabled": True,
                "ttl_s": self.ttl_s,
                "max_entries": self.max_entries,
                "entries": len(self._store),
                "hit_rate": round(self.stats["hits"] / lookups, 4) if lookups else 0.0,
                **dict(self.stats),
            }


__all__ = ["ResponseCache", "DEFAULT_TTL_S", "DEFAULT_MAX_ENTRIES", "KNOWN_CACHE_KEYS"]
