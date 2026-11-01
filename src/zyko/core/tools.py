"""Tool-schema conversion between ZYKO's generic format and provider formats.

ZYKO's internal tool format (the same one MCP uses for ``inputSchema``)::

    {"name": str, "description": str, "parameters": <JSON Schema object>}
"""

from __future__ import annotations

from typing import Any


def _schema(tool: dict[str, Any]) -> dict[str, Any]:
    params = tool.get("parameters") or tool.get("input_schema") or tool.get("inputSchema")
    if not isinstance(params, dict):
        params = {"type": "object", "properties": {}}
    return params


def to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description") or "",
                "parameters": _schema(t),
            },
        }
        for t in tools
    ]


def to_anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": t["name"],
            "description": t.get("description") or "",
            "input_schema": _schema(t),
        }
        for t in tools
    ]


def to_google_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "functionDeclarations": [
                {
                    "name": t["name"],
                    "description": t.get("description") or "",
                    "parameters": _schema(t),
                }
            ]
        }
        for t in tools
    ]


def generic_from_openai(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Convert OpenAI-style tools (as sent by gateway clients) to generic."""
    out: list[dict[str, Any]] = []
    for t in tools or []:
        fn = t.get("function") or t
        out.append(
            {
                "name": fn.get("name") or "",
                "description": fn.get("description") or "",
                "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return out
