"""Deterministic, keyless, network-free provider.

The mock provider exists so that *every* ZYKO capability — routing receipts,
policy enforcement, the gateway, MCP, agents, benchmarks — can be exercised
with zero API keys and zero network access. It is intentionally NOT part of
the auto-discovered registry: it only runs when explicitly requested via
``--demo``, ``ZYKO_DEMO=1`` or ``providers.mock.enabled: true`` in the config.

Replies are a deterministic function of the prompt, so demos and CI runs are
reproducible everywhere (Linux, Windows, macOS, Termux, Android).
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from zyko import kernel
from zyko.core.events import StreamEvent
from zyko.core.models import ModelInfo
from zyko.core.response import ChatRequest, ChatResponse, Usage
from zyko.providers.base import BaseProvider


class MockProvider(BaseProvider):
    """Offline stand-in that answers deterministically — never calls network."""

    name = "mock"
    DEFAULT_BASE_URL = "mock://local"
    KEY_ENV = None
    local = True
    DEFAULT_MODEL = "mock-mini"
    CATALOG = [
        ModelInfo("mock", "mock-mini", 32_000, 4_096, True, False, 0.0, 0.0,
                  ["free", "offline", "test"]),
        ModelInfo("mock", "mock-large", 128_000, 8_192, True, False, 0.0, 0.0,
                  ["free", "offline", "test"]),
    ]

    def _build(self, request: ChatRequest, *, stream: bool):  # pragma: no cover
        raise NotImplementedError("MockProvider answers without HTTP")

    def _parse_response(self, data: dict[str, Any], request: ChatRequest):  # pragma: no cover
        raise NotImplementedError("MockProvider answers without HTTP")

    # ----------------------------------------------------------------- reply
    @staticmethod
    def _prompt_of(request: ChatRequest) -> str:
        return request.messages[-1].plain_text() if request.messages else ""

    def _reply_text(self, request: ChatRequest) -> str:
        prompt = self._prompt_of(request)
        model = self._resolve_model(request)
        head = prompt.strip().replace("\n", " ")[:160]
        return (
            f"[zyko-mock/{model}] offline deterministic reply — "
            f"received {kernel.estimate_tokens(prompt)} estimated tokens: {head!r}. "
            "Routing, policy, receipts and streaming above are the real ZYKO "
            "code paths; add an API key or start Ollama for real inference."
        )

    def _tool_calls(self, request: ChatRequest) -> list[Any]:
        forced = request.metadata.get("force_tool")
        if not forced:
            return []
        from zyko.core.messages import ToolCall

        args = request.metadata.get("tool_args") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_raw": args}
        return [ToolCall(id="call-mock-0", name=str(forced), arguments=args)]

    async def acomplete(self, request: ChatRequest, *, retries: int | None = None) -> ChatResponse:
        tool_calls = self._tool_calls(request)
        text = None if tool_calls else self._reply_text(request)
        prompt = self._prompt_of(request)
        return ChatResponse(
            id=f"mock-{abs(hash(prompt)) % 10**10}",
            provider=self.name,
            model=self._resolve_model(request),
            content=text,
            tool_calls=tool_calls,
            usage=Usage(
                input_tokens=max(1, kernel.estimate_tokens(prompt)),
                output_tokens=max(1, kernel.estimate_tokens(text or "")),
            ),
            finish_reason="tool_calls" if tool_calls else "stop",
        )

    async def astream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        tool_calls = self._tool_calls(request)
        if tool_calls:
            for tc in tool_calls:
                yield StreamEvent("tool_call", {
                    "index": 0, "id": tc.id, "name": tc.name,
                    "args_delta": json.dumps(tc.arguments),
                })
            yield StreamEvent("done", {"finish_reason": "tool_calls"})
            return
        for word in self._reply_text(request).split(" "):
            if word:
                yield StreamEvent("text", {"text": word + " "})
        yield StreamEvent("done", {"finish_reason": "stop"})


def demo_enabled(settings: Any = None) -> bool:
    """True when the user asked for the keyless offline demo mode."""
    import os

    if os.environ.get("ZYKO_DEMO") == "1":
        return True
    if settings is not None:
        try:
            return bool(settings.get("providers.mock.enabled", False))
        except Exception:
            return False
    return False


__all__ = ["MockProvider", "demo_enabled"]
