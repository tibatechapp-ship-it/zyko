"""CLI behaviour end-to-end (no network)."""

from __future__ import annotations

import json

import pytest
import yaml

from zyko.cli import main


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert "zyko" in capsys.readouterr().out


def test_info_runs_without_keys(capsys):
    assert main(["info"]) == 0
    out = capsys.readouterr().out
    assert "ZYKO v" in out
    assert "Providers" in out


def test_doctor_runs(capsys):
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "ZYKO doctor" in out


def test_route_without_providers_fails_cleanly(capsys):
    assert main(["route", "hello"]) == 1
    err = capsys.readouterr().err
    assert "no providers configured" in err


def test_policy_check_valid_file(tmp_path, capsys):
    path = tmp_path / "p.yaml"
    path.write_text(yaml.safe_dump({
        "version": 1, "name": "ci-policy",
        "defaults": {"budget_usd_per_day": 3.0},
        "privacy": {"redact": ["email"]},
    }), encoding="utf-8")
    assert main(["policy", "check", str(path)]) == 0
    out = capsys.readouterr().out
    assert "ci-policy" in out and "valid" in out


def test_policy_redact_demo(capsys):
    assert main(["policy", "redact", "email me at bob@corp.com please"]) == 0
    out = capsys.readouterr().out
    assert "[EMAIL]" in out and "bob@corp.com" not in out


def test_models_without_providers(capsys):
    assert main(["models"]) == 1


def test_unknown_policy_exits_1(capsys):
    assert main(["policy", "show", "definitely-missing"]) == 1


def test_receipt_json_written(tmp_path, capsys, monkeypatch):
    """`zyko ask` with a fake provider writes a verifiable receipt."""
    from tests.fakes import FakeProvider

    fake = FakeProvider(script=["routed answer"])
    monkeypatch.setattr("zyko.cli.commands.configured_providers", lambda *_a, **_k: {"fake": fake})
    receipt_path = tmp_path / "receipt.json"
    code = main(["ask", "hello", "--receipt", str(receipt_path), "--explain", "--ledger", str(tmp_path / "l.json")])
    assert code == 0
    out = capsys.readouterr().out
    assert "routed answer" in out
    assert "routed via fake/" in out
    receipt = json.loads(receipt_path.read_text())
    assert receipt["chosen"].startswith("fake/")
    assert receipt["ranking"]
