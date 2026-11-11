"""اختبارات بوابة حقيقة الأرقام — README لا يكذب على التشغيل الفعلي.

العقود:
1. المفسر يقبل junit متطابقًا مع README، ويرفض أي انحراف (شارة/خط/junit).
2. وضع المزامنة يصحح الأرقام من الواقع مع حفظ بنية الملف.
3. README الفعلي متسق داخليًا: الشارة = ناجح السطر، والسطران يرويان القصة
   نفسها — يلتقط التعفّت محليًا حتى قبل تشغيل CI الكامل.
4. junit بلا testsuite أو غير المتسق يرفض صادقًا (لا رقم مفبرك).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "check_readme_metrics", ROOT / "scripts" / "check_readme_metrics.py"
)
assert _spec and _spec.loader
crm = importlib.util.module_from_spec(_spec)
sys.modules["check_readme_metrics"] = crm
_spec.loader.exec_module(crm)


def _fake_junit(tmp_path: Path, *, tests: int, failures: int, errors: int, skipped: int) -> Path:
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<testsuite name="pytest" tests="{tests}" failures="{failures}" '
        f'errors="{errors}" skipped="{skipped}">\n'
        "</testsuite>\n"
    )
    p = tmp_path / "junit.xml"
    p.write_text(xml, encoding="utf-8")
    return p


def _fake_readme(tmp_path: Path, *, badge: int, passed: int, skipped: int) -> Path:
    text = (
        "# مشروع\n\n"
        f"[![Tests](https://img.shields.io/badge/tests-{badge}%20passing-22c55e)](ci)\n\n"
        "```bash\npytest -q\n"
        f"# {passed} passed, {skipped} skipped\n```\n"
    )
    p = tmp_path / "README.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_accepts_matching_numbers(tmp_path: Path) -> None:
    junit = _fake_junit(tmp_path, tests=2037, failures=0, errors=0, skipped=13)
    readme = _fake_readme(tmp_path, badge=2024, passed=2024, skipped=13)
    assert crm.main(["--junit", str(junit), "--readme", str(readme)]) == 0


def test_rejects_rotten_badge(tmp_path: Path) -> None:
    junit = _fake_junit(tmp_path, tests=2037, failures=0, errors=0, skipped=13)
    readme = _fake_readme(tmp_path, badge=1581, passed=2024, skipped=13)
    assert crm.main(["--junit", str(junit), "--readme", str(readme)]) == 1


def test_rejects_rotten_count_line(tmp_path: Path) -> None:
    junit = _fake_junit(tmp_path, tests=2037, failures=0, errors=0, skipped=13)
    readme = _fake_readme(tmp_path, badge=2024, passed=2004, skipped=13)
    assert crm.main(["--junit", str(junit), "--readme", str(readme)]) == 1


def test_rejects_wrong_skip_count(tmp_path: Path) -> None:
    junit = _fake_junit(tmp_path, tests=2037, failures=0, errors=0, skipped=13)
    readme = _fake_readme(tmp_path, badge=2024, passed=2024, skipped=0)
    assert crm.main(["--junit", str(junit), "--readme", str(readme)]) == 1


def test_counts_failures_as_not_passed(tmp_path: Path) -> None:
    junit = _fake_junit(tmp_path, tests=100, failures=3, errors=2, skipped=5)
    passed, skipped = crm.junit_counts(junit)
    assert (passed, skipped) == (90, 5)


def test_sync_rewrites_from_reality(tmp_path: Path) -> None:
    junit = _fake_junit(tmp_path, tests=2037, failures=0, errors=0, skipped=13)
    readme = _fake_readme(tmp_path, badge=1581, passed=2004, skipped=13)
    rc = crm.main(["--junit", str(junit), "--readme", str(readme), "--sync"])
    assert rc == 1  # يفشل ويصلح معًا — الصادق
    text = readme.read_text(encoding="utf-8")
    assert crm.declared_counts(text) == (2024, 2024, 13)
    assert crm.main(["--junit", str(junit), "--readme", str(readme)]) == 0


def test_real_readme_internally_coherent() -> None:
    """README الفعلي: الشارة تساوي ناجح السطر — التعفّت يُلتقط محليًا."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    badge, passed, skipped = crm.declared_counts(text)
    assert badge == passed, f"الشارة ({badge}) اختلفت عن السطر ({passed})"
    assert passed > 1500 and skipped >= 0


def test_broken_junit_is_a_usage_error_not_a_lie(tmp_path: Path) -> None:
    bad = tmp_path / "bad.xml"
    bad.write_text("<not-a-suite/>", encoding="utf-8")
    try:
        crm.junit_counts(bad)
    except SystemExit as e:
        assert "testsuite" in str(e)
    else:
        raise AssertionError("junit تالف يجب أن يُرفض صادقًا")
