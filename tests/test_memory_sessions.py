"""SQLite memory store + the `zyko sessions` / `zyko cost` visibility commands."""

from __future__ import annotations

import json
import time

import pytest

from zyko.agents.memory import MemoryStore
from zyko.cli import main
from zyko.core.messages import Message, ToolCall
from zyko.platform.paths import sessions_db


# ----------------------------------------------------------------- MemoryStore
def test_store_append_history_roundtrip():
    store = MemoryStore()
    session = store.create_session(title="chat about routing")
    store.append(session, Message.user("hello router"))
    store.append(session, Message.assistant("hi, here is your plan"))
    history = store.history(session)
    assert [m.role.value for m in history] == ["user", "assistant"]
    assert history[0].content == "hello router"
    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["title"] == "chat about routing"
    assert sessions[0]["messages"] == 2
    assert "updated" in sessions[0]
    store.close()


def test_store_history_limit_returns_latest_in_order():
    store = MemoryStore()
    session = store.create_session()
    for i in range(5):
        store.append(session, Message.user(f"msg {i}"))
    limited = store.history(session, limit=2)
    assert [m.content for m in limited] == ["msg 3", "msg 4"]
    store.close()


def test_store_tool_calls_survive_persistence():
    store = MemoryStore()
    session = store.create_session()
    calls = [ToolCall(id="call_1", name="calculator", arguments={"a": 1, "b": 2})]
    store.append(session, Message.assistant(None, tool_calls=calls))
    store.append(session, Message.tool_result("call_1", "calculator", "3"))
    history = store.history(session)
    assert history[0].tool_calls is not None
    assert history[0].tool_calls[0].name == "calculator"
    assert history[0].tool_calls[0].arguments == {"a": 1, "b": 2}
    assert history[1].role.value == "tool"
    store.close()


def test_store_delete_and_clear():
    store = MemoryStore()
    s1 = store.create_session()
    s2 = store.create_session()
    store.append(s1, Message.user("one"))
    store.append(s2, Message.user("two"))
    assert store.delete_session(s1) is True
    assert store.delete_session(s1) is False
    assert store.history(s1) == []
    assert store.history(s2)
    assert store.clear() == 1
    assert store.list_sessions() == []
    assert store.clear() == 0
    store.close()


def test_store_shared_db_reopen(tmp_path):
    db = tmp_path / "mem" / "sessions.db"
    db.parent.mkdir(parents=True)
    store = MemoryStore(path=db)
    session = store.create_session()
    store.append(session, Message.user("persisted"))
    store.close()
    reopened = MemoryStore(path=db)
    assert reopened.history(session)[0].content == "persisted"
    reopened.close()


def test_sessions_db_respects_data_dir():
    assert sessions_db().is_absolute()


# ------------------------------------------------------------- sessions CLI
def test_sessions_cli_list_show_rm_clear(capsys):
    store = MemoryStore()
    s1 = store.create_session()
    store.append(s1, Message.user("what is routing?"))
    store.append(s1, Message.assistant("scored selection"))
    store.close()

    assert main(["sessions", "list"]) == 0
    out = capsys.readouterr().out
    assert s1 in out

    assert main(["sessions", "show", s1]) == 0
    out = capsys.readouterr().out
    assert "what is routing?" in out
    assert "scored selection" in out

    assert main(["sessions", "show", "missing-id"]) == 1
    capsys.readouterr()

    assert main(["sessions", "rm", s1, "never-existed"]) == 0
    out = capsys.readouterr().out
    assert "removed 1" in out

    store2 = MemoryStore()
    store2.create_session()
    store2.close()
    assert main(["sessions", "clear"]) == 1  # refuses without --yes
    capsys.readouterr()
    assert main(["sessions", "clear", "--yes"]) == 0
    assert "removed 1" in capsys.readouterr().out
    assert MemoryStore().list_sessions() == []


def test_sessions_cli_list_empty(capsys):
    assert main(["sessions", "list"]) == 0
    out = capsys.readouterr().out
    assert "no sessions" in out


# ----------------------------------------------------------------- cost CLI
def _write_audit(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def test_cost_cli_reports_spend_and_denials(tmp_path, capsys):
    now = time.time()
    audit = tmp_path / "audit.jsonl"
    _write_audit(
        audit,
        [
            {
                "ts": now,
                "policy": "p",
                "event": "allow",
                "candidate": "fake/small",
                "redactions": ["EMAIL"],
            },
            {
                "ts": now,
                "policy": "p",
                "event": "usage",
                "candidate": "fake/small",
                "cost": 0.002,
                "spent_today": 0.002,
                "estimated": False,
            },
            {
                "ts": now,
                "policy": "p",
                "event": "usage",
                "candidate": "fake/large",
                "cost": 0.01,
                "spent_today": 0.012,
                "estimated": True,
            },
            {
                "ts": now - 90 * 86400,
                "policy": "p",
                "event": "usage",
                "candidate": "fake/old",
                "cost": 5.0,
            },
            {
                "ts": now,
                "policy": "p",
                "event": "deny",
                "candidate": None,
                "rule": "budget_exceeded",
                "reason": "over cap",
            },
            "not-json-line",
        ],
    )
    assert main(["cost", "--audit", str(audit), "--days", "7"]) == 0
    out = capsys.readouterr().out
    assert "$0.012000" in out
    assert "fake/small" in out and "fake/large" in out
    assert "budget_exceeded" in out
    assert "redaction events" in out
    assert "fake/old" not in out  # 90 days ago, outside the 7-day window

    assert main(["cost", "--audit", str(audit), "--days", "0", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_spend_usd"] == pytest.approx(5.012)
    # old entry has no `estimated` flag → counted as vendor-reported
    assert payload["cost_accounting"] == {"vendor_reported": 2, "kernel_estimated": 1}
    assert payload["events"]["allow"] == 1
    assert payload["events"]["deny"] == 1


def test_cost_cli_days_window_excludes_old_entries(tmp_path, capsys):
    now = time.time()
    audit = tmp_path / "audit.jsonl"
    _write_audit(
        audit,
        [
            {"ts": now, "policy": "p", "event": "usage", "candidate": "fake/new", "cost": 0.01},
            {
                "ts": now - 30 * 86400,
                "policy": "p",
                "event": "usage",
                "candidate": "fake/old",
                "cost": 9.0,
            },
        ],
    )
    assert main(["cost", "--audit", str(audit), "--days", "7"]) == 0
    out = capsys.readouterr().out
    assert "fake/new" in out
    assert "fake/old" not in out
    assert "$0.010000" in out


def test_cost_cli_without_audit_log(capsys):
    assert main(["cost", "--audit", "/nonexistent/audit.jsonl"]) == 0
    out = capsys.readouterr().out
    assert "no audit log" in out
