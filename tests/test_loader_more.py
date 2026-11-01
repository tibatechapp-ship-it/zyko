"""Agent loader search paths, error reporting, and MCP wiring."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.fakes import FakeProvider
from zyko.agents.loader import build_agent, load_agent, load_agent_document
from zyko.exceptions import ConfigError
from zyko.router.engine import Router


def _router():
    return Router({"fake": FakeProvider()})


def test_load_document_by_absolute_path(tmp_path):
    path = tmp_path / "agent.yaml"
    path.write_text(yaml.safe_dump({"name": "abs", "system": "s"}), encoding="utf-8")
    doc = load_agent_document(path)
    assert doc["name"] == "abs"
    assert doc["_path"] == str(path)


def test_load_document_finds_yaml_suffix_in_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "worker.yaml").write_text("name: worker\n", encoding="utf-8")
    doc = load_agent_document("worker")
    assert doc["name"] == "worker"
    assert doc["_path"].endswith("worker.yaml")


def test_load_document_searches_examples_dir(monkeypatch):
    """Repo-root examples/ is on the search path — math-agent resolves."""
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    doc = load_agent_document("math-agent")
    assert doc["name"] == "math-agent"


def test_load_document_errors_are_actionable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as excinfo:
        load_agent_document("no-such-agent")
    assert "searched:" in str(excinfo.value)


def test_load_document_rejects_non_mapping(tmp_path, monkeypatch):
    path = tmp_path / "list.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_agent_document(path)
    assert "mapping" in str(excinfo.value)


def test_load_document_reports_invalid_yaml(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("name: [unclosed\n  bad", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_agent_document(path)
    assert "invalid agent file" in str(excinfo.value)


def test_build_agent_defaults_and_overrides():
    doc = {"name": "built", "max_steps": 4, "temperature": 0.2, "max_tokens": 100}
    agent = build_agent(doc, _router())
    assert agent.name == "built"
    assert agent.max_steps == 4
    assert agent.temperature == 0.2
    assert agent.max_tokens == 100
    assert agent.workspace == "."
    assert agent.mcp_clients == []


def test_build_agent_wires_mcp_clients():
    doc = {
        "name": "wired",
        "mcp_servers": [
            {"name": "fs", "command": ["python", "-c", "1"], "timeout": 5},
            {"command": ["python", "-c", "2"]},  # name auto-generated
        ],
    }
    agent = build_agent(doc, _router())
    assert [c.name for c in agent.mcp_clients] == ["fs", "mcp1"]
    assert agent.mcp_clients[0].request_timeout == 5.0


def test_load_agent_end_to_end(tmp_path):
    path = tmp_path / "calc.yaml"
    path.write_text("name: calc\ntools: [calculator]\n", encoding="utf-8")
    agent = load_agent(path, _router())
    assert agent.name == "calc"
    assert "calculator" in agent.builtin_tools
