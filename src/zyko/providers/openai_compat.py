"""OpenAI and every OpenAI-compatible vendor (Groq, Mistral, DeepSeek, OpenRouter,
xAI, Together AI).

One request builder, one parser, many subclasses that only declare endpoints,
catalogs and vendor-specific headers. Adding another OpenAI-compatible vendor
is a ~30-line subclass — that leverage is a core ZYKO design goal.
"""

from __future__ import annotations

from typing import Any

from zyko.core import tools as toolconv
from zyko.core.events import StreamEvent
from zyko.core.messages import ToolCall
from zyko.core.models import ModelInfo
from zyko.core.response import ChatRequest, ChatResponse
from zyko.providers.base import BaseProvider, _usage_from

REASONING_PREFIXES = ("o1", "o3", "o4")


class OpenAICompatProvider(BaseProvider):
    """Chat Completions API client."""

    name = "openai"
    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    DEFAULT_MODEL = "gpt-4o-mini"
    KEY_ENV = "OPENAI_API_KEY"
    # OpenAI documents stream_options.include_usage; subclasses only keep it
    # enabled when their vendor confirms support (OpenRouter does, for example).
    STREAM_INCLUDE_USAGE = True
    CATALOG = [
        ModelInfo("openai", "gpt-4o", 128_000, 16_384, True, True, 2.50, 10.00, ["flagship"]),
        ModelInfo(
            "openai", "gpt-4o-mini", 128_000, 16_384, True, True, 0.15, 0.60, ["cheap", "fast"]
        ),
        ModelInfo("openai", "gpt-4.1", 1_000_000, 32_768, True, True, 2.00, 8.00, ["long-context"]),
        ModelInfo("openai", "gpt-4.1-mini", 1_000_000, 32_768, True, True, 0.40, 1.60, ["cheap"]),
        ModelInfo("openai", "o4-mini", 200_000, 100_000, True, False, 1.10, 4.40, ["reasoning"]),
    ]

    def _build(
        self, request: ChatRequest, *, stream: bool
    ) -> tuple[str, dict[str, Any], dict[str, str]]:
        model = self._resolve_model(request)
        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_openai() for m in request.messages],
            "stream": stream,
        }
        if stream and self.STREAM_INCLUDE_USAGE:
            # Ask the vendor for a final usage chunk so streaming calls are
            # cost-accounted from real token counts, not estimates.
            payload["stream_options"] = {"include_usage": True}
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens:
            key = "max_completion_tokens" if model.startswith(REASONING_PREFIXES) else "max_tokens"
            payload[key] = request.max_tokens
        if request.tools:
            payload["tools"] = toolconv.to_openai_tools(request.tools)
            if request.tool_choice:
                payload["tool_choice"] = request.tool_choice
        if request.response_format:
            payload["response_format"] = request.response_format
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return f"{self.base_url}/chat/completions", payload, headers

    def _parse_response(self, data: dict[str, Any], request: ChatRequest) -> ChatResponse:
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        tool_calls = [ToolCall.from_openai(tc) for tc in message.get("tool_calls") or []]
        usage = _usage_from(data.get("usage"))
        return ChatResponse(
            id=data.get("id") or "openai",
            provider=self.name,
            model=data.get("model") or self._resolve_model(request),
            content=message.get("content"),
            tool_calls=tool_calls,
            usage=usage,
            finish_reason={"tool_calls": "tool_calls"}.get(
                choice.get("finish_reason", "stop"), choice.get("finish_reason", "stop")
            ),
            raw=data,
        )

    def _parse_stream_chunk(
        self, data: dict[str, Any], state: dict[str, Any]
    ) -> StreamEvent | None:
        choice = (data.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        if delta.get("content"):
            return StreamEvent("text", {"text": delta["content"]})
        for tc in delta.get("tool_calls") or []:
            fn = tc.get("function") or {}
            return StreamEvent(
                "tool_call",
                {
                    "index": tc.get("index", 0),
                    "id": tc.get("id") or "",
                    "name": fn.get("name") or "",
                    "args_delta": fn.get("arguments") or "",
                },
            )
        if data.get("usage"):
            return StreamEvent("usage", {"usage": data["usage"]})
        if choice.get("finish_reason"):
            return StreamEvent("done", {"finish_reason": choice["finish_reason"]})
        return None


class GroqProvider(OpenAICompatProvider):
    """Groq — LPU inference, ultra-low latency open models."""

    name = "groq"
    DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
    DEFAULT_MODEL = "llama-3.3-70b-versatile"
    KEY_ENV = "GROQ_API_KEY"
    STREAM_INCLUDE_USAGE = False  # vendor support for stream_options unconfirmed
    CATALOG = [
        ModelInfo(
            "groq", "llama-3.3-70b-versatile", 128_000, 32_768, True, False, 0.59, 0.79, ["open"]
        ),
        ModelInfo(
            "groq",
            "llama-3.1-8b-instant",
            128_000,
            131_072,
            True,
            False,
            0.05,
            0.08,
            ["open", "fast"],
        ),
    ]


class MistralProvider(OpenAICompatProvider):
    name = "mistral"
    DEFAULT_BASE_URL = "https://api.mistral.ai/v1"
    DEFAULT_MODEL = "mistral-small-latest"
    KEY_ENV = "MISTRAL_API_KEY"
    STREAM_INCLUDE_USAGE = False  # vendor support for stream_options unconfirmed
    CATALOG = [
        ModelInfo(
            "mistral", "mistral-large-latest", 128_000, 8_192, True, False, 2.00, 6.00, ["flagship"]
        ),
        ModelInfo(
            "mistral", "mistral-small-latest", 128_000, 8_192, True, False, 0.20, 0.60, ["cheap"]
        ),
        ModelInfo(
            "mistral", "open-mistral-nemo", 128_000, 8_192, True, False, 0.15, 0.15, ["open"]
        ),
    ]


class DeepSeekProvider(OpenAICompatProvider):
    name = "deepseek"
    DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
    DEFAULT_MODEL = "deepseek-chat"
    KEY_ENV = "DEEPSEEK_API_KEY"
    STREAM_INCLUDE_USAGE = False  # vendor support for stream_options unconfirmed
    CATALOG = [
        ModelInfo(
            "deepseek", "deepseek-chat", 64_000, 8_192, True, False, 0.27, 1.10, ["open", "cheap"]
        ),
        ModelInfo(
            "deepseek", "deepseek-reasoner", 64_000, 8_192, True, False, 0.55, 2.19, ["reasoning"]
        ),
    ]


class XAIProvider(OpenAICompatProvider):
    """xAI — Grok models, OpenAI-compatible at api.x.ai (docs.x.ai)."""

    name = "xai"
    DEFAULT_BASE_URL = "https://api.x.ai/v1"
    DEFAULT_MODEL = "grok-4.7"
    KEY_ENV = "XAI_API_KEY"
    STREAM_INCLUDE_USAGE = False  # vendor support for stream_options unconfirmed
    # List prices from docs.x.ai/developers/pricing (short-context rates;
    # long-context prompts >= 200k tokens bill higher). max_output is left at
    # the ModelInfo default where xAI does not publish a per-model cap.
    CATALOG = [
        ModelInfo(
            "xai",
            "grok-4.7",
            500_000,
            input_price_per_mtok=2.00,
            output_price_per_mtok=6.00,
            tags=["flagship"],
        ),
        ModelInfo(
            "xai",
            "grok-4.3",
            1_000_000,
            input_price_per_mtok=1.25,
            output_price_per_mtok=2.50,
            tags=["long-context", "reasoning"],
        ),
        ModelInfo(
            "xai",
            "grok-build-0.1",
            256_000,
            input_price_per_mtok=1.00,
            output_price_per_mtok=2.00,
            tags=["code"],
        ),
    ]


class TogetherProvider(OpenAICompatProvider):
    """Together AI — serverless open-model aggregation behind one key."""

    name = "together"
    DEFAULT_BASE_URL = "https://api.together.ai/v1"
    DEFAULT_MODEL = "zai-org/GLM-5.3-Flash"
    KEY_ENV = "TOGETHER_API_KEY"
    STREAM_INCLUDE_USAGE = False  # vendor support for stream_options unconfirmed
    # Slugs / context lengths / list prices from the docs.together.ai
    # serverless chat-models table (function calling confirmed for every
    # model below). max_output stays at the ModelInfo default where Together
    # does not publish a per-model cap.
    CATALOG = [
        ModelInfo(
            "together",
            "moonshotai/Kimi-K3",
            1_048_576,
            input_price_per_mtok=3.00,
            output_price_per_mtok=15.00,
            tags=["flagship", "open"],
        ),
        ModelInfo(
            "together",
            "zai-org/GLM-5.3",
            1_048_575,
            input_price_per_mtok=1.40,
            output_price_per_mtok=4.40,
            tags=["open"],
        ),
        ModelInfo(
            "together",
            "zai-org/GLM-5.3-Flash",
            1_048_575,
            input_price_per_mtok=0.15,
            output_price_per_mtok=0.50,
            tags=["cheap", "open"],
        ),
        ModelInfo(
            "together",
            "deepseek-ai/DeepSeek-V4.1-Flash",
            1_000_000,
            input_price_per_mtok=0.30,
            output_price_per_mtok=1.20,
            tags=["cheap", "open"],
        ),
        ModelInfo(
            "together",
            "openai/gpt-oss-120b",
            131_072,
            input_price_per_mtok=0.15,
            output_price_per_mtok=0.60,
            tags=["open"],
        ),
        ModelInfo(
            "together",
            "Qwen/Qwen3.5-9B",
            262_144,
            input_price_per_mtok=0.17,
            output_price_per_mtok=0.25,
            tags=["cheap", "open"],
        ),
    ]


class OpenRouterProvider(OpenAICompatProvider):
    """OpenRouter — meta-provider with 300+ models behind one key."""

    name = "openrouter"
    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
    DEFAULT_MODEL = "openai/gpt-4o-mini"
    KEY_ENV = "OPENROUTER_API_KEY"
    CATALOG = [
        ModelInfo(
            "openrouter", "openai/gpt-4o-mini", 128_000, 16_384, True, True, 0.15, 0.60, ["cheap"]
        ),
        ModelInfo(
            "openrouter",
            "meta-llama/llama-3.3-70b-instruct",
            128_000,
            32_768,
            True,
            False,
            0.12,
            0.30,
            ["open"],
        ),
        ModelInfo(
            "openrouter", "deepseek/deepseek-chat", 64_000, 8_192, True, False, 0.14, 0.28, ["open"]
        ),
        ModelInfo(
            "openrouter",
            "google/gemini-2.0-flash-exp:free",
            1_048_576,
            8_192,
            True,
            True,
            0.0,
            0.0,
            ["free"],
        ),
        ModelInfo(
            "openrouter",
            "mistralai/mistral-7b-instruct:free",
            32_768,
            8_192,
            True,
            False,
            0.0,
            0.0,
            ["free"],
        ),
    ]

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("default_headers", {})
        kwargs["default_headers"] = {
            **kwargs["default_headers"],
            "HTTP-Referer": "https://github.com/tibatechapp-ship-it/zyko",
            "X-Title": "ZYKO",
        }
        super().__init__(**kwargs)
