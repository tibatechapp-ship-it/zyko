"""Terminal output helpers — zero dependencies, Windows/Termux safe.

Plain-ASCII markers and fixed-width tables; no ANSI when the stream is not
a TTY (so piped output stays clean in CI logs on every platform).
"""

from __future__ import annotations

import os
import sys
from typing import Any, Iterable

_SUPPORTS_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _SUPPORTS_COLOR else text


def ok(text: str) -> str:
    return _paint(f"[OK]   {text}", "32")


def warn(text: str) -> str:
    return _paint(f"[WARN] {text}", "33")


def fail(text: str) -> str:
    return _paint(f"[FAIL] {text}", "31")


def info(text: str) -> str:
    return _paint(f"[INFO] {text}", "36")


def bold(text: str) -> str:
    return _paint(text, "1")


def kv(key: str, value: Any) -> None:
    print(f"  {key:<22} {value}")


def table(headers: list[str], rows: Iterable[Iterable[Any]]) -> None:
    rows = [list(r) for r in rows]
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)))


def error(err: BaseException) -> None:
    print(fail(str(err).splitlines()[0]), file=sys.stderr)
    for line in str(err).splitlines()[1:]:
        print(f"       {line}", file=sys.stderr)


def bullets(items: Iterable[str], marker: str = "  - ") -> None:
    for item in items:
        print(f"{marker}{item}")
