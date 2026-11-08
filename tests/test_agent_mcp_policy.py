"""Regression: MCP tool calls must obey the agent policy."""
import asyncio
from unittest.mock import Mock

from zyko.agents.agent import Agent
from zyko.core.messages import ToolCall


def _bare_agent(allows: bool) -> Agent:
    policy = Mock()
    policy.allows_tool.return_value = allows
    policy.explicitly_allows_tool.return_value = False
    agent = object.__new__(Agent)
    agent.policy = policy
    agent.mcp_clients = []
    agent.builtin_tools = {}
    return agent


def test_mcp_tool_blocked_by_policy():
    agent = _bare_agent(allows=False)
    out = asyncio.run(agent._execute(ToolCall(name="mcp__srv__do_thing", arguments={})))
    assert "denied by policy" in out, out


def test_mcp_tool_not_blocked_when_policy_permits():
    agent = _bare_agent(allows=True)
    out = asyncio.run(agent._execute(ToolCall(name="mcp__srv__do_thing", arguments={})))
    assert "denied by policy" not in out, out
    assert "no MCP server named" in out, out
