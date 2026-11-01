"""The `zyko` command-line interface.

Built on argparse only — zero third-party CLI dependencies — so the exact
same command set works on Linux, Windows, macOS and Termux with nothing to
compile.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Sequence

from zyko.cli import commands as cmd
from zyko.cli import ui
from zyko.exceptions import ZykoError
from zyko.log import setup_logging
from zyko.version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zyko",
        description=f"ZYKO v{__version__} — Universal AI Orchestration Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  zyko ask 'Explain MCP in one line' --explain\n"
            "  zyko route 'summarize this file'          # planning only, no API call\n"
            "  zyko ask 'hello' --demo                   # offline, no keys needed\n"
            "  zyko serve --port 8787                    # OpenAI-compatible gateway\n"
            "  zyko mcp serve                            # expose ZYKO as an MCP server\n"
            "  zyko doctor                               # diagnose platform + keys\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"zyko {__version__}")
    parser.add_argument("--log-level", default="WARNING", help="DEBUG/INFO/WARNING (default: WARNING)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def with_router(p: argparse.ArgumentParser) -> None:
        p.add_argument("--strategy", choices=["quality", "cost", "latency", "balanced"], default=None)
        p.add_argument("--policy", default=None, help="policy name or path (Policy-as-Code)")
        p.add_argument("--ledger", default=None, help="quality ledger JSON path")
        p.add_argument("--demo", action="store_true", help="offline mock provider: no keys, no network")

    # info / doctor / version
    sub.add_parser("info", help="platform, config and provider summary").set_defaults(func=cmd.cmd_info)
    sub.add_parser("doctor", help="diagnose environment, keys and local inference").set_defaults(func=cmd.cmd_doctor)
    sub.add_parser("version", help="print version and protocol info").set_defaults(func=cmd.cmd_version)

    # models
    p = sub.add_parser("models", help="list available models with scores")
    p.add_argument("provider", nargs="?", default=None)
    p.add_argument("--ledger", default=None)
    p.set_defaults(func=cmd.cmd_models)

    # ask
    p = sub.add_parser("ask", help="one-shot completion through the router")
    p.add_argument("prompt")
    p.add_argument("--model", default=None, help="provider/model or 'auto'")
    p.add_argument("--system", default=None)
    p.add_argument("--max-tokens", type=int, default=None)
    p.add_argument("--explain", action="store_true", help="print the routing decision")
    p.add_argument("--receipt", default=None, help="write the verification receipt to a JSON file")
    with_router(p)
    p.set_defaults(func=cmd.cmd_ask)

    # chat
    p = sub.add_parser("chat", help="interactive chat with session memory")
    p.add_argument("--session", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--system", default=None)
    p.add_argument("--max-tokens", type=int, default=None)
    with_router(p)
    p.set_defaults(func=cmd.cmd_chat)

    # route (planning only)
    p = sub.add_parser("route", help="show the routing plan (no API call)")
    p.add_argument("prompt", nargs="?", default="")
    p.add_argument("--json", action="store_true")
    with_router(p)
    p.set_defaults(func=cmd.cmd_route)

    # serve
    p = sub.add_parser("serve", help="OpenAI-compatible gateway over the router")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--api-key", default=None, help="require this bearer token on /v1/*")
    with_router(p)
    p.set_defaults(func=cmd.cmd_serve)

    # policy
    p = sub.add_parser("policy", help="Policy-as-Code: check, show, redact")
    pol = p.add_subparsers(dest="policy_cmd", required=True)
    c = pol.add_parser("check", help="validate a policy file")
    c.add_argument("file")
    c.set_defaults(func=cmd.cmd_policy)
    c = pol.add_parser("show", help="display a policy (or the builtin default)")
    c.add_argument("name", nargs="?", default=None)
    c.set_defaults(func=cmd.cmd_policy)
    c = pol.add_parser("redact", help="demo redaction on arbitrary text")
    c.add_argument("text")
    c.add_argument("name", nargs="?", default=None)
    c.set_defaults(func=cmd.cmd_policy)

    # mcp
    p = sub.add_parser("mcp", help="MCP integration")
    m = p.add_subparsers(dest="mcp_cmd", required=True)
    m.add_parser("serve", help="expose ZYKO as an MCP server over stdio").set_defaults(func=cmd.cmd_mcp)
    c = m.add_parser("tools", help="list tools of an MCP server: zyko mcp tools -- <cmd...>")
    c.add_argument("command", nargs="*", help="command to spawn (use -- before it)")
    c.set_defaults(func=cmd.cmd_mcp)

    # run (agents)
    p = sub.add_parser("run", help="run an agent from a YAML definition")
    p.add_argument("agent")
    p.add_argument("task")
    p.add_argument("--trace", action="store_true", help="print the step table")
    with_router(p)
    p.set_defaults(func=cmd.cmd_run)

    # bench
    p = sub.add_parser("bench", help="run the reproducible routing benchmark")
    p.add_argument("--update-ledger", action="store_true", help="merge results into the quality ledger")
    p.add_argument("--json-out", default=None, help="write full results JSON here")
    p.add_argument("--ledger", default=None)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument(
        "--repeats", type=int, default=1, help="repeat the suite N times for stabler medians (default 1)"
    )
    p.add_argument("--demo", action="store_true", help="benchmark the offline mock provider (CI/pipeline check)")
    p.set_defaults(func=cmd.cmd_bench)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args: Any = parser.parse_args(argv)
    quiet = not (getattr(args, "log_level", "WARNING") != "DEBUG")
    setup_logging(args.log_level if hasattr(args, "log_level") else "WARNING", quiet=quiet)
    try:
        result = args.func(args)
        return int(result or 0)
    except ZykoError as exc:
        ui.error(exc)
        return 1
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
