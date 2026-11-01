"""MCP client: spawn and drive MCP servers over stdio.

Any MCP tool — filesystem access, search, databases, browsers — becomes a
first-class ZYKO tool, usable by agents and by the router's tool-calling
requests. This is what "MCP-first" means in practice: ZYKO both *consumes*
MCP servers (as a client) and *is* one (``zyko mcp serve``).
"""

from __future__ import annotations

import asyncio
import itertools
import os
import time
from typing import Any

from zyko.exceptions import MCPError, ZykoTimeoutError
from zyko.log import get_logger
from zyko.mcp import protocol
from zyko.version import PROTOCOL_VERSION, __version__

log = get_logger("mcp")

_ids = itertools.count(1)


class MCPClient:
    """Async MCP client bound to one spawned server process."""

    def __init__(
        self,
        name: str,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        request_timeout: float = 20.0,
    ) -> None:
        if not command:
            raise MCPError(f"MCP server '{name}' has an empty command")
        self.name = name
        self.command = [str(part) for part in command]
        self.env = env
        self.cwd = cwd
        self.request_timeout = request_timeout
        self._process: asyncio.subprocess.Process | None = None
        self._pending: dict[int | str, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._server_info: dict[str, Any] = {}
        self._tools: list[dict[str, Any]] = []
        self._started = False

    # ------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        if self._started:
            return
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **(self.env or {})},
                cwd=self.cwd,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise MCPError(
                f"cannot spawn MCP server '{self.name}' ({self.command[0]}): {exc}",
                hint="install the server executable or fix the command in the agent/config file",
            ) from exc
        self._reader_task = asyncio.create_task(self._pump_stdout())
        handshake = await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "zyko", "version": __version__},
            },
        )
        self._server_info = handshake.get("serverInfo") or {}
        await self._notify("notifications/initialized")
        self._started = True
        log.info("mcp server '%s' ready (%s)", self.name, self._server_info.get("name", "?"))

    async def _pump_stdout(self) -> None:
        assert self._process and self._process.stdout
        async for raw in self._process.stdout:
            raw = raw.strip()
            if not raw:
                continue
            try:
                message = protocol.decode(raw)
            except MCPError as exc:
                log.warning("mcp '%s': %s", self.name, exc)
                continue
            msg_id = message.get("id")
            if msg_id in self._pending:
                fut = self._pending.pop(msg_id)
                if not fut.done():
                    if "error" in message:
                        err = message["error"]
                        fut.set_exception(
                            MCPError(f"mcp '{self.name}' error {err.get('code')}: {err.get('message')}")
                        )
                    else:
                        fut.set_result(message.get("result"))
            # notifications/requests from server: ignored for now (logged)
        # stdout closed: fail anything still pending
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(MCPError(f"mcp server '{self.name}' closed the stream"))
        self._pending.clear()

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        assert self._process and self._process.stdin
        self._process.stdin.write(protocol.encode(protocol.notification(method, params)))
        await self._process.stdin.drain()

    async def _request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if not self._process:
            raise MCPError(f"mcp server '{self.name}' not started")
        msg_id = next(_ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        assert self._process.stdin
        self._process.stdin.write(protocol.encode(protocol.request(msg_id, method, params)))
        await self._process.stdin.drain()
        try:
            return await asyncio.wait_for(fut, timeout=self.request_timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(msg_id, None)
            raise ZykoTimeoutError(
                f"mcp '{self.name}': no response to '{method}' within {self.request_timeout}s"
            ) from exc

    # ----------------------------------------------------------------- tools
    async def list_tools(self) -> list[dict[str, Any]]:
        """All tools exposed by the server, in ZYKO's generic schema."""
        if self._tools:
            return self._tools
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {} if cursor is None else {"cursor": cursor}
            page = await self._request("tools/list", params)
            for tool in page.get("tools") or []:
                out.append(
                    {
                        "name": tool.get("name") or "",
                        "description": tool.get("description") or "",
                        "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
                    }
                )
            cursor = page.get("nextCursor")
            if not cursor:
                break
        self._tools = out
        return out

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        started = time.perf_counter()
        page = await self._request("tools/call", {"name": name, "arguments": arguments or {}})
        elapsed = (time.perf_counter() - started) * 1000.0
        result = page.get("content") or []
        text = "\n".join(
            part.get("text") or "" for part in result if isinstance(part, dict) and part.get("type") == "text"
        )
        if page.get("isError"):
            raise MCPError(f"mcp '{self.name}' tool '{name}' failed: {text[:300]}")
        log.debug("mcp '%s' tool %s ok (%.0f ms, %d chars)", self.name, name, elapsed, len(text))
        return text

    def as_tools(self, tools: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """Expose cached tools to agents/providers, namespaced by server name."""
        return [
            {
                "name": f"{self.name}__{tool['name']}",
                "description": tool.get("description") or f"tool {tool['name']} from MCP server {self.name}",
                "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
            }
            for tool in (tools if tools is not None else self._tools)
        ]

    @staticmethod
    def split_qualified(name: str) -> tuple[str, str] | None:
        """``server__tool`` → (server, tool); None when not namespaced."""
        if "__" in name:
            server, _, tool = name.partition("__")
            return server, tool
        return None

    # ------------------------------------------------------------------ info
    @property
    def server_info(self) -> dict[str, Any]:
        return dict(self._server_info)

    async def aclose(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=3.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                self._process.kill()
        self._started = False

    # sync conveniences ------------------------------------------------------
    def start_sync(self) -> "MCPClient":
        from zyko.utils.loop import run_sync

        run_sync(self.start())
        return self

    def list_tools_sync(self) -> list[dict[str, Any]]:
        from zyko.utils.loop import run_sync

        return run_sync(self.list_tools())

    def call_tool_sync(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        from zyko.utils.loop import run_sync

        return run_sync(self.call_tool(name, arguments))

    def close_sync(self) -> None:
        from zyko.utils.loop import run_sync

        run_sync(self.aclose())
