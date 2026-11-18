#!/usr/bin/env python3
"""مولّد مصدر الحقيقة — metrics.json واحد تُشتق منه كل الأرقام المنشورة.

درس المراجعة الخارجية: شارة README تقول 3167 والفقرة الإنجليزية تقول 2991
وسجل التغييرات يقول 3209 — ثلاثة أرقام منسوخة يدويًا لنفس الحقيقة. هذا
السكربت يجعل الرقم **مشتقًا لا منسوخًا**: من junit التشغيل الفعلي يكتب

  1. ``docs/metrics.json``      — المصدر الوحيد (إصدار، منصة، ناجح، متخطى، بصمة junit)
  2. README (شارة + سطر + فقرة EN) — عبر عقد ``check_readme_metrics``
  3. CHANGELOG — رقم «N اختباراً ناجحاً» في قسم الإصدار الحالي فقط

ويحرسها اختبار ``tests/test_metrics_truth.py`` في كل تشغيل pytest —
التعفّت يُلتقط محليًا قبل CI والنشر.

الاستخدام (بعد تشغيل المجموعة الكاملة):

    pytest -q --junitxml=/tmp/junit.xml
    PYTHONPATH=src python scripts/make_metrics.py --junit /tmp/junit.xml

المكتبة القياسية فقط (قاعدة R1) + استيراد عقد README من سكربت الفحص نفسه
(عقد واحد لا نسختان).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from check_readme_metrics import sync_readme  # noqa: E402 — عقد الأرقام نفسه لا نسخة منه

METRICS_PATH = ROOT / "docs" / "metrics.json"
CHANGELOG_PATH = ROOT / "CHANGELOG.md"
README_PATH = ROOT / "README.md"

SCHEMA = "zyko.metrics/1"

# أول قسم H2 في CHANGELOG — «## X.Y.Z — …»
H2_RE = re.compile(r"^## (\d+\.\d+\.\d+) — ", re.MULTILINE)
# رقم الاختبارات الناجحة داخل قسم الإصدار: «3,206 اختباراً ناجحاً»
AR_COUNT_RE = re.compile(r"(\d[\d,]*)\s*اختباراً ناجحاً")


def _junit_counts(junit: Path) -> tuple[int, int]:
    """(ناجح، متخطى) — نفس قراءة سكربت الفحص (عقد واحد)."""
    import xml.etree.ElementTree as ET

    root = ET.parse(junit).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    if not suites:
        raise SystemExit("خطأ: junit بلا testsuite — ملف تالف")
    total = failures = errors = skipped = 0
    for s in suites:
        total += int(s.get("tests", 0))
        failures += int(s.get("failures", 0))
        errors += int(s.get("errors", 0))
        skipped += int(s.get("skipped", 0))
    passed = total - failures - errors - skipped
    if passed < 0:
        raise SystemExit("خطأ: junit غير متسق (ناجح سالب)")
    return passed, skipped


def _sync_changelog(text: str, version: str, passed: int) -> tuple[str, str]:
    """حدّث رقم الاختبارات في قسم الإصدار الحالي فقط — التاريخ لا يُحرَّر.

    يعيد (نص، حالة) — الحالة: synced | version-mismatch | no-count.
    """
    match = H2_RE.search(text)
    if match is None:
        return text, "version-mismatch"
    latest = match.group(1)
    if latest != version:
        return text, "version-mismatch"
    section_start = match.start()
    next_h2 = H2_RE.search(text, match.end())
    section_end = next_h2.start() if next_h2 else len(text)
    section = text[section_start:section_end]
    count = AR_COUNT_RE.search(section)
    if count is None:
        return text, "no-count"
    new_section = (
        section[: count.start(1)] + f"{passed:,}" + section[count.end(1) :]
    )
    return text[:section_start] + new_section + text[section_end:], "synced"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="مولّد مصدر حقيقة الأرقام")
    ap.add_argument("--junit", type=Path, required=True, help="junit.xml من التشغيل الكامل الفعلي")
    ap.add_argument("--no-changelog", action="store_true", help="لا تلمس CHANGELOG (أثناء التطوير)")
    args = ap.parse_args(argv)

    if not args.junit.is_file():
        print(f"خطأ: junit غير موجود: {args.junit}", file=sys.stderr)
        return 2

    from zyko.version import __version__  # PYTHONPATH=src

    passed, skipped = _junit_counts(args.junit)

    payload = {
        "schema": SCHEMA,
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "tests_passed": passed,
        "tests_skipped": skipped,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": f"pytest -q --junitxml={args.junit.name}",
        "junit_sha256": hashlib.sha256(args.junit.read_bytes()).hexdigest(),
    }
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    readme_text = README_PATH.read_text(encoding="utf-8")
    README_PATH.write_text(sync_readme(readme_text, passed, skipped), encoding="utf-8")

    status = "skipped (--no-changelog)"
    if not args.no_changelog:
        changelog_text = CHANGELOG_PATH.read_text(encoding="utf-8")
        changelog_text, status = _sync_changelog(changelog_text, __version__, passed)
        CHANGELOG_PATH.write_text(changelog_text, encoding="utf-8")

    print(f"✅ docs/metrics.json: {passed} ناجح، {skipped} متخطى، إصدار {__version__}")
    print(f"   README: شارة + سطر + فقرة EN مزامنة")
    print(f"   CHANGELOG: {status}" + (" — أضف قسم الإصدار قبل المزامنة" if status == "version-mismatch" else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
