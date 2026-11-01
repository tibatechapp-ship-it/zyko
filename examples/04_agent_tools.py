"""04 — Agents: a tool-using loop with policy guards and a full trace."""

from zyko import Zyko

zk = Zyko()

agent = zk.agent(
    {
        "name": "calc-agent",
        "system": "You solve math precisely. Use the calculator tool for arithmetic.",
        "max_steps": 6,
        "tools": ["calculator"],
    }
)

result = agent.run_sync("A factory makes 47 gadgets per hour and runs 16 hours a day. Output per week (7 days)?")

print(result.output)
print("\n--- trace ---")
for step in result.steps:
    print(f"step {step['step']}: via {step['candidate']} · tools: {', '.join(step['tool_calls']) or '-'}")
print(f"\ntokens: in={result.usage_input_tokens} out={result.usage_output_tokens} · {result.elapsed_s:.1f}s")

# MCP servers plug in the same way, declaratively:
#   agent = zk.agent("my-agent.yaml")   # with mcp_servers: [{name, command}]
