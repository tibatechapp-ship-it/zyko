"""Public-surface invariants: what `import zyko` and `zyko --help` promise
must stay true. Renames, removals, or broken CLI verbs fail here first."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import zyko
from tests.fakes import FakeProvider

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ZYKO = SRC / "zyko"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
MCP_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _cli(*argv: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    return subprocess.run(
        [sys.executable, "-m", "zyko", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=env,
    )


def test_all_exports_resolve_from_top_level():
    missing = [name for name in zyko.__all__ if not hasattr(zyko, name)]
    assert not missing, f"__all__ promises names the package does not ship: {missing}"


def test_all_exports_are_public_objects():
    weird = [
        name
        for name in zyko.__all__
        if not (callable(getattr(zyko, name)) or isinstance(getattr(zyko, name), str))
    ]
    assert not weird, f"exports that are neither callable nor version strings: {weird}"


def test_exception_hierarchy_roots_at_zyko_error():
    assert issubclass(zyko.ZykoError, Exception)
    for exc in (
        zyko.CrewError,
        zyko.GatewayAuthError,
        zyko.EmbedderError,
        zyko.SchemaSpecError,
        zyko.StructuredOutputError,
    ):
        assert issubclass(exc, zyko.ZykoError), f"{exc.__name__} left the hierarchy"
    assert issubclass(zyko.GatewayAuthError, Exception)


def test_client_constructs_offline_with_injected_provider():
    zk = zyko.Zyko(providers={"fake": FakeProvider(name="fake")})
    assert "fake" in zk.providers
    assert callable(zk.ask)
    assert callable(zk.structured)


def test_client_rejects_empty_configuration_cleanly():
    """No keys and no injected providers → typed error, never a traceback."""
    import pytest

    from zyko.exceptions import ProviderError

    with pytest.raises(ProviderError):
        zyko.Zyko()


def test_cli_build_parser_returns_argument_parser():
    from zyko.cli import build_parser

    parser = build_parser()
    assert parser.prog == "zyko"


def test_cli_help_lists_core_verbs():
    proc = _cli("--help")
    assert proc.returncode == 0
    for verb in ("ask", "route", "verify", "serve", "mcp", "factory"):
        assert verb in proc.stdout, f"core verb {verb!r} missing from --help"


def test_cli_dash_version_reports_runtime_version():
    proc = _cli("--version")
    assert proc.returncode == 0
    assert proc.stdout.strip() == f"zyko {zyko.__version__}"


def test_cli_unknown_command_exits_2_with_clean_error():
    proc = _cli("definitely-not-a-command")
    assert proc.returncode == 2
    assert "invalid choice" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_protocol_and_user_agent_track_version():
    from zyko.version import USER_AGENT

    assert MCP_DATE.match(zyko.PROTOCOL_VERSION), "PROTOCOL_VERSION must be an MCP date"
    assert USER_AGENT == f"zyko/{zyko.__version__}"
    assert SEMVER.match(zyko.__version__)


def test_package_is_py_typed():
    assert (ZYKO / "py.typed").is_file(), "py.typed marker missing from the package"
