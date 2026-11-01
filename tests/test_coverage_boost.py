"""Coverage boost for the gaps found in the v0.2.0 evaluation:
platform paths, the real MCP server subprocess, protocol framing, Google adapter.
"""

from __future__ import annotations

import sys

import pytest

from zyko.exceptions import MCPError
from zyko.mcp import protocol


# ------------------------------------------------------------ platform paths
def test_env_overrides_paths(tmp_path, monkeypatch):
    from zyko.platform import paths

    monkeypatch.setenv("ZYKO_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("ZYKO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ZYKO_CACHE_DIR", str(tmp_path / "cache"))
    assert paths.config_dir() == tmp_path / "cfg"
    assert paths.data_dir() == tmp_path / "data"
    assert paths.cache_dir() == tmp_path / "cache"
    assert paths.config_file() == tmp_path / "cfg" / "config.yaml"


def test_windows_branch(monkeypatch, tmp_path):
    from zyko.platform import paths
    from zyko.platform.detect import OSKind

    monkeypatch.delenv("ZYKO_CONFIG_DIR", raising=False)
    monkeypatch.delenv("ZYKO_DATA_DIR", raising=False)
    monkeypatch.delenv("ZYKO_CACHE_DIR", raising=False)
    monkeypatch.setattr(paths, "detect_os", lambda: OSKind.WINDOWS)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert paths.config_dir() == tmp_path / "roaming" / "zyko"
    assert paths.data_dir() == tmp_path / "local" / "zyko" / "data"
    assert paths.cache_dir() == tmp_path / "local" / "zyko" / "cache"


def test_macos_branch(monkeypatch, tmp_path):
    from zyko.platform import paths
    from zyko.platform.detect import OSKind

    monkeypatch.delenv("ZYKO_CONFIG_DIR", raising=False)
    monkeypatch.delenv("ZYKO_DATA_DIR", raising=False)
    monkeypatch.delenv("ZYKO_CACHE_DIR", raising=False)
    monkeypatch.setattr(paths, "detect_os", lambda: OSKind.MACOS)
    monkeypatch.setattr(paths, "_home", lambda: tmp_path)
    assert paths.config_dir() == tmp_path / "Library" / "Application Support" / "zyko"
    assert paths.data_dir() == tmp_path / "Library" / "Application Support" / "zyko" / "data"
    assert paths.cache_dir() == tmp_path / "Library" / "Caches" / "zyko"


def test_ensure_layout_creates_tree_and_termux_marker(tmp_path, monkeypatch):
    from zyko.platform import paths

    monkeypatch.setenv("ZYKO_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("ZYKO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ZYKO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")  # termux-ish prefix
    layout = paths.ensure_layout()
    assert layout["config"].is_dir() and layout["data"].is_dir() and layout["cache"].is_dir()
    assert (layout["data"] / ".termux-ok").exists()


# ------------------------------------------------------------- MCP protocol
def test_protocol_round_trip():
    req = protocol.request(7, "tools/list", {"cursor": "abc"})
    decoded = protocol.decode(protocol.encode(req))
    assert decoded == req


def test_protocol_notification_shape():
    note = protocol.notification("notifications/initialized")
    assert "id" not in note and note["method"] == "notifications/initialized"


def test_protocol_decode_rejects_garbage():
    with pytest.raises(MCPError):
        protocol.decode(b"this is not json {")


def test_protocol_decode_rejects_non_object():
    with pytest.raises(MCPError):
        protocol.decode(b"[1, 2, 3]")


def test_protocol_error_codes_shape():
    msg = protocol.error(3, protocol.METHOD_NOT_FOUND, "nope")
    assert msg["error"]["code"] == -32601
    assert msg["id"] == 3


async def test_mcp_server_subprocess_round_trip(tmp_path, monkeypatch):
    """Real end-to-end: spawn `python -m zyko mcp serve` and drive it as a client."""
    from zyko.mcp.client import MCPClient

    monkeypatch.setenv("ZYKO_DATA_DIR", str(tmp_path / "data"))
    client = MCPClient(
        "zyko",
        [sys.executable, "-m", "zyko", "mcp", "serve"],
        env={"ZYKO_DEMO": "1"},  # keyless demo router inside the child process
        request_timeout=30,
    )
    await client.start()
    try:
        assert client.server_info.get("name") == "zyko"
        tools = await client.list_tools()
        names = {t["name"] for t in tools}
        assert {"zyko_models", "zyko_route", "zyko_chat"} <= names
        answer = await client.call_tool("zyko_chat", {"prompt": "hello zyko"})
        assert "routed via" in answer
        namespaced = client.as_tools()
        assert all(n.startswith("zyko__") for (n,) in [(t["name"],) for t in namespaced])
        assert MCPClient.split_qualified("zyko__chat") == ("zyko", "chat")
        assert MCPClient.split_qualified("chat") is None
    finally:
        await client.aclose()


# ----------------------------------------------------------- Google adapter
def test_google_build_payload():
    from zyko.core.messages import Message
    from zyko.core.response import ChatRequest
    from zyko.providers.google import GoogleProvider

    provider = GoogleProvider(api_key="g-key")
    request = ChatRequest(messages=[Message.system("be brief"), Message.user("hi")], max_tokens=64)
    url, payload, headers = provider._build(request, stream=False)
    assert url == f"{GoogleProvider.DEFAULT_BASE_URL}/models/gemini-2.5-flash:generateContent"
    assert headers["x-goog-api-key"] == "g-key"
    assert payload["systemInstruction"]["parts"][0]["text"] == "be brief"
    assert payload["contents"][0]["role"] == "user"
    assert payload["generationConfig"]["maxOutputTokens"] == 64


def test_google_build_stream_url():
    from zyko.core.messages import Message
    from zyko.core.response import ChatRequest
    from zyko.providers.google import GoogleProvider

    provider = GoogleProvider(api_key="g-key")
    url, _payload, _headers = provider._build(
        ChatRequest(messages=[Message.user("hi")]), stream=True
    )
    assert url.endswith(":streamGenerateContent?alt=sse")


def test_google_parse_response():
    from zyko.core.messages import Message
    from zyko.core.response import ChatRequest
    from zyko.providers.google import GoogleProvider

    provider = GoogleProvider(api_key="g-key")
    data = {
        "responseId": "resp-1",
        "candidates": [
            {
                "content": {"parts": [{"text": "hello "}, {"text": "world"}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 7},
    }
    response = provider._parse_response(data, ChatRequest(messages=[Message.user("x")]))
    assert response.content == "hello \nworld"
    assert response.id == "resp-1"
    assert response.finish_reason == "stop"
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens == 7


def test_google_parse_function_call():
    from zyko.core.messages import Message
    from zyko.core.response import ChatRequest
    from zyko.providers.google import GoogleProvider

    provider = GoogleProvider(api_key="g-key")
    data = {
        "candidates": [
            {
                "content": {"parts": [{"functionCall": {"name": "calc", "args": {"x": 1}}}]},
                "finishReason": "STOP",
            }
        ],
    }
    response = provider._parse_response(data, ChatRequest(messages=[Message.user("x")]))
    assert response.tool_calls and response.tool_calls[0].name == "calc"
    assert response.tool_calls[0].arguments == {"x": 1}


# ------------------------------------------------------------ config edges
def test_settings_env_interpolation(monkeypatch, tmp_path):
    from zyko.config.settings import Settings

    cfg = tmp_path / "config.yaml"
    cfg.write_text("gateway:\n  api_key: ${MY_SECRET_TOKEN}\n", encoding="utf-8")
    monkeypatch.setenv("MY_SECRET_TOKEN", "abc123")
    settings = Settings.load(cfg)
    assert settings.get("gateway.api_key") == "abc123"


def test_settings_env_override_coercion(monkeypatch):
    from zyko.config.settings import Settings

    monkeypatch.setenv("ZYKO_GATEWAY_PORT", "9000")
    monkeypatch.setenv("ZYKO_REQUEST_TIMEOUT", "33")
    settings = Settings.load("/nonexistent/path.yaml")
    assert settings.get("gateway.port") == 9000
    assert settings.get("router.request_timeout_s") == 33.0
