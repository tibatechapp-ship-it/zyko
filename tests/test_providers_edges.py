"""Provider adapter edges (google/ollama), version sync, and a bench policy guard."""

from __future__ import annotations

import tomllib
from pathlib import Path

import httpx

from zyko.core.events import StreamEvent
from zyko.core.messages import Message
from zyko.core.response import ChatRequest
from zyko.providers.google import FINISH_MAP, GoogleProvider
from zyko.providers.ollama import OllamaProvider
from zyko.version import PROTOCOL_VERSION, __version__


def _req(**kw):
    return ChatRequest(messages=[Message.user("hi")], **kw)


# --------------------------------------------------------------- google edges
def test_google_build_full_payload():
    provider = GoogleProvider(api_key="g-key")
    url, payload, headers = provider._build(
        _req(temperature=0.4, max_tokens=256, tools=[{"name": "calc", "description": "d", "parameters": {"type": "object"}}]),
        stream=False,
    )
    assert url.endswith("/models/gemini-2.5-flash:generateContent")
    assert payload["generationConfig"] == {"temperature": 0.4, "maxOutputTokens": 256}
    assert payload["tools"]
    assert headers["x-goog-api-key"] == "g-key"


def test_google_build_stream_url():
    provider = GoogleProvider(api_key="k")
    url, _payload, _headers = provider._build(_req(), stream=True)
    assert "streamGenerateContent" in url and "alt=sse" in url


def test_google_parse_text_and_function_call():
    provider = GoogleProvider(api_key="k")
    data = {
        "responseId": "rid-1",
        "modelVersion": "gemini-2.5-flash-001",
        "candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [
            {"text": "partial"},
            {"functionCall": {"name": "calc", "args": {"a": 1}}},
            {"text": "text after call"},
        ]}}],
        "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 34},
    }
    response = provider._parse_response(data, _req())
    assert response.id == "rid-1"
    assert response.model == "gemini-2.5-flash-001"
    assert response.content == "partial\ntext after call"
    assert response.tool_calls[0].name == "calc"
    assert response.tool_calls[0].arguments == {"a": 1}
    assert response.finish_reason == "length"
    assert response.usage.input_tokens == 12 and response.usage.output_tokens == 34


def test_google_parse_empty_candidates():
    provider = GoogleProvider(api_key="k")
    response = provider._parse_response({}, _req())
    assert response.content is None
    assert response.finish_reason == "stop"


def test_google_stream_chunks():
    provider = GoogleProvider(api_key="k")
    text = provider._parse_stream_chunk({"candidates": [{"content": {"parts": [{"text": "chunk"}]}}]}, {})
    assert text == StreamEvent("text", {"text": "chunk"})
    call = provider._parse_stream_chunk(
        {"candidates": [{"content": {"parts": [{"functionCall": {"name": "t", "args": {}}}]}}]},
        {},
    )
    assert call.type == "tool_call" and call.data["name"] == "t"
    state = {}
    one = provider._parse_stream_chunk({"candidates": [{"content": {"parts": [{"functionCall": {"name": "x"}}]}}]}, state)
    two = provider._parse_stream_chunk({"candidates": [{"content": {"parts": [{"functionCall": {"name": "y"}}]}}]}, state)
    assert one.data["index"] == 0 and two.data["index"] == 1
    usage = provider._parse_stream_chunk({"usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 4}}, {})
    assert usage.type == "usage"
    assert provider._parse_stream_chunk({"candidates": [{"content": {"parts": []}}]}, {}) is None


def test_google_finish_map():
    assert FINISH_MAP["SAFETY"] == "content_filter"
    assert FINISH_MAP["RECITATION"] == "stop"


# --------------------------------------------------------------- ollama edges
def test_ollama_build_options_and_tools():
    provider = OllamaProvider(api_key=None)
    url, payload, headers = provider._build(_req(temperature=0.1, max_tokens=64), stream=False)
    assert url.endswith("/api/chat")
    assert payload["stream"] is False
    assert payload["options"] == {"temperature": 0.1, "num_predict": 64}
    assert headers == {}


def test_ollama_parse_tool_calls_and_usage():
    provider = OllamaProvider(api_key=None)
    data = {
        "model": "llama3.2",
        "message": {
            "content": None,
            "tool_calls": [{"function": {"name": "calc", "arguments": {"x": 2}}}],
        },
        "prompt_eval_count": 7,
        "eval_count": 9,
    }
    response = provider._parse_response(data, _req())
    assert response.tool_calls[0].name == "calc"
    assert response.tool_calls[0].arguments == {"x": 2}
    assert response.finish_reason == "tool_calls"
    assert response.usage.input_tokens == 7 and response.usage.output_tokens == 9


def test_ollama_stream_chunk_states():
    provider = OllamaProvider(api_key=None)
    text = provider._parse_stream_chunk({"message": {"content": "hi"}}, {})
    assert text == StreamEvent("text", {"text": "hi"})
    call = provider._parse_stream_chunk({"message": {"tool_calls": [{"function": {"name": "f"}}]}}, {})
    assert call.type == "tool_call"
    done = provider._parse_stream_chunk({"done": True, "prompt_eval_count": 5, "eval_count": 6}, {})
    assert done.type == "usage"
    assert provider._parse_stream_chunk({"message": {}}, {}) is None


def test_ollama_catalog_falls_back_when_unreachable():
    provider = OllamaProvider(api_key=None, base_url="http://127.0.0.1:1")
    assert provider.catalog() == OllamaProvider.CATALOG_FALLBACK
    assert provider.probe(timeout=0.1) is False


def test_ollama_catalog_parses_tags(monkeypatch):
    provider = OllamaProvider(api_key=None)
    payload = {"models": [{"name": "qwen2.5:3b", "context": 16384}, {"name": ""}]}
    captured = {}

    def fake_get(self, url):
        captured["url"] = url
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    catalog = provider.catalog()
    assert captured["url"].endswith("/api/tags")
    assert [m.id for m in catalog] == ["qwen2.5:3b"]
    assert catalog[0].context_window == 16384
    assert catalog[0].local is True


# ------------------------------------------------------------- version sync
def test_pyproject_version_matches_package():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert data["project"]["version"] == __version__


def test_user_agent_tracks_version():
    assert __version__ in __import__("zyko.version", fromlist=["USER_AGENT"]).USER_AGENT
    assert PROTOCOL_VERSION == "2024-11-05"
