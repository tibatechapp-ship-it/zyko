"""ZYKO Gateway — an OpenAI-compatible HTTP server on the Python stdlib.

``zyko serve`` turns any machine — including an Android phone running
Termux — into a local OpenAI-compatible inference gateway:

    POST /v1/chat/completions   (stream and non-stream)
    GET  /v1/models
    GET  /healthz

Only ``http.server`` + ``json`` are used, so there is nothing to compile and
nothing to install beyond ZYKO itself. Responses carry a ``zyko.receipt``
object: the verifiable routing decision (ranking, policy, attempts) that
produced the answer.
"""

from __future__ import annotations

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from zyko.core import tools as toolconv
from zyko.core.messages import Message
from zyko.core.response import ChatRequest
from zyko.exceptions import ZykoError
from zyko.gateway.auth import GatewayUser, UserStore
from zyko.log import get_logger
from zyko.utils.loop import SHARED_LOOP

log = get_logger("gateway")


def _openai_messages(payload: dict[str, Any]) -> list[Message]:
    messages: list[Message] = []
    for raw in payload.get("messages") or []:
        role = raw.get("role", "user")
        tool_calls = None
        if raw.get("tool_calls"):
            from zyko.core.messages import ToolCall

            tool_calls = [ToolCall.from_openai(tc) for tc in raw["tool_calls"]]
        messages.append(
            Message(
                role=role,
                content=raw.get("content"),
                tool_calls=tool_calls,
                tool_call_id=raw.get("tool_call_id"),
                name=raw.get("name"),
            )
        )
    return messages


def _response_to_openai(response: Any, receipt: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": response.id,
        "object": "chat.completion",
        "created": int(response.raw.get("created", 0))
        if isinstance(response.raw, dict) and response.raw.get("created")
        else 0,
        "model": response.model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response.content,
                    **(
                        {"tool_calls": [tc.to_openai() for tc in response.tool_calls]}
                        if response.tool_calls
                        else {}
                    ),
                },
                "finish_reason": response.finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        },
        "zyko": {"provider": response.provider, "receipt": receipt},
    }
    return body


class _Handler(BaseHTTPRequestHandler):
    router: Any = None
    api_key: str | None = None
    users: UserStore | None = None  # 0.7.0: multi-user identity + governance
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- plumbing
    def log_message(self, fmt: str, *args: Any) -> None:  # silence default noise
        log.debug("gateway: " + fmt, *args)

    def _authenticate(self) -> tuple[str | GatewayUser | None, bool]:
        """Resolve the caller identity; returns ``(identity, ok)``.

        ``identity`` is a :class:`GatewayUser` (users store), ``"api-key"``
        (legacy single token) or ``"anonymous"`` (open gateway). On failure
        the response is already written and ``ok`` is False. Comparisons are
        constant-time in every mode.
        """
        if self.users is not None:
            header = self.headers.get("Authorization", "")
            token = header[7:].strip() if header.startswith("Bearer ") else ""
            user = self.users.authenticate(token) if token else None
            if user is None:
                self._error(401, "invalid or missing bearer token")
                return None, False
            if not user.enabled:
                self._error(403, f"user '{user.name}' is disabled")
                return None, False
            if not ("chat" in user.roles or "admin" in user.roles):
                self._error(403, f"user '{user.name}' lacks a usable role")
                return None, False
            if not self.users.check_rate(user):
                self._error(
                    429,
                    f"user '{user.name}' exceeded rpm={user.rpm}",
                    err_type="zyko_rate_limit",
                )
                return None, False
            if not self.users.within_budget(user):
                self._error(
                    429,
                    f"user '{user.name}' exceeded daily_budget_usd={user.daily_budget_usd}",
                    err_type="zyko_budget_exceeded",
                )
                return None, False
            return user, True
        if self.api_key:
            header = self.headers.get("Authorization", "")
            if not hmac.compare_digest(header.encode(), f"Bearer {self.api_key}".encode()):
                self._error(401, "invalid or missing bearer token")
                return None, False
            return "api-key", True
        return "anonymous", True

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: int, message: str, err_type: str = "zyko_error") -> None:
        self._json(status, {"error": {"message": message, "type": err_type}})

    # -------------------------------------------------------------- routes
    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        identity, ok = self._authenticate()
        if not ok:
            return
        path = self.path.split("?")[0]
        if path == "/healthz":
            return self._json(200, {"status": "ok", "server": "zyko-gateway"})
        if path == "/v1/users/me":
            if not isinstance(identity, GatewayUser):
                return self._error(404, "/v1/users/me requires a users store")
            usage = self.users.ledger.today(identity.name)
            return self._json(
                200,
                {
                    "object": "user",
                    "user": identity.public(),
                    "usage_today": {
                        "requests": usage.get("requests", 0),
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "spend_usd": usage.get("spend_usd", 0.0),
                    },
                    "budget_remaining_usd": self.users.budget_left(identity),
                },
            )
        if path == "/v1/models":
            models = []
            for cand, breakdown in self.router.rank():
                models.append(
                    {
                        "id": cand.key,
                        "object": "model",
                        "owned_by": cand.provider,
                        "zyko_score": round(breakdown.total, 4),
                    }
                )
            return self._json(200, {"object": "list", "data": models})
        return self._error(404, f"no route: {path}")

    def do_POST(self) -> None:  # noqa: N802
        # Drain the request body BEFORE any early error return: with HTTP/1.1
        # keep-alive, an unread body would be parsed as the next request line
        # and corrupt the connection (classic 501-on-reuse failure).
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length > 0 else b""
        except (ValueError, OSError):
            body = b""
        identity, ok = self._authenticate()
        if not ok:
            return
        path = self.path.split("?")[0]
        if path != "/v1/chat/completions":
            return self._error(404, f"no route: {path}")
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return self._error(400, "request body is not valid JSON")
        try:
            response_format = payload.get("response_format")
            if response_format is not None and not isinstance(response_format, dict):
                return self._error(400, "response_format must be an object")
            request = ChatRequest(
                messages=_openai_messages(payload),
                model=payload.get("model") or "auto",
                temperature=payload.get("temperature"),
                max_tokens=payload.get("max_tokens"),
                tools=toolconv.generic_from_openai(payload.get("tools")),
                tool_choice=payload.get("tool_choice"),
                response_format=response_format,
            )
        except Exception as exc:
            return self._error(400, f"bad request: {exc}")

        stream = bool(payload.get("stream"))
        try:
            if stream:
                return self._stream_response(request, identity)
            outcome = SHARED_LOOP.run(self.router.aroute(request))
            assert outcome.response is not None
            if isinstance(identity, GatewayUser):
                outcome.receipt["user"] = identity.name
                self._record_usage(identity, outcome.receipt, outcome.response)
            return self._json(200, _response_to_openai(outcome.response, outcome.receipt))
        except ZykoError as exc:
            return self._error(502, str(exc), err_type="zyko_upstream_error")
        except Exception as exc:  # noqa: BLE001
            log.exception("gateway failure")
            return self._error(500, f"internal error: {exc}")

    def _record_usage(self, user: GatewayUser, receipt: dict[str, Any], response: Any) -> None:
        """Persist per-user usage; estimated cost from the chosen candidate."""
        assert self.users is not None
        est = (receipt.get("score_components") or {}).get("estimated_cost_usd")
        self.users.record_usage(
            user,
            cost_usd=float(est) if est else 0.0,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    def _stream_response(self, request: ChatRequest, identity: str | GatewayUser) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def send_chunk(data: bytes) -> None:
            self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
            self.wfile.flush()

        try:
            stream_est_cost = 0.0
            final_usage_raw: dict[str, Any] | None = None
            for event in self.router.stream_route(request):
                if event.type == "meta":
                    if isinstance(identity, GatewayUser):
                        receipt = event.data["receipt"] or {}
                        receipt["user"] = identity.name
                        est = (receipt.get("score_components") or {}).get("estimated_cost_usd")
                        stream_est_cost = float(est) if est else 0.0
                    payload = {
                        "id": "stream",
                        "object": "chat.completion.chunk",
                        "model": event.data["candidate"],
                        "choices": [
                            {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
                        ],
                        "zyko_receipt": event.data["receipt"],
                    }
                elif event.type == "text":
                    payload = {
                        "id": "stream",
                        "object": "chat.completion.chunk",
                        "model": request.model or "auto",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": event.data["text"]},
                                "finish_reason": None,
                            }
                        ],
                    }
                elif event.type == "usage":
                    final_usage_raw = event.data.get("usage")
                    continue
                elif event.type == "done":
                    payload = {
                        "id": "stream",
                        "object": "chat.completion.chunk",
                        "model": request.model or "auto",
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    }
                else:
                    continue
                send_chunk(
                    b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n\n"
                )
            if isinstance(identity, GatewayUser):
                usage = None
                try:
                    from zyko.providers.base import usage_from_raw

                    usage = usage_from_raw(final_usage_raw) if final_usage_raw else None
                except Exception:  # noqa: BLE001 - usage accounting never breaks the stream
                    usage = None
                assert self.users is not None
                self.users.record_usage(
                    identity,
                    cost_usd=stream_est_cost,
                    input_tokens=usage.input_tokens if usage else 0,
                    output_tokens=usage.output_tokens if usage else 0,
                )
            send_chunk(b"data: [DONE]\n\n")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def serve(
    router: Any,
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    api_key: str | None = None,
    users: UserStore | None = None,
) -> ThreadingHTTPServer:
    """Create, start and return a running gateway server.

    Auth modes, most to least governed: ``users`` (multi-user identities,
    per-user RPM + daily budgets, receipts carry the user name), ``api_key``
    (single legacy bearer token), or open (development only).
    """

    class BoundHandler(_Handler):
        pass

    BoundHandler.router = router
    BoundHandler.api_key = api_key
    BoundHandler.users = users
    httpd = ThreadingHTTPServer((host, port), BoundHandler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, name="zyko-gateway", daemon=True)
    thread.start()
    log.info("gateway listening on http://%s:%d", host, port)
    return httpd
