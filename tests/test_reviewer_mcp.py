"""اختبارات تكامل المراجع مع خادم MCP — أداة code_review بلا نموذج.

الاستجابات هنا مغلفة بمظروف JSON-RPC: {jsonrpc, id, result: {...}} —
لذلك نقرأ isError والمحتوى من داخل response["result"].
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from zyko.exceptions import ZykoError
from zyko.mcp.server import ZYKO_TOOLS, ZykoMCPServer

REPO = Path(__file__).resolve().parents[1]
SAMPLES = REPO / "samples" / "review"

BAD_SNIPPET = "def f(expr):\n    '''توثيق.'''\n    return eval(expr)\n"
CLEAN_SNIPPET = (
    'def total(values: list[int]) -> int:\n    """يجمع القيم."""\n    return sum(values)\n'
)


def _call(server: ZykoMCPServer, message: dict) -> dict:
    return asyncio.run(server.handle(message))


def _tool_payload(server: ZykoMCPServer, arguments: dict, msg_id: int = 2) -> dict:
    response = _call(
        server,
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": "code_review", "arguments": arguments},
        },
    )
    assert response["id"] == msg_id
    return response["result"]


def test_code_review_registered_in_catalog():
    assert "code_review" in [t["name"] for t in ZYKO_TOOLS]
    tool = next(t for t in ZYKO_TOOLS if t["name"] == "code_review")
    props = tool["inputSchema"]["properties"]
    assert "text" in props and "path" in props and "fail_under" in props


def test_tools_list_includes_code_review():
    server = ZykoMCPServer()
    response = _call(server, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = [t["name"] for t in response["result"]["tools"]]
    assert "code_review" in names


def test_call_with_bad_text_scores_low():
    server = ZykoMCPServer()
    result = _tool_payload(server, {"text": BAD_SNIPPET})
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["tool"] == "code_review"
    assert payload["min_score"] < 95
    assert payload["passed"] is False
    rule_ids = [f["rule_id"] for f in payload["results"][0]["findings"]]
    assert "R-SEC-101" in rule_ids


def test_call_with_clean_text_passes():
    server = ZykoMCPServer()
    payload = json.loads(_tool_payload(server, {"text": CLEAN_SNIPPET})["content"][0]["text"])
    assert payload["min_score"] == 100
    assert payload["passed"] is True


def test_call_with_path_reviews_file():
    server = ZykoMCPServer()
    payload = json.loads(
        _tool_payload(server, {"path": str(SAMPLES / "clean_error_handling.py")})["content"][0][
            "text"
        ]
    )
    assert payload["files"] == 1
    assert payload["min_score"] == 100


def test_call_with_bad_path_is_tool_error():
    server = ZykoMCPServer()
    result = _tool_payload(server, {"path": "/لا/يوجد/مجلد/هنا"})
    assert result["isError"] is True


def test_call_without_args_is_tool_error():
    server = ZykoMCPServer()
    result = _tool_payload(server, {})
    assert result["isError"] is True
    assert "code_review" in result["content"][0]["text"]


def test_direct_method_requires_text_or_path():
    with pytest.raises(ZykoError):
        ZykoMCPServer._code_review_text({})


def test_fail_under_override_flips_verdict():
    payload = json.loads(ZykoMCPServer._code_review_text({"text": BAD_SNIPPET, "fail_under": 10}))
    assert payload["passed"] is True  # الدرجة 85 أعلى من حد 10
    assert payload["fail_under"] == 10.0


def test_mcp_review_output_is_deterministic():
    server = ZykoMCPServer()
    a = _tool_payload(server, {"text": BAD_SNIPPET}, msg_id=7)["content"][0]["text"]
    b = _tool_payload(server, {"text": BAD_SNIPPET}, msg_id=8)["content"][0]["text"]
    # المعرف يختلف بين النداءين — نقارن الحمولة فقط بعد إزالة معرف الطلب
    assert json.loads(a) == json.loads(b)
