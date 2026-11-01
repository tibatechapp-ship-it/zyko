"""Unified message conversions."""

from __future__ import annotations

from zyko.core.messages import (
    Message,
    ToolCall,
    messages_to_anthropic,
    messages_to_google,
    messages_to_openai,
)


def test_openai_roundtrip_with_tools():
    messages = [
        Message.system("be brief"),
        Message.user("hi"),
        Message.assistant(tool_calls=[ToolCall(id="c1", name="calculator", arguments={"expression": "2+2"})]),
        Message.tool_result("c1", "calculator", "4"),
    ]
    out = messages_to_openai(messages)
    assert out[0]["role"] == "system"
    assert out[2]["tool_calls"][0]["function"]["name"] == "calculator"
    assert out[3]["role"] == "tool"
    assert out[3]["tool_call_id"] == "c1"


def test_anthropic_system_hoisted_and_tool_result_shape():
    messages = [
        Message.system("be brief"),
        Message.user("hi"),
        Message.tool_result("c1", "calc", "4"),
    ]
    system, out = messages_to_anthropic(messages)
    assert system == "be brief"
    assert out[-1]["content"][0]["type"] == "tool_result"
    assert out[-1]["content"][0]["tool_use_id"] == "c1"


def test_anthropic_assistant_tool_use_block():
    msg = Message.assistant("thinking", [ToolCall(id="c1", name="t", arguments={"a": 1})])
    out = msg.to_anthropic()
    kinds = [b["type"] for b in out["content"]]
    assert kinds == ["text", "tool_use"]
    assert out["content"][1]["input"] == {"a": 1}


def test_google_function_response_and_roles():
    messages = [
        Message.system("sys"),
        Message.user("hi"),
        Message.assistant(tool_calls=[ToolCall(id="x", name="t", arguments={"q": 1})]),
        Message.tool_result("x", "t", "42"),
    ]
    system, out = messages_to_google(messages)
    assert system == "sys"
    assert out[0]["role"] == "user"
    assert out[1]["role"] == "model"
    assert out[1]["parts"][0]["functionCall"]["name"] == "t"
    assert out[2]["parts"][0]["functionResponse"]["name"] == "t"


def test_tool_call_openai_arguments_json():
    tc = ToolCall(id="c", name="n", arguments={"x": 1})
    raw = tc.to_openai()
    assert raw["function"]["arguments"] == '{"x": 1}'
    parsed = ToolCall.from_openai(raw)
    assert parsed.arguments == {"x": 1}


def test_map_content_for_redaction():
    msg = Message.user("mail me at a@b.com")
    red = msg.map_content(lambda t: t.replace("a@b.com", "[EMAIL]"))
    assert "[EMAIL]" in red.content
    assert "a@b.com" in msg.content  # original untouched
