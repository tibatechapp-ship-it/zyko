"""The agent loop: model + tools + policy, iterated until done.

A ZYKO agent is intentionally small and inspectable: a ReAct-style loop
where the model either answers or calls tools (builtin or MCP), every tool
result is appended verbatim to the transcript, and every step is recorded
into a trace for later auditing. Guards: max steps, per-tool timeout,
policy allow-list, workspace confinement, output caps.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from zyko import kernel
from zyko.agents.tools_builtin import BuiltinTool, builtin_tools
from zyko.core.messages import Message, ToolCall
from zyko.core.response import ChatRequest
from zyko.exceptions import PolicyViolation, ToolError, ZykoError
from zyko.log import get_logger
from zyko.mcp.client import MCPClient
from zyko.policy.engine import PolicyEngine
from zyko.router.engine import Router

log = get_logger("agents")

TOOL_TIMEOUT_S = 45.0


@dataclass
class AgentResult:
    output: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    usage_input_tokens: int = 0
    usage_output_tokens: int = 0
    truncated: bool = False
    elapsed_s: float = 0.0


class Agent:
    """One configured brain: router + tools + optional policy."""

    def __init__(
        self,
        router: Router,
        *,
        name: str = "agent",
        system: str | None = None,
        model: str | None = None,
        max_steps: int = 8,
        tools: list[str] | None = None,
        mcp_clients: list[MCPClient] | None = None,
        policy: PolicyEngine | None = None,
        workspace: str = ".",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.router = router
        self.name = name
        self.system = system
        self.model = model
        self.max_steps = max_steps
        self.policy = policy
        self.workspace = workspace
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.mcp_clients = mcp_clients or []
        self._mcp_started = False

        wanted = set(tools) if tools is not None else None
        registry = builtin_tools(workspace=workspace)
        self.builtin_tools: dict[str, BuiltinTool] = {}
        for tool_name, tool in registry.items():
            if wanted is None or tool_name in wanted or f"builtin:{tool_name}" in wanted:
                self.builtin_tools[tool_name] = tool

    # ------------------------------------------------------------------ tools
    async def _ensure_mcp(self) -> None:
        if self._mcp_started:
            return
        for client in self.mcp_clients:
            await client.start()
        self._mcp_started = True

    async def tool_specs(self) -> list[dict[str, Any]]:
        await self._ensure_mcp()
        specs = [tool.spec() for tool in self.builtin_tools.values()]
        for client in self.mcp_clients:
            try:
                specs.extend(client.as_tools(await client.list_tools()))
            except ZykoError as exc:
                log.warning("mcp '%s' unavailable: %s", client.name, exc)
        return specs

    async def _execute(self, call: ToolCall) -> str:
        qualified = MCPClient.split_qualified(call.name)
        if qualified:
            server_name, tool_name = qualified
            client = next((c for c in self.mcp_clients if c.name == server_name), None)
            if client is None:
                return f"error: no MCP server named '{server_name}'"
            try:
                return await asyncio.wait_for(
                    client.call_tool(tool_name, call.arguments), timeout=TOOL_TIMEOUT_S
                )
            except asyncio.TimeoutError:
                return f"error: MCP tool '{call.name}' timed out after {TOOL_TIMEOUT_S}s"
            except ZykoError as exc:
                return f"error: {exc}"

        tool = self.builtin_tools.get(call.name)
        if tool is None:
            return f"error: unknown tool '{call.name}'"
        if tool.danger and not (self.policy and self.policy.explicitly_allows_tool(call.name)):
            return (
                f"error: tool '{call.name}' is blocked by policy "
                "(danger tools require an explicit entry in tools.allow)"
            )
        if self.policy and not self.policy.allows_tool(call.name):
            return f"error: tool '{call.name}' denied by policy"
        try:
            result = await asyncio.wait_for(tool.handler(**call.arguments), timeout=TOOL_TIMEOUT_S)
            return str(result)
        except (ToolError, ZykoError) as exc:
            return f"error: {exc}"
        except asyncio.TimeoutError:
            return f"error: tool '{call.name}' timed out after {TOOL_TIMEOUT_S}s"
        except TypeError as exc:
            return f"error: bad arguments for '{call.name}': {exc}"
        except Exception as exc:  # noqa: BLE001 - tool crashes must not kill the loop
            log.exception("tool %s crashed", call.name)
            return f"error: {type(exc).__name__}: {exc}"

    # ------------------------------------------------------------------- loop
    async def run(self, task: str, *, history: list[Message] | None = None) -> AgentResult:
        started = time.perf_counter()
        await self._ensure_mcp()

        messages: list[Message] = []
        if self.system:
            messages.append(Message.system(self.system))
        messages.extend(history or [])
        messages.append(Message.user(task))

        steps: list[dict[str, Any]] = []
        input_tokens = 0
        output_tokens = 0

        for step_index in range(1, self.max_steps + 1):
            request = ChatRequest(
                messages=messages,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                tools=await self.tool_specs(),
            )
            outcome = await self.router.aroute(request)
            response = outcome.response
            assert response is not None
            input_tokens += response.usage.input_tokens
            output_tokens += response.usage.output_tokens

            step_record = {
                "step": step_index,
                "candidate": outcome.candidate,
                "tool_calls": [tc.name for tc in response.tool_calls],
                "latency_ms": round(response.latency_ms, 1),
            }
            steps.append(step_record)

            if response.tool_calls:
                messages.append(Message.assistant(response.content, tool_calls=response.tool_calls))
                results: list[Message] = []
                for call in response.tool_calls:
                    output = await self._execute(call)
                    log.info("agent %s step %d tool %s → %d chars", self.name, step_index, call.name, len(output))
                    results.append(Message.tool_result(call.id, call.name, output))
                messages.extend(results)
                continue

            return AgentResult(
                output=response.text,
                steps=steps,
                usage_input_tokens=input_tokens,
                usage_output_tokens=output_tokens,
                elapsed_s=time.perf_counter() - started,
            )

        return AgentResult(
            output="(agent reached max_steps without a final answer — raise max_steps in the agent file)",
            steps=steps,
            usage_input_tokens=input_tokens,
            usage_output_tokens=output_tokens,
            truncated=True,
            elapsed_s=time.perf_counter() - started,
        )

    # ------------------------------------------------------------------- sync
    def run_sync(self, task: str, *, history: list[Message] | None = None) -> AgentResult:
        from zyko.utils.loop import run_sync

        return run_sync(self.run(task, history=history))


__all__ = ["Agent", "AgentResult", "ToolError", "PolicyViolation", "kernel"]
