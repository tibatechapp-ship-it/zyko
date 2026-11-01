"""Core contracts: messages, models, requests/responses, streaming events."""

from zyko.core.events import StreamEvent, accumulate_stream, done_event, sse_data_events, text_event
from zyko.core.messages import (
    Message,
    Role,
    ToolCall,
    messages_to_anthropic,
    messages_to_google,
    messages_to_openai,
)
from zyko.core.models import ModelInfo
from zyko.core.response import ChatRequest, ChatResponse, Usage

__all__ = [
    "Message",
    "Role",
    "ToolCall",
    "ModelInfo",
    "ChatRequest",
    "ChatResponse",
    "Usage",
    "StreamEvent",
    "text_event",
    "done_event",
    "accumulate_stream",
    "sse_data_events",
    "messages_to_openai",
    "messages_to_anthropic",
    "messages_to_google",
]
