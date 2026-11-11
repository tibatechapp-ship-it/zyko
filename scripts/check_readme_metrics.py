#!/usr/bin/env python3
"""بوابة حقيقة الأرقام — شارة README يجب أن تطابق التشغيل الذي حدث الآن.

القصة: شارة الاختبارات (1581) وسطر العد (2004) وشارة الموقع (438) تعفّت
خلف الواقع (2024 تمر + 13 تخطٍ) — أرقام تُحدَّث يدويًا تعفّت حتميًا.
هذا السكربت يجعل الكذب مستحيلًا آليًا: يقرأ XML junit للتشغيل الفعلي،
يستنتج (ناجح، متخطى)، ويقارن ما يعلنه README.

الاستخدام:
    pytest -q --junitxml=/tmp/junit.xml
    python scripts/check_readme_metrics.py --junit /tmp/junit.xml

    # وضع المزامنة (لتطويرك فقط — يصحح README من الواقع):
    python scripts/check_readme_metrics.py --junit /tmp/junit.xml --sync

أكواد الخروج: 0 متطابق · 1 تعفّت الأرقام (فشل صادق) · 2 خطأ استخدام.
المكتبة القياسية فقط (قاعدة R1).
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

# أنماط الحقيقة المعلنة في README — تعديلها يعني تغيير العقد مع هذا السكربت
BADGE_RE = re.compile(r"img\.shields\.io/badge/tests-(\d+)%20passing")
COUNT_RE = re.compile(r"^#\s+(\d+) passed, (\d+) skipped", re.MULTILINE)


def junit_counts(junit_path: Path) -> tuple[int, int]:
    """(ناجح، متخطى) من XML junit — حتمي من التشغيل الفعلي."""
    tree = ET.parse(junit_path)
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    if not suites:
        raise SystemExit("خطأ: لا توجد <testsuite> في الملف — junit تالف")
    total = failures = errors = skipped = 0
    for s in suites:
        total += int(s.get("tests", 0))
        failures += int(s.get("failures", 0))
        errors += int(s.get("errors", 0))
        skipped += int(s.get("skipped", 0))
    passed = total - failures - errors - skipped
    if passed < 0:
        raise SystemExit("خطأ: حساب junit لا يتسق (ناجح سالب) — الملف تالف")
    return passed, skipped


def declared_counts(readme_text: str) -> tuple[int, int, int]:
    """(شارة، ناجح المعلن، متخطى المعلن) من README — أو خطأ استخدام صادق."""
    badge = BADGE_RE.search(readme_text)
    count = COUNT_RE.search(readme_text)
    missing = []
    if not badge:
        missing.append("شارة tests-N-passing")
    if not count:
        missing.append('سطر "# N passed, M skipped"')
    if missing:
        raise SystemExit("خطأ: README فقد عقد الأرقام: " + " و".join(missing))
    return int(badge.group(1)), int(count.group(1)), int(count.group(2))


def sync_readme(readme_text: str, passed: int, skipped: int) -> str:
    """أعد كتابة الأرقام من الواقع — عقد الأنماط نفسه."""
    badge = BADGE_RE.search(readme_text)
    count = COUNT_RE.search(readme_text)
    assert badge and count
    readme_text = readme_text[: badge.start(1)] + str(passed) + readme_text[badge.end(1) :]
    count = COUNT_RE.search(readme_text)
    assert count
    replaced = f"# {passed} passed, {skipped} skipped"
    readme_text = readme_text[: count.start()] + replaced + readme_text[count.end() :]
    return readme_text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="بوابة حقيقة أرقام README")
    ap.add_argument("--junit", type=Path, required=True, help="ملف junit.xml للتشغيل الفعلي")
    ap.add_argument("--sync", action="store_true", help="صحّح README من الواقع بدل الفشل")
    ap.add_argument("--readme", type=Path, default=README, help="مسار README (للاختبار)")
    args = ap.parse_args(argv)

    if not args.junit.is_file():
        print(f"خطأ: junit غير موجود: {args.junit}", file=sys.stderr)
        return 2

    passed, skipped = junit_counts(args.junit)
    text = args.readme.read_text(encoding="utf-8")
    badge, declared_passed, declared_skipped = declared_counts(text)

    ok = badge == passed and declared_passed == passed and declared_skipped == skipped
    if ok:
        print(
            f"✅ حقيقة الأرقام: شارة {badge} = خط {declared_passed}/{declared_skipped} = junit {passed}/{skipped}"
        )
        return 0

    print(
        f"❌ تعفّت الأرقام: README يعلن شارة {badge} وخط {declared_passed}/{declared_skipped} "
        f"بينما junit يقول {passed}/{skipped}",
        file=sys.stderr,
    )
    if args.sync:
        args.readme.write_text(sync_readme(text, passed, skipped), encoding="utf-8")
        print("🔧 تمت المزامنة — أعد الفحص", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
