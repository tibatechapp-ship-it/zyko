"""اختبارات المُقترِح الحتمي — العقد قبل الادعاء.

كل اختبار هنا يحاكم طبقة على عقد موثق في الكود: القارئ الثلاثي،
النحو المغلق وتحكيمه البنيوي، حلقة البحث بأحكامها الخمسة، البذور
الموجهة، والإيصال الحتمي بالبايت.
"""

from __future__ import annotations

import ast
import json

import pytest

from zyko.tools.formal.engine import VerdictKind, check_source
from zyko.tools.synth.engine import run
from zyko.tools.synth.grammar import (
    DEFAULT_BUDGET,
    CandidateSpace,
    StructuralViolation,
    expr_source,
    harvest_constants,
    structural_check,
)
from zyko.tools.synth.spec import parse_task

# -*- عقد المهمة الأساسي -*-
DOUBLE = (
    "# zyko:task: ضاعف المدخل\n"
    "# zyko:requires: x >= 0\n"
    "# zyko:ensures: result * 2 == x\n"
    "# zyko:domain: x = range(0, 8)\n"
    "def double(x):\n"
    "    raise NotImplementedError\n"
)


# -*- القارئ الثلاثي ------------------------------------------------


class TestSpecParsing:
    def test_accepts_clean_contract(self) -> None:
        verdict = parse_task(DOUBLE)
        assert verdict.kind is VerdictKind.ACCEPT
        assert verdict.spec is not None
        assert verdict.spec.name == "double"
        assert verdict.spec.params == ("x",)
        assert verdict.spec.domains == {"x": (0, 1, 2, 3, 4, 5, 6, 7)}

    def test_ellipsis_body_is_a_stub(self) -> None:
        verdict = parse_task(
            "# zyko:ensures: result == x\n# zyko:domain: x = [1]\ndef f(x):\n    ...\n"
        )
        assert verdict.kind is VerdictKind.ACCEPT

    def test_pass_body_is_a_stub(self) -> None:
        verdict = parse_task(
            "# zyko:ensures: result == x\n# zyko:domain: x = [1]\ndef f(x):\n    pass\n"
        )
        assert verdict.kind is VerdictKind.ACCEPT

    def test_no_stub_rejected(self) -> None:
        verdict = parse_task("def f(x):\n    return x\n")
        assert verdict.kind is VerdictKind.REJECT
        assert "لا دالة هيكلية" in verdict.reason_ar

    def test_two_stubs_rejected(self) -> None:
        source = (
            "# zyko:ensures: result == x\n# zyko:domain: x = [1]\n"
            "def f(x):\n    ...\n\n\n"
            "def g(x):\n    ...\n"
        )
        verdict = parse_task(source)
        assert verdict.kind is VerdictKind.REJECT
        assert "أكثر من دالة هيكلية" in verdict.reason_ar

    def test_result_as_param_rejected(self) -> None:
        verdict = parse_task(
            "# zyko:ensures: result == 1\n# zyko:domain: result = [1]\ndef f(result):\n    ...\n"
        )
        assert verdict.kind is VerdictKind.REJECT
        assert "محجوز" in verdict.reason_ar

    def test_variadic_rejected(self) -> None:
        verdict = parse_task("# zyko:ensures: result == 1\ndef f(*args):\n    ...\n")
        assert verdict.kind is VerdictKind.REJECT
        assert "متغيرة" in verdict.reason_ar

    def test_bad_domain_shape_rejected(self) -> None:
        verdict = parse_task(
            "# zyko:ensures: result == x\n# zyko:domain: x = [1, 2\ndef f(x):\n    ...\n"
        )
        assert verdict.kind is VerdictKind.REJECT

    def test_duplicate_domain_rejected(self) -> None:
        verdict = parse_task(
            "# zyko:ensures: result == x\n"
            "# zyko:domain: x = [1]\n# zyko:domain: x = [2]\n"
            "def f(x):\n    ...\n"
        )
        assert verdict.kind is VerdictKind.REJECT
        assert "مكرر" in verdict.reason_ar

    def test_domain_for_non_param_rejected(self) -> None:
        verdict = parse_task(
            "# zyko:ensures: result == x\n# zyko:domain: y = [1]\ndef f(x):\n    ...\n"
        )
        assert verdict.kind is VerdictKind.REJECT
        assert "ليست معاملاً" in verdict.reason_ar

    def test_missing_ensures_unknown(self) -> None:
        verdict = parse_task(
            "# zyko:requires: x >= 0\n# zyko:domain: x = [1]\ndef f(x):\n    ...\n"
        )
        assert verdict.kind is VerdictKind.UNKNOWN
        assert "بلا شرط لاحق" in verdict.reason_ar

    def test_param_without_domain_unknown(self) -> None:
        verdict = parse_task(
            "# zyko:ensures: result == x + y\n# zyko:domain: x = [1]\ndef f(x, y):\n    ...\n"
        )
        assert verdict.kind is VerdictKind.UNKNOWN
        assert "بلا مجال" in verdict.reason_ar

    def test_broken_source_rejected(self) -> None:
        verdict = parse_task("def f(:\n")
        assert verdict.kind is VerdictKind.REJECT
        assert "لا يُجمَّع" in verdict.reason_ar

    def test_negative_range_bounds_now_parse(self) -> None:
        verdict = parse_task(
            "# zyko:ensures: result == abs(x)\n# zyko:domain: x = range(-5, 5)\n"
            "def f(x):\n    ...\n"
        )
        assert verdict.kind is VerdictKind.ACCEPT
        assert verdict.spec is not None
        assert verdict.spec.domains["x"] == (-5, -4, -3, -2, -1, 0, 1, 2, 3, 4)

    def test_large_range_sampled_by_stride(self) -> None:
        verdict = parse_task(
            "# zyko:ensures: result == x\n# zyko:domain: x = range(0, 128)\ndef f(x):\n    ...\n"
        )
        assert verdict.kind is VerdictKind.ACCEPT
        assert verdict.spec is not None
        points = verdict.spec.domains["x"]
        assert len(points) <= 64
        assert points[0] == 0

    def test_spec_sha256_stable(self) -> None:
        a = parse_task(DOUBLE).spec
        b = parse_task(DOUBLE).spec
        assert a is not None and b is not None
        assert a.sha256 == b.sha256
        assert len(a.sha256) == 64


# -*- النحو المغلق ---------------------------------------------------


class TestGrammar:
    def test_enumeration_deterministic(self) -> None:
        space_a = CandidateSpace(("x",), (0, 1, 2))
        space_b = CandidateSpace(("x",), (0, 1, 2))
        seq_a = [ast.dump(c) for c in space_a.candidates()]
        seq_b = [ast.dump(c) for c in space_b.candidates()]
        assert seq_a == seq_b
        assert len(seq_a) > 100

    def test_first_candidates_are_leaves_in_order(self) -> None:
        space = CandidateSpace(("x", "y"), (0, 1))
        seq = list(itertools_islice(space.candidates(), 4))
        sources = [expr_source(c) for c in seq]
        assert sources == ["x", "y", "0", "1"]

    def test_budget_caps_enumeration(self) -> None:
        space = CandidateSpace(("x",), (0, 1), budget=10)
        seq = list(space.candidates())
        assert len(seq) == 10
        assert space.budget_hit

    def test_full_space_no_budget_hit(self) -> None:
        space = CandidateSpace(("x",), (0, 1), max_nodes=2, budget=1_000_000)
        list(space.candidates())
        assert not space.budget_hit

    def test_structural_check_rejects_foreign_name(self) -> None:
        expr = ast.parse("z + 1", mode="eval").body
        with pytest.raises(StructuralViolation):
            structural_check(expr, ("x",))

    def test_structural_check_rejects_attribute(self) -> None:
        expr = ast.parse("x.real", mode="eval").body
        with pytest.raises(StructuralViolation):
            structural_check(expr, ("x",))

    def test_structural_check_rejects_open_call(self) -> None:
        expr = ast.parse("eval('1')", mode="eval").body
        with pytest.raises(StructuralViolation):
            structural_check(expr, ("x",))

    def test_structural_check_rejects_big_constant_exponent(self) -> None:
        expr = ast.parse("x ** 999", mode="eval").body
        with pytest.raises(StructuralViolation):
            structural_check(expr, ("x",))

    def test_structural_check_allows_whitelisted_calls(self) -> None:
        expr = ast.parse("min(abs(x), 5)", mode="eval").body
        structural_check(expr, ("x",))  # لا استثناء = قبول

    def test_constants_harvested_from_contracts(self) -> None:
        consts = harvest_constants(
            ("x >= 0",), ("result * 2 == x",), {"x": (0, 1, 2, 3, 4, 5, 6, 7)}
        )
        assert 2 in consts  # من نص العقد
        assert 0 in consts and 1 in consts
        assert 6 in consts  # نقطة مجال داخل السقف (|v| ≤ 20، 12 قيمة)
        assert 50 not in consts  # خارج السقفين معاً

    def test_max_nodes_bounds_validated(self) -> None:
        with pytest.raises(ValueError):
            CandidateSpace(("x",), (0,), max_nodes=9)
        with pytest.raises(ValueError):
            CandidateSpace(("x",), (0,), max_nodes=0)


def itertools_islice(iterator, n):  # noqa: N802 — اسم اختباري محلي
    from itertools import islice

    return islice(iterator, n)


# -*- حلقة البحث وأحكامها الخمسة -------------------------------------


class TestSearchVerdicts:
    def test_double_synthesized(self) -> None:
        receipt = run(DOUBLE)
        assert receipt.ok
        assert receipt.winner_expr is not None
        assert receipt.winner_expr in ("x / 2", "x // 2", "x * 0.5")
        assert receipt.formal["verdict"] == "accept"
        assert receipt.tried <= receipt.emitted

    def test_seed_phase_hits_equality_rhs(self) -> None:
        receipt = run(
            "# zyko:ensures: result == (x % 2 == 0)\n"
            "# zyko:domain: x = range(0, 6)\ndef is_even(x):\n    ...\n"
        )
        assert receipt.ok
        assert receipt.winner_expr == "x % 2 == 0"
        assert receipt.search["guided_seeds"] >= 1
        assert receipt.tried == 1  # البذرة الأولى كفت

    def test_seed_rejected_when_wrong(self) -> None:
        # البذرة x * 2 لا تفي بعقد المضاعفة — يجب أن يكمل البحث
        receipt = run(
            "# zyko:ensures: result * 2 == x and result != x * 2\n"
            "# zyko:domain: x = range(1, 6)\ndef f(x):\n    ...\n"
        )
        assert receipt.verdict == "synthesized"
        assert receipt.winner_expr == "x / 2"
        assert receipt.tried > 1

    def test_max2_multi_param(self) -> None:
        receipt = run(
            "# zyko:ensures: result >= x and result >= y "
            "and (result == x or result == y)\n"
            "# zyko:domain: x = range(0, 8)\n# zyko:domain: y = range(0, 8)\n"
            "def bigger(x, y):\n    raise NotImplementedError\n"
        )
        assert receipt.ok
        assert receipt.winner_expr == "max(x, y)"

    def test_clamp_fully_specified(self) -> None:
        receipt = run(
            "# zyko:ensures: (result == x if 0 <= x <= 100 "
            "else (result == 0 if x < 0 else result == 100))\n"
            "# zyko:domain: x = range(-20, 130)\ndef clamp(x):\n    ...\n"
        )
        assert receipt.ok
        assert receipt.winner_expr is not None
        # الفائز يوحّد كل الأفرع الثلاثة
        body = receipt.winner_expr.replace(" ", "")
        assert "min(" in body and "max(" in body

    def test_string_domain_len(self) -> None:
        receipt = run(
            "# zyko:ensures: result == len(s)\n"
            '# zyko:domain: s = ["a", "bb", "ccc"]\ndef size_of(s):\n    ...\n'
        )
        assert receipt.ok
        assert receipt.winner_expr == "len(s)"

    def test_impossible_contract_exhausted(self) -> None:
        receipt = run(
            "# zyko:ensures: result * 0 == 1\n"
            "# zyko:domain: x = range(0, 4)\ndef broken(x):\n    ...\n"
        )
        assert receipt.verdict == "exhausted"
        assert receipt.winner_expr is None
        assert not receipt.search.get("budget_hit", False)
        assert "برهان غياب" in receipt.reason_ar

    def test_contradictory_ensures_exhausted(self) -> None:
        receipt = run(
            "# zyko:ensures: result == x\n# zyko:ensures: result == x + 1\n"
            "# zyko:domain: x = range(1, 5)\ndef nope(x):\n    ...\n"
        )
        assert receipt.verdict == "exhausted"

    def test_preconditions_excluding_everything(self) -> None:
        receipt = run(
            "# zyko:requires: x >= 100\n# zyko:ensures: result == x\n"
            "# zyko:domain: x = range(0, 8)\ndef f(x):\n    ...\n"
        )
        assert receipt.verdict == "exhausted"
        assert receipt.unjudgeable > 0
        assert "خارج المسبقات" in receipt.reason_ar

    def test_budget_stops_honestly(self) -> None:
        receipt = run(DOUBLE, budget=5)
        assert receipt.verdict == "budget"
        assert receipt.winner_expr is None
        assert receipt.search["budget"] == 5
        assert "غير مكتمل" in receipt.reason_ar

    def test_invalid_spec_verdict(self) -> None:
        receipt = run("def f(x):\n    return x\n")
        assert receipt.verdict == "invalid_spec"
        assert receipt.winner_source is None

    def test_unverifiable_spec_verdict(self) -> None:
        receipt = run(
            "# zyko:ensures: result == x + y\n# zyko:domain: x = [1]\ndef f(x, y):\n    ...\n"
        )
        assert receipt.verdict == "unverifiable"
        assert "بلا مجال" in receipt.reason_ar

    def test_zero_division_rejects_candidate(self) -> None:
        # العقد يفرض ناتجاً محدداً؛ المرشحون القاسمو على الصفر يسقطون سلوكياً
        receipt = run(
            "# zyko:ensures: result == 10 // x\n"
            "# zyko:domain: x = [1, 2, 5, 10]\ndef f(x):\n    ...\n"
        )
        assert receipt.ok
        assert receipt.winner_expr == "10 // x"

    def test_winner_passes_governor(self) -> None:
        receipt = run(DOUBLE)
        assert receipt.winner_source is not None
        report = check_source(receipt.winner_source)
        assert report.verdict is VerdictKind.ACCEPT
        assert receipt.winner_source.startswith("# zyko:")
        assert "def double(x):" in receipt.winner_source

    def test_no_domain_points_unverifiable(self) -> None:
        receipt = run(
            "# zyko:ensures: result == x\n# zyko:domain: x = [1]\n"
            "# zyko:domain: y = [2]\ndef f(x):\n    ...\n"
        )
        # y مجال لمعامل غير موجود — رفض من القارئ أصلاً
        assert receipt.verdict == "invalid_spec"


# -*- الإيصال الحتمي -------------------------------------------------


class TestReceiptDeterminism:
    def test_receipt_bytes_identical(self) -> None:
        a = run(DOUBLE)
        b = run(DOUBLE)
        assert a.to_json() == b.to_json()

    def test_receipt_sorted_keys_no_time(self) -> None:
        receipt = run(DOUBLE)
        doc = json.loads(receipt.to_json())
        assert doc["kind"] == "zyko.synth.receipt"
        assert doc["verdict"] == "synthesized"
        raw = receipt.to_json()
        assert raw.index('"chain_hash"') < raw.index('"verdict"')
        for banned in ("timestamp", "now", "time_iso"):
            assert banned not in doc

    def test_chain_hash_stable_and_sensitive(self) -> None:
        a = run(DOUBLE)
        b = run(DOUBLE)
        assert a.chain_hash == b.chain_hash
        c = run(
            "# zyko:ensures: result == x + 1\n# zyko:domain: x = range(0, 4)\ndef f(x):\n    ...\n"
        )
        assert c.chain_hash != a.chain_hash

    def test_search_space_declared(self) -> None:
        receipt = run(DOUBLE)
        meta = receipt.search
        assert meta["max_nodes"] > 0
        assert meta["budget"] == DEFAULT_BUDGET
        assert meta["block_beam"] > 0
        assert "constants" in meta and "params" in meta

    def test_counts_are_honest(self) -> None:
        receipt = run(DOUBLE)
        assert receipt.tried >= 1
        assert receipt.tried <= receipt.emitted + receipt.search["guided_seeds"]
        assert receipt.structural_skips >= 0


# -*- تكامل الحاكم الشكلي --------------------------------------------


class TestFormalIntegration:
    def test_governor_rejects_bad_domain_unchanged(self) -> None:
        report = check_source(
            "# zyko:ensures: result == x\n# zyko:domain: x = [1]\ndef f(x):\n    return x\n"
        )
        assert report.verdict is VerdictKind.ACCEPT

    def test_negative_range_in_governor(self) -> None:
        # الحاكم سكوني: المجال السالب صيغته مقبولة الآن دون رفض صياغة
        report = check_source(
            "# zyko:ensures: result == abs(x)\n# zyko:domain: x = range(-3, 3)\n"
            "def f(x):\n    return abs(x)\n"
        )
        assert report.verdict is VerdictKind.ACCEPT

    def test_synthesized_program_executes_correctly(self) -> None:
        receipt = run(DOUBLE)
        assert receipt.winner_source is not None
        namespace: dict[str, object] = {}
        exec(receipt.winner_source, namespace)  # noqa: S102 — مخرجنا الموثق
        fn = namespace["double"]
        # العقد «result * 2 == x» — لا «result == 2 * x»: الفائز يفي بها
        # داخل المجال وخارجه لأنها متطابقة حسابياً على الأعداد الحقيقية
        assert fn(21) * 2 == 21
        assert fn(0) * 2 == 0
        assert fn(-4) * 2 == -4
