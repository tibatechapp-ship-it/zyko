"""اختبار عقد النشر — الوسم إلى الحزمة بلا حلقة مكسورة.

درس المراجعة الخارجية: تشغيل نشر PyPI رُفض بـ ``invalid-publisher`` —
مطابقة الناشر الموثوق أربعة حقول، والتعارض يُكتشف هنا لا عند الرفع.
العقود:

1. ``publish.yml`` يعلن البيئة ``release`` و ``id-token: write`` وينشر
   عبر ``pypa/gh-action-pypi-publish`` — الثلاثة حرفيًا (هوية الناشر).
2. خطوة سلامة الوسم موجودة: الوسم يشهّد نسخته قبل أي بناء.
3. ``docs/PUBLISHING.md`` يوثق قيم الناشر الأربعة نفسها — الوثيقة
   والكود عقد واحد لا نصان يتعافيان.
4. ``ci.yml`` يحمل حاجز التغطية على المجموعة الكاملة للمراجع (درس
   56.72%) وعقد حقيقة الأرقام (درس 3167/2991/3209) — البوابات
   المعلنة لا تُحذف بصمت.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLISH_YML = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
CI_YML = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
PUBLISHING = (ROOT / "docs" / "PUBLISHING.md").read_text(encoding="utf-8")


def test_publish_workflow_declares_the_trusted_publisher_identity() -> None:
    # الحقول الأربعة في نموذج PyPI — هذا الملف يصادق على ثلاثة منها،
    # والرابع (Owner/Repository) يوثقه PUBLISHING.md (انظر الاختبار الأخير)
    assert "environment: release" in PUBLISH_YML
    assert re.search(r"id-token:\s*write", PUBLISH_YML)
    assert "pypa/gh-action-pypi-publish" in PUBLISH_YML
    # اسم ملف الـ workflow هو نفسه المعلن في نموذج PyPI — إعادة التسمية
    # تكسر العقد فيُلقط هنا
    assert PUBLISH_YML.startswith("name: Publish to PyPI")


def test_publish_workflow_certifies_tag_version_before_building() -> None:
    assert "Tag must certify its own version" in PUBLISH_YML
    assert "from zyko.version import __version__" in PUBLISH_YML
    assert "tag == __version__" in PUBLISH_YML


def test_ci_keeps_the_full_suite_reviewer_coverage_gate() -> None:
    # درس 56.72%: القائمة المعددة يدويًا تتعفت — الحاجز يقيس zyko.reviewer
    # على المجموعة الكاملة ولا خفض للحد
    assert "--cov=zyko.reviewer" in CI_YML
    assert "--cov-fail-under=85" in CI_YML
    assert "pytest tests/\n          --cov=zyko.reviewer" in CI_YML
    # حاجز الأرقام حي في CI (شارة README == التشغيل الفعلي)
    assert "check_readme_metrics.py --junit" in CI_YML


def test_publishing_doc_carries_the_same_publisher_contract() -> None:
    for needle in ("tibatechapp-ship-it", "`zyko`", "`publish.yml`", "`release`"):
        assert needle in PUBLISHING, f"PUBLISHING.md فقد قيمة الناشر العقدية: {needle}"
    # درس invalid-publisher موثق بالاسم — لا يُحذف من التاريخ
    assert "invalid-publisher" in PUBLISHING
    # معيار الإنجاز: تثبيت من PyPI نفسها موثق لا مفترض
    assert "pip download" in PUBLISHING
