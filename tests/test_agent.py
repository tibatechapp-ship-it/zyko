"""Agent loop: tools, guards, traces."""

from __future__ import annotations

from tests.fakes import FakeProvider
from zyko.agents.agent import Agent
from zyko.core.messages import ToolCall
from zyko.policy.engine import PolicyEngine
from zyko.router.engine import Router


def _router_with_script(*script) -> Router:
    return Router({"fake": FakeProvider(script=list(script))})


async def test_calculator_tool_loop():
    router = _router_with_script(
        {"tool_calls": [ToolCall(id="c1", name="calculator", arguments={"expression": "21*2"})]},
        "The result is 42.",
    )
    agent = Agent(router, tools=["calculator"], max_steps=4)
    result = await agent.run("what is 21*2?")
    assert result.output == "The result is 42."
    assert len(result.steps) == 2
    assert result.steps[0]["tool_calls"] == ["calculator"]
    assert result.usage_output_tokens > 0


async def test_unknown_tool_returns_error_string_not_crash():
    router = _router_with_script(
        {"tool_calls": [ToolCall(id="c1", name="does_not_exist", arguments={})]},
        "moving on",
    )
    agent = Agent(router, tools=["calculator"])
    result = await agent.run("do it")
    assert result.output == "moving on"


async def test_shell_blocked_without_explicit_policy():
    router = _router_with_script(
        {"tool_calls": [ToolCall(id="c1", name="shell", arguments={"command": "ls"})]},
        "ok",
    )
    agent = Agent(router)  # wildcard default policy-like behaviour: no policy attached
    out = await agent._execute(ToolCall(id="c1", name="shell", arguments={"command": "ls"}))
    assert "blocked by policy" in out


async def test_shell_allowed_with_explicit_policy(tmp_path):
    policy = PolicyEngine(
        {"version": 1, "name": "p", "tools": {"allow": ["shell"]}}, state_dir=tmp_path
    )
    router = _router_with_script(
        {
            "tool_calls": [
                ToolCall(id="c1", name="shell", arguments={"command": "echo zyko-shell-ok"})
            ]
        },
    )
    agent = Agent(router, policy=policy, tools=["shell"])
    out = await agent._execute(
        ToolCall(id="c1", name="shell", arguments={"command": "echo zyko-shell-ok"})
    )
    assert "zyko-shell-ok" in out


async def test_write_and_read_file_confined_to_workspace(tmp_path):
    router = _router_with_script(
        {
            "tool_calls": [
                ToolCall(
                    id="w1",
                    name="write_file",
                    arguments={"path": "notes/x.txt", "content": "hello"},
                )
            ]
        },
        {"tool_calls": [ToolCall(id="r1", name="read_file", arguments={"path": "notes/x.txt"})]},
        "done",
    )
    agent = Agent(router, tools=["read_file", "write_file"], workspace=str(tmp_path))
    out = await agent._execute(
        ToolCall(id="w", name="write_file", arguments={"path": "notes/x.txt", "content": "hello"})
    )
    assert "wrote" in out
    content = await agent._execute(
        ToolCall(id="r", name="read_file", arguments={"path": "notes/x.txt"})
    )
    assert content == "hello"
    # path escape is rejected
    evil = await agent._execute(
        ToolCall(id="e", name="read_file", arguments={"path": "../escape.txt"})
    )
    assert "escapes" in evil


async def test_max_steps_truncation_flag():
    router = _router_with_script(
        {"tool_calls": [ToolCall(id="c1", name="calculator", arguments={"expression": "1+1"})]}
    )
    agent = Agent(router, tools=["calculator"], max_steps=2)
    result = await agent.run("loop forever")
    assert result.truncated is True
    assert len(result.steps) == 2


async def test_agent_with_policy_denied_tool(tmp_path):
    policy = PolicyEngine(
        {"version": 1, "name": "p", "tools": {"allow": ["*"], "deny": ["http_get"]}},
        state_dir=tmp_path,
    )
    router = _router_with_script(
        {
            "tool_calls": [
                ToolCall(id="c1", name="http_get", arguments={"url": "http://example.com"})
            ]
        },
        "gave up on fetch",
    )
    agent = Agent(router, policy=policy, tools=["http_get"])
    out = await agent._execute(
        ToolCall(id="c", name="http_get", arguments={"url": "http://example.com"})
    )
    assert "denied by policy" in out
