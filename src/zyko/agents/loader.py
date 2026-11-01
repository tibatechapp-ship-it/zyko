"""Declarative agent definitions (YAML)::

name: coder
system: You are a precise coding assistant...
model: auto            # or "openai/gpt-4o-mini"
max_steps: 10
tools: [calculator, read_file, write_file]
mcp_servers:
  - name: fs
    command: [npx, -y, "@modelcontextprotocol/server-filesystem", /tmp]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from zyko.agents.agent import Agent
from zyko.exceptions import ConfigError
from zyko.mcp.client import MCPClient
from zyko.platform.paths import config_dir
from zyko.policy.engine import PolicyEngine
from zyko.router.engine import Router


def _search_paths(name: str) -> list[Path]:
    path = Path(name)
    if path.is_absolute():
        return [path]
    return [
        Path.cwd() / name,
        config_dir() / "agents" / name,
        Path.cwd() / "examples" / "agents" / name,
    ]


def load_agent_document(source: str | Path) -> dict[str, Any]:
    import yaml

    candidates = _search_paths(str(source))
    for suffix in ("", ".yaml", ".yml"):
        for base in candidates:
            probe = base if suffix == "" else Path(str(base) + suffix)
            if probe.is_file():
                try:
                    doc = yaml.safe_load(probe.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise ConfigError(f"invalid agent file {probe}: {exc}") from exc
                if not isinstance(doc, dict):
                    raise ConfigError(f"agent file {probe} must contain a YAML mapping")
                doc["_path"] = str(probe)
                return doc
    raise ConfigError(
        f"agent '{source}' not found",
        hint="searched: " + ", ".join(str(p) for p in candidates),
    )


def build_agent(
    doc: dict[str, Any],
    router: Router,
    *,
    policy: PolicyEngine | None = None,
    workspace: str = ".",
) -> Agent:
    mcp_clients = [
        MCPClient(
            server.get("name") or f"mcp{i}",
            server.get("command") or [],
            env=server.get("env"),
            cwd=server.get("cwd"),
            request_timeout=float(server.get("timeout", 20.0)),
        )
        for i, server in enumerate(doc.get("mcp_servers") or [])
    ]
    return Agent(
        router,
        name=doc.get("name") or "agent",
        system=doc.get("system"),
        model=doc.get("model") or None,
        max_steps=int(doc.get("max_steps", 8)),
        tools=doc.get("tools"),
        mcp_clients=mcp_clients,
        policy=policy,
        workspace=doc.get("workspace") or workspace,
        temperature=doc.get("temperature"),
        max_tokens=doc.get("max_tokens"),
    )


def load_agent(source: str | Path, router: Router, **kwargs: Any) -> Agent:
    return build_agent(load_agent_document(source), router, **kwargs)


__all__ = ["load_agent", "load_agent_document", "build_agent"]
