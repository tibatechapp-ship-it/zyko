"""اختبارات أداة fix_workspace في خادم MCP: التسجيل، الاستدعاء، والتجريبية الدائمة.

العقد المُختبر هنا:
- الأداة سادسة الأدوات الحتمية في قائمة tools
- التجريبية الدائمة: لا بايت يتغير على القرص مهما كان الطلب
- كل نتيجة تحمل suggestion_ar لكل ملاحظة، وسببًا عربيًا لكل تخطٍ
- المسارات العدائية تُصدَّر أخطاء مكتوبة النوع لا انهيارًا
"""

from __future__ import annotations

import asyncio
import json

import pytest

from zyko.mcp.server import ZYKO_TOOLS, ZykoMCPServer

BUGGY = """import os


def flip(flag):
    return flag == None
"""


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


def test_fix_workspace_registered_with_the_deterministic_six():
    names = [t["name"] for t in ZYKO_TOOLS]
    # 9 أدوات مجموعًا: ثلاثة موجّهة للطوّر (models/route/chat) + ست حتمية بلا نموذج
    assert len(ZYKO_TOOLS) == 9
    assert [
        n
        for n in names
        if n
        in ("pii_ar_scan", "rtl_check", "code_review", "auto_fix", "run_pipeline", "fix_workspace")
    ] == [
        "pii_ar_scan",
        "rtl_check",
        "code_review",
        "auto_fix",
        "run_pipeline",
        "fix_workspace",
    ]
    tool = next(t for t in ZYKO_TOOLS if t["name"] == "fix_workspace")
    assert "EXISTING" in tool["description"]
    props = tool["inputSchema"]["properties"]
    assert "path" in props and "rounds" in props
    assert tool["inputSchema"]["required"] == ["path"]


def test_deterministic_tool_count_is_nine_total_six_deterministic():
    assert len(ZYKO_TOOLS) == 9


def test_fix_workspace_dry_run(server, tmp_path):
    src = tmp_path / "مشروع"
    src.mkdir()
    (src / "m.py").write_text(BUGGY, encoding="utf-8")
    before = (src / "m.py").read_bytes()
    resp = call(server, "fix_workspace", {"path": str(src)})
    assert resp["result"]["isError"] is False
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["tool"] == "fix_workspace"
    assert payload["ok"] is True
    assert payload["summary"]["fixed"] > 0
    assert payload["summary"]["changed_files"] > 0
    for f in payload["per_file"]:
        for o in f["outcomes"]:
            assert o["suggestion_ar"]
    assert (src / "m.py").read_bytes() == before, "الأداة التجريبية غيّرت القرص!"


def test_fix_workspace_reports_skipped_files(server, tmp_path):
    src = tmp_path / "فاسد"
    src.mkdir()
    (src / "enc.py").write_bytes(b"\xff\xfe\x00x")
    resp = call(server, "fix_workspace", {"path": str(src)})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["ok"] is True
    assert payload["summary"]["skipped"] == 1
    assert "UTF-8" in payload["per_file"][0]["reason_ar"]


def test_fix_workspace_missing_path(server, tmp_path):
    resp = call(server, "fix_workspace", {"path": str(tmp_path / "لا-يوجد")})
    assert resp["result"]["isError"] is True
    assert "path does not exist" in resp["result"]["content"][0]["text"]


def test_fix_workspace_requires_path(server):
    resp = call(server, "fix_workspace", {})
    assert resp["result"]["isError"] is True
    assert "requires" in resp["result"]["content"][0]["text"]


def test_fix_workspace_non_string_path(server):
    resp = call(server, "fix_workspace", {"path": 42})
    assert resp["result"]["isError"] is True


def test_fix_workspace_file_instead_of_dir_is_structured(server, tmp_path):
    p = tmp_path / "ملف.txt"
    p.write_text("ملف لا مجلد", encoding="utf-8")
    resp = call(server, "fix_workspace", {"path": str(p)})
    assert resp["result"]["isError"] is False  # فشل مهيكل داخل حمولة سليمة
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["ok"] is False
    assert payload["failed_stage"] == "scan"
    assert payload["error_ar"]


def test_fix_workspace_rounds_zero(server, tmp_path):
    src = tmp_path / "مشروع"
    src.mkdir()
    (src / "m.py").write_text(BUGGY, encoding="utf-8")
    resp = call(server, "fix_workspace", {"path": str(src), "rounds": 0})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["ok"] is True
    assert payload["summary"]["fixed"] == 0
    fates = {o["rule_id"]: o["status"] for f in payload["per_file"] for o in f["outcomes"]}
    assert fates.get("R-QLT-206") == "open"


def test_unknown_tool_still_errors(server):
    resp = call(server, "لا-أعرفه", {})
    assert resp["result"]["isError"] is True
    assert "unknown tool" in resp["result"]["content"][0]["text"]
