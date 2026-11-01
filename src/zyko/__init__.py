"""ZYKO — Universal AI Orchestration Platform.

Multi-provider routing with verifiable decisions, Policy-as-Code governance,
MCP-native agents. Pure Python core; runs on Linux, Windows, macOS, Android
and Termux.
"""

from zyko.client import RouteResult, Zyko
from zyko.core.messages import Message
from zyko.core.response import ChatRequest, ChatResponse
from zyko.exceptions import ZykoError
from zyko.version import PROTOCOL_VERSION, __version__

__all__ = [
    "Zyko",
    "RouteResult",
    "Message",
    "ChatRequest",
    "ChatResponse",
    "ZykoError",
    "__version__",
    "PROTOCOL_VERSION",
]
