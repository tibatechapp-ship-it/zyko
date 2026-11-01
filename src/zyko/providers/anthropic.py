"""Anthropic Claude adapter (Messages API)."""

from __future__ import annotations

from typing import Any

from zyko.core import tools as toolconv
from zyko.core.events import StreamEvent
from zyko.core.messages import ToolCall, messages_to_anthropic
from zyko.core.models import ModelInfo
from zyko.core.response import ChatRequest, ChatResponse
from zyko.providers.base import BaseProvider, _usage_from

STOP_REASONS = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
    "refusal": "content_filter",
}


class AnthropicProvider(BaseProvider):
    name = "anthropic"
    DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
    DEFAULT_MODEL = "claude-sonnet-4-20250514"
    KEY_ENV = "ANTHROPIC_API_KEY"
    CATALOG = [
        ModelInfo(
            "anthropic",
            "claude-opus-4-20250514",
            200_000,
            32_000,
            True,
            True,
            15.00,
            75.00,
            ["flagship"],
        ),
        ModelInfo(
            "anthropic",
            "claude-sonnet-4-20250514",
            200_000,
            64_000,
            True,
            True,
            3.00,
            15.00,
            ["balanced"],
        ),
        ModelInfo(
            "anthropic",
            "claude-3-7-sonnet-20250219",
            200_000,
            64_000,
            True,
            True,
            3.00,
            15.00,
            ["balanced"],
        ),
        ModelInfo(
            "anthropic",
            "claude-3-5-haiku-20241022",
            200_000,
            8_192,
            True,
            False,
            0.80,
            4.00,
            ["fast"],
        ),
    ]

    def _build(
        self, request: ChatRequest, *, stream: bool
    ) -> tuple[str, dict[str, Any], dict[str, str]]:
        system, messages = messages_to_anthropic(request.messages)
        payload: dict[str, Any] = {
            "model": self._resolve_model(request),
            "max_tokens": request.max_tokens or 4096,
            "messages": messages,
            "stream": stream,
        }
        if system:
            payload["system"] = system
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.tools:
            payload["tools"] = toolconv.to_anthropic_tools(request.tools)
        headers = {
            "x-api-key": self.api_key or "",
            "anthropic-version": "2023-06-01",
        }
        return f"{self.base_url}/messages", payload, headers

    def _parse_response(self, data: dict[str, Any], request: ChatRequest) -> ChatResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in data.get("content") or []:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text") or "")
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.get("id") or "",
                        name=block.get("name") or "",
                        arguments=block.get("input") or {},
                    )
                )
        return ChatResponse(
            id=data.get("id") or "anthropic",
            provider=self.name,
            model=data.get("model") or self._resolve_model(request),
            content="\n".join(text_parts) or None,
            tool_calls=tool_calls,
            usage=_usage_from(data.get("usage")),
            finish_reason=STOP_REASONS.get(data.get("stop_reason", "end_turn"), "stop"),
            raw=data,
        )

    def _parse_stream_chunk(
        self, data: dict[str, Any], state: dict[str, Any]
    ) -> StreamEvent | None:
        etype = data.get("type")
        if etype == "content_block_start":
            block = data.get("content_block") or {}
            index = data.get("index", 0)
            if block.get("type") == "tool_use":
                state.setdefault("blocks", {})[index] = {
                    "kind": "tool",
                    "id": block.get("id") or "",
                    "name": block.get("name") or "",
                }
                return StreamEvent(
                    "tool_call",
                    {
                        "index": index,
                        "id": block.get("id") or "",
                        "name": block.get("name") or "",
                        "args_delta": "",
                    },
                )
            state.setdefault("blocks", {})[index] = {"kind": "text"}
            return None
        if etype == "content_block_delta":
            index = data.get("index", 0)
            delta = data.get("delta") or {}
            if delta.get("type") == "input_json_delta":
                return StreamEvent(
                    "tool_call",
                    {
                        "index": index,
                        "id": "",
                        "name": "",
                        "args_delta": delta.get("partial_json") or "",
                    },
                )
            if delta.get("text"):
                return StreamEvent("text", {"text": delta["text"]})
            return None
        if etype == "message_delta":
            if data.get("usage"):
                return StreamEvent("usage", {"usage": data["usage"]})
            return None
        if etype == "message_start":
            usage = (data.get("message") or {}).get("usage")
            if usage:
                return StreamEvent("usage", {"usage": usage})
        return None
