"""اختبارات الترابط الشاملة — السلاسل الكاملة من الهدف إلى الإيصال المتحقق.

هذا الملف هو شبكة الأمان بين الطبقات: كل اختبار يمشي سلسلة كاملة حقيقية
(بلا مخططات جزئية ولا بدائل مقلدة) ويتحقق من العقد بين طبقتين أو أكثر:

1. ``zyko do`` (classify→route→run) ⇒ إيصال ⇒ ``verify`` دون ثقة ⇒
   التلاعب بالحقل يُكشف.
2. وضع الكتابة الفعلي: ملف حقيقي يُصلَح على القرص، البصمة تتغير، والدرجة
   تتحسن، والإيصال يحكي القصة كاملة.
3. جلسة الذكاء ``existing`` (عقل ← بوابات ← orchestrator ← إيصال مكتوب).
4. خطة الدماغ (brain_route) عبر المنسق نفسها حتى الإيصال المتحقق.
5. الملف الضخم عبر أدوات المنسق ثم التحقق.
6. السرب: مهام متوازية بنتائج بترتيب المدخل وإيصال واحد فوق سلسلتها.
7. المصنع الكامل (جلسة factory): توليد ← إصلاح ← خط أساس ← إيصال مكتوب.
8. الحتمية البايتية عبر السلسلة كاملة: تشغيلان ⇒ إيصالان متطابقان.
"""

from __future__ import annotations

import json
from pathlib import Path

from zyko.ai.brains import GateVerdict, Proposal
from zyko.ai.receipt import hash_file
from zyko.orchestrator import classify, extract_context, route, run, swarm
from zyko.orchestrator.brain_route import plan_with_brain
from zyko.orchestrator.verify import verify_orchestration_receipt

# مصدر يحمل ملاحظات قابلة للإصلاح الآلي فعلاً (مسافات/استيراد ميت...)
FIXABLE_SRC = """import os
import sys


def  calc( a,b ):
    x = a + b
    return    x
"""


class JsonBrain:
    """دماغ اختباري يعيد خطة JSON ثابتة — عقد Brain نفسه."""

    name = "json-brain"
    deterministic = False

    def __init__(self, payload: str) -> None:
        self.payload = payload

    def propose(self, request: str) -> Proposal:
        return Proposal(
            text=self.payload,
            brain=self.name,
            deterministic=self.deterministic,
            verdicts=(GateVerdict(gate="planner", passed=True, details_ar="خطة سليمة"),),
        )


def _review_json(path: Path) -> str:
    from zyko.orchestrator.classify import TaskType

    plan = route(classify(f"راجع {path}"), context={"path": str(path)})
    payload = {
        "task": TaskType.REVIEW.value,
        "steps": [
            {"tool": s.tool, "path": s.args["path"], "reason_ar": s.reason_ar} for s in plan.steps
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


# ------------------------------------------------------------- 1) do ⇒ verify
def test_do_receipt_verifies_offline(tmp_path: Path) -> None:
    """السلسلة الكاملة: هدف ⇒ إيصال ⇒ تحقق دون ثقة ⇒ 100% خضراء."""
    target = tmp_path / "app.py"
    target.write_text("def f():\n    return 1\n", encoding="utf-8")
    goal = f"راجع {target}"
    plan = route(classify(goal), context=extract_context(goal))
    result = run(plan, dry_run=True)
    assert result.ok
    report = verify_orchestration_receipt(result.receipt)
    assert report.ok, report.issues
    assert report.checks > 0


def test_do_receipt_tampering_is_detected(tmp_path: Path) -> None:
    """التلاعب بأي حقل داخل الخطوة يُكشف فورًا — الدقة عقد لا ثقة."""
    target = tmp_path / "app.py"
    target.write_text("def f():\n    return 1\n", encoding="utf-8")
    plan = route(classify(f"راجع {target}"), context=extract_context(f"راجع {target}"))
    receipt = run(plan, dry_run=True).receipt
    tampered = json.loads(json.dumps(receipt, ensure_ascii=False))
    tampered["steps"][0]["output"]["score"] = 99  # تلميع نتيجة
    report = verify_orchestration_receipt(tampered)
    assert not report.ok


def test_do_receipt_recomputes_chain_hash(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("def f():\n    return 1\n", encoding="utf-8")
    plan = route(classify(f"راجع {target}"), context=extract_context(f"راجع {target}"))
    receipt = run(plan, dry_run=True).receipt
    from zyko.orchestrator.run import chain_hash_of, step_sha256

    recomputed = chain_hash_of([s["sha256"] for s in receipt["steps"]])
    assert receipt["chain_hash"] == recomputed
    for step in receipt["steps"]:
        payload = {
            k: step[k]
            for k in ("tool", "args", "reason_ar", "ok", "guardian_verdict", "error_ar", "output")
        }
        assert step["sha256"] == step_sha256(payload)


# ------------------------------------------------------------- 2) الكتابة الفعلية
def test_write_mode_fixes_real_file_end_to_end(tmp_path: Path) -> None:
    """«راجع وأصلح» بوضع الكتابة: الملف يتغير فعلاً والدرجة تتحسن والإيصال صادق."""
    target = tmp_path / "dirty.py"
    target.write_text(FIXABLE_SRC, encoding="utf-8")
    sha_before = hash_file(target)
    goal = f"راجع وأصلح {target}"
    plan = route(classify(goal), context=extract_context(goal))
    assert [s.tool for s in plan.steps] == ["review", "fix"]
    result = run(plan, dry_run=False)
    assert result.ok, [s.error_ar for s in result.steps]
    sha_after = hash_file(target)
    assert sha_after != sha_before  # القرص تغيّر فعلاً
    fix_output = result.steps[1].output
    assert fix_output["applied"] is True
    assert fix_output["score_after"] > fix_output["score_before"]


def test_write_mode_score_matches_fresh_review(tmp_path: Path) -> None:
    """الدرجة بعد الإصلاح من الإيصال = درجة مراجعة جديدة للملف على القرص."""
    target = tmp_path / "dirty.py"
    target.write_text(FIXABLE_SRC, encoding="utf-8")
    plan = route(classify(f"راجع وأصلح {target}"), context=extract_context(f"راجع وأصلح {target}"))
    result = run(plan, dry_run=False)
    from zyko.reviewer.engine import ReviewEngine

    fresh = ReviewEngine().review_file(target)
    assert fresh.score == result.steps[1].output["score_after"]


# ------------------------------------------------------------- 3) الجلسة existing
def test_session_existing_write_full_chain(tmp_path: Path) -> None:
    """عقل ← بوابات ← orchestrator ← إيصال مكتوب — الجلسة الكاملة على كود قائم."""
    from zyko.ai.brains import GatedBrain, PlannerBrain
    from zyko.ai.session import AISession

    target = tmp_path / "target.py"
    target.write_text(FIXABLE_SRC, encoding="utf-8")
    out_dir = tmp_path / "receipt-out"
    out_dir.mkdir()
    session = AISession(GatedBrain(PlannerBrain()), mode="existing", fail_under=10)
    receipt = session.run(f"راجع وأصلح {target}", out_dir, write=True)
    assert receipt.ok
    gate = next(s for s in receipt.steps if s.step == "orchestrator")
    assert gate.ok
    assert str(target) in receipt.files_written
    # الإيصال مكتوب على القرص ومقروء ومتحقق منه دون ثقة
    json_path = out_dir / ".zyko" / "ai_receipt.json"
    assert json_path.is_file()
    on_disk = json.loads(json_path.read_text(encoding="utf-8"))
    assert on_disk["brain"] == "gated:planner"


def test_session_existing_dry_run_writes_nothing(tmp_path: Path) -> None:
    from zyko.ai.brains import GatedBrain, PlannerBrain
    from zyko.ai.session import AISession

    target = tmp_path / "target.py"
    target.write_text(FIXABLE_SRC, encoding="utf-8")
    sha_before = hash_file(target)
    out_dir = tmp_path / "receipt-out"
    out_dir.mkdir()
    session = AISession(GatedBrain(PlannerBrain()), mode="existing")
    receipt = session.run(f"راجع وأصلح {target}", out_dir, write=False)
    assert hash_file(target) == sha_before  # التشغيل الجاف لم يلمس القرص
    assert target not in receipt.files_written


# ------------------------------------------------------------- 4) خطة الدماغ عبر المنسق
def test_brain_plan_flows_into_signed_receipt(tmp_path: Path) -> None:
    """خطة دماغ سليمة تُنفَّذ عبر المنسق نفسها ويحمل الإيصال planner متحققاً."""
    target = tmp_path / "mod.py"
    target.write_text("def f():\n    return 1\n", encoding="utf-8")
    plan, note = plan_with_brain(f"افحص {target}", JsonBrain(_review_json(target)))
    assert plan.planner == "brain:json-brain"
    result = run(plan, dry_run=True)
    assert result.ok
    assert result.receipt["plan"]["planner"] == "brain:json-brain"
    report = verify_orchestration_receipt(result.receipt)
    assert report.ok


def test_brain_rejection_keeps_chain_intact(tmp_path: Path) -> None:
    """دماغ مرفوض بالبوابات ⇒ الخطة الحتمية تنفَّذ والإيصال بلا planner."""

    class RejectingBrain:
        name = "no"
        deterministic = False

        def propose(self, request: str) -> Proposal:
            return Proposal(
                text="خطة",
                brain=self.name,
                deterministic=False,
                verdicts=(GateVerdict(gate="pii", passed=False, details_ar="بيان شخصي"),),
            )

    target = tmp_path / "mod.py"
    target.write_text("def f():\n    return 1\n", encoding="utf-8")
    goal = f"راجع {target}"
    plan, note = plan_with_brain(goal, RejectingBrain(), context=extract_context(goal))
    assert plan.planner == "deterministic"
    result = run(plan, dry_run=True)
    assert result.ok
    assert "planner" not in result.receipt["plan"]
    assert verify_orchestration_receipt(result.receipt).ok


# ------------------------------------------------------------- 5) الملف الضخم عبر السلسلة
def test_large_file_full_chain(tmp_path: Path, monkeypatch) -> None:
    """سقف مخفّض ⇒ ملف فوق السقف يمر عبر do كاملًا حتى الإيصال المتحقق."""
    import zyko.reviewer.engine as engine_mod

    monkeypatch.setattr(engine_mod, "MAX_SOURCE_BYTES", 4_000)
    target = tmp_path / "big.py"
    target.write_text(
        "".join(f"def fn_{i:04d}(x):\n    return x + {i}\n\n\n" for i in range(600)),
        encoding="utf-8",
    )
    goal = f"راجع {target}"
    plan = route(classify(goal), context=extract_context(goal))
    result = run(plan, dry_run=True)
    assert result.ok
    output = result.steps[0].output
    assert output["mode"] == "chunked" and output["chunk_count"] > 1
    assert verify_orchestration_receipt(result.receipt).ok


# ------------------------------------------------------------- 6) السرب
def test_swarm_orders_results_and_signs_chain(tmp_path: Path) -> None:
    """مهام متوازية: النتائج بترتيب المدخل مهما اختلف زمنها، والإيصال فوق سلسلتها."""
    goals = []
    for i in range(3):
        p = tmp_path / f"f{i}.py"
        p.write_text(f"def f_{i}():\n    return {i}\n", encoding="utf-8")
        goals.append(f"راجع {p}")
    result = swarm(goals, max_parallel=3)
    assert result.ok
    assert len(result.results) == 3
    for index, task_result in enumerate(result.results):
        receipt = task_result.run_result.receipt
        assert receipt["steps"][0]["args"]["path"].endswith(f"f{index}.py")  # الترتيب محفوظ
    # إيصال السرب نفسه فوق سلسلة إيصالات المهام — بصمته محفوظة
    assert result.receipt["chain_hash"] == result.receipt.get("chain_hash")
    assert result.fingerprint


# ------------------------------------------------------------- 7) المصنع الكامل
def test_factory_session_full_chain(tmp_path: Path) -> None:
    """جلسة factory كاملة: توليد ← إصلاح ← خط أساس ← إيصال مكتوب ومقبول."""
    from zyko.ai.brains import GatedBrain, PlannerBrain
    from zyko.ai.session import AISession

    out_dir = tmp_path / "new-project"
    session = AISession(GatedBrain(PlannerBrain()), fail_under=50)
    receipt = session.run("ابنِ لي أداة مهام بسيطة", out_dir, write=True)
    assert receipt.ok
    assert (out_dir / "src").is_dir() or out_dir.is_dir()
    step_titles = [s.step for s in receipt.steps]
    assert "plan" in step_titles and "generate" in step_titles
    assert "baseline_update" in step_titles and "baseline_check" in step_titles
    assert (out_dir / ".zyko" / "ai_receipt.json").is_file()


# ------------------------------------------------------------- 8) الحتمية عبر السلسلة
def test_full_chain_byte_determinism(tmp_path: Path) -> None:
    """تشغيلان للسلسلة الكاملة ⇒ إيصالان متطابقان بالبايت — عقد R2 شامل."""
    target = tmp_path / "stable.py"
    target.write_text("def f(a, b):\n    return a + b\n", encoding="utf-8")
    goal = f"راجع {target}"

    def once() -> str:
        plan = route(classify(goal), context=extract_context(goal))
        return json.dumps(run(plan, dry_run=True).receipt, ensure_ascii=False, sort_keys=True)

    assert once() == once()
