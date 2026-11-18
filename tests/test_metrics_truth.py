"""اختبار حارس مصدر الحقيقة — رقم واحد مشتق لا ثلاثة منسوخة.

درس المراجعة الخارجية: شارة README (3167) وفقرة الإنجليزية (2991) وسجل
التغييرات (3209) تتناقض — أرقام يدوية تتخالف. العقد هنا:

1. ``docs/metrics.json`` موجود، بعقده ``zyko.metrics/1``، وإصداره يساوي
   إصدار الحزمة المثبتة (التزام الترقية: bump ⇒ إعادة توليد من تشغيل فعلي).
2. README الثلاثي (شارة، سطر، فقرة EN) كلها تساوي ``metrics.json``.
3. قسم الإصدار الأخير في CHANGELOG يحمل الإصدار نفسه ورقم الاختبارات
   نفسه — التاريخ المؤرشف للأرقام السابقة لا يُحرَّر، والرقم الحي واحد.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from zyko.version import __version__  # noqa: E402 — المسار يُبنى فوقه

METRICS = ROOT / "docs" / "metrics.json"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"

H2_RE = re.compile(r"^## (\d+\.\d+\.\d+) — ", re.MULTILINE)
AR_COUNT_RE = re.compile(r"(\d[\d,]*)\s*اختباراً ناجحاً")


def _metrics() -> dict:
    assert METRICS.is_file(), "docs/metrics.json مفقود — أعد التوليد بـ scripts/make_metrics.py"
    return json.loads(METRICS.read_text(encoding="utf-8"))


def test_metrics_receipt_is_coherent_with_installed_package() -> None:
    d = _metrics()
    assert d["schema"] == "zyko.metrics/1"
    assert d["version"] == __version__, (
        "metrics.json يوثق إصدارًا غير المثبت — أعد التوليد بـ scripts/make_metrics.py بعد أي bump"
    )
    assert isinstance(d["tests_passed"], int) and d["tests_passed"] > 1500
    assert isinstance(d["tests_skipped"], int) and d["tests_skipped"] >= 0
    assert re.fullmatch(r"[0-9a-f]{64}", d["junit_sha256"])
    assert d["generated_utc"] and d["command"]


def test_readme_three_numbers_all_match_metrics() -> None:
    d = _metrics()
    text = README.read_text(encoding="utf-8")
    badge = re.search(r"img\.shields\.io/badge/tests-(\d+)%20passing", text)
    line = re.search(r"^#\s+(\d+) passed, (\d+) skipped", text, re.MULTILINE)
    en = re.search(r"(?<![\w.])(\d+) tests passing on", text)
    assert badge and line and en, "README فقد أحد الأنماط الثلاثة (شارة/سطر/فقرة EN)"
    assert int(badge.group(1)) == d["tests_passed"], (
        f"الشارة {badge.group(1)} ≠ {d['tests_passed']}"
    )
    assert int(line.group(1)) == d["tests_passed"]
    assert int(line.group(2)) == d["tests_skipped"]
    assert int(en.group(1)) == d["tests_passed"], f"فقرة EN {en.group(1)} ≠ {d['tests_passed']}"


def test_changelog_latest_section_carries_the_same_truth() -> None:
    d = _metrics()
    text = CHANGELOG.read_text(encoding="utf-8")
    match = H2_RE.search(text)
    assert match, "CHANGELOG بلا قسم إصدار"
    assert match.group(1) == d["version"], (
        f"أحدث قسم CHANGELOG ({match.group(1)}) ≠ إصدار metrics.json ({d['version']}) — "
        "أضف قسم الإصدار الجديد ثم أعد المزامنة"
    )
    next_h2 = H2_RE.search(text, match.end())
    section = text[match.start() : next_h2.start() if next_h2 else len(text)]
    count = AR_COUNT_RE.search(section)
    assert count, "قسم الإصدار الأخير بلا رقم اختبارات — أضف «N اختباراً ناجحاً»"
    assert int(count.group(1).replace(",", "")) == d["tests_passed"], (
        f"CHANGELOG يقول {count.group(1)} بينما metrics.json يقول {d['tests_passed']}"
    )
