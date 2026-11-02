"""Google Gemini adapter (Generative Language API)."""

from __future__ import annotations

from typing import Any

from zyko.core import tools as toolconv
from zyko.core.events import StreamEvent
from zyko.core.messages import ToolCall, messages_to_google
from zyko.core.models import ModelInfo
from zyko.core.response import ChatRequest, ChatResponse
from zyko.providers.base import BaseProvider, _usage_from

FINISH_MAP = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "stop",
}


class GoogleProvider(BaseProvider):
    name = "google"
    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    DEFAULT_MODEL = "gemini-2.5-flash"
    KEY_ENV = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
    CATALOG = [
        ModelInfo(
            "google",
            "gemini-2.5-pro",
            1_048_576,
            65_536,
            True,
            True,
            1.25,
            10.00,
            ["flagship", "reasoning"],
        ),
        ModelInfo(
            "google",
            "gemini-2.5-flash",
            1_048_576,
            65_536,
            True,
            True,
            0.30,
            2.50,
            ["fast", "cheap"],
        ),
        ModelInfo("google", "gemini-2.0-flash", 1_048_576, 8_192, True, True, 0.10, 0.40, ["fast"]),
    ]

    def _build(
        self, request: ChatRequest, *, stream: bool
    ) -> tuple[str, dict[str, Any], dict[str, str]]:
        model = self._resolve_model(request)
        system, contents = messages_to_google(request.messages)
        payload: dict[str, Any] = {"contents": contents}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        gen: dict[str, Any] = {}
        if request.temperature is not None:
            gen["temperature"] = request.temperature
        if request.max_tokens:
            gen["maxOutputTokens"] = request.max_tokens
        rf = request.response_format or {}
        if rf.get("type") in ("json_object", "json_schema"):
            gen["responseMimeType"] = "application/json"
            if rf.get("type") == "json_schema":
                inner = (rf.get("json_schema") or {}).get("schema")
                if inner:
                    gen["responseSchema"] = inner
        if gen:
            payload["generationConfig"] = gen
        if request.tools:
            payload["tools"] = toolconv.to_google_tools(request.tools)
        verb = "streamGenerateContent" if stream else "generateContent"
        url = f"{self.base_url}/models/{model}:{verb}"
        if stream:
            url += "?alt=sse"
        headers = {"x-goog-api-key": self.api_key or ""}
        return url, payload, headers

    def _parse_response(self, data: dict[str, Any], request: ChatRequest) -> ChatResponse:
        candidates = data.get("candidates") or [{}]
        candidate = candidates[0]
        parts = ((candidate.get("content") or {}).get("parts")) or []
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for i, part in enumerate(parts):
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                call = part["functionCall"]
                tool_calls.append(
                    ToolCall(
                        id=f"call_{len(tool_calls)}_{i}",
                        name=call.get("name") or "",
                        arguments=call.get("args") or {},
                    )
                )
        return ChatResponse(
            id=data.get("responseId") or "google",
            provider=self.name,
            model=data.get("modelVersion") or self._resolve_model(request),
            content="\n".join(text_parts) or None,
            tool_calls=tool_calls,
            usage=_usage_from(
                {
                    "prompt_tokens": (data.get("usageMetadata") or {}).get("promptTokenCount"),
                    "completion_tokens": (data.get("usageMetadata") or {}).get(
                        "candidatesTokenCount"
                    ),
                }
            ),
            finish_reason=FINISH_MAP.get(candidate.get("finishReason", "STOP"), "stop"),
            raw=data,
        )

    def _parse_stream_chunk(
        self, data: dict[str, Any], state: dict[str, Any]
    ) -> StreamEvent | None:
        candidates = data.get("candidates") or [{}]
        parts = ((candidates[0].get("content") or {}).get("parts")) or []
        for part in parts:
            if "text" in part:
                return StreamEvent("text", {"text": part["text"]})
            if "functionCall" in part:
                call = part["functionCall"]
                idx = state.get("call_index", 0)
                state["call_index"] = idx + 1
                return StreamEvent(
                    "tool_call",
                    {
                        "index": idx,
                        "id": f"call_{idx}",
                        "name": call.get("name") or "",
                        "args_delta": "",
                    },
                )
        if data.get("usageMetadata"):
            meta = data["usageMetadata"]
            return StreamEvent(
                "usage",
                {
                    "usage": {
                        "prompt_tokens": meta.get("promptTokenCount"),
                        "completion_tokens": meta.get("candidatesTokenCount"),
                    }
                },
            )
        return None
