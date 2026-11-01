"""ZYKO kernel — hot-path math with an optional Rust accelerator.

``zyko.kernel`` exposes a stable, small API::

    estimate_tokens(text) -> int
    estimate_messages_tokens(messages) -> int
    cosine_similarity(a, b) -> float
    top_k(scores, k) -> list[int]
    moving_average(values, window) -> list[float]
    backend() -> "rust" | "python"

If the compiled extension ``zyko_kernel`` is importable it overrides the
Python reference implementations at import time; otherwise the pure-Python
versions are used. Behaviour is byte-identical (covered by parity tests),
so on any platform without a compiler — Termux on Android, locked-down
Windows machines — ZYKO just works, slightly slower.
"""

from __future__ import annotations

from zyko.kernel import python_impl as _py

KERNEL_BACKEND = "python"

estimate_tokens = _py.estimate_tokens
estimate_messages_tokens = _py.estimate_messages_tokens
cosine_similarity = _py.cosine_similarity
top_k = _py.top_k
moving_average = _py.moving_average

try:  # optional Rust accelerator (pip install zyko[accel] + maturin develop)
    import zyko_kernel as _rs  # type: ignore[import-not-found]

    estimate_tokens = _rs.estimate_tokens
    cosine_similarity = _rs.cosine_similarity
    top_k = _rs.top_k
    moving_average = _rs.moving_average
    KERNEL_BACKEND = "rust"
except ImportError:  # pragma: no cover - depends on environment
    _rs = None


def backend() -> str:
    return KERNEL_BACKEND


def messages_tokens(messages: list) -> int:
    """Estimate the token footprint of a full message list."""
    if KERNEL_BACKEND == "rust" and _rs is not None and hasattr(_rs, "estimate_messages_tokens"):
        return int(_rs.estimate_messages_tokens(messages))
    return _py.estimate_messages_tokens(messages)


__all__ = [
    "estimate_tokens",
    "estimate_messages_tokens",
    "messages_tokens",
    "cosine_similarity",
    "top_k",
    "moving_average",
    "backend",
    "KERNEL_BACKEND",
]
