"""Crew: a sequential multi-agent pipeline with shared context.

Roadmap step 4 (``docs/STRATEGY.md``) — parity with CrewAI in simplicity,
stronger in governance. A crew is an ordered list of steps; each step is one
configured :class:`~zyko.agents.Agent` plus a task template. Templates may
reference:

* ``{task}``   — the crew-level input passed to :meth:`Crew.run`
* ``{output}`` — the previous step's final output (empty for the first step)
* ``{key}``    — any earlier step's declared ``output_key``

Formatting is deliberate and safe:

* unknown placeholders stay literal — ``{json}`` inside normal prose is
  text, never a crash (a ``string.Formatter`` with a ``__missing__`` map);
* substituted values are never re-formatted, so outputs containing braces
  (JSON, code) survive round-trips;
* templates are validated when a step is added (fail fast, not mid-run) —
  malformed placeholders like ``{}`` or ``{a!}`` raise :class:`CrewError`
  immediately.

Governance: the crew injects no hidden prompts. Every agent keeps its own
system prompt, tools and policy; the only content the crew adds is the task
text you declared. Every step runs inside a ``crew.step`` span nested under
a ``crew.run`` span, and the :class:`CrewResult` carries per-step records
plus token totals you can audit offline.

::

    from zyko import Zyko
    from zyko.crew import Crew

    zk = Zyko()
    crew = Crew(router=zk.router, tracer=zk.tracer, name="triage")
    crew.add(classifier, "Classify the ticket: {task}", output_key="class")
    crew.add(replier, "Draft a reply. Ticket: {task}\\nClassification: {class}")
    result = crew.run("my invoice is late")
    print(result.output)          # final agent's answer
    print(result.outputs["class"])
"""

from __future__ import annotations

import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from string import Formatter
from typing import Any

from zyko.agents.agent import Agent, AgentResult
from zyko.exceptions import CrewError
from zyko.log import get_logger
from zyko.observability.tracer import Tracer
from zyko.router.engine import Router
from zyko.utils.loop import run_sync

log = get_logger("crew")


class _SafeDict(dict):
    """Format mapping whose missing keys render back as literal ``{key}``."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def fill_template(template: str, **fields: str) -> str:
    """Fill ``{placeholders}`` from *fields*; unknown keys stay literal.

    Substituted values are never re-scanned, so agent outputs that contain
    braces (JSON, code, other templates) pass through untouched. Positional
    or malformed placeholders (``{}``, ``{0}``, ``{a!}``) raise
    :class:`CrewError` — :meth:`Crew.add` validates every template up front
    so this never fires mid-run.
    """
    try:
        return template.format_map(_SafeDict(**fields))
    except (ValueError, IndexError) as exc:
        raise CrewError(f"invalid task template {template!r}: {exc}") from exc


def _validate_template(template: str) -> None:
    """Reject templates that would crash at fill time (fail fast on add)."""
    for _, field_name, spec, conversion in Formatter().parse(template):
        if field_name is None:
            continue
        if not field_name and not spec and not conversion:
            # "{}" — positional auto-numbering has no meaning in a crew task.
            raise CrewError(
                f"invalid task template {template!r}: positional '{{}}' is not allowed; "
                "use named placeholders: {task}, {output} or an earlier output_key"
            )
        if field_name and not field_name.isidentifier():
            raise CrewError(
                f"invalid task template {template!r}: placeholder '{field_name}' is not "
                "a valid name; use {task}, {output} or an earlier output_key"
            )
    fill_template(template, task="", output="")


@dataclass
class CrewStep:
    """One pipeline entry: an agent, its task template, its output key."""

    agent: Agent
    task: str
    output_key: str


@dataclass
class CrewResult:
    """Everything a crew run produced, in one auditable receipt."""

    output: str
    outputs: dict[str, str] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    usage_input_tokens: int = 0
    usage_output_tokens: int = 0
    truncated: bool = False
    elapsed_s: float = 0.0
    trace_id: str | None = None


class Crew:
    """An ordered, sequential multi-agent pipeline with shared context.

    Build it directly (``Crew(router=..., tracer=...)`` then ``add()``) or
    declaratively via :func:`zyko.crew.load_crew` / ``zk.crew("file.yaml")``.
    ``add`` is chainable and validates everything up front; ``run`` executes
    the steps in order, feeding each task the shared context it declares.
    """

    def __init__(
        self,
        *,
        router: Router,
        tracer: Tracer | None = None,
        name: str = "crew",
    ) -> None:
        self.router = router
        self.tracer = tracer
        self.name = name
        self._steps: list[CrewStep] = []
        self._keys: set[str] = set()

    # ------------------------------------------------------------- building
    @property
    def steps(self) -> list[CrewStep]:
        """The declared steps (read-only copy; use :meth:`add` to append)."""
        return list(self._steps)

    def _next_key(self, base: str) -> str:
        if base not in self._keys:
            return base
        n = 2
        while f"{base}_{n}" in self._keys:
            n += 1
        return f"{base}_{n}"

    def add(
        self,
        agent: Agent,
        task: str,
        *,
        output_key: str | None = None,
    ) -> "Crew":
        """Append a step; validates the task template and output key now.

        ``output_key`` defaults to the agent's name (deduped as ``name_2``,
        ``name_3``, … for repeated agent names). Duplicate *explicit* keys
        raise :class:`CrewError` — silent overwrites would corrupt the
        shared context later steps depend on.
        """
        if not isinstance(agent, Agent):
            raise CrewError(
                f"crew steps take an Agent instance, got {type(agent).__name__}",
                hint="build one with zk.agent('file.yaml') or zyko.agents.Agent(router, ...)",
            )
        if not isinstance(task, str) or not task.strip():
            raise CrewError(
                f"agent '{agent.name}': task template must be a non-empty string",
            )
        if output_key is not None:
            if not isinstance(output_key, str) or not output_key.strip():
                raise CrewError(f"agent '{agent.name}': output_key must be a non-empty string")
            if output_key in self._keys:
                raise CrewError(
                    f"duplicate output_key '{output_key}' in crew '{self.name}'",
                    hint="every step must publish under a unique key so later "
                    "templates can reference it unambiguously",
                )
            key = output_key
        else:
            key = self._next_key(agent.name or "step")
        _validate_template(task)
        self._steps.append(CrewStep(agent=agent, task=task, output_key=key))
        self._keys.add(key)
        return self

    # ------------------------------------------------------------- execution
    async def arun(self, task: str) -> CrewResult:
        """Run every step in order; returns the aggregated :class:`CrewResult`."""
        if not self._steps:
            raise CrewError(
                f"crew '{self.name}' has no steps",
                hint="call add() at least once, or declare steps: in the YAML file",
            )
        if not isinstance(task, str):
            raise CrewError("crew input must be a string")
        started = time.perf_counter()

        run_cm = (
            self.tracer.span("crew.run", crew=self.name, steps=len(self._steps))
            if self.tracer is not None
            else nullcontext(None)
        )
        with run_cm as run_span:
            outputs: dict[str, str] = {}
            records: list[dict[str, Any]] = []
            input_tokens = 0
            output_tokens = 0
            truncated = False
            previous = ""

            for index, step in enumerate(self._steps, 1):
                filled = fill_template(step.task, task=task, output=previous, **outputs)
                step_cm = (
                    self.tracer.span(
                        "crew.step",
                        agent=step.agent.name,
                        key=step.output_key,
                        index=index,
                    )
                    if self.tracer is not None
                    else nullcontext(None)
                )
                with step_cm:
                    result: AgentResult = await step.agent.run(filled)

                input_tokens += result.usage_input_tokens
                output_tokens += result.usage_output_tokens
                truncated = truncated or result.truncated
                outputs[step.output_key] = result.output
                records.append(
                    {
                        "step": index,
                        "agent": step.agent.name,
                        "key": step.output_key,
                        "task": filled,
                        "output": result.output,
                        "agent_steps": len(result.steps),
                        "truncated": result.truncated,
                        "elapsed_s": round(result.elapsed_s, 2),
                    }
                )
                log.info(
                    "crew '%s' step %d/%d agent '%s' → %d chars",
                    self.name,
                    index,
                    len(self._steps),
                    step.agent.name,
                    len(result.output),
                )
                previous = result.output

            return CrewResult(
                output=previous,
                outputs=outputs,
                steps=records,
                usage_input_tokens=input_tokens,
                usage_output_tokens=output_tokens,
                truncated=truncated,
                elapsed_s=time.perf_counter() - started,
                trace_id=run_span.trace_id if run_span is not None else None,
            )

    def run(self, task: str) -> CrewResult:
        """Sync mirror of :meth:`arun` (safe to call from any thread)."""
        return run_sync(self.arun(task))


__all__ = ["Crew", "CrewResult", "CrewStep", "fill_template"]
