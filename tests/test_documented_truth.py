"""بوابة صدق الموثقات — المستعار من nexus-core: المعلن يُقاس لا يُفترض.

الفجوة: وثيقة تقييم أو سجل تغييرات تعفّت خلف الواقع — صفة بنية تتغير
في الكود وتبقى موثقة قديمة. هذا الاختبار يجعل الانفلات فشل اختبار لا
اكتشافًا متأخرًا: كل ادعاء بنيوي في EVAL/CHANGELOG يقابله وجود فعلي
في الكود، وما يتغير مع كل تشغيل (عدد الاختبارات) تديره بواباته الخاصة
(``check_readme_metrics``) — لا ازدواج للعدّ هنا.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

JAIL_LEVELS = {"landlock", "bwrap", "none"}


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_runtime_dependencies_match_eval_claim() -> None:
    """التقييم يعلن «اعتماديتان فقط» — pyproject هو الحكم لا النص."""
    deps = _pyproject()["project"]["dependencies"]
    names = sorted(
        dep.split(">")[0].split("=")[0].split("[")[0].strip().lower() for dep in deps
    )
    assert names == ["httpx", "pyyaml"], (
        f"الاعتميات تغيرت ({names}) — حدّث ادعاء EVAL في نفس الـPR"
    )


def test_jail_levels_trio_matches_documented_claim() -> None:
    """الوثائق تعلن ثلاثية مستويات العزل — الكود يحملها بالأسماء نفسها."""
    from zyko.sandbox import jail

    assert {
        jail.JAIL_LEVEL_LANDLOCK,
        jail.JAIL_LEVEL_BWRAP,
        jail.JAIL_LEVEL_NONE,
    } == JAIL_LEVELS
    assert jail.jail_level() in JAIL_LEVELS  # الكشف لا يخترع مستوى رابعًا


def test_documented_layers_have_real_modules() -> None:
    """الطبقات الخمس المعلنة في EVAL لها وحدات فعلية قابلة للاستيراد."""
    import zyko.kernel  # noqa: F401 — الطبقة 1: النواة الحتمية
    import zyko.mind.loop  # noqa: F401 — الطبقة 2: حلقة الانعكاس
    from zyko.mind.global_memory import GlobalMemory  # noqa: F401 — الطبقة 4
    from zyko.sandbox.audit import AuditLog  # noqa: F401 — الطبقة 3: التدقيق
    from zyko.sandbox.contracts import PermissionContract  # noqa: F401 — العقد
    from zyko.sandbox.jail import jail_level  # noqa: F401 — الطبقة 5: العزل


def test_eval_doc_version_header_matches_release() -> None:
    """ترويسة EVAL تحمل إصدارًا — يجب أن تواكب الإصدار الحالي."""
    version = _pyproject()["project"]["version"]
    doc = (ROOT / "docs" / "EVAL_2026-11-12.md").read_text(encoding="utf-8")
    assert f"**الإصدار:** {version}" in doc, (
        "ترويسة EVAL خلف الإصدار — حدّثها في نفس الـPR"
    )


def test_baseline_artifact_exists() -> None:
    """المرجع الداخلي المعلن في EVAL ملف حقيقي في المستودع."""
    assert (ROOT / "benchmarks" / "results" / "baseline_2026-11-11.json").is_file()
