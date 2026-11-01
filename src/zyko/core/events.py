"""Streaming primitives shared by every provider adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class StreamEvent:
    """A single streaming delta.

    Types: ``text`` (data.text), ``tool_call`` (data carries index/id/name and
    ``args_delta``), ``usage`` (data.usage), ``done`` (data.finish_reason).
    """

    type: str
    data: dict[str, Any] = field(default_factory=dict)


def text_event(text: str) -> StreamEvent:
    return StreamEvent("text", {"text": text})


def done_event(finish_reason: str = "stop") -> StreamEvent:
    return StreamEvent("done", {"finish_reason": finish_reason})


async def accumulate_stream(
    events: AsyncIterator[StreamEvent],
) -> tuple[str, list[dict[str, Any]], Any]:
    """Consume a stream and return ``(text, tool_call_accumulators, usage)``.

    Tool call accumulators are dicts keyed by provider index:
    ``{"id", "name", "arguments"}`` — arguments merged from ``args_delta``.
    """
    text_parts: list[str] = []
    tools: dict[int, dict[str, Any]] = {}
    usage: Any = None
    async for ev in events:
        if ev.type == "text":
            text_parts.append(ev.data.get("text") or "")
        elif ev.type == "tool_call":
            idx = int(ev.data.get("index", 0))
            acc = tools.setdefault(idx, {"id": "", "name": "", "arguments": ""})
            acc["id"] = acc["id"] or ev.data.get("id") or ""
            acc["name"] = acc["name"] or ev.data.get("name") or ""
            acc["arguments"] += ev.data.get("args_delta") or ""
        elif ev.type == "usage":
            usage = ev.data.get("usage")
    return "".join(text_parts), [tools[k] for k in sorted(tools)], usage


async def sse_data_events(byte_iter: AsyncIterator[bytes]) -> AsyncIterator[dict[str, Any]]:
    """Parse an SSE byte stream into JSON ``data:`` payloads.

    Handles partial lines, CRLF, and the OpenAI ``[DONE]`` sentinel. Events
    that are not JSON (keep-alive comments, empty lines) are skipped.
    """
    buf = b""
    async for chunk in byte_iter:
        buf += chunk
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            payload = _extract_data(raw)
            if payload is None:
                continue
            if payload == "[DONE]":
                return
            try:
                yield json.loads(payload)
            except json.JSONDecodeError:
                continue
    # flush a trailing line without newline
    payload = _extract_data(buf)
    if payload and payload != "[DONE]":
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            pass


def _extract_data(raw: bytes) -> str | None:
    line = raw.decode("utf-8", "replace").rstrip("\r")
    if not line.startswith("data:"):
        return None
    return line[5:].strip()
