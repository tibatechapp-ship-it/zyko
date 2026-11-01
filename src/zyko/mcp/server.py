"""ZYKO as an MCP server (`zyko mcp serve`).

Exposes ZYKO's capabilities — chat, verifiable routing, model discovery —
as MCP tools, so any MCP host (Claude Desktop, IDEs, other agents) can use
ZYKO as its model-routing backend. The protocol layer is stdlib-only and
async, so it runs identically on Linux, Windows, macOS and Termux.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from zyko.exceptions import ZykoError
from zyko.log import get_logger
from zyko.mcp import protocol
from zyko.version import PROTOCOL_VERSION, __version__

log = get_logger("mcp.server")

ZYKO_TOOLS: list[dict[str, Any]] = [
    {
        "name": "zyko_models",
        "description": "List AI models available to ZYKO across all configured providers.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "zyko_route",
        "description": "Explain how ZYKO would route a prompt: ranked candidates with quality/cost/latency scores (no API call).",
        "inputSchema": {
            "type": "object",
            "properties": {"prompt": {"type": "string", "description": "sample prompt to size the estimate"}},
            "required": [],
        },
    },
    {
        "name": "zyko_chat",
        "description": "Send a prompt through ZYKO's router (policy-checked, best candidate) and return the answer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "model": {"type": "string", "description": "optional provider/model override"},
            },
            "required": ["prompt"],
        },
    },
]


class ZykoMCPServer:
    """Stdio MCP server exposing ZYKO tools."""

    def __init__(self, *, router: Any = None) -> None:
        self._router = router
        self._router_built = router is not None

    # ------------------------------------------------------------- dispatch
    async def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        msg_id = message.get("id")
        if msg_id is None:
            return None  # notification: nothing to answer
        try:
            if method == "initialize":
                params = message.get("params") or {}
                requested = params.get("protocolVersion")
                return protocol.result(
                    msg_id,
                    {
                        "protocolVersion": requested if requested in (None, PROTOCOL_VERSION) else PROTOCOL_VERSION,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "zyko", "version": __version__},
                    },
                )
            if method == "ping":
                return protocol.result(msg_id, {})
            if method == "tools/list":
                return protocol.result(msg_id, {"tools": ZYKO_TOOLS})
            if method == "tools/call":
                params = message.get("params") or {}
                return protocol.result(msg_id, await self._call_tool(params.get("name") or "", params.get("arguments") or {}))
            return protocol.error(msg_id, protocol.METHOD_NOT_FOUND, f"unknown method: {method}")
        except ZykoError as exc:
            return protocol.result(msg_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
        except Exception as exc:  # noqa: BLE001 - surfaced to the host, never crashes the loop
            log.exception("mcp tool call failed")
            return protocol.result(msg_id, {"content": [{"type": "text", "text": f"internal error: {exc}"}], "isError": True})

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "zyko_models":
            text = self._models_text()
        elif name == "zyko_route":
            text = await self._route_text(arguments.get("prompt") or "")
        elif name == "zyko_chat":
            prompt = str(arguments.get("prompt") or "").strip()
            if not prompt:
                raise ZykoError("zyko_chat requires a non-empty 'prompt'")
            text = await self._chat_text(prompt, arguments.get("model"))
        else:
            return {
                "content": [{"type": "text", "text": f"unknown tool '{name}'"}],
                "isError": True,
            }
        return {"content": [{"type": "text", "text": text}], "isError": False}

    # --------------------------------------------------------------- backends
    def _ensure_router(self) -> Any:
        if not self._router_built:
            from zyko.config.settings import Settings
            from zyko.platform.paths import ledger_file
            from zyko.policy.engine import load_policy
            from zyko.providers import configured_providers
            from zyko.providers.mock import MockProvider, demo_enabled
            from zyko.router.engine import Router
            from zyko.router.quality import QualityLedger

            settings = Settings.load()
            if demo_enabled(settings):
                providers: dict[str, Any] = {"mock": MockProvider()}
            else:
                providers = configured_providers(settings.provider_settings)
            if not providers:
                # Keyless host: same keyless-first-run behaviour as the CLI.
                providers = {"mock": MockProvider()}
            # Same governance as the CLI: default_policy, ledger, demo mode.
            policy = None
            policy_name = settings.get("default_policy")
            if policy_name:
                policy = load_policy(policy_name)
            self._router = Router(
                providers,
                ledger=QualityLedger.load(ledger_file()),
                policy=policy,
                strategy=settings.get("router.strategy", "balanced"),
                max_fallbacks=settings.get("router.max_fallbacks", 3),
            )
            self._router_built = True
        return self._router

    def _models_text(self) -> str:
        """List the models the router can actually use (policy-filtered)."""
        router = self._ensure_router()
        lines: list[str] = []
        for provider_name in sorted(router.providers):
            provider = router.providers[provider_name]
            for info in provider.catalog():
                price = (
                    "free"
                    if info.local
                    else (
                        f"${info.input_price_per_mtok}/${info.output_price_per_mtok} per Mtok"
                        if info.input_price_per_mtok is not None
                        else "n/a"
                    )
                )
                lines.append(f"{info.qualified:50} ctx={info.context_window:>8} {price}")
        return "\n".join(lines) or "(no models)"

    async def _route_text(self, prompt: str) -> str:
        from zyko import kernel

        router = self._ensure_router()
        est_in = max(kernel.estimate_tokens(prompt), 16)
        explanation = router.explain(est_input_tokens=est_in)
        lines = [f"strategy: {explanation['strategy']}"]
        for i, entry in enumerate(explanation["ranking"][:10], 1):
            lines.append(
                f"{i:2}. {entry['candidate']:44} score={entry['total']:.3f} "
                f"(q={entry['quality']:.2f} c={entry['cost_score']:.2f} l={entry['latency_score']:.2f})"
            )
        return "\n".join(lines)

    async def _chat_text(self, prompt: str, model: str | None) -> str:
        from zyko.core.messages import Message
        from zyko.core.response import ChatRequest

        router = self._ensure_router()
        request = ChatRequest(messages=[Message.user(prompt)], model=model)
        outcome = await router.aroute(request)
        assert outcome.response is not None
        receipt = outcome.receipt
        return (
            f"{outcome.response.text}\n\n"
            f"---\nrouted via {receipt['chosen']} (strategy={receipt['strategy']}, "
            f"attempts={len(receipt['attempts'])})"
        )

    # ------------------------------------------------------------------ loop
    async def serve(self, *, stdin=None, stdout=None) -> None:
        stdin = stdin or sys.stdin.buffer
        stdout = stdout or sys.stdout.buffer

        async def byte_iter():
            while True:
                line = await asyncio.to_thread(stdin.readline)
                if not line:
                    return
                yield line

        async for raw in _lines(byte_iter()):
            if isinstance(raw, bytes):
                # Undecodable frame: answer per JSON-RPC 2.0 spec (parse error,
                # id null) and keep serving — a bad line must not kill the host.
                response = protocol.error(None, protocol.PARSE_ERROR, "invalid JSON-RPC frame")
            else:
                message = raw
                response = await self.handle(message)
            if response is not None:
                stdout.write(protocol.encode(response))
                await asyncio.to_thread(stdout.flush)


async def _lines(byte_iter):
    buf = b""
    async for chunk in byte_iter:
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line.strip():
                try:
                    yield protocol.decode(line)
                except ZykoError as exc:
                    log.warning("mcp server dropped undecodable frame: %s", exc)
                    yield b"__undecodable__"


def main() -> int:
    """Console entrypoint for `zyko mcp serve`."""
    server = ZykoMCPServer()
    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
