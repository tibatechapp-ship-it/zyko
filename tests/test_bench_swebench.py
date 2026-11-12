"""اختبارات بروتوكول SWE-bench-Lite (جولة 8) — كلها بلا شبكة وبلا مفتاح.

الحقن يحكم: ``Runner`` وهمي يعيد مخرجات pytest المعلبة، ``Transport`` وهمي
يعيد ردود عقل معلبة، وgit الحقيقي يعمل على مستودع مصغّر محلي — بذلك تبقى
الاختبارات حتمية بالبايت على أي جهاز.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from zyko.benchmarks.swebench import (
    SWEAggregate,
    SWEAttempt,
    SWEBrain,
    SWEInstance,
    SWEVerdict,
    aggregate,
    apply_candidate,
    attempt_repair,
    build_choice_request,
    build_diff_request,
    check_patch_contract,
    diff_paths,
    evaluate_instance,
    extract_diff,
    line_removes_file,
    load_instances,
    parse_choice,
    repo_py_tree,
    run_ids,
)

# تخطٍ موثق: النواة تعلن Landlock لكن إقامته تفشل في حاويات CI
# (سياسات seccomp تحجب landlock_add_rule) — بروبة إقامة حقيقية تقرر.
from zyko.sandbox import jail as _jail_mod

_jail_broken = (
    _jail_mod.jail_level() == _jail_mod.JAIL_LEVEL_LANDLOCK
    and not _jail_mod.jail_establishment_ok()
)
_working_jail = pytest.mark.skipif(
    _jail_broken,
    reason="إقامة الحبس النواتي تفشل في هذه البيئة (seccomp الحاوية يحجب Landlock) — تخطٍ موثق لا فشل",
)

DATA = Path(__file__).resolve().parents[1] / "benchmarks" / "data" / "swe_bench_lite_requests.json"


def _instance(**overrides) -> SWEInstance:
    base = dict(
        instance_id="psf__requests-0000", repo="psf/requests", base_commit="a" * 40,
        version="2.4", problem_statement="تقرير علة: الترميز يكسر الطريقة",
        test_patch="diff", fail_to_pass=("test_requests.py::A::x", "test_requests.py::A::y"),
        pass_to_pass=("test_requests.py::B::z",),
    )
    return SWEInstance(**{**base, **overrides})


# --------------------------------------------------------------- التحميل
def test_load_instances_real_file_sorted_and_parsed():
    instances = load_instances(DATA)
    ids = [i.instance_id for i in instances]
    assert len(instances) == 6
    assert ids == sorted(ids)
    for inst in instances:
        assert inst.fail_to_pass and inst.pass_to_pass
        assert inst.fail_to_pass == tuple(sorted(inst.fail_to_pass))
        assert inst.repo == "psf/requests"
        assert len(inst.base_commit) == 40


def test_load_instances_provenance_fields():
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    assert raw["repo_filter"] == "psf/requests"
    assert raw["gold_patch_excluded"].strip()  # الاستبعاد موثق نصاً لا مكتوماً
    assert raw["source"].startswith("princeton-nlp/SWE-bench_Lite")


def test_load_instances_empty_fields_guard(tmp_path):
    doc = {"instances": [{"instance_id": "x", "repo": "r", "base_commit": "b" * 40,
                          "version": "1", "problem_statement": "p", "test_patch": "t",
                          "FAIL_TO_PASS": None, "PASS_TO_PASS": "a\nb"}]}
    path = tmp_path / "inst.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    instances = load_instances(path)
    assert instances[0].fail_to_pass == ()
    assert instances[0].pass_to_pass == ("a", "b")


# --------------------------------------------------------------- الرقعة
_PATCH = """--- a/requests/models.py
+++ b/requests/models.py
@@ -1,3 +1,4 @@
 import os
+import sys
 import json"""


def test_extract_diff_fenced_block_wins():
    text = "شرح\n```diff\n" + _PATCH + "\n```\nبعده"
    assert extract_diff(text) == _PATCH.strip()


def test_extract_diff_raw_fallback():
    assert extract_diff("بدون سورة\n" + _PATCH).startswith("--- a/")
    assert extract_diff("لا رقعة هنا إطلاقاً") is None
    assert extract_diff("") is None


def test_extract_diff_reconstructs_bare_hunks_from_known_path():
    """الأجزاء العارية ``@@`` بلا ترويسات — تُبنى حولها ترويسة من مسار طلبنا."""
    reply = "الإصلاح:\n@@ -1,1 +1,2 @@\n value = 1\n+value = 2\nشرح النهاية"
    patch = extract_diff(reply, fallback_path="src.py")
    assert patch.startswith("--- a/src.py\n+++ b/src.py")
    assert "@@ -1,1 +1,2 @@" in patch
    # بلا مسار معلوم — الصدق: لا رقعة
    assert extract_diff(reply, fallback_path=None) is None
    assert extract_diff("لا شيء", fallback_path="src.py") is None


def test_diff_paths_sorted_and_cleaned():
    patch = """--- a/requests/models.py
+++ b/requests/models.py
@@ -1 +1 @@
--- a/requests/sessions.py
+++ /dev/null
@@ -1 +0,0 @@
-bye
--- /dev/null
+++ b/requests/api.py
@@ -1 +1 @@
+new"""
    assert diff_paths(patch) == ("requests/api.py", "requests/models.py", "requests/sessions.py")


def test_patch_contract_accepts_and_rejects():
    ok, why = check_patch_contract(_PATCH)
    assert ok and "مسموح" in why
    ok, why = check_patch_contract("   ")
    assert not ok and "فارغة" in why
    ok, why = check_patch_contract("ليست رقعة")
    assert not ok and "لا مسارات" in why
    ok, why = check_patch_contract(_PATCH.replace("a/requests/models.py", "/etc/passwd")
                                   .replace("b/requests/models.py", "/etc/passwd"))
    assert not ok and "مطلق" in why
    sensitive = _PATCH.replace("requests/models.py", ".env")
    ok, why = check_patch_contract(sensitive)
    assert not ok and "حساس" in why
    ok, why = check_patch_contract(_PATCH + "x" * 70_000)
    assert not ok and "السقف" in why


def test_patch_contract_rejects_test_deletion():
    deleter = """--- a/test_requests.py
+++ /dev/null
@@ -1,10 +0,0 @@
-old"""
    ok, why = check_patch_contract(deleter)
    assert not ok and "ملف اختبار" in why
    # تعديل اختبار (ليس حذفاً) — مسموح لأن الرقعة القانونية قد تلمس سياق الاختبار
    modifier = """--- a/test_requests.py
+++ b/test_requests.py
@@ -1,2 +1,2 @@
-old
+new"""
    assert check_patch_contract(modifier)[0]


def test_line_removes_file():
    assert line_removes_file("--- a/t.py\n+++ /dev/null\n-x", "t.py")
    assert not line_removes_file(_PATCH, "requests/models.py")


# --------------------------------------------------------------- التشغيل
class FakeRun:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _pytest_stdout(failed_ids, passed):
    lines = "\n".join(f"FAILED {fid} - assert False" for fid in failed_ids)
    summary = f"{passed} passed" + (f", {len(failed_ids)} failed" if failed_ids else "")
    return f"short test summary info\n{lines}\n===== {summary} in 1.0s ====="


def test_run_ids_parses_failed_and_passed():
    calls = []
    def runner(args, **kwargs):
        calls.append(args)
        return FakeRun(1, stdout=_pytest_stdout(["t.py::A::x"], 5))
    run = run_ids(Path("/tmp"), ("t.py::A::x", "t.py::A::y"), "python3", runner=runner)
    assert run.exit_code == 1 and run.passed_count == 5
    assert run.failed_ids == ("t.py::A::x",)
    assert run.ok is False
    assert calls[0][0] == "python3" and "-m" in calls[0] and "pytest" in calls[0]
    assert "--tb=no" in calls[0] and "-rf" in calls[0]


def test_run_ids_timeout_and_missing_python():
    def timeout_runner(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=5)
    run = run_ids(Path("/tmp"), ("a::b",), "python3", runner=timeout_runner)
    assert run.exit_code == -1 and "المهلة" in run.error_ar
    def missing(args, **kwargs):
        raise FileNotFoundError("nope")
    run = run_ids(Path("/tmp"), ("a::b",), "python9", runner=missing)
    assert "المفسّر" in run.error_ar


def test_run_ids_no_ids_is_documented_guard():
    run = run_ids(Path("/tmp"), (), "python3")
    assert run.exit_code == 0 and "لا عقد" in run.error_ar


def test_run_ids_exit_two_is_error():
    run = run_ids(Path("/tmp"), ("a::b",), "python3",
                  runner=lambda args, **kw: FakeRun(2, stdout="usage error"))
    assert run.exit_code == 2 and "خرج بـ 2" in run.error_ar


# --------------------------------------------------------------- التطبيق بـ git الحقيقي
@pytest.fixture()
def mini_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def test_apply_candidate_real_git_success(mini_repo):
    patch = """--- a/src.py
+++ b/src.py
@@ -1 +1,2 @@
 value = 1
+value = 2"""
    ok, why = apply_candidate(mini_repo, patch, subprocess.run)
    assert ok and "طُبِّقت" in why
    assert "value = 2" in (mini_repo / "src.py").read_text(encoding="utf-8")


def test_apply_candidate_real_git_rejects_broken_context(mini_repo):
    patch = """--- a/src.py
+++ b/src.py
@@ -9,1 +9,2 @@
 nonexistent context line
+added"""
    ok, why = apply_candidate(mini_repo, patch, subprocess.run)
    assert not ok and "فشل" in why


# --------------------------------------------------------------- الحكم
def _verdict_dict_runner(base_failed, after_failed, total_passed=100):
    outputs = [
        FakeRun(1, stdout=_pytest_stdout(base_failed, 0)),
        FakeRun(0, stdout=_pytest_stdout(after_failed, total_passed)),
    ]
    def runner(args, **kwargs):
        return outputs.pop(0)
    return runner


def test_evaluate_instance_resolved_env_with_env_fail():
    inst = _instance()
    # الأساس: الفشل فيه هو الفشل الأول الممرر — لكن B::z لم يفشل في الأساس هنا
    outputs = [
        FakeRun(1, stdout=_pytest_stdout(["test_requests.py::A::x", "test_requests.py::A::y", "test_requests.py::B::z"], 0)),
        FakeRun(0, stdout=_pytest_stdout(["test_requests.py::B::z"], 2)),
    ]
    def runner(args, **kwargs):
        return outputs.pop(0)
    verdict = evaluate_instance(inst, Path("/w"), "python3",
                                candidate_patch="not-applied-yet", runner=runner)
    # الرقعة "not-applied-yet" ستُرفض في العقد — نتحقق من مسار الرفض بدل الحكم
    assert not verdict.patch_applied and "لا مسارات" in verdict.contract_reason_ar
    assert verdict.f2p_failed_at_base == ("test_requests.py::A::x", "test_requests.py::A::y")
    assert verdict.p2p_failed_at_base == ("test_requests.py::B::z",)


@_working_jail
def test_evaluate_instance_full_resolution_flow(mini_repo):
    """قياس حقيقي كامل: عقدة pytest فاشلة ثم ناجحة بعد رقعة حقيقية."""
    inst = _instance(
        fail_to_pass=("test_level.py::test_value",),
        pass_to_pass=(),
    )
    (mini_repo / "test_level.py").write_text(
        "def test_value():\n    from src import value\n    assert value == 2\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=mini_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "test"], cwd=mini_repo, check=True)
    python_bin = "python3"
    patch = """--- a/src.py
+++ b/src.py
@@ -1 +1 @@
-value = 1
+value = 2"""
    verdict = evaluate_instance(inst, mini_repo, python_bin,
                                candidate_patch=patch, runner=subprocess.run)
    assert verdict.patch_applied
    assert verdict.f2p_failed_at_base == ("test_level.py::test_value",)
    assert verdict.f2p_failed_after == ()
    assert verdict.resolved_strict and verdict.resolved_env
    assert verdict.f2p_repaired_count == 1
    assert len(verdict.chain_hash) == 16


def test_evaluate_instance_contract_rejection_documented():
    inst = _instance()
    runner = _verdict_dict_runner(base_failed=["test_requests.py::A::x"], after_failed=[])
    verdict = evaluate_instance(inst, Path("/w"), "python3",
                                candidate_patch="--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-x\n+y",
                                runner=runner)
    assert not verdict.patch_applied and "حساس" in verdict.contract_reason_ar
    assert verdict.f2p_failed_after == inst.fail_to_pass  # لم تُطبَّق ⇒ الفشل باقٍ
    assert verdict.patch_sha16


def test_evaluate_instance_base_timeout_no_verdict():
    def timeout_runner(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=9)
    verdict = evaluate_instance(_instance(), Path("/w"), "python3",
                                candidate_patch=None, runner=timeout_runner)
    assert not verdict.patch_applied and "المهلة" in verdict.runs_error_ar


def test_verdict_chain_hash_is_byte_deterministic():
    kwargs = dict(
        instance_id="x", patch_applied=True, apply_error_ar=None,
        f2p_failed_at_base=("a",), p2p_failed_at_base=("b",),
        f2p_passed_after=("a",), f2p_failed_after=(), p2p_failed_after=(),
        patch_sha16="deadbeefdeadbeef",
    )
    assert SWEVerdict(**kwargs).chain_hash == SWEVerdict(**kwargs).chain_hash
    doc = SWEVerdict(**kwargs).to_dict()
    assert not any("time" in key or "second" in key for key in doc)


# --------------------------------------------------------------- العقل الحقيقي
def _transport_reply(content):
    return lambda payload: {"choices": [{"message": {"content": content}}]}


def test_swe_brain_without_env_is_disabled_honestly(monkeypatch):
    monkeypatch.delenv("ZYKO_QWEN_HOST", raising=False)
    monkeypatch.delenv("ZYKO_QWEN_API_KEY", raising=False)
    brain = SWEBrain(mode="choice")
    proposal = brain.propose("اختر ملفاً")
    assert not proposal.accepted and "معطل" in proposal.verdicts[0].details_ar


def test_swe_brain_transport_error_is_arabic():
    brain = SWEBrain(mode="diff", host="http://x/v1", api_key="k",
                     transport=lambda payload: {"error": {"message": "HTTP 502"}})
    proposal = brain.propose("أعد رقعة")
    assert not proposal.accepted and "502" in proposal.verdicts[0].details_ar


def test_swe_brain_malformed_response():
    brain = SWEBrain(mode="choice", host="http://x/v1", api_key="k",
                     transport=lambda payload: {"unexpected": True})
    assert not brain.propose("س").accepted


def test_swe_brain_happy_transport_carries_system_and_user():
    seen = {}
    def transport(payload):
        seen.update(payload)
        return {"choices": [{"message": {"content": "requests/models.py"}}]}
    brain = SWEBrain(mode="choice", transport=transport)
    proposal = brain.propose("التقرير\nالشجرة")
    assert proposal.accepted and proposal.deterministic is False
    assert seen["messages"][0]["role"] == "system"
    assert "مصدر" in seen["messages"][0]["content"]


def test_choice_request_and_parse():
    tree = ("requests/api.py", "requests/models.py")
    inst = _instance()
    request = build_choice_request(inst, tree)
    assert "التقرير" in request and "requests/models.py" in request
    assert parse_choice("أقترح requests/models.py لكونه جوهر النموذج", tree) == "requests/models.py"
    assert parse_choice("لا مسار هنا", tree) is None


def test_diff_request_contains_file_content():
    request = build_diff_request(_instance(), "requests/models.py", "X = 1\n")
    assert "X = 1" in request and "requests/models.py" in request


def test_repo_py_tree_sorted_excluding_tests():
    def runner(args, **kwargs):
        return FakeRun(0, stdout="requests/sessions.py\nrequests/api.py\ntest_requests.py\n")
    assert repo_py_tree(Path("/w"), runner) == ("requests/api.py", "requests/sessions.py")


# --------------------------------------------------------------- المحاولة
class CannedBrain:
    def __init__(self, text, accepted=True):
        from zyko.ai.brains import GateVerdict, Proposal
        self._proposal = Proposal(text=text, brain="canned", deterministic=False,
                                  verdicts=(GateVerdict(gate="fake", passed=accepted),))
        self.calls = []

    def propose(self, request):
        self.calls.append(request)
        return self._proposal


@_working_jail
def test_attempt_repair_happy_path_real_git(mini_repo):
    inst = _instance(
        instance_id="psf__requests-0000",
        fail_to_pass=("test_level.py::test_value",),
        pass_to_pass=(),
        problem_statement="القيمة يجب أن تكون 2",
    )
    (mini_repo / "test_level.py").write_text(
        "def test_value():\n    from src import value\n    assert value == 2\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=mini_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "test"], cwd=mini_repo, check=True)
    choice = CannedBrain("اخترنا src.py")
    diff = CannedBrain("الحل:\n```diff\n--- a/src.py\n+++ b/src.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n```")
    attempt = attempt_repair(inst, mini_repo, "python3", choice, diff, runner=subprocess.run)
    assert attempt.file_choice == "src.py"
    assert attempt.proposal_accepted
    assert attempt.verdict.resolved_env and attempt.verdict.resolved_strict
    assert len(attempt.choice_reply_sha16) == 16 and len(attempt.diff_reply_sha16) == 16


def test_attempt_repair_gate_rejection_documented(mini_repo):
    choice = CannedBrain("src.py", accepted=False)
    diff = CannedBrain("لا يُطلب مني أبداً")
    attempt = attempt_repair(_instance(), mini_repo, "python3", choice, diff, runner=subprocess.run)
    assert not attempt.proposal_accepted
    assert "اختيار الملف" in attempt.verdict.attempts_note_ar


def test_attempt_repair_no_diff_in_reply(mini_repo):
    choice = CannedBrain("src.py")
    diff = CannedBrain("شرح بلا رقعة إطلاقاً")
    attempt = attempt_repair(_instance(), mini_repo, "python3", choice, diff, runner=subprocess.run)
    assert attempt.proposal_accepted and attempt.verdict.patch_applied is False
    assert "لا رقعة موحدة" in attempt.verdict.attempts_note_ar


# --------------------------------------------------------------- الخلاصة
def test_aggregate_counts_and_rate():
    def verdict(resolved_env, resolved_strict, applied, repaired):
        return SWEVerdict(
            instance_id="x", patch_applied=applied, apply_error_ar=None,
            f2p_failed_at_base=("f1", "f2"), p2p_failed_at_base=(),
            f2p_passed_after=("f1",) if repaired else (),
            f2p_failed_after=() if repaired else ("f1", "f2"),
            p2p_failed_after=(),
        )
    attempts = (
        SWEAttempt(instance_id="a", file_choice="f", choice_reply_sha16="1",
                   diff_reply_sha16="2", proposal_accepted=True,
                   verdict=verdict(True, True, True, True)),
        SWEAttempt(instance_id="b", file_choice=None, choice_reply_sha16="",
                   diff_reply_sha16="", proposal_accepted=False,
                   verdict=verdict(False, False, False, False)),
    )
    agg = aggregate(attempts)
    assert isinstance(agg, SWEAggregate)
    assert agg.total == 2 and agg.resolved_env == 1 and agg.resolved_strict == 1
    assert agg.applied_count == 1 and agg.gate_rejections == 1
    assert agg.f2p_repaired_total == 1
    # الاتحاد لكل محاولة = عقدا FAIL_TO_PASS ("f1","f2") × محاولتان = 4
    assert agg.f2p_total == 4
    assert agg.resolve_rate_env == 0.5
