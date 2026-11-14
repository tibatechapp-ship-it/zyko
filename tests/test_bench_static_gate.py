"""اختبارات البوابة الثابتة في حلقة الإصلاح (الموجة 29).

العقد: **لا رقعة تدخل القياس قبل أن تعيد القواعد الثمانية والثلاثون
الحكم على المصدر المصلَّح** — رقعة تكسر بنية الملف أو تُدخل ملاحظة
لم تكن في الأساس أو تُدنّس درجته تُرفض بعد التطبيق وتُعاد الشجرة إلى
الأساس قبل أي تشغيل اختبارات، والرفض معلن في الحكم لا مكتوم. وكل
رقعة تُؤرشف نصها الكامل في المحاولة — لا بصمة بلا نص فلا تدقيق
مُعاد (درس فحص نتائج الموجة 25: بصمات بلا نصوص تُفقد القدرة على
إعادة الحكم).

بلا شبكة وبلا مفتاح: git حقيقي على مستودع مصغّر، وRunner وهمي يعيد
مخرجات pytest معلبة — حتمي بالبايت على أي جهاز.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable

import pytest

from zyko.benchmarks.swebench import (
    SWEAttempt,
    SWEInstance,
    aggregate,
    apply_candidate,
    attempt_repair,
    evaluate_instance,
    patch_touched_py_files,
    run_static_gate,
)

# ---------------------------------------------------------------- القوالب
CLEAN_SRC = """def add(a, b):
    total = a + b
    return total


def div(a, b):
    if b == 0:
        raise ValueError("قسمة على صفر")
    return a // b
"""

# ملف أساس يحمل ملاحظة واحدة (except عارٍ — R-ERR-001 عالية: وزنها 8 ⇒ 92)
DIRTY_SRC = """def grab(items):
    try:
        return sum(items)
    except:
        return 0


def add(a, b):
    return a + b
"""

# تعديل مشروع: سطر تعليق بعد return total — بلا ملاحظات جديدة
GOOD_PATCH = """--- a/calc.py
+++ b/calc.py
@@ -1,6 +1,7 @@
 def add(a, b):
     total = a + b
     return total
+    # تعديل مشروع بلا ملاحظات


 def div(a, b):
"""

# رقعة تُدخل ملاحظة جديدة لم تكن في الأساس (except عارٍ — R-ERR-001)
BAD_PATCH = """--- a/calc.py
+++ b/calc.py
@@ -7,3 +7,10 @@
     if b == 0:
         raise ValueError("قسمة على صفر")
     return a // b
+
+
+def grab(items):
+    try:
+        return sum(items)
+    except:
+        return 0
"""

# رقعة تكسر البنية — المصدر المصلَّح لا يُحلَّل
BROKEN_PATCH = """--- a/calc.py
+++ b/calc.py
@@ -1,6 +1,8 @@
 def add(a, b):
     total = a + b
     return total
+def broken(:
+    pass


 def div(a, b):
"""

# رقعة تُدنّس الدرجة بلا قاعدة جديدة: أساس يحمل except عارٍ واحد،
# والرقعة تضيف ثانيًا — R-ERR-001 من 1 إلى 2 والدرجة من 92 إلى 84
SCORE_PATCH = """--- a/dirty.py
+++ b/dirty.py
@@ -7,3 +7,10 @@

 def add(a, b):
     return a + b
+
+
+def grab2(items):
+    try:
+        return sum(items)
+    except:
+        return 0
"""

NEW_FILE_PATCH = """--- /dev/null
+++ b/new_mod.py
@@ -0,0 +1,5 @@
+def grab(items):
+    try:
+        return sum(items)
+    except:
+        return 0
"""

MD_PATCH = """--- a/README.md
+++ b/README.md
@@ -1 +1,2 @@
+# عنوان
"""

DELETE_PATCH = """--- a/legacy.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def grab(items):
-    return 0
"""


@pytest.fixture
def gate_repo(tmp_path):
    """مستودع مصغّر بملف نظيف — HEAD هو الأساس الذي تقيس عليه البوابة."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "calc.py").write_text(CLEAN_SRC, encoding="utf-8")
    _git_commit_all(repo)
    return repo


@pytest.fixture
def dirty_repo(tmp_path):
    """مستودع مصغّر بملف ملوث بملاحظة واحدة (R-ERR-001) — الدرجة 92."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "dirty.py").write_text(DIRTY_SRC, encoding="utf-8")
    _git_commit_all(repo)
    return repo


def _git_commit_all(repo) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def _instance() -> SWEInstance:
    return SWEInstance(
        instance_id="psf__requests-0000",
        repo="psf/requests",
        base_commit="a" * 40,
        version="2.4",
        problem_statement="تقرير علة: القسمة تكسر العقد",
        test_patch="diff",
        fail_to_pass=("tests/test_calc.py::test_div",),
        pass_to_pass=("tests/test_calc.py::test_add",),
    )


def _pytest_runner() -> Callable[..., subprocess.CompletedProcess]:
    """Runner وهمي مُميِّز: pytest يعيد مخرجات معلبة، وgit يُنفَّذ حقاً.

    البوابة الثابتة وحرس التطبيق يأنفان git الحقيقي (show/apply/checkout)
    — تمييز الأوامر واجب: ما هو قياسُ مزيَّفٌ لا يجوز أن يمس الشجرة.
    """
    calls = {"n": 0}

    def runner(args, **kwargs):
        if args and args[0] == "git":
            return subprocess.run(args, **kwargs)
        calls["n"] += 1
        if calls["n"] == 1:
            out = "FAILED tests/test_calc.py::test_div\n1 failed, 1 passed\n"
            return subprocess.CompletedProcess(args, 1, stdout=out, stderr="")
        out = "2 passed\n"
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")

    return runner


class CannedBrain:
    def __init__(self, text, accepted=True):
        from zyko.ai.brains import GateVerdict, Proposal

        self._proposal = Proposal(
            text=text,
            brain="canned",
            deterministic=False,
            verdicts=(GateVerdict(gate="fake", passed=accepted),),
        )
        self.calls = []

    def propose(self, request):
        self.calls.append(request)
        return self._proposal


# ------------------------------------------------- patch_touched_py_files
def test_touched_py_files_filters_sorts_and_dedupes():
    patch = GOOD_PATCH + MD_PATCH + DELETE_PATCH
    assert patch_touched_py_files(patch) == ("calc.py", "legacy.py")


def test_touched_py_files_empty_for_no_diff():
    assert patch_touched_py_files("لا رقعة هنا") == ()


# --------------------------------------------------- run_static_gate مباشر
def test_gate_accepts_clean_fix(gate_repo):
    gate = run_static_gate(gate_repo, GOOD_PATCH, subprocess.run)
    assert gate["schema"] == "zyko.static_gate/1"
    assert gate["accepted"] is True
    assert gate["files_checked"] == ("calc.py",)
    assert gate["reasons_ar"] == ()
    assert gate["per_file"][0]["accepted"] is True
    # الأساس يحمل ملاحظتين معلومتين (R-QLT-204 منخفضة ×2 — وزن 2) ⇒ 96
    assert gate["per_file"][0]["score_before"] == 96
    assert gate["per_file"][0]["score_after"] == 96


def test_gate_rejects_new_finding_and_names_rule(gate_repo):
    ok, _ = apply_candidate(gate_repo, BAD_PATCH, subprocess.run)
    assert ok
    gate = run_static_gate(gate_repo, BAD_PATCH, subprocess.run)
    assert gate["accepted"] is False
    reasons = " | ".join(gate["reasons_ar"])
    assert "R-ERR-001" in reasons
    per = gate["per_file"][0]
    assert per["accepted"] is False
    assert per["score_after"] < per["score_before"]


def test_gate_rejects_parse_break(gate_repo):
    ok, _ = apply_candidate(gate_repo, BROKEN_PATCH, subprocess.run)
    assert ok
    gate = run_static_gate(gate_repo, BROKEN_PATCH, subprocess.run)
    assert gate["accepted"] is False
    assert any("لا يُحلَّل" in r for r in gate["reasons_ar"])


def test_gate_skips_new_file_with_no_baseline(gate_repo):
    ok, _ = apply_candidate(gate_repo, NEW_FILE_PATCH, subprocess.run)
    assert ok
    gate = run_static_gate(gate_repo, NEW_FILE_PATCH, subprocess.run)
    assert gate["accepted"] is True
    assert gate["files_checked"] == ()
    assert gate["files_skipped"] == [
        {"path": "new_mod.py", "reason_ar": "ملف جديد بلا أساس مقارنة"}
    ]


def test_gate_skips_deleted_file(gate_repo):
    (gate_repo / "legacy.py").write_text("def grab(items):\n    return 0\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=gate_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add legacy"], cwd=gate_repo, check=True)
    ok, _ = apply_candidate(gate_repo, DELETE_PATCH, subprocess.run)
    assert ok
    gate = run_static_gate(gate_repo, DELETE_PATCH, subprocess.run)
    assert gate["accepted"] is True
    assert gate["files_checked"] == ()
    assert gate["files_skipped"] == [{"path": "legacy.py", "reason_ar": "ملف محذوف في الرقعة"}]


def test_gate_rejects_score_regression_without_new_rules(dirty_repo):
    ok, _ = apply_candidate(dirty_repo, SCORE_PATCH, subprocess.run)
    assert ok
    gate = run_static_gate(dirty_repo, SCORE_PATCH, subprocess.run)
    assert gate["accepted"] is False
    per = gate["per_file"][0]
    assert per["checks"]["no_new_findings"] is True
    assert per["checks"]["score_not_worse"] is False
    # الأساس: R-ERR-001 (8) + R-QLT-204 ×2 (4) ⇒ 88، وبعده أربعة عناصر ⇒ 78
    assert per["score_before"] == 88
    assert per["score_after"] == 78


# ---------------------------------------------- التكامل في evaluate_instance
def test_evaluate_rejects_bad_patch_and_restores_tree(gate_repo):
    before = (gate_repo / "calc.py").read_text(encoding="utf-8")
    verdict = evaluate_instance(
        _instance(), gate_repo, "python3", candidate_patch=BAD_PATCH, runner=_pytest_runner()
    )
    assert verdict.patch_applied is False
    assert verdict.static_gate_reason_ar != ""
    assert verdict.resolved_strict is False
    # الشجرة عادت إلى الأساس بالبايت — لا أثر للرقعة المرفوضة
    assert (gate_repo / "calc.py").read_text(encoding="utf-8") == before
    # البوابة الثابتة كاملة في الحكم لا مختزلة
    assert verdict.static_gate["schema"] == "zyko.static_gate/1"
    assert verdict.static_gate["accepted"] is False


def test_evaluate_passes_good_patch_with_clean_gate(gate_repo):
    verdict = evaluate_instance(
        _instance(), gate_repo, "python3", candidate_patch=GOOD_PATCH, runner=_pytest_runner()
    )
    assert verdict.patch_applied is True
    assert verdict.static_gate_reason_ar == ""
    assert verdict.static_gate["accepted"] is True
    assert verdict.resolved_env is True


def test_aggregate_counts_static_gate_rejections(gate_repo):
    bad = evaluate_instance(
        _instance(), gate_repo, "python3", candidate_patch=BAD_PATCH, runner=_pytest_runner()
    )
    good = evaluate_instance(
        _instance(), gate_repo, "python3", candidate_patch=GOOD_PATCH, runner=_pytest_runner()
    )
    attempts = tuple(
        SWEAttempt(
            instance_id=v.instance_id,
            file_choice="calc.py",
            choice_reply_sha16="0" * 16,
            diff_reply_sha16="1" * 16,
            proposal_accepted=True,
            verdict=v,
        )
        for v in (bad, good)
    )
    agg = aggregate(attempts)
    assert agg.static_gate_rejections == 1
    assert agg.applied_count == 1


# ----------------------------------------- أرشفة نص الرقعة في المحاولة
def test_attempt_repair_archives_patch_text(gate_repo):
    choice = CannedBrain("calc.py")
    diff = CannedBrain("الحل:\n```diff\n" + GOOD_PATCH + "```")
    attempt = attempt_repair(
        _instance(), gate_repo, "python3", choice, diff, runner=_pytest_runner()
    )
    # الأرشفة تحمل الرقعة كما طُبِّقت فعلاً — كما يُخرجها extract_diff
    assert attempt.patch_text == GOOD_PATCH.strip()
    assert attempt.to_dict()["patch_text"] == GOOD_PATCH.strip()
    assert attempt.verdict.patch_applied is True
