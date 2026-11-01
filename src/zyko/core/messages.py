"""Unified message and model interface — the ZYKO core contract.

Every provider adapter converts to/from these dataclasses, so routing,
policies, agents and the gateway are written once against a single format
and never touch vendor payloads again.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    """A tool invocation requested by a model."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_openai(cls, raw: dict[str, Any]) -> "ToolCall":
        fn = raw.get("function") or {}
        args_raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
        except json.JSONDecodeError:
            args = {"_raw": args_raw}
        return cls(id=raw.get("id") or "", name=fn.get("name") or "", arguments=args)

    def to_openai(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments or {})},
        }

    def to_anthropic(self) -> dict[str, Any]:
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.arguments or {}}

    def to_google(self) -> dict[str, Any]:
        return {"functionCall": {"name": self.name, "args": self.arguments or {}}}


@dataclass
class Message:
    """A single conversation message in provider-neutral form."""

    role: Role | str
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.role, str):
            self.role = Role(self.role)

    # -- convenience constructors -----------------------------------------
    @classmethod
    def system(cls, text: str) -> "Message":
        return cls(role=Role.SYSTEM, content=text)

    @classmethod
    def user(cls, text: str) -> "Message":
        return cls(role=Role.USER, content=text)

    @classmethod
    def assistant(
        cls, text: str | None = None, tool_calls: list[ToolCall] | None = None
    ) -> "Message":
        return cls(role=Role.ASSISTANT, content=text, tool_calls=tool_calls)

    @classmethod
    def tool_result(cls, tool_call_id: str, name: str, content: str) -> "Message":
        return cls(role=Role.TOOL, content=content, tool_call_id=tool_call_id, name=name)

    # -- conversions --------------------------------------------------------
    def to_openai(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": self.role.value}
        if self.content is not None:
            msg["content"] = self.content
        if self.tool_calls:
            msg["tool_calls"] = [tc.to_openai() for tc in self.tool_calls]
        if self.role is Role.TOOL:
            msg["tool_call_id"] = self.tool_call_id or ""
            msg["name"] = self.name or "tool"
        return msg

    def to_anthropic(self) -> dict[str, Any]:
        if self.role is Role.TOOL:
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": self.tool_call_id or "",
                        "content": self.content or "",
                    }
                ],
            }
        if self.role is Role.SYSTEM:
            return {"role": "user", "content": self.content or ""}  # hoisted by caller
        blocks: list[dict[str, Any]] = []
        if self.content:
            blocks.append({"type": "text", "text": self.content})
        for tc in self.tool_calls or []:
            blocks.append(tc.to_anthropic())
        return {"role": self.role.value, "content": blocks or [{"type": "text", "text": ""}]}

    def to_google(self) -> dict[str, Any]:
        if self.role is Role.TOOL:
            return {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "name": self.name or "tool",
                            "response": {"result": self.content or ""},
                        }
                    }
                ],
            }
        role = "model" if self.role in (Role.ASSISTANT,) else "user"
        parts: list[dict[str, Any]] = []
        if self.content:
            parts.append({"text": self.content})
        for tc in self.tool_calls or []:
            parts.append(tc.to_google())
        return {"role": role, "parts": parts}

    # -- helpers -------------------------------------------------------------
    def map_content(self, fn: Callable[[str], str]) -> "Message":
        return Message(
            role=self.role,
            content=fn(self.content) if self.content is not None else None,
            tool_calls=self.tool_calls,
            tool_call_id=self.tool_call_id,
            name=self.name,
        )

    def plain_text(self) -> str:
        return self.content or ""


def messages_to_openai(messages: list[Message]) -> list[dict[str, Any]]:
    return [m.to_openai() for m in messages]


def messages_to_anthropic(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    """Returns ``(system_text, messages)`` — the system prompt is hoisted out."""
    system_parts: list[str] = []
    rest: list[dict[str, Any]] = []
    for m in messages:
        if m.role is Role.SYSTEM:
            system_parts.append(m.content or "")
        else:
            rest.append(m.to_anthropic())
    return "\n".join(p for p in system_parts if p), rest


def messages_to_google(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    rest: list[dict[str, Any]] = []
    for m in messages:
        if m.role is Role.SYSTEM:
            system_parts.append(m.content or "")
        else:
            rest.append(m.to_google())
    return "\n".join(p for p in system_parts if p), rest
