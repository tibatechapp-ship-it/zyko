"""ZYKO as an MCP server (`zyko mcp serve`).

Exposes ZYKO's capabilities — chat, verifiable routing, model discovery —
as MCP tools, so any MCP host (Claude Desktop, IDEs, other agents) can use
ZYKO as its model-routing backend. The protocol layer is stdlib-only and
async, so it runs identically on Linux, Windows, macOS and Termux.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from zyko.exceptions import ZykoError
from zyko.log import get_logger
from zyko.mcp import protocol
from zyko.version import PROTOCOL_VERSION, __version__

log = get_logger("mcp.server")

ZYKO_TOOLS: list[dict[str, Any]] = [
    {
        "name": "zyko_models",
        "description": "List AI models available to ZYKO across all configured providers.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "zyko_route",
        "description": "Explain how ZYKO would route a prompt: ranked candidates with quality/cost/latency scores (no API call).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "sample prompt to size the estimate"}
            },
            "required": [],
        },
    },
    {
        "name": "zyko_chat",
        "description": "Send a prompt through ZYKO's router (policy-checked, best candidate) and return the answer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "model": {"type": "string", "description": "optional provider/model override"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "pii_ar_scan",
        "description": (
            "Deterministic Arabic PII detection — phones (22 countries), national IDs "
            "(8 formats, checksum-validated), IBAN (mod-97), bank cards (Luhn, incl. mada), "
            "names, addresses, emails. No model needed, fully reproducible. Phase 0 (D6)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Arabic/Arabic-mixed text to scan"},
                "min_confidence": {"type": "number", "description": "default 0.5"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "rtl_check",
        "description": (
            "Deterministic RTL problem check (15 rules) for CSS / HTML / Python / text: "
            "text-align:left in RTL, physical margins, missing dir, Arabic-vs-Latin "
            "comparisons, Trojan-Source bidi chars. No model needed. Phase 0 (D6)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "source to check"},
                "lang": {
                    "type": "string",
                    "enum": ["css", "html", "python", "text"],
                    "description": "default: text",
                },
                "path": {
                    "type": "string",
                    "description": "alternative to text: check a file or folder on disk",
                },
            },
            "required": [],
        },
    },
    {
        "name": "code_review",
        "description": (
            "Deterministic Arabic code review (27 AST rules): error handling, "
            "security, quality. Score 0-100 + Arabic verdict + findings with "
            "rule id/line/col and a suggested fix each. No model, no network, "
            "byte-reproducible. Phase 2 (D22-40)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "python source to review"},
                "path": {
                    "type": "string",
                    "description": "file or folder to review (alternative to text)",
                },
                "fail_under": {
                    "type": "number",
                    "description": "minimum acceptable score, default 90",
                },
            },
            "required": [],
        },
    },
    {
        "name": "auto_fix",
        "description": (
            "Deterministic Arabic auto-fixer (12 safe AST paths over the 27 "
            "review rules): fixes bare except, raise-from, open-outside-with, "
            "shell=True on list args, mutable defaults, unsafe yaml, weak "
            "hashes, TLS verify off, missing Arabic docstrings, ==None, dead "
            "imports, lambda assigns. Every finding keeps its suggestion_ar; "
            "output re-parsed before acceptance; idempotent. Dry-run only "
            "(never writes files). No model, no network. Phase 3 (D41-58)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "python source to fix"},
                "path": {
                    "type": "string",
                    "description": "file or folder to fix (alternative to text)",
                },
                "rules": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'restrict the active auto rules, e.g. ["R-SEC-103"]',
                },
            },
            "required": [],
        },
    },
    {
        "name": "run_pipeline",
        "description": (
            "The deterministic Arabic feedback loop in one call: coder -> "
            "reviewer -> fixer (Phase 4, D59-72). Takes an Arabic project "
            "description, plans it, generates the file tree in memory, runs "
            "the 27-rule review, applies the 12 safe auto-fix paths, then "
            "re-reviews: returns per-file scores before/after and every "
            "finding's fate with its suggestion_ar. Dry-run only (never "
            "writes files, never touches the network). Same guarantees as "
            "python -m zyko.pipeline run --dry-run."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Arabic description of the project to build",
                },
                "rounds": {
                    "type": "integer",
                    "description": "review->fix rounds after generation (0 = review only, cap 3, default 1)",
                },
            },
            "required": ["description"],
        },
    },
    {
        "name": "fix_workspace",
        "description": (
            "The deterministic Arabic engine on an EXISTING project directory "
            "(Phase 5, D73-90). Walks the given directory for Python files, "
            "runs the 27-rule review, applies the 12 safe auto-fix paths in "
            "rounds, then re-reviews: returns per-file scores before/after, "
            "every finding's fate with its suggestion_ar, and skipped files "
            "(bad encoding / broken syntax) with Arabic reasons. Dry-run only "
            "(never writes files, never touches the network). Same guarantees "
            "as python -m zyko.workspace run."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to an existing Python project directory",
                },
                "rounds": {
                    "type": "integer",
                    "description": "review->fix rounds (0 = review only, cap 3, default 1)",
                },
            },
            "required": ["path"],
        },
    },
]


class ZykoMCPServer:
    """Stdio MCP server exposing ZYKO tools."""

    def __init__(self, *, router: Any = None) -> None:
        self._router = router
        self._router_built = router is not None

    # ------------------------------------------------------------- dispatch
    async def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        msg_id = message.get("id")
        if msg_id is None:
            return None  # notification: nothing to answer
        try:
            if method == "initialize":
                params = message.get("params") or {}
                requested = params.get("protocolVersion")
                return protocol.result(
                    msg_id,
                    {
                        "protocolVersion": requested
                        if requested in (None, PROTOCOL_VERSION)
                        else PROTOCOL_VERSION,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": "zyko", "version": __version__},
                    },
                )
            if method == "ping":
                return protocol.result(msg_id, {})
            if method == "tools/list":
                return protocol.result(msg_id, {"tools": ZYKO_TOOLS})
            if method == "tools/call":
                params = message.get("params") or {}
                return protocol.result(
                    msg_id,
                    await self._call_tool(params.get("name") or "", params.get("arguments") or {}),
                )
            return protocol.error(msg_id, protocol.METHOD_NOT_FOUND, f"unknown method: {method}")
        except ZykoError as exc:
            return protocol.result(
                msg_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True}
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the host, never crashes the loop
            log.exception("mcp tool call failed")
            return protocol.result(
                msg_id,
                {"content": [{"type": "text", "text": f"internal error: {exc}"}], "isError": True},
            )

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "zyko_models":
            text = self._models_text()
        elif name == "zyko_route":
            text = await self._route_text(arguments.get("prompt") or "")
        elif name == "zyko_chat":
            prompt = str(arguments.get("prompt") or "").strip()
            if not prompt:
                raise ZykoError("zyko_chat requires a non-empty 'prompt'")
            text = await self._chat_text(prompt, arguments.get("model"))
        elif name == "pii_ar_scan":
            text = self._pii_ar_scan_text(arguments)
        elif name == "rtl_check":
            text = self._rtl_check_text(arguments)
        elif name == "code_review":
            text = self._code_review_text(arguments)
        elif name == "auto_fix":
            text = self._auto_fix_text(arguments)
        elif name == "run_pipeline":
            text = self._run_pipeline_text(arguments)
        elif name == "fix_workspace":
            text = self._fix_workspace_text(arguments)
        else:
            return {
                "content": [{"type": "text", "text": f"unknown tool '{name}'"}],
                "isError": True,
            }
        return {"content": [{"type": "text", "text": text}], "isError": False}

    # -------------------------------------------------- deterministic tools
    @staticmethod
    def _pii_ar_scan_text(arguments: dict[str, Any]) -> str:
        """`pii_ar_scan` — Arabic PII findings as readable text (no model)."""
        import json

        from zyko.tools.pii_ar import TYPE_LABELS, PIIScanner

        text = str(arguments.get("text") or "")
        if not text.strip():
            raise ZykoError("pii_ar_scan requires a non-empty 'text'")
        min_conf = float(arguments.get("min_confidence") or 0.5)
        findings = PIIScanner(min_confidence=min_conf).scan(text)
        payload = {
            "tool": "pii_ar_scan",
            "count": len(findings),
            "findings": [
                {
                    "type": f.type,
                    "type_ar": TYPE_LABELS.get(f.type, f.type),
                    "value": f.value,
                    "valid": f.valid,
                    "confidence": round(f.confidence, 2),
                    "start": f.start,
                    "end": f.end,
                }
                for f in findings
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _rtl_check_text(arguments: dict[str, Any]) -> str:
        """`rtl_check` — RTL problem findings as readable text (no model)."""
        import json

        from zyko.tools.rtl import SEVERITY_AR, RTLChecker

        text_arg = arguments.get("text")
        path_arg = arguments.get("path")
        if text_arg:
            lang = arguments.get("lang") or "text"
            findings = RTLChecker().check_source(str(text_arg), lang, "<text>")
            files = 1
        elif path_arg:
            findings, files = RTLChecker().check_path(str(path_arg))
        else:
            raise ZykoError("rtl_check requires 'text' (with optional 'lang') or 'path'")
        payload = {
            "tool": "rtl_check",
            "files_scanned": files,
            "count": len(findings),
            "findings": [
                {
                    "rule": f.rule,
                    "severity": f.severity,
                    "severity_ar": SEVERITY_AR[f.severity],
                    "message": f.message,
                    "file": f.file,
                    "line": f.line,
                    "col": f.col,
                    "suggestion": f.suggestion,
                }
                for f in findings
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _code_review_text(arguments: dict[str, Any]) -> str:
        """`code_review` — مراجعة عربية حتمية للشيفرة (بلا نموذج)."""
        import json

        from zyko.reviewer import ReviewEngine

        text_arg = arguments.get("text")
        path_arg = arguments.get("path")
        fail_under = float(arguments.get("fail_under") or 90)
        engine = ReviewEngine()
        if text_arg:
            results = [engine.review_source(str(text_arg), "<text>")]
        elif path_arg:
            from pathlib import Path

            if not Path(path_arg).exists():
                raise ZykoError(f"code_review: path does not exist: {path_arg}")
            results = engine.review_path(str(path_arg))
        else:
            raise ZykoError("code_review requires 'text' or 'path'")
        if not results:
            raise ZykoError("code_review: no python files found at the given path")
        min_score = min(r.score for r in results)
        payload = {
            "tool": "code_review",
            "files": len(results),
            "min_score": min_score,
            "fail_under": fail_under,
            "passed": min_score >= fail_under,
            "results": [r.to_dict() for r in results],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _auto_fix_text(arguments: dict[str, Any]) -> str:
        """`auto_fix` — إصلاح عربي حتمي آمن (تجريبي دائمًا: لا كتابة على القرص)."""
        import json

        from zyko.fixer import FixerEngine

        text_arg = arguments.get("text")
        path_arg = arguments.get("path")
        rules_arg = arguments.get("rules")
        rules = tuple(str(r) for r in rules_arg) if rules_arg else None
        engine = FixerEngine(rules=rules)
        if text_arg:
            results = [engine.fix_source(str(text_arg), "<text>")]
        elif path_arg:
            from pathlib import Path

            if not Path(path_arg).exists():
                raise ZykoError(f"auto_fix: path does not exist: {path_arg}")
            results = engine.fix_path(str(path_arg))
        else:
            raise ZykoError("auto_fix requires 'text' or 'path'")
        if not results:
            raise ZykoError("auto_fix: no python files found at the given path")
        from zyko.fixer.engine import summarize_fix

        payload = {
            "tool": "auto_fix",
            "summary": summarize_fix(results),
            "results": [r.to_dict() for r in results],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _run_pipeline_text(arguments: dict[str, Any]) -> str:
        """`run_pipeline` — الحلقة كاملة (تجريبية دائمًا: لا كتابة على القرص)."""
        import json

        from zyko.pipeline import PipelineEngine, pipeline_payload_summary

        description = arguments.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ZykoError("run_pipeline requires a non-empty Arabic 'description'")
        rounds = arguments.get("rounds", 1)
        result = PipelineEngine().run(description, "<mcp-memory>", rounds=rounds, write=False)
        if not result.ok:
            payload = {
                "tool": "run_pipeline",
                "ok": False,
                "failed_stage": result.failed_stage,
                "error_ar": result.error_ar,
                "problems": result.problems,
            }
        else:
            payload = {
                "tool": "run_pipeline",
                "ok": True,
                "summary": pipeline_payload_summary(result),
                "plan": result.plan,
                "per_file": [dict(f) for f in result.per_file],
            }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _fix_workspace_text(arguments: dict[str, Any]) -> str:
        """`fix_workspace` — المحرك على مجلد قائم (تجريبية دائمًا: لا كتابة)."""
        import json
        from pathlib import Path

        from zyko.workspace import WorkspaceEngine, workspace_payload_summary

        path_arg = arguments.get("path")
        if not isinstance(path_arg, str) or not path_arg.strip():
            raise ZykoError("fix_workspace requires a non-empty 'path'")
        if not Path(path_arg).exists():
            raise ZykoError(f"fix_workspace: path does not exist: {path_arg}")
        rounds = arguments.get("rounds", 1)
        result = WorkspaceEngine().run(path_arg, rounds=rounds, write="none")
        if not result.ok:
            payload = {
                "tool": "fix_workspace",
                "ok": False,
                "failed_stage": result.failed_stage,
                "error_ar": result.error_ar,
            }
        else:
            payload = {
                "tool": "fix_workspace",
                "ok": True,
                "summary": workspace_payload_summary(result),
                "per_file": [dict(f) for f in result.per_file],
            }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    # --------------------------------------------------------------- backends
    def _ensure_router(self) -> Any:
        if not self._router_built:
            from zyko.config.settings import Settings
            from zyko.platform.paths import ledger_file
            from zyko.policy.engine import load_policy
            from zyko.providers import configured_providers
            from zyko.providers.mock import MockProvider, demo_enabled
            from zyko.router.engine import Router
            from zyko.router.quality import QualityLedger

            settings = Settings.load()
            if demo_enabled(settings):
                providers: dict[str, Any] = {"mock": MockProvider()}
            else:
                providers = configured_providers(settings.provider_settings)
            if not providers:
                # Keyless host: same keyless-first-run behaviour as the CLI.
                providers = {"mock": MockProvider()}
            # Same governance as the CLI: default_policy, ledger, demo mode.
            policy = None
            policy_name = settings.get("default_policy")
            if policy_name:
                policy = load_policy(policy_name)
            self._router = Router(
                providers,
                ledger=QualityLedger.load(ledger_file()),
                policy=policy,
                strategy=settings.get("router.strategy", "balanced"),
                max_fallbacks=settings.get("router.max_fallbacks", 3),
            )
            self._router_built = True
        return self._router

    def _models_text(self) -> str:
        """List the models the router can actually use (policy-filtered)."""
        router = self._ensure_router()
        lines: list[str] = []
        for provider_name in sorted(router.providers):
            provider = router.providers[provider_name]
            for info in provider.catalog():
                price = (
                    "free"
                    if info.local
                    else (
                        f"${info.input_price_per_mtok}/${info.output_price_per_mtok} per Mtok"
                        if info.input_price_per_mtok is not None
                        else "n/a"
                    )
                )
                lines.append(f"{info.qualified:50} ctx={info.context_window:>8} {price}")
        return "\n".join(lines) or "(no models)"

    async def _route_text(self, prompt: str) -> str:
        from zyko import kernel

        router = self._ensure_router()
        est_in = max(kernel.estimate_tokens(prompt), 16)
        explanation = router.explain(est_input_tokens=est_in)
        lines = [f"strategy: {explanation['strategy']}"]
        for i, entry in enumerate(explanation["ranking"][:10], 1):
            lines.append(
                f"{i:2}. {entry['candidate']:44} score={entry['total']:.3f} "
                f"(q={entry['quality']:.2f} c={entry['cost_score']:.2f} l={entry['latency_score']:.2f})"
            )
        return "\n".join(lines)

    async def _chat_text(self, prompt: str, model: str | None) -> str:
        from zyko.core.messages import Message
        from zyko.core.response import ChatRequest

        router = self._ensure_router()
        request = ChatRequest(messages=[Message.user(prompt)], model=model)
        outcome = await router.aroute(request)
        assert outcome.response is not None
        receipt = outcome.receipt
        return (
            f"{outcome.response.text}\n\n"
            f"---\nrouted via {receipt['chosen']} (strategy={receipt['strategy']}, "
            f"attempts={len(receipt['attempts'])})"
        )

    # ------------------------------------------------------------------ loop
    async def serve(self, *, stdin=None, stdout=None) -> None:
        stdin = stdin or sys.stdin.buffer
        stdout = stdout or sys.stdout.buffer

        async def byte_iter():
            while True:
                line = await asyncio.to_thread(stdin.readline)
                if not line:
                    return
                yield line

        async for raw in _lines(byte_iter()):
            if isinstance(raw, bytes):
                # Undecodable frame: answer per JSON-RPC 2.0 spec (parse error,
                # id null) and keep serving — a bad line must not kill the host.
                response = protocol.error(None, protocol.PARSE_ERROR, "invalid JSON-RPC frame")
            else:
                message = raw
                response = await self.handle(message)
            if response is not None:
                stdout.write(protocol.encode(response))
                await asyncio.to_thread(stdout.flush)


async def _lines(byte_iter):
    buf = b""
    async for chunk in byte_iter:
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line.strip():
                try:
                    yield protocol.decode(line)
                except ZykoError as exc:
                    log.warning("mcp server dropped undecodable frame: %s", exc)
                    yield b"__undecodable__"


def main() -> int:
    """Console entrypoint for `zyko mcp serve`."""
    server = ZykoMCPServer()
    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
