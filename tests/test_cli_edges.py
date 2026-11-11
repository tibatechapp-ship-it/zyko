"""تغطية أطر CLI — الفروع الموثقة التي كشفها قياس التغطية للوحدة الأكبر
(`cli/commands.py`). كل اختبار يمرر مسارًا واحدًا موثقًا برسالته العربية
أو عقد JSON الخاص به، بلا شبكة وبلا نماذج.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types

import pytest

from tests.fakes import FakeProvider
from zyko.cli import main

DAAD_INSTALL_HINT = "pip install git+https://github.com/tibatechapp-ship-it/daad.git"


def _daad_available() -> bool:
    try:
        return (
            subprocess.run(  # nosec B607
                [sys.executable, "-m", "daad", "version"], capture_output=True
            ).returncode
            == 0
        )
    except OSError:
        return False


daad_required = pytest.mark.skipif(not _daad_available(), reason="daad not installed")

HELLO_DAAD = 'اطبع("مرحبا من ضاد")\n'


# ------------------------------------------------------------------ route/chat
def test_route_json_with_prompt_estimates_tokens(capsys):
    assert main(["route", "راجع هذا الملف جيداً", "--json"]) == 0
    raw = capsys.readouterr().out
    data = json.loads(raw[raw.index("{") :])  # سطر [WARN] للمزوّد يسبق JSON
    assert data["strategy"]
    assert isinstance(data["ranking"], list)


def test_chat_eof_ends_cleanly(monkeypatch, capsys):
    fake = FakeProvider(script=["reply"])
    monkeypatch.setattr("zyko.cli.commands.configured_providers", lambda *_a, **_k: {"fake": fake})

    def eof(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert main(["chat"]) == 0


# ------------------------------------------------------------------ hash-key
def test_hash_key_blank_key_fails(capsys):
    assert main(["hash-key", "--key", "   "]) == 1
    assert "empty key" in capsys.readouterr().err


def test_hash_key_empty_via_hidden_prompt_fails(monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda *_a, **_k: "")
    assert main(["hash-key"]) == 1
    assert "empty key" in capsys.readouterr().err


# ------------------------------------------------------------------ policy
def test_policy_show_default_builtin(capsys):
    assert main(["policy", "show"]) == 0
    out = capsys.readouterr().out
    assert "policy: default" in out
    assert "models allow" in out


def test_policy_redact_builtin_masks_email(capsys):
    assert main(["policy", "redact", "راسلني على user@example.com اليوم"]) == 0
    out = capsys.readouterr().out
    assert "user@example.com" not in out


def test_policy_unknown_subcommand_rejected_by_parser():
    # العقد الفعلي: المحلل يرفض الاسم المجهول قبل cmd_policy — سطر raise
    # داخل cmd_policy دفاعي لا يبلغه مسار المحلل.
    with pytest.raises(SystemExit):
        main(["policy", "bogus"])


# ------------------------------------------------------------------ mcp/sessions
def test_mcp_unknown_subcommand_rejected_by_parser():
    with pytest.raises(SystemExit):
        main(["mcp", "bogus"])


def test_sessions_unknown_action_rejected_by_parser():
    with pytest.raises(SystemExit):
        main(["sessions", "bogus"])


def test_sessions_rm_removes_documented_session(capsys):
    from zyko.agents.memory import MemoryStore

    store = MemoryStore()
    sid = store.create_session()
    assert main(["sessions", "rm", sid]) == 0
    assert "removed 1 session(s)" in capsys.readouterr().out
    assert store.history(sid) == []


# ------------------------------------------------------------------ gauntlet
def test_gauntlet_per_intent_zero_rejected(capsys):
    assert main(["gauntlet", "--per-intent", "0"]) == 2
    assert "--per-intent" in capsys.readouterr().err or "خطأ" in capsys.readouterr().err


def test_gauntlet_negative_execute_rejected(capsys):
    assert main(["gauntlet", "--execute", "-1"]) == 2


def test_gauntlet_repeats_below_one_rejected(capsys):
    assert main(["gauntlet", "--repeats", "-1", "--review-sample", "2"]) == 2
    assert "--repeats" in capsys.readouterr().err


# ------------------------------------------------------------------ verify
def test_verify_json_with_missing_ledger_is_empty_ledger(tmp_path, capsys):
    receipt = tmp_path / "r.json"
    assert main(["ask", "--demo", "اختبار", "--receipt", str(receipt)]) == 0
    capsys.readouterr()  # تفريغ مخرجات ask — نقرأ JSON الـverify وحده
    assert main(["verify", str(receipt), "--json", "--ledger", str(tmp_path / "l.json")]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True


def test_verify_json_valid_receipt(tmp_path, capsys):
    receipt = tmp_path / "r.json"
    assert main(["ask", "--demo", "اختبار", "--receipt", str(receipt)]) == 0
    capsys.readouterr()  # تفريغ مخرجات ask — نقرأ JSON الـverify وحده
    assert main(["verify", str(receipt), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data.get("ok") is True
    assert "checks" in data or "issues" in data


# ------------------------------------------------------------------ do
def test_do_json_prints_signed_receipt(tmp_path, capsys):
    target = tmp_path / "code.py"
    target.write_text("x = 1\n", encoding="utf-8")
    assert main(["do", f"راجع {target}", "--json", "--dry-run"]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["chain_hash"]
    assert receipt["kind"] == "orchestrator"


# ------------------------------------------------------------------ cost/trace/cache
def test_cost_audit_json_with_corrupt_lines_skipped(tmp_path, capsys):
    audit = tmp_path / "audit.jsonl"
    audit.write_text(
        "\n" + "{تالف\n" + json.dumps({"type": "request"}) + "\n",
        encoding="utf-8",
    )
    assert main(["cost", "--audit", str(audit), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["audit_file"] == str(audit)


def test_cache_json_disabled_contract(capsys):
    assert main(["cache", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    # العقد: مستهلك الآلة يحصل على JSON صالح دائماً — ممكّناً أو لا
    assert "enabled" in data and "entries" in data


def test_cache_disabled_human_output_shows_how_to_enable(capsys):
    assert main(["cache"]) == 0
    assert "response cache is disabled" in capsys.readouterr().out


def test_trace_json_with_corrupt_and_valid_spans(tmp_path, capsys):
    from zyko.observability.tracer import TraceSpan

    log = tmp_path / "trace.jsonl"
    span = TraceSpan(
        trace_id="t1", span_id="s1", parent_id=None, name="op", started_at=1.0, duration_ms=2.0
    )
    log.write_text(
        json.dumps(span.to_dict()) + "\n" + "{تالف\n" + "\n",
        encoding="utf-8",
    )
    assert main(["traces", "--file", str(log), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["spans"] and data["traces"]


def test_trace_filter_no_hit_warns(tmp_path, capsys):
    from zyko.observability.tracer import TraceSpan

    log = tmp_path / "trace.jsonl"
    span = TraceSpan(trace_id="t1", span_id="s1", parent_id=None, name="op", started_at=1.0)
    log.write_text(json.dumps(span.to_dict()) + "\n", encoding="utf-8")
    assert main(["traces", "--file", str(log), "--trace", "missing-id"]) == 0
    assert "no spans found for trace missing-id" in capsys.readouterr().out


def test_trace_json_empty_contract(tmp_path, capsys):
    assert main(["traces", "--file", str(tmp_path / "ghost.jsonl"), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {"trace_file": str(tmp_path / "ghost.jsonl"), "spans": [], "traces": []}


# ------------------------------------------------------------------ generate
def _generate_input(monkeypatch, answer: str):
    monkeypatch.setattr("builtins.input", lambda _prompt="": answer)


def test_generate_eof_cancels_without_writing(tmp_path, monkeypatch, capsys):
    def eof(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    out = tmp_path / "proj"
    assert main(["new", "--plan", "أداة تجريبية", "--out", str(out), "--no-git"]) == 1
    assert "أُلغي" in capsys.readouterr().out
    assert not out.exists()


def test_generate_rejected_answer_cancels(tmp_path, monkeypatch, capsys):
    _generate_input(monkeypatch, "لا")
    out = tmp_path / "proj"
    assert main(["new", "--plan", "أداة تجريبية", "--out", str(out), "--no-git"]) == 1
    assert "أُلغي" in capsys.readouterr().out
    assert not out.exists()


def test_generate_approved_writes_project(tmp_path, monkeypatch, capsys):
    _generate_input(monkeypatch, "نعم")
    out = tmp_path / "proj"
    assert main(["new", "--plan", "أداة حساب", "--out", str(out), "--no-git"]) == 0
    text = capsys.readouterr().out
    assert "وُلّد" in text
    assert "فحص ثابت (ast + RTL): نظيف" in text
    assert out.exists()


def test_generate_existing_target_reports_exit_two(tmp_path, monkeypatch, capsys):
    _generate_input(monkeypatch, "نعم")
    monkeypatch.setattr(
        "zyko.coder.generate.materialize",
        lambda *_a, **_k: (_ for _ in ()).throw(FileExistsError("المجلد موجود")),
    )
    out = tmp_path / "proj"
    assert main(["new", "--plan", "أداة حساب", "--out", str(out), "--no-git"]) == 2
    assert "المجلد موجود" in capsys.readouterr().err


def test_generate_static_rejection_exit_one(tmp_path, monkeypatch, capsys):
    _generate_input(monkeypatch, "نعم")
    fake_report = types.SimpleNamespace(ok=False, problems=["RTL مشكلة اختبار"])
    monkeypatch.setattr("zyko.coder.precheck.check_source_tree", lambda *_a, **_k: fake_report)
    out = tmp_path / "proj"
    assert main(["new", "--plan", "أداة حساب", "--out", str(out), "--no-git"]) == 1
    err = capsys.readouterr().err
    assert "الفحص الثابت رفض المشروع" in err


def test_generate_run_tests_failure_exit_one(tmp_path, monkeypatch, capsys):
    _generate_input(monkeypatch, "نعم")
    assert main(["new", "--plan", "أداة حساب", "--out", str(tmp_path / "first"), "--no-git"]) == 0
    capsys.readouterr()  # تفريغ مخرجات التوليد الأول
    fake_full = types.SimpleNamespace(problems=["اختبار فاشل محقون"])
    monkeypatch.setattr("zyko.coder.precheck.full_gate", lambda *_a, **_k: fake_full)
    assert (
        main(
            [
                "new",
                "--plan",
                "أداة حساب",
                "--out",
                str(tmp_path / "second"),
                "--no-git",
                "--run-tests",
            ]
        )
        == 1
    )
    assert "اختبارات المشروع لم تمر" in capsys.readouterr().err


# ------------------------------------------------------------------ py (ضاد)
@daad_required
def test_py_out_writes_transpiled_python(tmp_path, capsys):
    src = tmp_path / "hello.daad"
    src.write_text(HELLO_DAAD, encoding="utf-8")
    out = tmp_path / "hello.py"
    assert main(["py", str(src), "--out", str(out)]) == 0
    assert "اكتُب" in capsys.readouterr().out
    assert out.is_file() and "اطبع(" in out.read_text(encoding="utf-8")


@daad_required
def test_py_stdout_returns_zero(tmp_path):
    src = tmp_path / "hello.daad"
    src.write_text(HELLO_DAAD, encoding="utf-8")
    assert main(["py", str(src), "--stdout"]) == 0


@daad_required
def test_py_bad_source_returns_transpiler_exit_code(tmp_path):
    src = tmp_path / "bad.daad"
    src.write_text("هذا ليس كود ضاد صالحًا (\n", encoding="utf-8")
    out = tmp_path / "bad.py"
    assert main(["py", str(src), "--out", str(out)]) != 0


@daad_required
def test_py_default_passthrough_returns_zero(tmp_path):
    src = tmp_path / "hello.daad"
    src.write_text(HELLO_DAAD, encoding="utf-8")
    assert main(["py", str(src)]) == 0


def test_py_missing_transpiler_documented_hint(tmp_path, monkeypatch, capsys):
    src = tmp_path / "hello.daad"
    src.write_text(HELLO_DAAD, encoding="utf-8")

    def no_daad(*_a, **_k):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "call", no_daad)
    assert main(["py", str(src)]) == 1
    assert "مترجم ضاد غير مثبّت" in capsys.readouterr().err
