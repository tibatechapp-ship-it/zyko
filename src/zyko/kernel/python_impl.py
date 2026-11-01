"""Pure-Python reference implementations of ZYKO's hot-path math.

The optional Rust extension (``zyko-kernel``, PyO3) provides identical
semantics for these functions with better throughput; when it is not
installed — e.g. on Termux without a toolchain — ZYKO transparently falls
back to this module. Correctness first, speed optional.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence


def estimate_tokens(text: str) -> int:
    """Documented heuristic: ~4 chars/token, floored by the word count.

    Good enough for routing/cost estimation (±20%); never used for billing.
    """
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4, len(text.split()))


def estimate_messages_tokens(messages: Iterable[Any]) -> int:
    total = 0
    for message in messages:
        content = getattr(message, "content", None) or ""
        total += estimate_tokens(content) + 4  # role/structure overhead
        for call in getattr(message, "tool_calls", None) or []:
            total += estimate_tokens(str(call.arguments)) + 8
    return total


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def top_k(scores: Sequence[float], k: int) -> list[int]:
    """Indices of the *k* highest scores, best first (stable)."""
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return order[: max(0, k)]


def moving_average(values: Sequence[float], window: int) -> list[float]:
    if window <= 1 or not values:
        return list(values)
    out: list[float] = []
    running = 0.0
    for i, value in enumerate(values):
        running += value
        if i >= window:
            running -= values[i - window]
        out.append(running / min(i + 1, window))
    return out
