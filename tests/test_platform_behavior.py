"""Platform behavior invariants: the CLI end-to-end, offline, on every host.

Nothing here may touch the network: demo providers, planning-only routes and
offline receipt verification are the behaviors ZYKO promises to Termux and
air-gapped boxes. Each test drives `python -m zyko` in a subprocess so the
real entrypoint (not a shortcut) is what is proven."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ZYKO = SRC / "zyko"


def run_cli(*argv: str, env_extra: dict[str, str] | None = None):
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "zyko", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=env,
    )


def test_cli_version_reports_protocol_offline():
    proc = run_cli("version")
    assert proc.returncode == 0
    assert "MCP protocol" in proc.stdout


def test_cli_info_runs_offline():
    proc = run_cli("info")
    assert proc.returncode == 0
    assert "ZYKO v" in proc.stdout


def test_cli_route_plans_without_network():
    proc = run_cli("route", "summarize this file")
    assert proc.returncode == 0
    assert "routing plan" in proc.stdout
    assert "strategy" in proc.stdout


def test_cli_models_warns_cleanly_without_providers():
    proc = run_cli("models")
    assert proc.returncode == 1
    assert "no models available" in proc.stdout + proc.stderr
    assert "Traceback" not in proc.stdout + proc.stderr


def test_demo_ask_arabic_prompt_receipt_roundtrip(tmp_path):
    receipt = tmp_path / "receipt.json"
    ask = run_cli("ask", "اشرح MCP في سطر واحد", "--demo", "--receipt", str(receipt))
    assert ask.returncode == 0, ask.stderr
    assert receipt.is_file(), "ask --demo did not write the receipt"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload, "receipt is empty"
    verify = run_cli("verify", str(receipt))
    assert verify.returncode == 0
    assert "verified" in verify.stdout.lower()


def test_verify_missing_receipt_fails_cleanly(tmp_path):
    proc = run_cli("verify", str(tmp_path / "nope.json"))
    assert proc.returncode == 1
    assert "does not exist" in proc.stdout + proc.stderr
    assert "Traceback" not in proc.stdout + proc.stderr


def test_verify_corrupt_receipt_fails_cleanly(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"broken": true}', encoding="utf-8")
    proc = run_cli("verify", str(bad))
    assert proc.returncode == 1
    assert "Traceback" not in proc.stdout + proc.stderr


def test_unknown_command_exits_2():
    proc = run_cli("not-a-verb")
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr


def test_platform_module_is_stdlib_only():
    stdlib = sys.stdlib_module_names
    offenders: list[str] = []
    for path in sorted(ZYKO.joinpath("platform").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in stdlib and root != "zyko":
                        offenders.append(f"{path.name}: {root}")
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                root = node.module.split(".")[0]
                if root not in stdlib and root != "zyko":
                    offenders.append(f"{path.name}: {root}")
    assert not offenders, f"platform layer pulled third-party code: {offenders}"


def test_env_override_is_visible_through_cli_info(tmp_path):
    override = tmp_path / "custom-config"
    proc = run_cli("info", env_extra={"ZYKO_CONFIG_DIR": str(override)})
    assert proc.returncode == 0
    assert str(override) in proc.stdout, (
        "zyko info ignored ZYKO_CONFIG_DIR — state would leak to the default dir"
    )
