"""المكوّن 3 — بوابة run: نجاح، فشل، dry-run، حتمية الإيصال، تكامل حقيقي.

الأدوات الحقيقية تعمل على ملفات tmp_path: مراجعة AST فعلية، إصلاح فعلي
عند dry_run=False فقط، Guardian يمنع PII فعلاً، والإيصال يتحقق منه
المحقق نفسه و`zyko verify` عبر CLI.
"""

from __future__ import annotations

import hashlib
import json
import types

import pytest

from zyko.cli import main
from zyko.orchestrator import Plan, Step, classify, route, run
from zyko.orchestrator.run import StepResult
from zyko.orchestrator.verify import verify_orchestration_receipt

BARE_EXCEPT_SRC = "def f():\n    try:\n        pass\n    except:\n        pass\n"


def _review_plan(path: str) -> Plan:
    return route(classify("راجع الهدف"), context={"path": path})


def _fix_plan(path: str) -> Plan:
    return route(classify("أصلح الهدف"), context={"path": path})


def _write(tmp_path, name: str, content: str):
    target = tmp_path / name
    target.write_text(content, encoding="utf-8")
    return target


class TestStepResultBasics:
    def test_step_result_frozen(self):
        result = StepResult(Step("review"), True, None, None, 1, "ALLOW", "ab" * 32)
        with pytest.raises(Exception):
            result.ok = False  # type: ignore[misc]

    def test_step_sha256_deterministic(self):
        from zyko.orchestrator.run import step_payload, step_sha256

        payload = step_payload(
            Step("review", {"path": "a.py"}, "سبب"), True, "ALLOW", None, {"x": 1}
        )
        assert step_sha256(payload) == step_sha256(dict(payload))

    def test_step_sha256_changes_with_output(self):
        from zyko.orchestrator.run import step_payload, step_sha256

        payload = step_payload(Step("review"), True, "ALLOW", None, {"x": 1})
        changed = step_payload(Step("review"), True, "ALLOW", None, {"x": 2})
        assert step_sha256(payload) != step_sha256(changed)


class TestRunDryRun:
    def test_dry_run_default_writes_nothing(self, tmp_path):
        target = _write(tmp_path, "m.py", BARE_EXCEPT_SRC)
        result = run(_fix_plan(str(target)))
        assert result.receipt["dry_run"] is True
        assert target.read_text(encoding="utf-8") == BARE_EXCEPT_SRC

    def test_review_plan_ok_on_real_file(self, tmp_path):
        target = _write(tmp_path, "m.py", "def f():\n    return 1\n")
        result = run(_review_plan(str(target)))
        assert result.ok is True and result.receipt["ok"] is True

    def test_receipt_structure_exact(self, tmp_path):
        target = _write(tmp_path, "m.py", "def f():\n    return 1\n")
        receipt = run(_review_plan(str(target))).receipt
        assert set(receipt) == {"version", "kind", "ok", "dry_run", "plan", "steps", "chain_hash"}
        assert receipt["version"] == 1 and receipt["kind"] == "orchestrator"

    def test_guardian_verdict_recorded(self, tmp_path):
        target = _write(tmp_path, "m.py", "def f():\n    return 1\n")
        result = run(_review_plan(str(target)))
        assert result.steps[0].guardian_verdict == "ALLOW"

    def test_chain_hash_recomputes_from_step_hashes(self, tmp_path):
        target = _write(tmp_path, "m.py", "def f():\n    return 1\n")
        result = run(_fix_plan(str(target)))
        expected = hashlib.sha256(
            "|".join(s.sha256 for s in result.steps).encode("utf-8")
        ).hexdigest()
        assert result.receipt["chain_hash"] == expected


class TestRunGuardian:
    def test_pii_in_args_is_denied(self):
        result = run(_review_plan("0501234567.py"))
        assert result.ok is False
        assert result.steps[0].guardian_verdict == "DENY"

    def test_deny_stops_plan_after_one_step(self):
        result = run(_fix_plan("0501234567.py"))
        assert len(result.steps) == 1  # خطوة fix لم تُنفَّذ إطلاقاً

    def test_deny_error_is_arabic_and_explicit(self):
        result = run(_review_plan("0501234567.py"))
        error = result.steps[0].error_ar or ""
        assert "المحرّس منع الخطوة (DENY)" in error

    def test_deny_receipt_records_verdict(self):
        result = run(_fix_plan("0501234567.py"))
        assert result.receipt["ok"] is False
        assert result.receipt["steps"][0]["guardian_verdict"] == "DENY"


class TestRunFailStop:
    def test_missing_path_fails_with_arabic_error(self, tmp_path):
        result = run(_review_plan(str(tmp_path / "لن-أوجد.py")))
        assert result.ok is False
        assert "غير موجود" in (result.steps[0].error_ar or "")

    def test_failure_stops_remaining_steps(self, tmp_path):
        missing = str(tmp_path / "لن-أوجد.py")
        result = run(_fix_plan(missing))
        assert [s.step.tool for s in result.steps] == ["review"]  # fix لم يُنفَّذ

    def test_unknown_tool_fails_cleanly(self):
        plan = Plan(classify("راجع الهدف"), (Step("أداة-وهمية", {"path": "x.py"}, "سبب"),), 0.0, ())
        result = run(plan)
        assert result.ok is False
        assert "أداة غير معروفة" in (result.steps[0].error_ar or "")


class TestRunRealTools:
    def test_review_output_has_score_and_verdict(self, tmp_path):
        target = _write(tmp_path, "m.py", BARE_EXCEPT_SRC)
        output = run(_review_plan(str(target))).steps[0].output
        assert isinstance(output, dict) and "score" in output and "verdict_ar" in output

    def test_fix_dry_run_reports_without_writing(self, tmp_path):
        target = _write(tmp_path, "m.py", BARE_EXCEPT_SRC)
        output = run(_fix_plan(str(target))).steps[1].output
        assert output["would_fix"] >= 1 and "dry_run_ar" in output  # تجريبي: بلا كتابة
        assert target.read_text(encoding="utf-8") == BARE_EXCEPT_SRC

    def test_fix_apply_writes_file(self, tmp_path):
        target = _write(tmp_path, "m.py", BARE_EXCEPT_SRC)
        result = run(_fix_plan(str(target)), dry_run=False)
        assert result.ok is True
        assert target.read_text(encoding="utf-8") != BARE_EXCEPT_SRC  # تغيّر فعلاً
        assert "except Exception" in target.read_text(encoding="utf-8")

    def test_baseline_check_without_baseline_is_documented_state(self, tmp_path):
        output = (
            run(route(classify("حلل المستودع"), context={"src": str(tmp_path)})).steps[0].output
        )
        assert output["baseline_status"] == "missing" and output["verdict_ar"] != ""

    def test_verify_step_validates_orchestrator_receipt(self, tmp_path):
        target = _write(tmp_path, "m.py", "def f():\n    return 1\n")
        first = run(_review_plan(str(target)))
        receipt_file = tmp_path / "receipt.json"
        receipt_file.write_text(json.dumps(first.receipt, ensure_ascii=False), encoding="utf-8")
        verify_step = Step("verify", {"receipt": str(receipt_file)}, "سبب")
        plan = Plan(classify("تحقق"), (verify_step,), 0.0, ())
        result = run(plan)
        assert result.ok is True and result.steps[0].output["ok"] is True


class TestRunGenerate:
    def test_generate_dry_run_lists_tree_without_writing(self, tmp_path):
        step = Step("generate", {"description": "أداة سطر أوامر عربية للتحليل"}, "سبب")
        plan = Plan(classify("أنشئ مشروع"), (step,), 0.0, ())
        result = run(plan)
        assert result.ok is True
        output = result.steps[0].output
        assert output["name"] == "zyko-project" and output["total_bytes"] > 0
        assert list(tmp_path.iterdir()) == []  # لم يُكتب أي ملف

    def test_generate_apply_writes_project(self, tmp_path):
        out = tmp_path / "generated"
        step = Step(
            "generate", {"description": "أداة سطر أوامر عربية للتحليل", "out": str(out)}, "سبب"
        )
        plan = Plan(classify("أنشئ مشروع"), (step,), 0.0, ())
        result = run(plan, dry_run=False)
        assert result.ok is True and out.exists()
        assert "RECEIPT.md" in result.steps[0].output["files"]


class TestRunTranspile:
    def test_transpile_missing_file_fails(self, tmp_path):
        step = Step("transpile", {"file": str(tmp_path / "لن-أوجد.daad")}, "سبب")
        plan = Plan(classify("ترجم"), (step,), 0.0, ())
        result = run(plan)
        assert result.ok is False and "غير موجود" in (result.steps[0].error_ar or "")

    def test_transpile_dry_run_returns_code_without_writing(self, tmp_path, monkeypatch):
        calls: list[list[str]] = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return types.SimpleNamespace(returncode=0, stdout="print('مرحبا')\n", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)
        source = _write(tmp_path, "app.daad", "اكتب(«مرحبا»)")
        step = Step("transpile", {"file": str(source)}, "سبب")
        plan = Plan(classify("ترجم"), (step,), 0.0, ())
        result = run(plan)
        assert result.ok is True and result.steps[0].output["code"] == "print('مرحبا')\n"
        assert list(tmp_path.glob("*.py")) == []  # لا كتابة في الوضع التجريبي

    def test_transpile_apply_writes_out_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "subprocess.run",
            lambda argv, **kw: types.SimpleNamespace(
                returncode=0, stdout="print('مرحبا')\n", stderr=""
            ),
        )
        source = _write(tmp_path, "app.daad", "اكتب(«مرحبا»)")
        out = tmp_path / "app.py"
        step = Step("transpile", {"file": str(source), "out": str(out)}, "سبب")
        plan = Plan(classify("ترجم"), (step,), 0.0, ())
        result = run(plan, dry_run=False)
        assert result.ok is True and out.read_text(encoding="utf-8") == "print('مرحبا')\n"


class TestRunDeterminism:
    def test_two_runs_produce_identical_receipts(self, tmp_path):
        target = _write(tmp_path, "m.py", BARE_EXCEPT_SRC)
        first = run(_fix_plan(str(target)))
        second = run(_fix_plan(str(target)))
        assert first.receipt == second.receipt  # بما فيها chain_hash — بالبايت

    def test_100_runs_chain_hash_stable(self, tmp_path):
        target = _write(tmp_path, "m.py", "def f():\n    return 1\n")
        plan = _review_plan(str(target))
        expected = run(plan).receipt["chain_hash"]
        for _ in range(100):
            assert run(plan).receipt["chain_hash"] == expected

    def test_receipt_json_roundtrip(self, tmp_path):
        target = _write(tmp_path, "m.py", "def f():\n    return 1\n")
        receipt = run(_review_plan(str(target))).receipt
        restored = json.loads(json.dumps(receipt, ensure_ascii=False))
        assert restored == receipt


class TestOrchestratorVerify:
    def test_fresh_receipt_verifies_ok(self, tmp_path):
        target = _write(tmp_path, "m.py", "def f():\n    return 1\n")
        report = verify_orchestration_receipt(run(_review_plan(str(target))).receipt)
        assert report.ok is True and report.checks >= 3 and report.issues == []

    def test_tampered_args_detected(self, tmp_path):
        target = _write(tmp_path, "m.py", "def f():\n    return 1\n")
        receipt = run(_review_plan(str(target))).receipt
        receipt["steps"][0]["args"]["path"] = "معدَّل.py"
        issues = [i.code for i in verify_orchestration_receipt(receipt).issues]
        assert "STEP_SHA_MISMATCH" in issues

    def test_tampered_chain_detected(self, tmp_path):
        target = _write(tmp_path, "m.py", "def f():\n    return 1\n")
        receipt = run(_review_plan(str(target))).receipt
        receipt["chain_hash"] = "0" * 64
        issues = [i.code for i in verify_orchestration_receipt(receipt).issues]
        assert "CHAIN_HASH_MISMATCH" in issues

    def test_wrong_version_rejected(self, tmp_path):
        target = _write(tmp_path, "m.py", "def f():\n    return 1\n")
        receipt = run(_review_plan(str(target))).receipt
        receipt["version"] = 99
        issues = [i.code for i in verify_orchestration_receipt(receipt).issues]
        assert "VERSION_UNSUPPORTED" in issues


class TestDoCLI:
    def test_do_review_dry_run_exit_zero(self, tmp_path, capsys):
        target = _write(tmp_path, "m.py", "def f():\n    return 1\n")
        assert main(["do", "راجع m.py", "--path", str(target)]) == 0
        out = capsys.readouterr().out
        assert "الخطة" in out and "chain_hash" in out

    def test_do_unknown_task_exit_one(self, capsys):
        assert main(["do", "الجو جميل"]) == 1
        assert "لم أفهم المهمة" in capsys.readouterr().out

    def test_do_failing_step_exit_two(self, tmp_path, capsys):
        assert main(["do", "راجع شيء", "--path", str(tmp_path / "لن-أوجد.py")]) == 2

    def test_do_deterministic_stdout(self, tmp_path, capsys):
        target = _write(tmp_path, "m.py", "def f():\n    return 1\n")
        main(["do", "راجع m.py", "--path", str(target)])
        first = capsys.readouterr().out
        main(["do", "راجع m.py", "--path", str(target)])
        second = capsys.readouterr().out
        assert first == second  # معيار النجاح رقم 4: diff بلا فرق

    def test_do_writes_receipt_and_verify_accepts_it(self, tmp_path, capsys):
        target = _write(tmp_path, "m.py", "def f():\n    return 1\n")
        receipt_file = tmp_path / "orchestrator-receipt.json"
        assert main(["do", "راجع m.py", "--path", str(target), "--receipt", str(receipt_file)]) == 0
        assert receipt_file.exists()
        assert main(["verify", str(receipt_file)]) == 0  # معيار النجاح رقم 5

    def test_do_write_applies_fix(self, tmp_path, capsys):
        target = _write(tmp_path, "m.py", BARE_EXCEPT_SRC)
        assert main(["do", "أصلح m.py", "--path", str(target), "--write"]) == 0
        assert (
            target.read_text(encoding="utf-8") != BARE_EXCEPT_SRC
        )  # القاعدة R9: كتابة بموافقة صريحة فقط
