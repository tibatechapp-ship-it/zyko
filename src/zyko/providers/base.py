"""Provider adapter base class.

Implements everything vendors share — retries with exponential backoff,
per-event-loop ``httpx`` client reuse, timeout mapping, HTTP error mapping,
SSE/NDJSON streaming — while each concrete adapter only describes request
building and payload parsing.
"""

from __future__ import annotations

import asyncio
import random
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Iterator

import httpx

from zyko.core.events import StreamEvent, accumulate_stream, sse_data_events
from zyko.core.messages import ToolCall, messages_to_openai  # noqa: F401 (re-exported convenience)
from zyko.core.models import ModelInfo
from zyko.core.response import ChatRequest, ChatResponse
from zyko.exceptions import AuthError, ProviderError, RateLimitError, ZykoTimeoutError
from zyko.log import get_logger
from zyko.utils.loop import SHARED_LOOP

log = get_logger("providers")

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


class BaseProvider(ABC):
    """Contract every provider adapter fulfils."""

    name: str = "base"
    DEFAULT_BASE_URL: str = ""
    DEFAULT_MODEL: str | None = None
    KEY_ENV: str | tuple[str, ...] | None = None
    local: bool = False  # local providers (ollama) need no API key
    CATALOG: list[ModelInfo] = []
    # Only set True after confirming the vendor accepts OpenAI's
    # ``stream_options: {"include_usage": true}`` — wrong flags can 400.
    # Enables vendor-reported usage in streams, which the router uses to
    # charge the policy budget with *real* token counts instead of estimates.
    STREAM_INCLUDE_USAGE: bool = False
    _stream_protocol: str = "sse"  # or "ndjson" (ollama)

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self._transport = transport
        self._default_headers = default_headers or {}
        self._clients: dict[asyncio.AbstractEventLoop, httpx.AsyncClient] = {}

    # ------------------------------------------------------------------ client
    def _client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        client = self._clients.get(loop)
        if client is None:
            client = httpx.AsyncClient(
                timeout=self.timeout, transport=self._transport, headers=self._default_headers
            )
            self._clients[loop] = client
        return client

    async def aclose(self) -> None:
        for client in list(self._clients.values()):
            await client.aclose()
        self._clients.clear()

    # ----------------------------------------------------------------- request
    @abstractmethod
    def _build(
        self, request: ChatRequest, *, stream: bool
    ) -> tuple[str, dict[str, Any], dict[str, str]]:
        """Return ``(url, payload, extra_headers)`` for the vendor API."""

    @abstractmethod
    def _parse_response(self, data: dict[str, Any], request: ChatRequest) -> ChatResponse:
        """Convert a non-streaming vendor payload to a :class:`ChatResponse`."""

    def _parse_stream_chunk(
        self, data: dict[str, Any], state: dict[str, Any]
    ) -> StreamEvent | None:
        return None  # adapters with streaming override this

    def _resolve_model(self, request: ChatRequest) -> str:
        model = request.model
        if not model or model == "auto" or "/" in model:
            # "provider/model" routing: strip the prefix when it matches us
            if model and "/" in model:
                _, _, suffix = model.partition("/")
                if suffix:
                    return suffix
            if not self.DEFAULT_MODEL:
                raise ProviderError(
                    "no model specified and provider has no default",
                    provider=self.name,
                    hint="pass model=<id> or configure a default_model",
                )
            return self.DEFAULT_MODEL
        return model

    # ------------------------------------------------------------------- send
    async def acomplete(self, request: ChatRequest, *, retries: int | None = None) -> ChatResponse:
        attempts = self.retries if retries is None else retries
        attempt = 0
        while True:
            try:
                started = time.perf_counter()
                response = await self._send(request)
                response.latency_ms = (time.perf_counter() - started) * 1000.0
                return response
            except ProviderError as exc:
                if not exc.retryable or attempt >= attempts:
                    raise
                retry_after = getattr(exc, "retry_after", None)
                if retry_after is not None and float(retry_after) > 0:
                    # The vendor told us exactly when to come back (HTTP 429
                    # with Retry-After) — honor it instead of our own curve.
                    delay = min(max(float(retry_after), 0.05), 30.0)
                else:
                    delay = min(0.5 * (2**attempt), 8.0) * (0.5 + random.random() / 2)
                log.warning(
                    "%s: retryable error (status=%s), retry %d/%d in %.1fs: %s",
                    self.name,
                    exc.status,
                    attempt + 1,
                    attempts,
                    delay,
                    exc,
                )
                attempt += 1
                await asyncio.sleep(delay)

    async def _send(self, request: ChatRequest) -> ChatResponse:
        url, payload, headers = self._build(request, stream=False)
        client = self._client()
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ZykoTimeoutError(
                f"{self.name}: request timed out after {self.timeout}s",
                hint="raise router.request_timeout_s in the config",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"{self.name}: network error: {exc}", provider=self.name, retryable=True
            ) from exc
        if resp.status_code >= 400:
            self._raise_for_status(resp)
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(
                f"{self.name}: invalid JSON in response", provider=self.name, retryable=True
            ) from exc
        return self._parse_response(data, request)

    async def astream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        url, payload, headers = self._build(request, stream=True)
        client = self._client()
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread())[:500]
                self._raise_for_status(resp, body=body.decode("utf-8", "replace"))
            state: dict[str, Any] = {}
            if self._stream_protocol == "ndjson":
                async for data in self._iter_ndjson(resp):
                    ev = self._parse_stream_chunk(data, state)
                    if ev:
                        yield ev
            else:
                async for data in sse_data_events(resp.aiter_bytes()):
                    ev = self._parse_stream_chunk(data, state)
                    if ev:
                        yield ev

    async def _iter_ndjson(self, resp: httpx.Response) -> AsyncIterator[dict[str, Any]]:
        import json as _json

        buf = b""
        async for chunk in resp.aiter_bytes():
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if line:
                    try:
                        yield _json.loads(line)
                    except _json.JSONDecodeError:
                        continue
        if buf.strip():
            try:
                yield _json.loads(buf)
            except _json.JSONDecodeError:
                pass

    def _raise_for_status(self, resp: httpx.Response, *, body: str | None = None) -> None:
        if body is None:
            body = ""
        snippet = (body or resp.text or "")[:300]
        status = resp.status_code
        if status == 429:
            raise RateLimitError(
                f"{self.name}: HTTP 429: {snippet or resp.reason_phrase}",
                provider=self.name,
                status=status,
                retryable=True,
                hint="the retry loop honors the vendor's Retry-After automatically",
                retry_after=_retry_after_seconds(resp),
            )
        hint = None
        if status in (401, 403):
            exc: type[ProviderError] = AuthError
            hint = "check the API key for this provider"
        elif status in RETRYABLE_STATUS:
            exc = ProviderError
        else:
            exc = ProviderError
            hint = "inspect the request payload; see provider docs"
        raise exc(
            f"{self.name}: HTTP {status}: {snippet or resp.reason_phrase}",
            provider=self.name,
            status=status,
            retryable=status in RETRYABLE_STATUS,
            hint=hint,
        )

    # -------------------------------------------------------------- sync API
    def complete(self, request: ChatRequest) -> ChatResponse:
        return SHARED_LOOP.run(self.acomplete(request))

    def stream(self, request: ChatRequest) -> Iterator[StreamEvent]:
        return SHARED_LOOP.iterate(self.astream(request))

    async def astream_collect(self, request: ChatRequest) -> ChatResponse:
        """Convenience: run a streaming request and materialise the response."""
        text, tool_accs, usage = await accumulate_stream(self.astream(request))
        tool_calls = [
            ToolCall(
                id=acc["id"] or f"call_{i}",
                name=acc["name"],
                arguments=_safe_json(acc["arguments"]),
            )
            for i, acc in enumerate(tool_accs)
        ]
        started = time.perf_counter()
        return ChatResponse(
            id="stream",
            provider=self.name,
            model=self._resolve_model(request),
            content=text or None,
            tool_calls=tool_calls,
            usage=_usage_from(usage),
            finish_reason="tool_calls" if tool_calls else "stop",
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    # --------------------------------------------------------------- catalog
    def catalog(self) -> list[ModelInfo]:
        return list(self.CATALOG)

    def find_model(self, model_id: str) -> ModelInfo | None:
        for info in self.catalog():
            if info.id == model_id:
                return info
        return None


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """Parse the HTTP ``Retry-After`` header (delay-seconds or HTTP-date)."""
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_json(raw: str) -> dict[str, Any]:
    import json

    try:
        value = json.loads(raw) if raw else {}
        return value if isinstance(value, dict) else {"_raw": raw}
    except json.JSONDecodeError:
        return {"_raw": raw}


def _usage_from(data: dict[str, Any] | None) -> Any:
    from zyko.core.response import Usage

    if not data:
        return Usage()
    return Usage(
        input_tokens=int(
            data.get("input_tokens")
            or data.get("prompt_tokens")
            or data.get("prompt_eval_count")
            or 0
        ),
        output_tokens=int(
            data.get("output_tokens")
            or data.get("completion_tokens")
            or data.get("eval_count")
            or 0
        ),
    )


usage_from_raw = _usage_from  # public alias — the router reads stream usage through it
