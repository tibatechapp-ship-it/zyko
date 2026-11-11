"""اختبارات أداة MCP الجديدة baseline_check: العاشرة والسابعة الحتمية.

العقد المُختبر هنا:
- tools/list يعرض 12 أداة وbaseline_check ضمنها بمخطط مدخلات سليم
- الاستدعاء يقرأ فقط: لا ينشئ .zyko ولا يكتب أي شيء على القرص
- بلا خط أساس ⇒ حالة موثقة (baseline_status=missing) لا isError
- مسار مفقود أو فارغ ⇒ isError برسالة واضحة (اصطلاح الأدوات الحتمية)
- الحتمية: استدعاءان على نفس الحالة ⇒ نفس النص بالبايتات
"""

from __future__ import annotations

import asyncio
import json

import pytest

from zyko.mcp.server import ZYKO_TOOLS, ZykoMCPServer

CLEAN = '"""نظيف."""\n\n\ndef add(a, b):\n    return a + b\n'
BUGGY = "def f(x):\n    return eval(x)\n"

DETERMINISTIC_TOOLS = {
    "pii_ar_scan",
    "rtl_check",
    "code_review",
    "auto_fix",
    "run_pipeline",
    "fix_workspace",
    "baseline_check",
}


def _call(server: ZykoMCPServer, name: str, arguments: dict) -> dict:
    resp = asyncio.run(
        server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
    )
    assert resp is not None and "result" in resp
    return resp["result"]


def _payload(server: ZykoMCPServer, name: str, arguments: dict) -> str:
    resp = _call(server, name, arguments)
    assert resp["isError"] is False
    return resp["content"][0]["text"]


@pytest.fixture()
def project(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    (src / "a.py").write_text(CLEAN, encoding="utf-8", newline="\n")
    (src / "b.py").write_text(BUGGY, encoding="utf-8", newline="\n")
    return src


def test_tools_list_has_12_with_sandbox_tools():
    names = [t["name"] for t in ZYKO_TOOLS]
    # 0.27.0: sandbox_run_tests وsandbox_patch انضما إلى القائمة (12 أداة)
    assert len(names) == 12
    assert "baseline_check" in names
    assert "sandbox_run_tests" in names and "sandbox_patch" in names
    tool = next(t for t in ZYKO_TOOLS if t["name"] == "baseline_check")
    assert tool["inputSchema"]["required"] == ["path"]
    props = tool["inputSchema"]["properties"]
    assert set(props) == {"path", "baseline"}
    assert "Phase 6" in tool["description"]


def test_seven_deterministic_tools_registered():
    deterministic = {t["name"] for t in ZYKO_TOOLS if t["name"] in DETERMINISTIC_TOOLS}
    assert deterministic == DETERMINISTIC_TOOLS
    assert len(DETERMINISTIC_TOOLS) == 7


def test_call_reports_missing_baseline_and_writes_nothing(project):
    server = ZykoMCPServer()
    out = _payload(server, "baseline_check", {"path": str(project)})
    d = json.loads(out)
    assert d["tool"] == "baseline_check" and d["ok"] is True
    assert d["exit_code"] == 1
    assert d["summary"]["baseline_status"] == "missing"
    assert "لا خط أساس" in d["summary"]["verdict_ar"]
    assert not (project / ".zyko").exists()  # قراءة فقط دائمًا


def test_call_with_stored_baseline(project):
    from zyko.baseline import BaselineEngine

    assert BaselineEngine().update(project).ok
    server = ZykoMCPServer()
    out = _payload(server, "baseline_check", {"path": str(project)})
    d = json.loads(out)
    assert d["ok"] is True and d["exit_code"] == 0
    s = d["summary"]
    assert s["baseline_status"] == "ok"
    assert s["reviewed"] == 2 and s["regressed_files"] == 0
    assert s["min_score_current"] is not None
    paths = {f["path"] for f in d["per_file"]}
    assert paths == {"a.py", "b.py"}
    assert not list((project / ".zyko").iterdir())[1:]  # ملف واحد فقط: baseline.json


def test_call_is_deterministic(project):
    from zyko.baseline import BaselineEngine

    BaselineEngine().update(project)
    server = ZykoMCPServer()
    out1 = _payload(server, "baseline_check", {"path": str(project)})
    out2 = _payload(server, "baseline_check", {"path": str(project)})
    assert out1 == out2


def test_call_detects_regression(project):
    from zyko.baseline import BaselineEngine

    BaselineEngine().update(project)
    (project / "a.py").write_text(CLEAN + "\n\n\ndef p(x):\n    return eval(x)\n", encoding="utf-8")
    server = ZykoMCPServer()
    d = json.loads(_payload(server, "baseline_check", {"path": str(project)}))
    assert d["exit_code"] == 1
    assert d["summary"]["regressed_files"] == 1
    assert d["summary"]["new_findings_total"] >= 1
    hit = next(f for f in d["per_file"] if f["path"] == "a.py")
    assert hit["status"] == "regressed"


def test_call_custom_baseline_path(project, tmp_path):
    from zyko.baseline import BaselineEngine

    custom = tmp_path / "guard" / "baseline.json"
    BaselineEngine().update(project, baseline_path=custom)
    server = ZykoMCPServer()
    d = json.loads(
        _payload(
            server,
            "baseline_check",
            {"path": str(project), "baseline": str(custom)},
        )
    )
    assert d["summary"]["baseline_status"] == "ok"


def test_missing_path_is_tool_error():
    server = ZykoMCPServer()
    response = _call(server, "baseline_check", {"path": "/لا-يوجد"})
    assert response["isError"] is True
    assert "does not exist" in response["content"][0]["text"]


def test_empty_path_is_tool_error():
    server = ZykoMCPServer()
    for args in ({}, {"path": ""}, {"path": "  "}):
        response = _call(server, "baseline_check", args)
        assert response["isError"] is True
        assert "non-empty" in response["content"][0]["text"]


def test_bad_baseline_arg_is_tool_error(project):
    server = ZykoMCPServer()
    response = _call(server, "baseline_check", {"path": str(project), "baseline": ""})
    assert response["isError"] is True
    assert "non-empty" in response["content"][0]["text"]


def test_structured_failure_is_payload_not_crash(project, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{فاسد", encoding="utf-8")
    server = ZykoMCPServer()
    d = json.loads(_payload(server, "baseline_check", {"path": str(project), "baseline": str(bad)}))
    assert d["ok"] is False and d["failed_stage"] == "baseline"
    assert d["error_ar"]
