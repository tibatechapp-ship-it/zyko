"""اختبارات حلقة الإصلاح الموسعة (جولة 9) — بلا شبكة، بلا مفتاح، بالبايت.

سيناريوهات العلة الموثقة من الجولة 8 تُعاد هنا كعقود:
1. رقعة مشوهة رفضها ``git apply`` → رجعية → محاولة ثانية ناجحة (كانت نهاية الفشل، صارت متابعة).
2. رفض حرس (تعدد ملفات فوق السياسة) → رجعية → تصحيح.
3. رقعة طُبِّقت ولم تحل → رجعية الاختبارات → حلّ عند المحاولة التالية.
4. الميزانية نافدة → الفشل موثق كاملاً لا مُجمَّل.
5. الحلقة تغيّر الملف نفسه حين تدل الرجعية على خطأ الاختيار.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from zyko.benchmarks.repair_loop import (
    MAX_ATTEMPTS_DEFAULT,
    MAX_FILES_DEFAULT,
    RepairLoop,
    feedback_from_apply_error,
    feedback_from_contract,
    feedback_from_failed_tests,
)

from zyko.benchmarks.swebench import SWEInstance


class CannedBrain:
    """عقل معلب: ردود بترتيب معلن — كل نداء يسجل طلبه للتحقق من الرجعية."""

    def __init__(self, replies: list[str], accepted_flags: list[bool] | None = None):
        from zyko.ai.brains import GateVerdict, Proposal

        self._replies = list(replies)
        self._flags = accepted_flags or [True] * len(self._replies)
        self._proposal_template = (GateVerdict, Proposal)
        self.calls: list[str] = []

    def propose(self, request: str) -> object:
        from zyko.ai.brains import GateVerdict, Proposal

        self.calls.append(request)
        text = self._replies.pop(0) if self._replies else ""
        passed = self._flags.pop(0) if self._flags else False
        return Proposal(text=text, brain="canned", deterministic=False,
                        verdicts=(GateVerdict(gate="fake", passed=passed),))


class FakeRun:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _instance(**overrides) -> SWEInstance:
    base = dict(
        instance_id="psf__requests-0000", repo="psf/requests", base_commit="a" * 40,
        version="2.4", problem_statement="القيمة يجب أن تكون 2",
        test_patch="diff", fail_to_pass=("test_level.py::test_value",),
        pass_to_pass=(),
    )
    return SWEInstance(**{**base, **overrides})


@pytest.fixture()
def mini_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "alt.py").write_text("alt = 1\n", encoding="utf-8")
    (repo / "test_level.py").write_text(
        "def test_value():\n    from src import value\n    assert value == 2\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


GOOD_PATCH = "```diff\n--- a/src.py\n+++ b/src.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n```"
GOOD_PATCH_RAW = "--- a/src.py\n+++ b/src.py\n@@ -1 +1 @@\n-value = 1\n+value = 2"
CORRUPT_PATCH = "```diff\n--- a/src.py\n+++ b/src.py\n@@ -9,1 +9,2 @@\n سياق غير موجود أبداً\n+س\n```"
MULTI_FILE_PATCH = ("--- a/src.py\n+++ b/src.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
                    "--- a/alt.py\n+++ b/alt.py\n@@ -1 +1 @@\n-alt = 1\n+alt = 2")


def _tree_runner():
    def runner(args, **kwargs):
        if args[:2] == ["git", "ls-files"]:
            return FakeRun(0, stdout="alt.py\nsrc.py\ntest_requests.py\n")
        return subprocess.run(args, **kwargs)
    return runner


def test_budget_contract_enforced():
    with pytest.raises(ValueError):
        RepairLoop(None, None, max_attempts=0)
    with pytest.raises(ValueError):
        RepairLoop(None, None, max_attempts=9)
    with pytest.raises(ValueError):
        RepairLoop(None, None, max_files=0)
    assert MAX_ATTEMPTS_DEFAULT == 3 and MAX_FILES_DEFAULT == 3


def test_feedback_builders_are_deterministic():
    f1 = feedback_from_apply_error("فشل فحص التطبيق: corrupt patch at line 22")
    assert "git apply" in f1 and "corrupt patch at line 22" in f1
    f2 = feedback_from_contract("الرقعة تلمس 5 مساراً — فوق سياسة تعدد الملفات المعلنة (3)")
    assert "الحرس" in f2 and "5 مساراً" in f2
    f3 = feedback_from_failed_tests(("b::y", "a::x", "c::z"))
    assert f3.splitlines()[1:] == ["a::x", "b::y", "c::z"]  # ترتيب حتمي
    assert f1 == feedback_from_apply_error("فشل فحص التطبيق: corrupt patch at line 22")


def test_corrupt_patch_then_retry_resolves(mini_repo):
    """سيناريو الجولة 8 الحرفي: رقعة مشوهة → رجعية التطبيق → إصلاح عند المحاولة 2."""
    choice = CannedBrain(["src.py", "src.py"])
    diff = CannedBrain([CORRUPT_PATCH, GOOD_PATCH])
    loop = RepairLoop(choice, diff)
    result = loop.run(_instance(), mini_repo, "python3", runner=_tree_runner())
    assert [a.applied for a in result.attempts] == [False, True]
    assert result.attempts[0].apply_error_ar and "فشل" in result.attempts[0].apply_error_ar
    assert result.attempts[1].feedback_sha16  # الثانية بنيت على رجعية
    assert result.attempts[1].stop_reason_ar == "انصراف — حلّ"
    assert result.resolved_env and result.resolved_strict
    assert len(result.chain_hash) == 16
    # الرجعية وصلت فعلاً إلى العقل في الطلب الثاني
    assert "رجعية المحاولة السابقة" in choice.calls[1]


def test_contract_rejection_then_fix(mini_repo):
    """تعدد ملفات فوق السياسة → رجعية الحرس → رقعة بملف واحد → تطبيق."""
    choice = CannedBrain(["src.py", "src.py"])
    diff = CannedBrain([MULTI_FILE_PATCH, GOOD_PATCH])
    loop = RepairLoop(choice, diff, max_files=1)
    result = loop.run(_instance(), mini_repo, "python3", runner=_tree_runner())
    assert "تعدد الملفات" in result.attempts[0].contract_reason_ar
    assert not result.attempts[0].accepted and result.attempts[1].applied
    assert result.resolved_env


def test_applied_but_not_resolved_then_feedback_then_resolve(mini_repo):
    """رقعة تُطبَّق ولا تحل → رجعية الاختبارات → رقعة ثانية تحل."""
    wrong_patch = "--- a/src.py\n+++ b/src.py\n@@ -1 +1 @@\n-value = 1\n+value = 9"
    follow_patch = "--- a/src.py\n+++ b/src.py\n@@ -1 +1 @@\n-value = 9\n+value = 2"
    choice = CannedBrain(["src.py", "src.py"])
    diff = CannedBrain([wrong_patch, follow_patch])
    loop = RepairLoop(choice, diff)
    result = loop.run(_instance(), mini_repo, "python3", runner=_tree_runner())
    assert [a.applied for a in result.attempts] == [True, True]
    assert result.attempts[0].stop_reason_ar == "متابعة — رجعية الاختبارات بُنيت"
    assert result.resolved_env
    # رجعية الاختبارات فيها العقدة الفاشلة نفسها
    assert "test_level.py::test_value" in choice.calls[1]


def test_budget_exhaustion_documented_not_polished(mini_repo):
    """الميزانية نافدة على فشل مستمر — الفشل كامل موثق، لا تحريف."""
    choice = CannedBrain(["src.py", "src.py", "src.py"])
    diff = CannedBrain([CORRUPT_PATCH, CORRUPT_PATCH, CORRUPT_PATCH])
    loop = RepairLoop(choice, diff, max_attempts=3)
    result = loop.run(_instance(), mini_repo, "python3", runner=_tree_runner())
    assert len(result.attempts) == 3
    assert all(not a.applied for a in result.attempts)
    assert result.attempts[-1].stop_reason_ar == "نهاية الميزانية — التطبيق فشل"
    assert not result.verdict.patch_applied
    assert not result.resolved_env
    # لا رجعية للمحاولة الرابعة — لا ميزانية
    assert "رجعية المحاولة السابقة" in choice.calls[2]
    assert len(choice.calls) == 3


def test_loop_switches_file_when_feedback_points_elsewhere(mini_repo):
    """الملف يتغير بين المحاولات — تعدد الملفات بمعنى الاختيار لا التحرير فقط."""
    choice = CannedBrain(["src.py", "alt.py"])
    diff = CannedBrain([CORRUPT_PATCH, GOOD_PATCH])
    loop = RepairLoop(choice, diff)
    result = loop.run(_instance(), mini_repo, "python3", runner=_tree_runner())
    assert result.file_choices == ("src.py", "alt.py")


def test_gate_rejection_terminates_with_documentation(mini_repo):
    """رفض بوابة PII/RTL — لا رجعية ممكنة للنص المرفوض، انصراف موثق."""
    choice = CannedBrain(["src.py"])
    diff = CannedBrain([GOOD_PATCH], accepted_flags=[False])
    loop = RepairLoop(choice, diff)
    result = loop.run(_instance(), mini_repo, "python3", runner=_tree_runner())
    assert not result.attempts[0].accepted
    assert "بوابة" in result.attempts[0].contract_reason_ar
    assert not result.verdict.patch_applied


def test_no_valid_file_choice_documents_and_stops(mini_repo):
    choice = CannedBrain(["ليس ملفاً في الشجرة"])
    diff = CannedBrain([])
    loop = RepairLoop(choice, diff)
    result = loop.run(_instance(), mini_repo, "python3", runner=_tree_runner())
    assert result.attempts[0].file_choice is None
    assert "لا ملف صالح" in result.attempts[0].stop_reason_ar
    assert result.chain_hash


def test_loop_result_receipt_is_byte_deterministic(mini_repo, tmp_path):
    """حلقتان: الأولى على المستودع العذب، والثانية على نسخة git متطابقة بالبايت."""
    clone = tmp_path / "repo-clone"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(mini_repo), str(clone)], check=True)
    choice = CannedBrain(["src.py", "src.py"])
    diff = CannedBrain([CORRUPT_PATCH, GOOD_PATCH])
    r1 = RepairLoop(choice, diff).run(_instance(), mini_repo, "python3", runner=_tree_runner())
    choice2 = CannedBrain(["src.py", "src.py"])
    diff2 = CannedBrain([CORRUPT_PATCH, GOOD_PATCH])
    r2 = RepairLoop(choice2, diff2).run(_instance(), clone, "python3", runner=_tree_runner())
    assert r1.chain_hash == r2.chain_hash
    doc = r1.to_dict()
    assert not any("time" in k or "second" in k for k in doc)
