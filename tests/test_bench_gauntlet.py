"""اختبارات الفحص الكبير: 1000 برنامج حقيقي تُبنى وتُختبر — صادقة وحتمية.

الطبقات هنا:
  1) المصفوفة — 1000 مخطط صالحًا متميزًا، حتميًا بالبايت على 100 إعادة؛
  2) الشيفرة الساكنة — كل البرامج الـ1000 تُبنى وتُفحص (تجميع شكلي كامل)؛
  3) التنفيذ الحقيقي — عينة حتمية تُبنى على القرص وتُشغَّل اختباراتها
     الخاصة (pytest داخل المشروع المولَّد) وتُقبل 100%؛
  4) الإيصال — حتمي بالبايت (الزمن خارجه إلا بطلب صريح)؛
  5) الصدق — مخطط فاسد يعود صفًا فاشلًا بمشكلة عربية لا يُخفى.
"""

from __future__ import annotations

import json

from zyko.benchmarks.gauntlet import (
    EXTRA_MODULE_POOL,
    GauntletReport,
    build_matrix,
    run_gauntlet,
)
from zyko.coder.heuristics import intent_specs, known_intents
from zyko.coder.plan import ProjectPlan


# ============================================================ المصفوفة
def test_matrix_1000_plans_all_valid_and_distinct() -> None:
    plans = build_matrix(100)
    assert len(plans) == 1000  # 10 نوايا × 100 تنويعًا
    assert len({p.name for p in plans}) == 1000  # لا اسمان متطابقان
    assert len({p.description for p in plans}) == 1000  # لا وصفان متطابقان
    assert {p.name.rsplit("-", 1)[0] for p in plans} == {s["name"] for s in intent_specs()}
    bad = [(p.name, p.validate()) for p in plans if p.validate()]
    assert bad == [], f"مخططات غير صالحة: {bad[:3]}"


def test_matrix_covers_all_three_templates() -> None:
    plans = build_matrix(100)
    templates = {p.template for p in plans}
    assert templates == {"python-cli", "fastapi-api", "static-site"}


def test_matrix_variations_really_vary_modules() -> None:
    plans = build_matrix(100)
    module_sets = {p.modules for p in plans}
    assert len(module_sets) > 10  # التنويعات تُغيّر الوحدات فعلًا لا الأسماء فقط
    for p in plans:
        assert p.modules[: len(p.modules) - 1] or p.modules  # لا فارغ أبدًا


def test_matrix_deterministic_100_rebuilds() -> None:
    """P6: نفس المدخل ⇒ نفس المصفوفة بالبايت — 100 إعادة كاملة."""
    import hashlib

    first = None
    for _ in range(100):
        plans = build_matrix(100)
        blob = json.dumps([p.to_dict() for p in plans], ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        first = first or digest
        assert digest == first


def test_intent_specs_is_public_and_complete() -> None:
    specs = intent_specs()
    assert len(specs) == 10
    assert {s["id"] for s in specs} == set(known_intents())
    for spec in specs:
        assert spec["name"] and spec["template"] in {"python-cli", "fastapi-api", "static-site"}
        assert isinstance(spec["modules"], tuple) and spec["modules"]


def test_extra_module_pool_is_safe_identifiers() -> None:
    import keyword

    for mod in EXTRA_MODULE_POOL:
        assert mod.isidentifier() and not keyword.iskeyword(mod)


# ============================================================ الشيفرة الساكنة (كل 1000)
def test_static_checks_pass_over_full_matrix() -> None:
    """البرنامج الـ1000 كله يُبنى ويمر الفحص الساكن — لا استثناء ولا خروج صامت."""
    report = run_gauntlet(per_intent=100, execute=0)
    assert report.total == 1000
    assert report.passed == 1000, report.table_ar()
    assert report.ok


# ============================================================ التنفيذ الحقيقي
def test_executed_sample_real_tests_pass() -> None:
    """عينة حتمية (برنامج لكل نية) تُبنى على القرص وتُشغَّل اختباراتها — 100%."""
    report = run_gauntlet(per_intent=1, execute=10, timeout=120)
    executed_rows = [r for r in report.rows if r.tests_ok is not None]
    assert len(executed_rows) == 10
    assert {r.intent for r in executed_rows} == {
        s["name"] for s in intent_specs()
    }  # عينة تغطي كل النوايا
    assert all(r.ok for r in executed_rows), [
        (r.name, r.problems) for r in executed_rows if not r.ok
    ]
    assert report.ok and report.passed == 10


def test_receipt_is_byte_deterministic_across_runs() -> None:
    """P6: إيصالان منفصلان بنفس المدخل ⇒ to_json متطابق بالبايت (الزمن خارجه)."""
    r1 = run_gauntlet(per_intent=2, execute=0)
    r2 = run_gauntlet(per_intent=2, execute=0)
    assert r1.to_json() == r2.to_json()
    assert r1.chain_hash == r2.chain_hash


def test_timing_only_on_explicit_request() -> None:
    r = run_gauntlet(per_intent=2, execute=0)
    assert "seconds" not in r.to_json()
    assert "seconds" in r.to_json(include_timing=True)


# ============================================================ الصدق
def test_invalid_plan_is_an_honest_failure_not_a_crash(tmp_path) -> None:
    from zyko.benchmarks.gauntlet import run_one

    broken = ProjectPlan(
        name="x",  # اسم أقصر من الحد — validate() ترفضه عربيًا
        template="python-cli",
        description="مشروع مكسور عمدًا للتحقق من الصدق",
        modules=("tasks",),
        dependencies=(),
        run_commands=(),
        display_name="مكسور",
        author="zyko-bench",
    )
    row = run_one(broken, 999, root=tmp_path)
    assert not row.ok
    assert row.problems and any("الاسم" in p for p in row.problems)


def test_report_counts_and_chain_hash() -> None:
    report = run_gauntlet(per_intent=2, execute=0)
    assert isinstance(report, GauntletReport)
    assert report.total == 20
    by_intent = report.by_intent()
    assert len(by_intent) == 10
    assert all(built == 2 and good == built for built, good in by_intent.values())
    assert len(report.chain_hash) == 64


def test_table_ar_renders_mmlu_style() -> None:
    report = run_gauntlet(per_intent=2, execute=2, timeout=120)
    table = report.table_ar()
    assert "الفحص الكبير" in table
    assert "100%" in table
    assert "ناجح" in table
    assert report.chain_hash[:16] in table
    assert "نُفِّذت باختباراتها الحقيقية" in table


# ============================================================ سطر الأوامر
def test_cli_gauntlet_exit_zero_and_json_out(tmp_path) -> None:
    from zyko.cli.commands import cmd_gauntlet

    class Args:
        per_intent = 1
        execute = 1
        execute_all = False
        json_out = str(tmp_path / "receipt.json")
        include_timing = False

    args = Args()
    rc = cmd_gauntlet(args)
    assert rc == 0
    receipt = json.loads((tmp_path / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["kind"] == "gauntlet"
    assert receipt["total"] == 10 and receipt["passed"] == 10
    assert receipt["executed"] == 1
    assert len(receipt["chain_hash"]) == 64


def test_cli_gauntlet_invalid_args_exit_two(capsys) -> None:
    from zyko.cli.commands import cmd_gauntlet

    class Args:
        per_intent = 0
        execute = 0
        execute_all = False
        json_out = None
        include_timing = False

    assert cmd_gauntlet(Args()) == 2
    assert "per-intent" in capsys.readouterr().err
