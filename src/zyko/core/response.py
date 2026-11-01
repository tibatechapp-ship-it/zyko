"""Request/response contracts for the unified completion interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from zyko.core.messages import Message, ToolCall
from zyko.core.models import ModelInfo


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def merged(self, other: "Usage | None") -> "Usage":
        if not other:
            return self
        return Usage(
            input_tokens=self.input_tokens + (other.input_tokens or 0),
            output_tokens=self.output_tokens + (other.output_tokens or 0),
        )

    def cost_usd(self, model: ModelInfo | None) -> float | None:
        return model.cost_usd(self.input_tokens, self.output_tokens) if model else None


@dataclass
class ChatRequest:
    """A provider-neutral completion request."""

    messages: list[Message] = field(default_factory=list)
    model: str | None = None  # None / "auto" → router picks
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None  # generic tool schema
    tool_choice: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_model(self, model: str) -> "ChatRequest":
        return ChatRequest(
            messages=self.messages,
            model=model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            tools=self.tools,
            tool_choice=self.tool_choice,
            metadata=self.metadata,
        )

    @property
    def text(self) -> str:
        return "\n".join(m.plain_text() for m in self.messages if m.content)


@dataclass
class ChatResponse:
    """A provider-neutral completion response."""

    id: str
    provider: str
    model: str
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    finish_reason: str = "stop"
    latency_ms: float = 0.0
    raw: Any = None

    @property
    def text(self) -> str:
        return self.content or ""


FINISH_ALIASES = {
    "stop": "stop",
    "end_turn": "stop",
    "tool_use": "tool_calls",
    "tool_calls": "tool_calls",
    "length": "length",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "content_filter": "content_filter",
}
