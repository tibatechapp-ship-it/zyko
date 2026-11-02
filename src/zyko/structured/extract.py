"""Extract a JSON value from free-form model text.

Models routinely wrap JSON in prose ("Here is the JSON you asked for:"),
markdown fences, or reasoning blocks (DeepSeek's ``<think>…</think>``).
Structured output must survive all of it — LangChain solves this with a
whole parser ecosystem; ZYKO ships one well-tested function.
"""

from __future__ import annotations

import json
from typing import Any

_FENCE = "```"


def _strip_reasoning(text: str) -> str:
    """Drop ``<think>…</think>`` / ``<thinking>…</thinking>`` blocks."""
    for tag in ("think", "thinking"):
        while True:
            start = text.find(f"<{tag}>")
            if start == -1:
                break
            end = text.find(f"</{tag}>", start)
            text = text[:start] + text[end + len(tag) + 3 :] if end != -1 else text[:start]
    return text


def _candidates(text: str) -> list[str]:
    """Yield plausible JSON payloads from ``text``, most-direct first."""
    stripped = text.strip()
    if stripped:
        yield stripped
        # markdown fences: prefer ```json blocks, then any ``` block
        for fence in ("```json", _FENCE):
            start = 0
            while True:
                begin = text.find(fence, start)
                if begin == -1:
                    break
                open_end = text.find("\n", begin)
                close = text.find(_FENCE, open_end if open_end != -1 else begin + len(fence))
                if open_end != -1 and close != -1:
                    yield text[open_end + 1 : close].strip()
                    start = close + len(_FENCE)
                else:
                    break
    # first balanced {…} / […] scan, string-aware
    depth = 0
    start = -1
    in_string = False
    escaped = False
    closer = ""
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            if depth == 0:
                start = index
                closer = "}" if char == "{" else "]"
            depth += 1
        elif char in "}]":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1 and char == closer:
                    yield text[start : index + 1]
                    start = -1


def extract_json(text: str | None) -> Any | None:
    """Return the first JSON value found in ``text``, or ``None``.

    Order of attempts: the whole (reasoning-stripped, trimmed) text, then
    markdown-fenced blocks, then the first balanced ``{…}``/``[…]`` span.
    Values that parse but are not JSON (NaN via ``json.loads``) are accepted
    as-is; the schema validator rejects them downstream.
    """
    if not text:
        return None
    cleaned = _strip_reasoning(text)
    for candidate in _candidates(cleaned):
        try:
            return json.loads(candidate)
        except (ValueError, TypeError):
            continue
    return None


__all__ = ["extract_json"]
