"""Scripted fake providers for deterministic router/agent/gateway tests."""

from __future__ import annotations

from typing import Any

from zyko.core.events import StreamEvent
from zyko.core.models import ModelInfo
from zyko.core.response import ChatRequest, ChatResponse, Usage
from zyko.exceptions import ProviderError
from zyko.providers.base import BaseProvider


class FakeProvider(BaseProvider):
    """Returns scripted answers in order; can fail the first N calls."""

    name = "fake"
    DEFAULT_BASE_URL = "http://fake.invalid"
    KEY_ENV = None
    local = True
    DEFAULT_MODEL = "fake-small"

    def __init__(
        self,
        *,
        catalog: list[ModelInfo] | None = None,
        script: list[Any] | None = None,
        fail_first: int = 0,
        input_price: float = 0.5,
        output_price: float = 1.5,
        name: str = "fake",
    ) -> None:
        super().__init__(api_key=None, timeout=5.0)
        self.name = name
        self._catalog = catalog or [
            ModelInfo(
                name, "fake-small", 8_000, 2_000, True, False, input_price, output_price, ["cheap"]
            ),
            ModelInfo(
                name,
                "fake-large",
                32_000,
                4_000,
                True,
                False,
                input_price * 10,
                output_price * 10,
                ["flagship"],
            ),
        ]
        self.script = list(script) if script else ["ok"]
        self.fail_first = fail_first
        self.calls = 0

    def _build(self, request: ChatRequest, *, stream: bool):  # pragma: no cover - unused
        raise NotImplementedError

    def _parse_response(self, data: dict[str, Any], request: ChatRequest):  # pragma: no cover
        raise NotImplementedError

    async def acomplete(self, request: ChatRequest, *, retries: int | None = None) -> ChatResponse:
        self.calls += 1
        if self.calls <= self.fail_first:
            raise ProviderError(
                f"{self.name}: simulated outage", provider=self.name, retryable=False
            )
        entry = self.script[min(self.calls - 1 - self.fail_first, len(self.script) - 1)]
        if isinstance(entry, dict) and entry.get("tool_calls"):
            return ChatResponse(
                id=f"fake-{self.calls}",
                provider=self.name,
                model=request.model or self.DEFAULT_MODEL,
                content=entry.get("content"),
                tool_calls=entry["tool_calls"],
                usage=Usage(20, 10),
                finish_reason="tool_calls",
            )
        text = entry if isinstance(entry, str) else str(entry)
        return ChatResponse(
            id=f"fake-{self.calls}",
            provider=self.name,
            model=request.model or self.DEFAULT_MODEL,
            content=text,
            usage=Usage(20, 10),
        )

    async def astream(self, request: ChatRequest):
        response = await self.acomplete(request)
        for word in (response.text or "").split(" "):
            if word:
                yield StreamEvent("text", {"text": word + " "})
        yield StreamEvent("usage", {"usage": {"prompt_tokens": 20, "completion_tokens": 10}})
        yield StreamEvent("done", {"finish_reason": "stop"})

    def catalog(self):
        return list(self._catalog)

    def find_model(self, model_id: str):
        for info in self._catalog:
            if info.id == model_id:
                return info
        return None
