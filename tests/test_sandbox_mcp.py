"""اختبارات أداتَي MCP المعزولتين — التسجيل، الموافقة الصريحة، سلسلة التدقيق."""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

from zyko.mcp.server import ZYKO_TOOLS, ZykoMCPServer

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

PY = sys.executable.replace("\\", "/").split("/")[-1].replace(".exe", "") or "python"


@pytest.fixture()
def server():
    return ZykoMCPServer()


def call(server, name, args):
    resp = asyncio.run(
        server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": args},
            }
        )
    )
    return resp


def _payload(resp):
    return json.loads(resp["result"]["content"][0]["text"])


# ---------------------------------------------------------------- التسجيل
def test_sandbox_tools_registered():
    names = [t["name"] for t in ZYKO_TOOLS]
    assert "sandbox_run_tests" in names and "sandbox_patch" in names
    run_tool = next(t for t in ZYKO_TOOLS if t["name"] == "sandbox_run_tests")
    assert "audit" in run_tool["description"].lower()
    assert set(run_tool["inputSchema"]["required"]) == {"root"}
    patch_tool = next(t for t in ZYKO_TOOLS if t["name"] == "sandbox_patch")
    assert "allow_write" in patch_tool["inputSchema"]["properties"]


# ---------------------------------------------------------------- run_tests
@_working_jail
def test_run_tests_green(server, tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    resp = call(server, "sandbox_run_tests", {"root": str(tmp_path)})
    assert resp["result"]["isError"] is False
    payload = _payload(resp)
    assert payload["tool"] == "sandbox_run_tests"
    assert payload["result"]["ok"] is True
    assert payload["result"]["command"].startswith(PY)


@_working_jail
def test_run_tests_red(server, tmp_path):
    (tmp_path / "test_bad.py").write_text("def test_bad():\n    assert 1 == 2\n", encoding="utf-8")
    payload = _payload(call(server, "sandbox_run_tests", {"root": str(tmp_path)}))
    assert payload["result"]["ok"] is False
    assert payload["result"]["failed"] == 1


def test_run_tests_audit_written_and_chained(server, tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    _payload(call(server, "sandbox_run_tests", {"root": str(tmp_path)}))
    audit_file = tmp_path / ".zyko" / "tools" / "audit.jsonl"
    assert audit_file.is_file()
    from zyko.sandbox.audit import AuditLog

    assert AuditLog(audit_file).verify().ok


def test_run_tests_missing_root_is_clean_error(server, tmp_path):
    resp = call(server, "sandbox_run_tests", {"root": str(tmp_path / "مفقود")})
    assert resp["result"]["isError"] is True
    assert "does not exist" in resp["result"]["content"][0]["text"]


@_working_jail
def test_run_tests_no_shell_no_env_secrets(server, monkeypatch, tmp_path):
    monkeypatch.setenv("CANARY_TOKEN", "v" * 40)
    (tmp_path / "test_env.py").write_text(
        "import os\n\n\ndef test_env():\n"
        "    for v in os.environ.values():\n"
        "        assert v != " + "\"" + "v" * 40 + "\"\n",
        encoding="utf-8",
    )
    payload = _payload(call(server, "sandbox_run_tests", {"root": str(tmp_path)}))
    assert payload["result"]["ok"] is True


# ---------------------------------------------------------------- patch
def test_patch_denied_without_consent(server, tmp_path):
    f = tmp_path / "app.py"
    f.write_text("أصل\n", encoding="utf-8")
    payload = _payload(
        call(server, "sandbox_patch", {"root": str(tmp_path), "path": "app.py",
                                       "old_text": "أصل", "new_text": "معدّل"})
    )
    assert payload["result"]["ok"] is False
    assert f.read_text(encoding="utf-8") == "أصل\n"  # القرص لم يُمس


def test_patch_with_explicit_consent_applies(server, tmp_path):
    f = tmp_path / "app.py"
    f.write_text("أصل\n", encoding="utf-8")
    payload = _payload(
        call(server, "sandbox_patch", {"root": str(tmp_path), "path": "app.py",
                                       "old_text": "أصل", "new_text": "معدّل",
                                       "allow_write": True})
    )
    assert payload["result"]["ok"] is True
    assert f.read_text(encoding="utf-8") == "معدّل\n"


def test_patch_consent_true_but_outside_root_denied(server, tmp_path):
    payload = _payload(
        call(server, "sandbox_patch", {"root": str(tmp_path), "path": "../خارج.py",
                                       "content": "hi", "allow_write": True})
    )
    assert payload["result"]["ok"] is False


def test_patch_denial_also_audited(server, tmp_path):
    _payload(
        call(server, "sandbox_patch", {"root": str(tmp_path), "path": "a.py", "content": "x"})
    )
    audit_file = tmp_path / ".zyko" / "tools" / "audit.jsonl"
    blob = audit_file.read_text(encoding="utf-8")
    assert "DENY" in blob
