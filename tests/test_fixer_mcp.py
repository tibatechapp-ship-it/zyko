"""اختبارات أداة auto_fix في خادم MCP: التسجيل، الاستدعاء، وسلامة التجريبية."""

from __future__ import annotations

import json

import pytest

from zyko.mcp.server import ZYKO_TOOLS, ZykoMCPServer


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


def test_auto_fix_registered_in_tools():
    names = [t["name"] for t in ZYKO_TOOLS]
    assert "auto_fix" in names
    tool = next(t for t in ZYKO_TOOLS if t["name"] == "auto_fix")
    assert "deterministic" in tool["description"].lower()
    props = tool["inputSchema"]["properties"]
    assert "text" in props and "path" in props and "rules" in props


def test_auto_fix_text_mode(server):
    resp = call(server, "auto_fix", {"text": "import os\n"})
    assert resp["result"]["isError"] is False
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["tool"] == "auto_fix"
    assert payload["summary"]["fixed"] == 1
    assert "import os" not in payload["results"][0]["fixed_source"]


def test_auto_fix_is_dry_run_on_disk(server, tmp_path):
    p = tmp_path / "t.py"
    original = "import os\n"
    p.write_text(original, encoding="utf-8")
    resp = call(server, "auto_fix", {"path": str(p)})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["summary"]["changed_files"] == 1
    assert p.read_text(encoding="utf-8") == original  # القرص لم يُمس


def test_auto_fix_path_folder(server, tmp_path):
    (tmp_path / "a.py").write_text("import os\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("import sys\nx = 1\n", encoding="utf-8")
    resp = call(server, "auto_fix", {"path": str(tmp_path)})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["summary"]["files"] == 2
    assert payload["summary"]["fixed"] == 2


def test_auto_fix_missing_path_raises(server, tmp_path):
    # المحول يهضم ZykoError ويحوله ردّ خطأ مهيكلاً — لا استثناء للاتصال
    resp = call(server, "auto_fix", {"path": str(tmp_path / "غير_موجود.py")})
    assert resp["result"]["isError"] is True
    assert "does not exist" in resp["result"]["content"][0]["text"]


def test_auto_fix_requires_text_or_path(server):
    resp = call(server, "auto_fix", {})
    assert resp["result"]["isError"] is True
    assert "requires" in resp["result"]["content"][0]["text"]


def test_auto_fix_rules_filter(server):
    src = "import os\nimport hashlib\nhashlib.md5(b'x')\n"
    resp = call(server, "auto_fix", {"text": src, "rules": ["R-SEC-106"]})
    payload = json.loads(resp["result"]["content"][0]["text"])
    fixed_src = payload["results"][0]["fixed_source"]
    assert "sha256" in fixed_src
    assert "import os" in fixed_src  # مقيّد


def test_auto_fix_on_broken_source_structured(server):
    resp = call(server, "auto_fix", {"text": "def broken(:\n"})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["results"][0]["parse_error_ar"]


def test_four_deterministic_tools_complete():
    names = {t["name"] for t in ZYKO_TOOLS}
    assert {"pii_ar_scan", "rtl_check", "code_review", "auto_fix"} <= names
