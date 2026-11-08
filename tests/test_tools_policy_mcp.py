"""اختبارات التكامل: PolicyEngine × pii_ar (D5) + أداتا MCP (D6) + بوابات المرحلة 0."""

import json
from pathlib import Path

import pytest

from zyko.core.messages import Message
from zyko.core.response import ChatRequest
from zyko.mcp.server import ZYKO_TOOLS, ZykoMCPServer
from zyko.policy.engine import KNOWN_FN_REDACTORS, Redactor

REPO = Path(__file__).parents[1]


# ------------------------------------------------------------ D5: Redactor


def test_pii_ar_redactor_masks_arabic_pii():
    r = Redactor.from_doc({"redact": ["pii_ar"]})
    cleaned, labels = r.apply("اسمي محمد أحمد ورقمي ٠٥٠١٢٣٤٥٦٧")
    assert labels.count("pii_ar") == 2
    assert "محمد أحمد" not in cleaned and "٠٥٠١٢٣٤٥٦٧" not in cleaned
    assert "[اسم]" in cleaned and "[هاتف]" in cleaned


def test_pii_ar_runs_before_generic_regexes():
    r = Redactor.from_doc({"redact": ["pii_ar", "phone", "email"]})
    cleaned, labels = r.apply("راسلني على a@b.example أو اتصل 0501234567")
    # الهاتف العربي سبق النمط العام
    assert labels[0] == "pii_ar"
    assert "0501234567" not in cleaned and "a@b.example" not in cleaned


def test_redactor_bool_with_fn_rules_only():
    assert bool(Redactor.from_doc({"redact": ["pii_ar"]}))
    assert not Redactor.from_doc({})


def test_unknown_redactor_name_lists_pii_ar():
    with pytest.raises(Exception) as exc:
        Redactor.from_doc({"redact": ["nope"]})
    assert "pii_ar" in str(exc.value)


def test_known_fn_redactors_tuple():
    assert KNOWN_FN_REDACTORS == ("pii_ar",)


def test_policy_engine_check_request_redacts_arabic():
    """الحجب العربي يعمل داخل المسار الفعلي قبل وصول النموذج (بوابة D5)."""
    from zyko.policy.engine import PolicyEngine

    engine = PolicyEngine(
        {
            "version": 1,
            "name": "pii_ar_test",
            "privacy": {"redact": ["pii_ar"]},
        }
    )
    request = ChatRequest(messages=[Message.user("اسمي محمد أحمد ورقمي 0501234567")])
    decision = engine.check_request(request, _FakeCandidate())
    assert decision.allowed
    text = decision.request.messages[0].content
    assert "محمد أحمد" not in text and "0501234567" not in text
    assert decision.redactions == ["pii_ar"]


class _FakeCandidate:
    provider = "mock"
    model = "mock-1"

    @property
    def key(self) -> str:
        return "mock/mock-1"


# ------------------------------------------------------------ D6: أداتا MCP


def test_mcp_tools_list_includes_phase0_tools():
    names = {t["name"] for t in ZYKO_TOOLS}
    assert {"pii_ar_scan", "rtl_check"} <= names
    # مخططات مدخلات سليمة
    for t in ZYKO_TOOLS:
        assert t["inputSchema"]["type"] == "object"


@pytest.mark.asyncio
async def test_mcp_pii_ar_scan_tool():
    result = await ZykoMCPServer().handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "pii_ar_scan", "arguments": {"text": "جوال التاجر ٠٥٠١٢٣٤٥٦٧"}},
        }
    )
    assert not result["result"]["isError"]
    payload = json.loads(result["result"]["content"][0]["text"])
    assert payload["tool"] == "pii_ar_scan" and payload["count"] >= 1
    assert payload["findings"][0]["type"] == "phone"


@pytest.mark.asyncio
async def test_mcp_pii_ar_scan_empty_text_is_error():
    result = await ZykoMCPServer().handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "pii_ar_scan", "arguments": {"text": "   "}},
        }
    )
    assert result["result"]["isError"]


@pytest.mark.asyncio
async def test_mcp_rtl_check_tool_by_text():
    result = await ZykoMCPServer().handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "rtl_check",
                "arguments": {
                    "text": "[dir=rtl] .a { text-align: left; }",
                    "lang": "css",
                },
            },
        }
    )
    payload = json.loads(result["result"]["content"][0]["text"])
    assert payload["count"] == 1
    assert payload["findings"][0]["rule"] == "RTL-CSS-001"
    assert payload["findings"][0]["severity_ar"] == "خطأ"


@pytest.mark.asyncio
async def test_mcp_rtl_check_tool_by_path():
    result = await ZykoMCPServer().handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "rtl_check", "arguments": {"path": str(REPO / "samples")}},
        }
    )
    payload = json.loads(result["result"]["content"][0]["text"])
    assert payload["files_scanned"] == 2  # rtl_bad.css + arabic_mix.txt
    rules = {f["rule"] for f in payload["findings"]}
    assert "RTL-CSS-001" in rules  # من rtl_bad.css
    assert "RTL-TXT-001" in rules  # من arabic_mix.txt


@pytest.mark.asyncio
async def test_mcp_rtl_check_requires_input():
    result = await ZykoMCPServer().handle(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "rtl_check", "arguments": {}},
        }
    )
    assert result["result"]["isError"]


@pytest.mark.asyncio
async def test_mcp_unknown_tool_still_unknown():
    result = await ZykoMCPServer().handle(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "nope", "arguments": {}},
        }
    )
    assert result["result"]["isError"]


def test_mcp_tools_documented_as_model_free():
    for tool in ("pii_ar_scan", "rtl_check"):
        desc = next(t["description"] for t in ZYKO_TOOLS if t["name"] == tool)
        assert "no model" in desc.lower()


# ------------------------------------------------------------ بوابات المرحلة 0


def test_gate_policy_example_exists_and_loads():
    """بوابة: zyko policy check examples/policies/pii_ar.yaml يمر."""
    from zyko.policy.engine import load_policy

    engine = load_policy(REPO / "examples" / "policies" / "pii_ar.yaml")
    assert engine.name == "pii_ar"
    assert engine.warnings == [], f"تحذيرات المخطط: {engine.warnings}"
    assert engine.redactor  # الحجب مفعّل فعليًا


def test_gate_policy_redacts_via_loaded_example():
    from zyko.policy.engine import load_policy

    engine = load_policy(REPO / "examples" / "policies" / "pii_ar.yaml")
    cleaned = engine.redact_text("الشكاوى إلى support@zyko.example أو 0501234567")
    assert "support@zyko.example" not in cleaned and "0501234567" not in cleaned


def test_gate_typography_scan_clean():
    """بوابة: فحص typographic عربي نظيف على src."""
    import sys

    sys.path.insert(0, str(REPO / "scripts"))
    try:
        from check_arabic_typography import check_path

        assert check_path(REPO / "src") == []
    finally:
        sys.path.pop(0)


def test_no_secrets_in_changed_files():
    """قاعدة غير قابلة للتفاوض: لا مفاتيح في الشيفرة أو الأمثلة."""
    banned = ("ghp_", "github_pat_", "sk-", "AIza")
    for rel in (
        "src/zyko/tools/pii_ar/engine.py",
        "src/zyko/tools/rtl/core.py",
        "examples/policies/pii_ar.yaml",
        "samples/arabic_mix.txt",
    ):
        text = (REPO / rel).read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"مفتاح محتمل في {rel}"
