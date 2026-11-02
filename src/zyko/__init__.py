"""ZYKO — Universal AI Orchestration Platform.

Multi-provider routing with verifiable decisions, Policy-as-Code governance,
MCP-native agents. Pure Python core; runs on Linux, Windows, macOS, Android
and Termux.
"""

from zyko.client import RouteResult, StructuredResult, Zyko
from zyko.core.messages import Message
from zyko.core.response import ChatRequest, ChatResponse
from zyko.exceptions import (
    SchemaSpecError,
    StructuredOutputError,
    ZykoError,
)
from zyko.structured import extract_json, validate_against_schema
from zyko.version import PROTOCOL_VERSION, __version__

__all__ = [
    "Zyko",
    "RouteResult",
    "StructuredResult",
    "Message",
    "ChatRequest",
    "ChatResponse",
    "ZykoError",
    "SchemaSpecError",
    "StructuredOutputError",
    "extract_json",
    "validate_against_schema",
    "__version__",
    "PROTOCOL_VERSION",
]
