"""Declarative crew definitions (YAML)::

    name: support-triage
    steps:
      - agent: triage.yaml          # reference an agent file (searched like agents)
        task: "Classify the ticket: {task}"
        output_key: classification
      - agent:                      # or define the agent inline
          name: responder
          system: You draft customer replies. Be brief and factual.
          model: auto
          max_steps: 6
        task: "Draft a reply. Ticket: {task}\\nClassification: {classification}"

Placeholders resolve against the shared context: ``{task}`` (the crew
input), ``{output}`` (previous step's output) and every earlier
``output_key``. Unknown names stay literal — see ``zyko.crew.engine``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from zyko.agents.loader import build_agent, load_agent_document
from zyko.crew.engine import Crew
from zyko.exceptions import ConfigError, CrewError
from zyko.policy.engine import PolicyEngine
from zyko.router.engine import Router


def load_crew(
    source: str | Path,
    router: Router,
    *,
    policy: PolicyEngine | None = None,
    workspace: str = ".",
    tracer: Any | None = None,
) -> Crew:
    """Load a crew from a YAML file (path, or a name searched like agents).

    Configuration problems raise :class:`~zyko.exceptions.ConfigError`
    before anything runs; runtime failures raise :class:`CrewError` or the
    underlying typed provider error — never a bare string.
    """
    import yaml

    from zyko.agents.loader import _search_paths

    path = Path(source)
    candidates = [path] if path.is_absolute() else _search_paths(str(source))
    doc: dict[str, Any] | None = None
    for probe in candidates:
        for suffix in ("", ".yaml", ".yml"):
            target = probe if suffix == "" else Path(str(probe) + suffix)
            if target.is_file():
                try:
                    loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
                except Exception as exc:  # noqa: BLE001 - surfaced as ConfigError
                    raise ConfigError(f"invalid crew file {target}: {exc}") from exc
                if not isinstance(loaded, dict):
                    raise ConfigError(f"crew file {target} must contain a YAML mapping")
                doc = loaded
                break
        if doc is not None:
            break
    if doc is None:
        raise ConfigError(
            f"crew '{source}' not found",
            hint="searched: " + ", ".join(str(p) for p in candidates),
        )

    crew = Crew(router=router, tracer=tracer, name=str(doc.get("name") or "crew"))
    raw_steps = doc.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ConfigError(
            f"crew file '{source}' must declare a non-empty 'steps:' list",
            hint="each step: agent: (file name or inline mapping) + task: template "
            "(+ optional output_key:)",
        )
    for index, raw in enumerate(raw_steps, 1):
        if not isinstance(raw, dict):
            raise ConfigError(f"crew step {index} in '{source}' must be a mapping")
        agent_spec = raw.get("agent")
        if isinstance(agent_spec, str):
            agent = build_agent(
                load_agent_document(agent_spec), router, policy=policy, workspace=workspace
            )
        elif isinstance(agent_spec, dict):
            agent = build_agent(agent_spec, router, policy=policy, workspace=workspace)
        else:
            raise ConfigError(
                f"crew step {index} in '{source}': 'agent' must be an agent file name "
                "or an inline agent mapping"
            )
        task = raw.get("task")
        if not isinstance(task, str) or not task.strip():
            raise ConfigError(
                f"crew step {index} (agent '{agent.name}') in '{source}' must declare "
                "a non-empty 'task:' template"
            )
        output_key = raw.get("output_key")
        if output_key is not None and not isinstance(output_key, str):
            raise ConfigError(f"crew step {index} in '{source}': 'output_key' must be a string")
        try:
            crew.add(agent, task, output_key=output_key)
        except CrewError as exc:
            # Engine invariants (duplicate key, bad template) are config bugs
            # when they come from a declared crew file.
            raise ConfigError(f"crew step {index} in '{source}': {exc}") from exc
    return crew


__all__ = ["load_crew"]
