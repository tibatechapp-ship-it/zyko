"""Command implementations for the ZYKO CLI."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from zyko import kernel
from zyko.agents.loader import build_agent, load_agent_document
from zyko.agents.memory import MemoryStore
from zyko.cli import ui
from zyko.cli.ui import bold
from zyko.config.settings import Settings
from zyko.core.messages import Message
from zyko.exceptions import ConfigError, ZykoError
from zyko.log import get_logger
from zyko.platform import cache_dir, config_dir, config_file, data_dir, platform_info
from zyko.policy.engine import PolicyEngine, builtin_default_policy, load_policy
from zyko.providers import configured_providers, get_provider_class, is_configured, provider_names
from zyko.router.engine import Router
from zyko.router.quality import QualityLedger
from zyko.utils.loop import run_sync
from zyko.version import __version__

log = get_logger("cli")


# --------------------------------------------------------------------- helpers
def _build_router(args: Any) -> Router:
    settings = Settings.load()
    providers = configured_providers(settings.provider_settings)
    ledger = QualityLedger.load(_ledger_path(args))
    policy = None
    name = getattr(args, "policy", None) or settings.get("default_policy")
    if name:
        policy = load_policy(name)
    return Router(
        providers,
        ledger=ledger,
        policy=policy,
        strategy=getattr(args, "strategy", None) or settings.get("router.strategy", "balanced"),
        max_fallbacks=int(settings.get("router.max_fallbacks", 3)),
    )


def _ledger_path(args: Any):
    from zyko.platform.paths import ledger_file

    return Path(getattr(args, "ledger", None)) if getattr(args, "ledger", None) else ledger_file()


# ------------------------------------------------------------------- commands
def cmd_info(args: Any) -> int:
    p = platform_info()
    print(bold(f"ZYKO v{__version__}"))
    ui.kv("platform", p.describe())
    ui.kv("kernel backend", kernel.backend())
    ui.kv("config file", config_file())
    ui.kv("config dir", config_dir())
    ui.kv("data dir", data_dir())
    ui.kv("cache dir", cache_dir())
    try:
        import httpx  # noqa: F401
        import yaml  # noqa: F401

        ui.kv("dependencies", "httpx, PyYAML — ok")
    except ImportError as exc:
        print(ui.warn(f"missing dependency: {exc}"))
    print()
    print(bold("Providers"))
    for name in provider_names():
        cls = get_provider_class(name)
        configured = is_configured(name, Settings.load().provider_setting(name))
        env = cls.KEY_ENV if isinstance(cls.KEY_ENV, str) else (", ".join(cls.KEY_ENV) if cls.KEY_ENV else "n/a (local)")
        state = ui.ok("configured") if configured else ui.warn(f"needs {env}")
        print(f"  {name:<12} {state}")
    return 0


def cmd_models(args: Any) -> int:
    settings = Settings.load()
    providers = configured_providers(settings.provider_settings)
    if args.provider:
        providers = {k: v for k, v in providers.items() if k == args.provider}
        if not providers:
            raise ConfigError(f"provider '{args.provider}' is not configured")
    rows = []
    for name, provider in sorted(providers.items()):
        for info in provider.catalog():
            mscore = QualityLedger.load(_ledger_path(args)).score(name, info.id)
            price = (
                "local/free"
                if info.local
                else (
                    f"${info.input_price_per_mtok}/${info.output_price_per_mtok}/Mtok"
                    if info.input_price_per_mtok is not None
                    else "-"
                )
            )
            rows.append([info.qualified, info.context_window, price, f"{mscore.quality:.3f}", ",".join(info.tags)])
    if not rows:
        print(ui.warn("no models available — configure a provider key or start Ollama"))
        return 1
    ui.table(["model", "ctx", "price", "quality", "tags"], rows)
    return 0


def cmd_ask(args: Any) -> int:
    router = _build_router(args)
    started = time.perf_counter()
    outcome = router.route(_request_from(args))
    assert outcome.response is not None
    print(outcome.response.text)
    if args.explain:
        receipt = outcome.receipt
        print()
        print(ui.bold(f"routed via {receipt['chosen']} ({receipt['strategy']}, {outcome.response.latency_ms:.0f} ms)"))
        for i, entry in enumerate(receipt["ranking"][:5], 1):
            print(f"  {i}. {entry['candidate']:<40} score={entry['total']:.3f}")
    if args.receipt:
        Path(args.receipt).write_text(json.dumps(outcome.receipt, indent=2), encoding="utf-8")
        print(ui.info(f"receipt written to {args.receipt}"), file=sys.stderr)
    _ = started
    return 0


def cmd_route(args: Any) -> int:
    router = _build_router(args)
    explanation = router.explain()
    if args.json:
        print(json.dumps(explanation, indent=2))
        return 0
    print(ui.bold(f"routing plan — strategy: {explanation['strategy']}"))
    rows = [
        [i, e["candidate"], f"{e['total']:.3f}", f"{e['quality']:.2f}", f"{e['cost_score']:.2f}",
         f"{e['latency_score']:.2f}",
         "-" if e["estimated_cost_usd"] is None else f"${e['estimated_cost_usd']:.6f}"]
        for i, e in enumerate(explanation["ranking"], 1)
    ]
    ui.table(["#", "candidate", "score", "quality", "cost", "latency", "est$/req"], rows)
    print()
    print(ui.info("planning only — no API call made. Use `zyko ask` to execute."))
    return 0


def cmd_chat(args: Any) -> int:
    router = _build_router(args)
    store = MemoryStore()
    session = args.session or store.create_session()
    history = store.history(session)
    print(ui.info(f"session {session} — {len(history)} messages loaded. /exit to quit, /new, /model <p/m>"))
    model = args.model
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("/exit", "/quit"):
            break
        if line == "/new":
            session = store.create_session()
            history = []
            print(ui.info(f"new session {session}"))
            continue
        if line.startswith("/session"):
            print(ui.info(f"current session: {session}"))
            continue
        if line.startswith("/model "):
            model = line.split(" ", 1)[1].strip() or None
            print(ui.info(f"model → {model or 'auto'}"))
            continue
        store.append(session, Message.user(line))
        request = _request_from(args, prompt=line, model=model, history=history)
        try:
            outcome = router.route(request)
            answer = outcome.response.text if outcome.response else ""
            print(f"zyko> {answer}")
            store.append(session, Message.assistant(answer))
            chosen = outcome.receipt.get("chosen")
            print(ui.info(f"via {chosen} · {outcome.response.latency_ms:.0f} ms"))
        except ZykoError as exc:
            print(ui.fail(str(exc).splitlines()[0]))
        history = store.history(session)
    return 0


def cmd_serve(args: Any) -> int:
    from zyko.gateway.server import serve

    settings = Settings.load()
    router = _build_router(args)
    api_key = args.api_key or settings.get("gateway.api_key")
    host = args.host or settings.get("gateway.host", "127.0.0.1")
    port = int(args.port or settings.get("gateway.port", 8787))
    httpd = serve(router, host=host, port=port, api_key=api_key)
    print(ui.ok(f"gateway on http://{host}:{port}/v1  (OpenAI-compatible) — Ctrl+C to stop"))
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        httpd.shutdown()
    return 0


def cmd_policy(args: Any) -> int:
    if args.policy_cmd == "check":
        engine = load_policy(args.file)
        _print_policy(engine)
        print(ui.ok(f"policy '{engine.name}' is valid"))
        return 0
    if args.policy_cmd == "show":
        if args.name:
            engine = load_policy(args.name)
            _print_policy(engine)
        else:
            _print_policy(PolicyEngine(builtin_default_policy()))
        return 0
    if args.policy_cmd == "redact":
        engine = load_policy(args.name) if args.name else PolicyEngine(builtin_default_policy())
        engine.doc.setdefault("privacy", {})["redact"] = engine.doc.get("privacy", {}).get("redact") or [
            "email", "phone", "credit_card", "iban", "ssn"
        ]
        from zyko.policy.engine import Redactor

        engine.redactor = Redactor.from_doc(engine.doc["privacy"])
        print(engine.redact_text(args.text))
        return 0
    raise ConfigError(f"unknown policy subcommand: {args.policy_cmd}")


def _print_policy(engine: PolicyEngine) -> None:
    snap = engine.snapshot()
    print(ui.bold(f"policy: {snap['policy']}"))
    ui.kv("budget remaining", "-" if snap["budget_remaining_usd"] is None else f"${snap['budget_remaining_usd']:.2f}")
    ui.kv("redaction", "on" if snap["redaction_active"] else "off")
    ui.kv("rate limit", snap["rate_limit_rpm"] or "off")
    models = engine.doc.get("models") or {}
    ui.kv("models allow", ", ".join(models.get("allow", ["*"])))
    if models.get("deny"):
        ui.kv("models deny", ", ".join(models["deny"]))
    if engine.doc.get("tools", {}).get("deny"):
        ui.kv("tools deny", ", ".join(engine.doc["tools"]["deny"]))


def cmd_mcp(args: Any) -> int:
    if args.mcp_cmd == "serve":
        from zyko.mcp.server import main as mcp_main

        return mcp_main()
    if args.mcp_cmd == "tools":
        if not args.command:
            raise ConfigError("usage: zyko mcp tools -- <command> [args...]", hint="e.g. zyko mcp tools -- npx -y mcp-server-fetch")
        from zyko.mcp.client import MCPClient

        client = MCPClient("cli", args.command).start_sync()
        try:
            tools = client.list_tools_sync()
        finally:
            client.close_sync()
        ui.table(["tool", "description"], [[t["name"], (t["description"] or "")[:60]] for t in tools])
        return 0
    raise ConfigError(f"unknown mcp subcommand: {args.mcp_cmd}")


def cmd_run(args: Any) -> int:
    router = _build_router(args)
    doc = load_agent_document(args.agent)
    agent = build_agent(doc, router, policy=router.policy, workspace=doc.get("workspace", "."))
    tools = run_sync(agent.tool_specs())
    print(ui.info(f"agent '{agent.name}' · tools: {', '.join(t['name'] for t in tools) or '(none)'}"))
    result = agent.run_sync(args.task)
    print(result.output)
    if args.trace:
        print()
        ui.table(["step", "routed via", "tools"], [[s["step"], s["candidate"], ",".join(s["tool_calls"]) or "-"] for s in result.steps])
    print(ui.info(f"{len(result.steps)} steps · {result.elapsed_s:.1f}s · tokens in={result.usage_input_tokens} out={result.usage_output_tokens}"), file=sys.stderr)
    return 0


def cmd_bench(args: Any) -> int:
    from zyko.benchmarks.routing_bench import run_bench

    return run_bench(args)


def cmd_doctor(args: Any) -> int:
    print(bold("ZYKO doctor"))
    p = platform_info()
    ui.kv("os", p.describe())
    if p.os.value in ("termux", "android"):
        ui.kv("mobile", "yes — ZYKO runs natively; see android/README.md for tips")
    ui.kv("kernel", kernel.backend())
    settings = Settings.load()
    ui.kv("config", str(settings.source) if settings.source else "(defaults only — no config file found)")
    print()
    print(bold("Provider keys"))
    any_key = False
    for name in provider_names():
        cls = get_provider_class(name)
        section = settings.provider_setting(name)
        configured = is_configured(name, section)
        env = cls.KEY_ENV if isinstance(cls.KEY_ENV, str) else (", ".join(cls.KEY_ENV) if cls.KEY_ENV else "local")
        any_key = any_key or configured
        print(f"  {'OK ' if configured else '-- '} {name:<12} ({env})")
    if not any_key:
        print(ui.warn("no provider keys found — set one, or install Ollama for a keyless local setup"))
    print()
    print(bold("Local inference"))
    try:
        import httpx

        resp = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2.0)
        models = [m.get("name") for m in resp.json().get("models", [])]
        print(ui.ok(f"ollama reachable — models: {', '.join(models) or '(none pulled)'}"))
    except Exception:
        print(ui.warn("ollama not reachable at 127.0.0.1:11434 (optional, but great on Termux/phone)"))
    print()
    print(ui.ok("doctor finished"))
    return 0


# ----------------------------------------------------------------- shared bits
def _request_from(args: Any, *, prompt: str | None = None, model: str | None = None, history=None):
    from zyko.core.messages import Message
    from zyko.core.response import ChatRequest

    text = prompt if prompt is not None else getattr(args, "prompt", "")
    messages = list(history or [])
    if getattr(args, "system", None) and not messages:
        messages.append(Message.system(args.system))
    messages.append(Message.user(text))
    return ChatRequest(
        messages=messages,
        model=model or getattr(args, "model", None),
        max_tokens=getattr(args, "max_tokens", None),
    )
