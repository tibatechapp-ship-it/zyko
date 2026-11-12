"""اختبارات run_tests — قائمة بيضاء، بيئة بلا أسرار، مهلة، عدّادات صادقة."""

from __future__ import annotations

import sys

import pytest

# تخطٍ موثق: النواة تعلن Landlock لكن إقامته تفشل في حاويات CI
# (سياسات seccomp تحجب landlock_add_rule) — بروبة إقامة حقيقية تقرر،
# والعقد نفسه fail-closed: لا تشغيل بلا عزل ولا ادعاء نجاح زور.
from zyko.sandbox import jail as _jail_mod
from zyko.sandbox.contracts import PermissionContract
from zyko.sandbox.runner import run_tests

_jail_broken = (
    _jail_mod.jail_level() == _jail_mod.JAIL_LEVEL_LANDLOCK
    and not _jail_mod.jail_establishment_ok()
)
pytestmark = pytest.mark.skipif(
    _jail_broken,
    reason="إقامة الحبس النواتي تفشل في هذه البيئة (seccomp الحاوية يحجب Landlock) — تخطٍ موثق لا فشل",
)

PY = sys.executable.replace("\\", "/").split("/")[-1].replace(".exe", "") or "python"


def _contract(tmp_path, **kw):
    defaults = dict(allow_run_tests=True, allowed_commands=(PY, "pytest"))
    defaults.update(kw)
    return PermissionContract.for_roots(tmp_path, **defaults)


def _write_tests(tmp_path, body="def test_ok():\n    assert True\n"):
    (tmp_path / "test_ok.py").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------- النجاح
def test_run_green_tests_pass(tmp_path):
    _write_tests(tmp_path)
    result = run_tests(_contract(tmp_path), argv=[PY, "-m", "pytest", "-q"], cwd=tmp_path)
    assert result.ok and result.exit_code == 0
    assert result.passed == 1
    # الأمانة: عدّاد غائب = بلا ادعاء — لا صفر مفترض
    assert result.failed is None and result.errors is None
    assert "خضراء" in result.reason_ar


def test_run_red_tests_fail_with_counts(tmp_path):
    _write_tests(tmp_path, "def test_bad():\n    assert 1 == 2\n")
    result = run_tests(_contract(tmp_path), argv=[PY, "-m", "pytest", "-q"], cwd=tmp_path)
    assert not result.ok and result.exit_code != 0
    assert result.failed == 1
    assert "حمراء" in result.reason_ar


def test_command_recorded_in_result(tmp_path):
    result = run_tests(_contract(tmp_path), argv=[PY, "-m", "pytest", "-q"], cwd=tmp_path)
    assert result.command == f"{PY} -m pytest -q"


# ---------------------------------------------------------------- الحراسة
def test_command_not_whitelisted_rejected(tmp_path):
    result = run_tests(
        _contract(tmp_path, allowed_commands=("pytest",)),
        argv=["curl", "http://evil.example"],
    )
    assert not result.ok and result.exit_code == 2
    assert "القائمة البيضاء" in result.reason_ar


def test_run_tests_requires_flag(tmp_path):
    contract = PermissionContract.for_roots(tmp_path)  # بلا allow_run_tests
    result = run_tests(contract, argv=[PY, "-m", "pytest"])
    assert not result.ok and "لا يفعّل" in result.reason_ar


def test_string_command_rejected_not_splitted(tmp_path):
    """النص الواحد لا يُفتّل صدفة — argv قائمة أو رفض."""
    result = run_tests(_contract(tmp_path), argv="python -m pytest")
    assert not result.ok and "قائمة" in result.reason_ar


def test_cwd_outside_roots_rejected(tmp_path):
    _write_tests(tmp_path)
    outside = tmp_path.parent / "غير-مسموح"
    result = run_tests(_contract(tmp_path), argv=[PY, "-m", "pytest", "-q"], cwd=outside)
    assert not result.ok and "حارس الدليل" in result.reason_ar


def test_runner_shadow_file_rejected(tmp_path):
    """pytest.py في الجذر يظلل المشغّل نفسه — رفض قبل التنفيذ."""
    _write_tests(tmp_path)
    (tmp_path / "pytest.py").write_text("print('خطف المشغّل')\n", encoding="utf-8")
    result = run_tests(_contract(tmp_path), argv=[PY, "-m", "pytest", "-q"], cwd=tmp_path)
    assert not result.ok and "يظلّل" in result.reason_ar


# ---------------------------------------------------------------- البيئة
def test_secrets_never_reach_subprocess(monkeypatch, tmp_path):
    """الأسرار في البيئة الأصل لا تعبر إلى الاختبارات — دليل قاطع من الداخل."""
    monkeypatch.setenv("ZYKO_CANARY_KEY", "top-secret-canary-value")
    # اختبار يفشل لو وجد السر في بيئته — الفشل هنا دليل نجاح الحرس
    _write_tests(
        tmp_path,
        "import os\n"
        "def test_no_secret_in_env():\n"
        "    for name, value in os.environ.items():\n"
        "        assert 'top-secret-canary-value' != value, f'{name} leak'\n",
    )
    result = run_tests(_contract(tmp_path), argv=[PY, "-m", "pytest", "-q"], cwd=tmp_path)
    assert result.ok and result.passed == 1


def test_stable_env_vars_present(tmp_path):
    _write_tests(
        tmp_path,
        "import os\n"
        "def test_env():\n"
        "    assert os.environ.get('PYTHONDONTWRITEBYTECODE') == '1'\n"
        "    assert os.environ.get('PYTHONIOENCODING') == 'utf-8'\n",
    )
    result = run_tests(_contract(tmp_path), argv=[PY, "-m", "pytest", "-q"], cwd=tmp_path)
    assert result.ok


# ---------------------------------------------------------------- المهلة
def test_timeout_kills_run_and_documents(tmp_path):
    _write_tests(
        tmp_path,
        "import time\ndef test_hangs():\n    time.sleep(60)\n",
    )
    contract = _contract(tmp_path, timeout_s=2.0)
    result = run_tests(contract, argv=[PY, "-m", "pytest", "-q"], cwd=tmp_path)
    assert not result.ok
    assert result.timed_out and result.exit_code == 124
    assert "المهلة" in result.reason_ar


# ---------------------------------------------------------------- العدادات
def test_unittest_counts_parsed(tmp_path):
    (tmp_path / "test_u.py").write_text(
        "import unittest\n\n\nclass T(unittest.TestCase):\n"
        "    def test_passes(self):\n        self.assertTrue(True)\n",
        encoding="utf-8",
    )
    result = run_tests(_contract(tmp_path), argv=[PY, "-m", "unittest", "-v"], cwd=tmp_path)
    assert result.passed == 1
    # الخروج 0 لأن الاختبار الأخضر
    assert result.ok


def test_no_counters_means_no_claims(tmp_path):
    """أمر لا ينتج عدّادات — الأمانة: بلا ادعاء نجاح عددي."""
    (tmp_path / "script.py").write_text("print('لا اختبارات هنا')\n", encoding="utf-8")
    result = run_tests(_contract(tmp_path), argv=[PY, "script.py"], cwd=tmp_path)
    assert result.ok  # خروج 0
    assert result.passed is None and result.failed is None
    assert "بلا عدّادات" in result.reason_ar


def test_missing_command_documented_not_raised(tmp_path):
    """أمر غائب: فشل موثق بالعربي لا استثناء خارج — على أي مستوى عزل.

    بلا غلاف: exec نفسه يرمي OSError فيُوثّق «فشل قبل البدء»؛ وتحت
    غلاف bwrap: الغلاف هو من يشغّل فيخرج بخطى موثقة لا استثناء —
    والعقد واحد في الحالتين: لا استثناء يهرب، والفشل عربي معلن.
    """
    contract = _contract(tmp_path, allowed_commands=("لا-يوجد-على-النظام-هذا",))
    result = run_tests(contract, argv=["لا-يوجد-على-النظام-هذا", "-q"])
    assert not result.ok
    assert result.reason_ar  # توثيق عربي غير فارغ في كل الحالات
    if _jail_mod.jail_level() == _jail_mod.JAIL_LEVEL_BWRAP:
        # تحت الغلاف: bwrap يفشل في exec الغائب — خروج موثق لا استثناء للعملية
        assert result.exit_code != 0
    else:
        assert "فشل قبل البدء" in result.reason_ar


# ---------------------------------------------------------------- المخرجات
def test_output_tails_capped(tmp_path):
    (tmp_path / "test_noisy.py").write_text(
        "import sys\ndef test_noisy():\n    print('ض' * 50_000)\n",
        encoding="utf-8",
    )
    contract = _contract(tmp_path, max_output_chars=500)
    result = run_tests(contract, argv=[PY, "-m", "pytest", "-q"], cwd=tmp_path)
    assert len(result.stdout_tail) <= 500


def test_to_dict_deterministic_no_env(tmp_path):
    import json

    _write_tests(tmp_path)
    result = run_tests(_contract(tmp_path), argv=[PY, "-m", "pytest", "-q"], cwd=tmp_path)
    blob = json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True)
    keys = list(json.loads(blob))
    assert keys == sorted(keys)
    # لا بيئة ولا مسار مطلق في التمثيل
    assert "PYTHONPATH" not in blob
    assert str(tmp_path) not in blob


def test_dry_workspace_no_tests_is_documented_failure(tmp_path):
    """مجلد بلا اختبارات — pytest يخرج بصفر الحدوث (خروج 5) موثق لا ادعاء."""
    result = run_tests(_contract(tmp_path), argv=[PY, "-m", "pytest", "-q"], cwd=tmp_path)
    assert not result.ok
    assert result.exit_code == 5  # pytest "no tests collected"


@pytest.mark.parametrize(
    "sneaky",
    (
        ["pytest", "-c", "import os"],
        [PY, "-c", "import os; os.system('rm -rf /')"],
        ["pytest", "--rootdir=../../"],
    ),
)
def test_suspicious_but_whitelisted_args_behave_documented(tmp_path, sneaky):
    """حماية العمق ترفض محارف الصدفة، والبقية تُنفَّذ موثقة بلا صدفة."""
    contract = _contract(tmp_path)
    tokens, reason = contract.check_command(sneaky)
    # المحارف المرفوضة تُرفض؛ الأخرى تُقبل وتُنفذ بلا shell إطلاقاً
    if tokens is None:
        result = run_tests(contract, argv=sneaky)
        assert not result.ok and "حارس الأمر" in result.reason_ar
