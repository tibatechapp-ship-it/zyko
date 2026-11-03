"""Crew: the sequential multi-agent pipeline (0.6.0).

Covers the three pillars the roadmap promised: CrewAI-parity simplicity
(declare steps, get an answer), safe shared context (task/output/output_key
templates that never crash on unknown keys and never re-format values) and
stronger governance (typed errors, per-step records, crew.run/crew.step
spans, no hidden prompts).
"""

from __future__ import annotations

import json

import pytest
import yaml

from tests.fakes import FakeProvider
from zyko.agents.agent import Agent
from zyko.crew import Crew, fill_template
from zyko.exceptions import ConfigError, CrewError, ProviderError
from zyko.observability import InMemorySink, Tracer
from zyko.router.engine import Router


# ------------------------------------------------------------------- helpers
class RecordingFake(FakeProvider):
    """FakeProvider that remembers the flattened text of every request."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.seen: list[str] = []

    async def acomplete(self, request, *, retries=None):  # noqa: D102 - inherit docs
        self.seen.append(request.text)
        return await super().acomplete(request, retries=retries)


def _crew(*script: object, tracer: Tracer | None = None, name: str = "crew"):
    prov = RecordingFake(script=list(script))
    router = Router({"fake": prov})
    return Crew(router=router, tracer=tracer, name=name), prov


def _agent(router: Router, name: str = "worker", **kwargs) -> Agent:
    return Agent(router, name=name, **kwargs)


def _write_yaml(path, doc) -> str:
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return str(path)


# ------------------------------------------------------------ template engine
def test_fill_template_known_and_unknown_keys():
    out = fill_template("T:{task} P:{output} U:{nope}", task="in", output="prev")
    assert out == "T:in P:prev U:{nope}"


def test_fill_template_values_are_never_reformatted():
    out = fill_template("D:{output}", output='{"a": 1}')
    assert out == 'D:{"a": 1}'


def test_fill_template_positional_and_bad_conversion_rejected():
    with pytest.raises(CrewError):
        fill_template("hello {}")
    with pytest.raises(CrewError):
        fill_template("hi {0}")
    with pytest.raises(CrewError):
        fill_template("bad {a!}")


def test_add_rejects_positional_and_malformed_templates():
    crew, _ = _crew("ok")
    agent = _agent(crew.router)
    with pytest.raises(CrewError, match="positional"):
        crew.add(agent, "hello {}")
    with pytest.raises(CrewError, match="not"):
        crew.add(agent, "hi {0}")


# ------------------------------------------------------------- building phase
def test_add_rejects_non_agent_and_empty_task():
    crew, _ = _crew("ok")
    with pytest.raises(CrewError, match="Agent instance"):
        crew.add("not-an-agent", "task")  # type: ignore[arg-type]
    agent = _agent(crew.router)
    with pytest.raises(CrewError, match="non-empty"):
        crew.add(agent, "   ")


def test_add_rejects_duplicate_output_key():
    crew, _ = _crew("ok")
    agent = _agent(crew.router, name="a")
    crew.add(agent, "t1", output_key="out")
    with pytest.raises(CrewError, match="duplicate output_key 'out'"):
        crew.add(agent, "t2", output_key="out")


def test_default_output_keys_follow_agent_names_and_dedup():
    crew, _ = _crew("one", "two")
    router = crew.router
    crew.add(_agent(router, name="worker"), "t1")
    crew.add(_agent(router, name="worker"), "t2")
    assert crew.steps[0].output_key == "worker"
    assert crew.steps[1].output_key == "worker_2"


def test_steps_property_is_a_defensive_copy():
    crew, _ = _crew("ok")
    crew.add(_agent(crew.router), "t")
    crew.steps.clear()
    assert len(crew.steps) == 1


# ------------------------------------------------------------------ execution
async def test_single_step_run_receipt():
    crew, _ = _crew("final answer")
    crew.add(_agent(crew.router), "do {task}")
    res = await crew.arun("hello")
    assert res.output == "final answer"
    assert res.outputs == {"worker": "final answer"}
    assert res.elapsed_s > 0
    assert res.trace_id is None  # no tracer wired
    assert res.truncated is False


async def test_two_steps_share_context_in_order():
    crew, prov = _crew("alpha", "beta")
    router = crew.router
    crew.add(_agent(router, name="first"), "Step one: {task}")
    crew.add(_agent(router, name="second"), "Continue. Previous said: {output}")
    res = await crew.arun("kickoff")
    assert res.output == "beta"
    assert "Step one: kickoff" in prov.seen[0]
    assert "Previous said: alpha" in prov.seen[1]
    assert list(res.outputs) == ["first", "second"]


async def test_output_key_reference_flows_forward():
    crew, prov = _crew("CLASS: billing", "REPLY sent")
    router = crew.router
    crew.add(_agent(router, name="classifier"), "Classify: {task}", output_key="class")
    crew.add(_agent(router, name="replier"), "Reply. Ticket: {task}\nClass: {class}")
    res = await crew.arun("my invoice is late")
    assert "Classify: my invoice is late" in prov.seen[0]
    assert "Ticket: my invoice is late" in prov.seen[1]
    assert "Class: CLASS: billing" in prov.seen[1]
    assert res.outputs["class"] == "CLASS: billing"
    assert res.steps[1]["task"].endswith("Class: CLASS: billing")


async def test_unknown_placeholder_survives_to_the_agent():
    crew, prov = _crew("ok")
    crew.add(_agent(crew.router), 'Reply with JSON key "{nonsense}" for {task}')
    await crew.arun("x")
    assert '"{nonsense}"' in prov.seen[0]


async def test_agent_system_prompts_are_preserved_and_not_shared():
    """Governance: the crew injects no hidden prompts across agents."""
    crew, prov = _crew("a1", "b1")
    router = crew.router
    crew.add(_agent(router, name="a", system="SYSTEM-ALPHA"), "t {task}")
    crew.add(_agent(router, name="b", system="SYSTEM-BETA"), "t2 {output}")
    await crew.arun("x")
    assert "SYSTEM-ALPHA" in prov.seen[0]
    assert "SYSTEM-BETA" not in prov.seen[0]
    assert "SYSTEM-BETA" in prov.seen[1]
    assert "SYSTEM-ALPHA" not in prov.seen[1]


async def test_usage_and_elapsed_aggregate_across_steps():
    crew, _ = _crew("one", "two", "three")
    router = crew.router
    for i in range(3):
        crew.add(_agent(router, name=f"a{i}"), f"t{i} {{task}}")
    res = await crew.arun("x")
    assert res.usage_input_tokens == 60  # 3 calls x Usage(20, 10)
    assert res.usage_output_tokens == 30
    assert len(res.steps) == 3
    assert res.steps[0]["agent"] == "a0"


async def test_truncated_step_is_flagged_not_fatal():
    from zyko.core.messages import ToolCall

    crew, prov = _crew(
        {"tool_calls": [ToolCall(id="c1", name="calculator", arguments={"expression": "1+1"})]},
        "never reached",
    )
    router = crew.router
    crew.add(_agent(router, name="looper", max_steps=1), "loop {task}")
    res = await crew.arun("x")
    assert res.truncated is True
    assert res.steps[0]["truncated"] is True
    assert "max_steps" in res.output
    assert prov.seen and "loop x" in prov.seen[0]


async def test_provider_failure_raises_typed_error_through_the_pipeline():
    # fail everything: the router's internal retry budget must be exhausted
    # before the ProviderError escapes the pipeline as a typed failure.
    prov = FakeProvider(script=["ok"], fail_first=99)
    crew = Crew(router=Router({"fake": prov}))
    crew.add(_agent(crew.router), "t {task}")
    with pytest.raises(ProviderError):
        await crew.arun("x")


async def test_non_string_crew_input_rejected():
    crew, _ = _crew("ok")
    crew.add(_agent(crew.router), "t")
    with pytest.raises(CrewError, match="input must be a string"):
        await crew.arun(123)  # type: ignore[arg-type]


def test_run_sync_mirror_from_sync_context():
    crew, _ = _crew("sync answer")
    crew.add(_agent(crew.router), "t {task}")
    res = crew.run("hello")
    assert res.output == "sync answer"


# ------------------------------------------------------------------ tracing
async def test_spans_nest_crew_step_under_crew_run():
    sink = InMemorySink()
    crew, _ = _crew("one", "two", tracer=Tracer(sinks=[sink]))
    router = crew.router
    crew.add(_agent(router, name="first"), "t1 {task}")
    crew.add(_agent(router, name="second"), "t2 {output}")
    res = await crew.arun("x")
    spans = sink.spans()
    names = [s.name for s in spans]
    # InMemorySink records spans when they END — children close before parents.
    assert names == ["crew.step", "crew.step", "crew.run"]
    run_span = spans[-1]
    assert run_span.attributes["crew"] == "crew"
    assert run_span.attributes["steps"] == 2
    for sp in spans[:-1]:
        assert sp.parent_id == run_span.span_id
        assert sp.trace_id == run_span.trace_id
    assert spans[0].attributes["agent"] == "first"
    assert spans[1].attributes["key"] == "second"
    assert res.trace_id == run_span.trace_id


async def test_failure_marks_crew_run_span_error():
    sink = InMemorySink()
    prov = FakeProvider(script=["ok"], fail_first=99)
    router = Router({"fake": prov})
    crew = Crew(router=router, tracer=Tracer(sinks=[sink]))
    crew.add(_agent(router), "t {task}")
    with pytest.raises(ProviderError):
        await crew.arun("x")
    run_span = sink.spans()[-1]
    assert run_span.name == "crew.run"
    assert run_span.status == "error"
    assert "error" in run_span.attributes


# ---------------------------------------------------------------- YAML loader
def _inline_crew_doc() -> dict:
    return {
        "name": "triage-demo",
        "steps": [
            {
                "agent": {
                    "name": "classifier",
                    "system": "You classify tickets.",
                    "model": "auto",
                },
                "task": "Classify: {task}",
                "output_key": "class",
            },
            {
                "agent": {"name": "replier", "system": "You draft replies."},
                "task": "Reply. Ticket: {task}\nClass: {class}",
            },
        ],
    }


def test_load_crew_inline_agents_and_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "crew.yaml"
    _write_yaml(path, _inline_crew_doc())
    from zyko.crew import load_crew

    prov = RecordingFake(script=["CLASS: billing", "REPLY sent"])
    crew = load_crew(path, Router({"fake": prov}))
    assert crew.name == "triage-demo"
    assert [s.agent.name for s in crew.steps] == ["classifier", "replier"]
    res = crew.run("invoice late")
    assert res.output == "REPLY sent"
    assert res.outputs["class"] == "CLASS: billing"
    assert "Class: CLASS: billing" in prov.seen[1]


def test_load_crew_agent_file_reference(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_yaml(
        tmp_path / "classifier.yaml",
        {"name": "classifier", "system": "SYS-MARKER-CLASSIFIER", "model": "auto"},
    )
    path = _write_yaml(
        tmp_path / "mixed.yaml",
        {
            "name": "mixed",
            "steps": [
                {"agent": "classifier.yaml", "task": "T1 {task}"},
                {
                    "agent": {"name": "replier", "system": "SYS-MARKER-REPLIER"},
                    "task": "T2 {output}",
                },
            ],
        },
    )
    from zyko.crew import load_crew

    prov = RecordingFake(script=["alpha", "beta"])
    crew = load_crew(path, Router({"fake": prov}))
    res = crew.run("x")
    assert "SYS-MARKER-CLASSIFIER" in prov.seen[0]
    assert "SYS-MARKER-REPLIER" in prov.seen[1]
    assert "T2 alpha" in prov.seen[1]
    assert res.output == "beta"


def test_load_crew_resolves_bare_name_with_yaml_suffix(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_yaml(tmp_path / "mycrew.yaml", _inline_crew_doc())
    from zyko.crew import load_crew

    crew = load_crew("mycrew", Router({"fake": RecordingFake(script=["a", "b"])}))
    assert crew.name == "triage-demo"


def test_load_crew_not_found_and_invalid_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from zyko.crew import load_crew

    with pytest.raises(ConfigError, match="not found"):
        load_crew("missing", Router({"fake": RecordingFake()}))
    bad = tmp_path / "broken.yaml"
    bad.write_text("steps: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid crew file"):
        load_crew(bad, Router({"fake": RecordingFake()}))


@pytest.mark.parametrize(
    "doc,match",
    [
        ({"name": "x"}, "non-empty 'steps:'"),
        ({"name": "x", "steps": []}, "non-empty 'steps:'"),
        ({"name": "x", "steps": ["nope"]}, "must be a mapping"),
        ({"name": "x", "steps": [{"task": "t"}]}, "'agent' must be"),
        (
            {"name": "x", "steps": [{"agent": "missing.yaml", "task": "t"}]},
            "agent 'missing.yaml' not found",
        ),
        (
            {"name": "x", "steps": [{"agent": {"name": "a"}, "task": ""}]},
            "non-empty 'task:'",
        ),
        (
            {
                "name": "x",
                "steps": [
                    {"agent": {"name": "a"}, "task": "t", "output_key": "k"},
                    {"agent": {"name": "b"}, "task": "t", "output_key": "k"},
                ],
            },
            "duplicate output_key",
        ),
    ],
)
def test_load_crew_config_errors(tmp_path, monkeypatch, doc, match):
    monkeypatch.chdir(tmp_path)
    from zyko.crew import load_crew

    path = _write_yaml(tmp_path / "crew.yaml", doc)
    with pytest.raises(ConfigError, match=match):
        load_crew(path, Router({"fake": RecordingFake(script=["a"])}))


def test_load_crew_bad_template_is_config_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from zyko.crew import load_crew

    path = _write_yaml(
        tmp_path / "crew.yaml",
        {"name": "x", "steps": [{"agent": {"name": "a"}, "task": "broken {} template"}]},
    )
    with pytest.raises(ConfigError, match="positional"):
        load_crew(path, Router({"fake": RecordingFake(script=["a"])}))


# ------------------------------------------------------------- facade + CLI
def test_zk_crew_facade_runs_and_traces(tmp_path, monkeypatch):
    from zyko import Zyko

    fake = RecordingFake(script=["CLASS: billing", "REPLY sent"])
    monkeypatch.setattr("zyko.client.configured_providers", lambda *_a, **_k: {"fake": fake})
    zk = Zyko(ledger_path=tmp_path / "ledger.json")
    path = _write_yaml(tmp_path / "crew.yaml", _inline_crew_doc())
    crew = zk.crew(path)
    res = crew.run("invoice late")
    assert res.output == "REPLY sent"
    assert res.trace_id  # zk.tracer is wired into the crew
    spans = zk.tracer.sinks and [s for s in zk.tracer.sinks if isinstance(s, InMemorySink)]
    assert spans and any(s.name == "crew.run" for s in spans[0].spans())


def test_cli_crew_json_and_trace(tmp_path, monkeypatch, capsys):
    """End-to-end through the real argparse surface, keyless demo provider."""
    from zyko.cli import main

    path = _write_yaml(tmp_path / "crew.yaml", _inline_crew_doc())
    monkeypatch.chdir(tmp_path)
    code = main(["crew", path, "--input", "invoice late", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["output"]
    assert list(payload["outputs"]) == ["class", "replier"]
    assert len(payload["steps"]) == 2

    code = main(["crew", path, "--input", "invoice late", "--trace"])
    assert code == 0
    out = capsys.readouterr().out
    assert "classifier" in out and "replier" in out
