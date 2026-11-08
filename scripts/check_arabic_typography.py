#!/usr/bin/env python3
"""فحص typographic للنصوص العربية داخل الشيفرة — بوابة CI (المرحلة 0، D7).

يفحص كل ثوابت السلاسل في ملفات .py (عبر ast، بلا اعتماديات) ويكشف:
  T1: فاصلة لاتينية بين كلمتين عربيتين — الصواب «،»
  T2: علامة استفهام لاتينية بعد كلمة عربية — الصواب «؟»
  T3: فاصلة منقوطة لاتينية بين كلمتين عربيتين — الصواب «؛»

الخروج: 0 سليم · 1 مخالفات (تُطبع مع الملف والسطر).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ARABIC_LETTER = "\u0621-\u063a\u0641-\u064a\u066e-\u06d5"
_AR = f"[{ARABIC_LETTER}]"

_T1 = re.compile(rf"{_AR}[ ]*,[ ]*{_AR}")
_T2 = re.compile(rf"{_AR}\s*\?")
_T3 = re.compile(rf"{_AR}[ ]*;[ ]*{_AR}")

_CHECKS = (
    ("T1", _T1, "فاصلة لاتينية بين كلمتين عربيتين — استخدم «،»"),
    ("T2", _T2, "استفهام لاتيني بعد كلمة عربية — استخدم «؟»"),
    ("T3", _T3, "فاصلة منقوطة لاتينية بين كلمتين عربيتين — استخدم «؛»"),
)

_SKIP_PARTS = ("__pycache__", ".git", "node_modules", ".venv", "venv")


def string_literals(source: str):
    """كل نص ثابت في الملف (سلاسل عادية وأجزاء f-strings حرفية)."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    yield part.lineno, part.value


def check_path(root: Path) -> list[tuple[str, str, int, str, str]]:
    """يرجع (قاعدة، ملف، سطر، مقتطف، شرح) لكل مخالفة."""
    violations: list[tuple[str, str, int, str, str]] = []
    for path in sorted(root.rglob("*.py")):
        if any(p in _SKIP_PARTS or p.endswith(".egg-info") for p in path.parts):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            literals = list(string_literals(source))
        except SyntaxError:
            continue  # ملف مكسور يلتقطه pytest لا هذا الفحص
        for lineno, text in literals:
            for rule_id, rx, desc in _CHECKS:
                m = rx.search(text)
                if m:
                    start = max(0, m.start() - 10)
                    excerpt = text[start : m.end() + 10].replace("\n", " ")
                    violations.append((rule_id, str(path), lineno, excerpt, desc))
    return violations


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_arabic_typography.py <path>", file=sys.stderr)
        return 2
    violations = check_path(Path(argv[1]))
    for rule_id, path, lineno, excerpt, desc in violations:
        print(f"[{rule_id}] {path}:{lineno}  {desc}\n      …{excerpt}…")
    if violations:
        print(f"\nمخالفات typographic: {len(violations)}")
        return 1
    print("الفحص المطبعي العربي: سليم ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
