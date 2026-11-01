"""xAI + Together AI providers: registration, request shape, catalogs, key envs."""

from __future__ import annotations

import json
from typing import Any

import httpx

from zyko.core.messages import Message
from zyko.core.models import ModelInfo
from zyko.core.response import ChatRequest
from zyko.providers import build_provider, get_provider_class, provider_names
from zyko.providers.openai_compat import TogetherProvider, XAIProvider


def _request(**kw: Any) -> ChatRequest:
    return ChatRequest(messages=[Message.user("hi")], **kw)


# ------------------------------------------------------------------ registry
def test_registry_contains_ten_providers_with_the_new_two():
    names = provider_names()
    assert len(names) == 10  # mock/demo is internal and deliberately unregistered
    assert "xai" in names
    assert "together" in names


def test_unknown_provider_hint_lists_new_names():
    from zyko.exceptions import ConfigError

    try:
        get_provider_class("nope")
    except ConfigError as exc:
        msg = str(exc)
        assert "xai" in msg and "together" in msg
    else:  # pragma: no cover
        raise AssertionError("expected ConfigError")


# ---------------------------------------------------------------- request shape
def test_xai_request_shape_and_default_model():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "x1",
                "model": "grok-4.7",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hey"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    provider = XAIProvider(api_key="xai-test", transport=httpx.MockTransport(handler))
    resp = provider.complete(_request())  # no model → DEFAULT_MODEL
    assert captured["url"] == "https://api.x.ai/v1/chat/completions"
    assert captured["auth"] == "Bearer xai-test"
    assert captured["payload"]["model"] == "grok-4.7"
    assert resp.provider == "xai"
    assert resp.model == "grok-4.7"
    assert resp.text == "hey"


def test_together_request_shape_and_default_model():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "t1",
                "model": "zai-org/GLM-5.3-Flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "salam"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 3},
            },
        )

    provider = TogetherProvider(api_key="tog-test", transport=httpx.MockTransport(handler))
    resp = provider.complete(_request())  # no model → DEFAULT_MODEL
    assert captured["url"] == "https://api.together.ai/v1/chat/completions"
    assert captured["payload"]["model"] == "zai-org/GLM-5.3-Flash"
    assert resp.provider == "together"
    assert resp.text == "salam"


# -------------------------------------------------------------------- catalogs
def test_new_catalogs_integrity():
    for cls in (XAIProvider, TogetherProvider):
        assert cls.CATALOG, f"{cls.__name__} catalog must not be empty"
        for info in cls.CATALOG:
            assert isinstance(info, ModelInfo)
            assert info.provider == cls.name, info.qualified
            assert info.qualified.startswith(f"{cls.name}/")
            assert info.context_window > 0
            assert info.supports_tools, f"{info.qualified} must support tools"
            assert info.tags, f"{info.qualified} must carry at least one tag"
            assert info.input_price_per_mtok is not None
            assert info.output_price_per_mtok is not None
            assert info.input_price_per_mtok > 0
            assert info.output_price_per_mtok > 0
            # cost math stays sane
            cost = info.cost_usd(1_000_000, 1_000_000)
            assert cost is not None
            assert abs(cost - (info.input_price_per_mtok + info.output_price_per_mtok)) < 1e-9


def test_xai_catalog_models():
    ids = {info.id for info in XAIProvider.CATALOG}
    assert ids == {"grok-4.7", "grok-4.3", "grok-build-0.1"}


def test_together_catalog_models():
    ids = {info.id for info in TogetherProvider.CATALOG}
    assert ids == {
        "moonshotai/Kimi-K3",
        "zai-org/GLM-5.3",
        "zai-org/GLM-5.3-Flash",
        "deepseek-ai/DeepSeek-V4.1-Flash",
        "openai/gpt-oss-120b",
        "Qwen/Qwen3.5-9B",
    }


# ------------------------------------------------------------- key resolution
def test_key_env_resolution(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "env-xai")
    provider = build_provider("xai", {})
    assert provider.api_key == "env-xai"
    assert provider.base_url == "https://api.x.ai/v1"

    monkeypatch.setenv("TOGETHER_API_KEY", "env-tog")
    provider = build_provider("together", {})
    assert provider.api_key == "env-tog"
    assert provider.base_url == "https://api.together.ai/v1"
