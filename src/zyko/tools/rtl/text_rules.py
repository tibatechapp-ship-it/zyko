"""قواعد النصوص العامة (.md/.txt) — أسطر مختلطة الاتجاه.

RTL-TXT-001 (معلومة): سطر يجمع جريًا عربيًا (≥3 حروف) وجريًا لاتينيًا (≥4 حروف)
قد يُعرض مبعثرًا في الطرفيات والمحررات. كتل الشيفرة المسوّرة في Markdown
تُتجاهل لأنها شيفرة LTR بطبيعتها.
"""

from __future__ import annotations

import re

from .core import Finding

_AR_RUN_RE = re.compile(r"[\u0621-\u064A\u066E-\u06D5]{3,}")
_LATIN_RUN_RE = re.compile(r"[A-Za-z]{4,}")

_FENCE_PREFIXES = ("```", "~~~")


def check_text(source: str, filename: str = "<inline>") -> list[Finding]:
    """يفحص نصًا عامًا سطرًا سطرًا (حتمي بالكامل)."""
    findings: list[Finding] = []
    in_fence = False
    for lineno, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(_FENCE_PREFIXES):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _AR_RUN_RE.search(line) and _LATIN_RUN_RE.search(line):
            findings.append(
                Finding(
                    "RTL-TXT-001",
                    "info",
                    "سطر مختلط الاتجاه (عربي + لاتيني) — قد يُعرض مبعثرًا في الطرفيات",
                    filename,
                    lineno,
                    1,
                    stripped[:120],
                    "أضف علامات الاتجاه أو اجعل الجري اللاتيني في سطر/خلية منفصلة",
                )
            )
    return findings
