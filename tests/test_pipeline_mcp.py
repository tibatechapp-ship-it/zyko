"""اختبارات أداة run_pipeline في خادم MCP: التسجيل، الاستدعاء، والتجريبية الدائمة."""

from __future__ import annotations

import json

import pytest

from zyko.mcp.server import ZYKO_TOOLS, ZykoMCPServer

DESC = "أريد قائمة مهام يومية بسيطة أضيف فيها المهام وأشطبها عند إنجازها"


@pytest.fixture()
def server():
    return ZykoMCPServer()


def call(server, name, args):
    resp = __import__("asyncio").run(
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


def test_run_pipeline_registered_in_tools():
    names = [t["name"] for t in ZYKO_TOOLS]
    assert "run_pipeline" in names
    tool = next(t for t in ZYKO_TOOLS if t["name"] == "run_pipeline")
    assert "deterministic" in tool["description"].lower()
    props = tool["inputSchema"]["properties"]
    assert "description" in props and "rounds" in props
    assert tool["inputSchema"]["required"] == ["description"]


def test_run_pipeline_dry_run(server):
    resp = call(server, "run_pipeline", {"description": DESC})
    assert resp["result"]["isError"] is False
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["tool"] == "run_pipeline"
    assert payload["ok"] is True
    assert payload["summary"]["fixed"] > 0
    assert payload["plan"]["name"] == "todo-cli"
    for f in payload["per_file"]:
        for o in f["outcomes"]:
            assert o["suggestion_ar"]


def test_run_pipeline_never_touches_disk(server, tmp_path):
    out = tmp_path / "ابدا"
    resp = call(server, "run_pipeline", {"description": DESC})
    assert resp["result"]["isError"] is False
    assert not out.exists()  # الأداة لا تأخذ مسارًا أصلًا — تجريبية بالتصميم


def test_run_pipeline_requires_description(server):
    resp = call(server, "run_pipeline", {})
    assert resp["result"]["isError"] is True
    assert "requires" in resp["result"]["content"][0]["text"]


def test_run_pipeline_structured_failure(server):
    resp = call(server, "run_pipeline", {"description": ""})
    assert resp["result"]["isError"] is True  # الحارس قبل المحرك
    resp2 = call(server, "run_pipeline", {"description": "ا" * 5000})
    payload = json.loads(resp2["result"]["content"][0]["text"])
    assert payload["ok"] is False
    assert payload["failed_stage"] == "coder"
    assert payload["error_ar"]


def test_five_deterministic_tools_complete():
    names = {t["name"] for t in ZYKO_TOOLS}
    assert {"pii_ar_scan", "rtl_check", "code_review", "auto_fix", "run_pipeline"} <= names
