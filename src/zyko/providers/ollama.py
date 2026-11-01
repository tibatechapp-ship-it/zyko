"""Ollama adapter — the offline/local workhorse for Linux, Termux and Android.

Runs entirely on-device: same laptop or phone, zero API keys, zero data
leaving the machine. ZYKO treats local models as first-class routing
candidates and privacy-preserving fallbacks.
"""

from __future__ import annotations

from typing import Any

import httpx

from zyko.core import tools as toolconv
from zyko.core.events import StreamEvent
from zyko.core.messages import ToolCall
from zyko.core.models import ModelInfo
from zyko.core.response import ChatRequest, ChatResponse
from zyko.providers.base import BaseProvider


class OllamaProvider(BaseProvider):
    name = "ollama"
    DEFAULT_BASE_URL = "http://127.0.0.1:11434"
    DEFAULT_MODEL = "llama3.2"
    KEY_ENV = None
    local = True
    _stream_protocol = "ndjson"
    CATALOG_FALLBACK = [
        ModelInfo(
            "ollama", "llama3.2", 128_000, 8_192, True, False, 0.0, 0.0, ["local"], local=True
        ),
        ModelInfo("ollama", "qwen2.5", 32_768, 8_192, True, False, 0.0, 0.0, ["local"], local=True),
        ModelInfo("ollama", "gemma2", 8_192, 8_192, False, False, 0.0, 0.0, ["local"], local=True),
        ModelInfo("ollama", "mistral", 32_768, 8_192, True, False, 0.0, 0.0, ["local"], local=True),
    ]

    def _build(
        self, request: ChatRequest, *, stream: bool
    ) -> tuple[str, dict[str, Any], dict[str, str]]:
        payload: dict[str, Any] = {
            "model": self._resolve_model(request),
            "messages": [m.to_openai() for m in request.messages],
            "stream": stream,
        }
        options: dict[str, Any] = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.max_tokens:
            options["num_predict"] = request.max_tokens
        if options:
            payload["options"] = options
        if request.tools:
            payload["tools"] = toolconv.to_openai_tools(request.tools)
        return f"{self.base_url}/api/chat", payload, {}

    def _parse_response(self, data: dict[str, Any], request: ChatRequest) -> ChatResponse:
        message = data.get("message") or {}
        tool_calls = [
            ToolCall(
                id=f"call_{i}",
                name=(tc.get("function") or {}).get("name") or "",
                arguments=(tc.get("function") or {}).get("arguments") or {},
            )
            for i, tc in enumerate(message.get("tool_calls") or [])
        ]
        usage_in = int(data.get("prompt_eval_count") or 0)
        usage_out = int(data.get("eval_count") or 0)
        return ChatResponse(
            id="ollama",
            provider=self.name,
            model=data.get("model") or self._resolve_model(request),
            content=message.get("content") or None,
            tool_calls=tool_calls,
            usage=_ollama_usage(usage_in, usage_out),
            finish_reason="tool_calls" if tool_calls else "stop",
            raw=data,
        )

    def _parse_stream_chunk(
        self, data: dict[str, Any], state: dict[str, Any]
    ) -> StreamEvent | None:
        message = data.get("message") or {}
        if message.get("content"):
            return StreamEvent("text", {"text": message["content"]})
        for i, tc in enumerate(message.get("tool_calls") or []):
            fn = tc.get("function") or {}
            return StreamEvent(
                "tool_call",
                {"index": i, "id": f"call_{i}", "name": fn.get("name") or "", "args_delta": ""},
            )
        if data.get("done"):
            return StreamEvent(
                "usage",
                {
                    "usage": {
                        "prompt_eval_count": data.get("prompt_eval_count"),
                        "eval_count": data.get("eval_count"),
                    }
                },
            )
        return None

    def probe(self, timeout: float = 0.75) -> bool:
        """Cheap reachability check so the router never promises a dead backend."""
        try:
            with httpx.Client(timeout=timeout) as client:
                return client.get(f"{self.base_url}/api/tags").status_code == 200
        except Exception:
            return False

    def catalog(self) -> list[ModelInfo]:
        """Best-effort discovery of locally installed models via /api/tags."""
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                models = resp.json().get("models") or []
        except Exception:
            return list(self.CATALOG_FALLBACK)
        out: list[ModelInfo] = []
        for entry in models:
            name = entry.get("name") or ""
            if not name:
                continue
            out.append(
                ModelInfo(
                    provider=self.name,
                    id=name,
                    context_window=int(entry.get("context") or 8192),
                    supports_tools=True,
                    input_price_per_mtok=0.0,
                    output_price_per_mtok=0.0,
                    tags=["local"],
                    local=True,
                )
            )
        return out or list(self.CATALOG_FALLBACK)


def _ollama_usage(input_tokens: int, output_tokens: int):
    from zyko.core.response import Usage

    return Usage(input_tokens=input_tokens, output_tokens=output_tokens)
