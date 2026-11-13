"""اختبارات منقِذ المسار الحتمي (الموجة 25) — بلا شبكة، بلا نموذج، بالبايت.

درس العينة الواسعة بالبايت: 34 حالة من 44 ماتت عند «اختيار الملف رُفض
ببوابة أو لم يعطِ مساراً موجوداً» — نقطة فشل أحادية. هذه الاختبارات
تُثبت عقود المنقذ الثلاثة:
1. درجات معلنة بالترتيب (عقل ← تطبيع ← معجمي) — أول مسار حي يفوز.
2. لا مسار خارج الشجرة إطلاقاً — والغموض رفض لا تخمين.
3. الإنقاذ يُعلن في محاولة الحلقة (rescue_mode) — لا استبدال صامت.
"""

from __future__ import annotations

import subprocess

from zyko.benchmarks.path_rescue import (
    candidate_paths_from_reply,
    rescue_choice,
    resolve_candidate,
)
from zyko.benchmarks.repair_loop import RepairLoop
from zyko.benchmarks.swebench import SWEInstance

TREE = (
    "requests/api.py",
    "requests/adapters.py",
    "requests/models.py",
    "requests/sessions.py",
    "requests/utils.py",
)


def _instance(**overrides) -> SWEInstance:
    base = dict(
        instance_id="psf__requests-0000",
        repo="psf/requests",
        base_commit="a" * 40,
        version="2.4",
        problem_statement="PreparedRequest drops Content-Length header on redirect in sessions",
        test_patch="diff",
        fail_to_pass=("test_requests.py::test_no_content_length",),
        pass_to_pass=(),
    )
    return SWEInstance(**{**base, **overrides})


# ------------------------------------------------------------ المرشّحات
def test_candidates_strip_code_spans_and_prefixes():
    text = "`requests/models.py` ثم a/api.py ثم psf__requests-1142/models.py"
    assert candidate_paths_from_reply(text) == (
        "requests/models.py",
        "api.py",
        "models.py",
    )


def test_candidates_drop_noise_without_extension():
    assert candidate_paths_from_reply("لا شيء هنا إطلاقاً") == ()
    assert candidate_paths_from_reply("") == ()


# ------------------------------------------------------------ المطابقة
def test_resolve_exact_then_suffix_then_ambiguous():
    assert resolve_candidate("requests/models.py", TREE) == "requests/models.py"
    # لاحقة فريدة: models.py لاحقة واحدة في الشجرة
    assert resolve_candidate("models.py", TREE) == "requests/models.py"
    # غموض عقد: لاحقتان ممكنتان ⇒ رفض لا تخمين — الشجرة هنا تساوي
    # اللاحقة نفسها فتُقبل تاماً، لذا نضيف نظيراً ليجبر الرفض
    wider = TREE + ("contrib/models.py",)
    assert resolve_candidate("models.py", wider) is None
    assert resolve_candidate("لا_يوجد.py", TREE) is None
    assert resolve_candidate("requests/models.py", ()) is None


# ------------------------------------------------------------ الدرجات
def test_stage_brain_valid_path_in_reply():
    resc = rescue_choice("أقترح requests/models.py لأنه المصدر", TREE, _instance())
    assert resc.mode == "brain"
    assert resc.path == "requests/models.py"
    assert not resc.rescued  # المسار القياسي لا يُعد إنقاذاً


def test_stage_normalize_recovers_from_basename_only():
    """التطبيع ينشط حين لا يظهر في الرد مسار شجري حرفي — العقل يقول
    «models.py» فحسب: parse_choice يخفق والتطبيع يطابق باللاحقة الفريدة."""
    resc = rescue_choice("عدّل `models.py` أولاً", TREE, _instance())
    assert resc.mode == "normalize"
    assert resc.path == "requests/models.py"
    assert resc.rescued


def test_stage_brain_precedes_normalize_for_verbatim_paths():
    """الأولوية المعلنة: الرد الذي يذكر مساراً شجرياً حرفياً يُحسم في
    الدرج الأول (العقد الأصلي لا يتغير) حتى لو جاء بسوابق أ/ب."""
    resc = rescue_choice("`a/requests/models.py`", TREE, _instance())
    assert resc.mode == "brain"
    assert resc.path == "requests/models.py"
    assert not resc.rescued


def test_stage_lexical_without_any_reply():
    resc = rescue_choice("", TREE, _instance())
    assert resc.mode == "lexical"
    assert resc.path is not None and resc.path in TREE


def test_stage_none_on_empty_tree():
    resc = rescue_choice("", (), _instance())
    assert resc.mode == "none"
    assert resc.path is None


def test_determinism_byte_identical():
    inst = _instance()
    a = rescue_choice("context-free reply", TREE, inst)
    b = rescue_choice("context-free reply", TREE, inst)
    assert a == b


def test_path_never_outside_tree():
    inst = _instance()
    for reply in (
        "`../../etc/passwd`",
        "`/absolute/models.py`",
        "`requests/../../secret.py`",
        "``",
    ):
        resc = rescue_choice(reply, TREE, inst)
        assert resc.path is None or resc.path in TREE


# ------------------------------------------------- التوصيل في الحلقة
class CannedBrain:
    """عقل معلب — نفس عقد اختبارات الحلقة، كل نداء يُسجل."""

    def __init__(self, replies: list[str], accepted_flags: list[bool] | None = None):

        self._replies = list(replies)
        self._flags = accepted_flags or [True] * len(self._replies)
        self.calls: list[str] = []

    def propose(self, request: str) -> object:
        from zyko.ai.brains import GateVerdict, Proposal

        self.calls.append(request)
        text = self._replies.pop(0) if self._replies else ""
        passed = self._flags.pop(0) if self._flags else False
        return Proposal(
            text=text,
            brain="canned",
            deterministic=False,
            verdicts=(GateVerdict(gate="fake", passed=passed),),
        )


def _mini_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "alt.py").write_text("alt = 1\n", encoding="utf-8")
    (repo / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
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


def test_loop_survives_choice_failure_via_rescue(tmp_path):
    """درس الموجة 25 بالبايت: رد اختيار أعمى (لا مسار فيه) كان يكسر الحلقة —
    الآن المنقذ المعجمي يواصلها إلى مرحلة الرقعة، والوضع موثق في المحاولة."""
    repo = _mini_repo(tmp_path)
    choice = CannedBrain(["لا أعرف أي ملف — عذرًا"], [True])
    diff = CannedBrain(
        ["```diff\n--- a/src.py\n+++ b/src.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n```"]
    )
    loop = RepairLoop(choice, diff, max_attempts=1)
    result = loop.run(_instance(), repo, "python3")
    attempt = result.attempts[0]
    assert attempt.file_choice is not None
    assert attempt.rescue_mode == "lexical"
    # الحلقة وصلت مرحلة الرقعة فعلاً — الرد الثاني استُهلك
    assert len(diff.calls) == 1


def test_loop_declares_brain_mode_on_gate_rejected_choice(tmp_path):
    """رد الاختيار رُفض ببوابة لكنه سمّى مساراً حياً: المسار يُستخرج
    للتوثيق فقط (لا نص حر يعبر) والوضع «brain» يُعلن لا يُطمَس."""
    repo = _mini_repo(tmp_path)
    choice = CannedBrain(["الملف src.py يحتاج تعديلاً"], [False])
    diff = CannedBrain(
        ["```diff\n--- a/src.py\n+++ b/src.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n```"]
    )
    loop = RepairLoop(choice, diff, max_attempts=1)
    result = loop.run(_instance(), repo, "python3")
    attempt = result.attempts[0]
    assert attempt.file_choice == "src.py"
    assert attempt.rescue_mode == "brain"
    assert "rescue_mode" in attempt.to_dict()


def test_loop_attempt_receipt_covers_rescue(tmp_path):
    """سلسلة الإيصال تحمل وضع الإنقاذ — أي تحرير لاحق يكشفه بصمة السلسلة."""
    repo = _mini_repo(tmp_path)
    choice = CannedBrain(["لا أعرف"], [True])
    diff = CannedBrain(["لا رقعة"])
    loop = RepairLoop(choice, diff, max_attempts=1)
    result = loop.run(_instance(), repo, "python3")
    doc = result.to_dict()
    assert doc["attempts"][0]["rescue_mode"] == "lexical"
    assert result.chain_hash
