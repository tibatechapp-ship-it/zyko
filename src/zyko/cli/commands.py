"""Command implementations for the ZYKO CLI."""

from __future__ import annotations

import json
import os
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
    demo = getattr(args, "demo", False) or os.environ.get("ZYKO_DEMO") == "1"
    if not demo:
        providers = configured_providers(settings.provider_settings)
        if not providers:
            # Keyless first run: instead of failing, fall back to the built-in
            # deterministic demo provider so every command works out of the box
            # on every platform (Linux, Windows, macOS, Android, Termux).
            demo = True
            print(
                ui.warn(
                    "no providers configured — using the built-in demo provider "
                    "(deterministic, offline). Export an API key or start Ollama "
                    "for real inference."
                ),
                file=sys.stderr,
            )
    if demo:
        from zyko.providers.mock import MockProvider

        providers = {"mock": MockProvider()}
    else:
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
        cache=policy.cache if policy else None,
    )


def _ledger_path(args: Any):
    from zyko.platform.paths import ledger_file

    return Path(getattr(args, "ledger", None)) if getattr(args, "ledger", None) else ledger_file()


# ------------------------------------------------------------------- commands
def cmd_version(args: Any) -> int:
    from zyko.version import PROTOCOL_VERSION

    print(f"zyko {__version__} (MCP protocol {PROTOCOL_VERSION})")
    return 0


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
        env = (
            cls.KEY_ENV
            if isinstance(cls.KEY_ENV, str)
            else (", ".join(cls.KEY_ENV) if cls.KEY_ENV else "n/a (local)")
        )
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
            rows.append(
                [
                    info.qualified,
                    info.context_window,
                    price,
                    f"{mscore.quality:.3f}",
                    ",".join(info.tags),
                ]
            )
    if not rows:
        print(ui.warn("no models available — configure a provider key or start Ollama"))
        return 1
    ui.table(["model", "ctx", "price", "quality", "tags"], rows)
    return 0


def cmd_ask(args: Any) -> int:
    router = _build_router(args)
    outcome = router.route(_request_from(args))
    assert outcome.response is not None
    print(outcome.response.text)
    if args.explain:
        receipt = outcome.receipt
        print()
        print(
            ui.bold(
                f"routed via {receipt['chosen']} ({receipt['strategy']}, {outcome.response.latency_ms:.0f} ms)"
            )
        )
        for i, entry in enumerate(receipt["ranking"][:5], 1):
            print(f"  {i}. {entry['candidate']:<40} score={entry['total']:.3f}")
    if args.receipt:
        Path(args.receipt).write_text(json.dumps(outcome.receipt, indent=2), encoding="utf-8")
        print(ui.info(f"receipt written to {args.receipt}"), file=sys.stderr)
    return 0


def cmd_route(args: Any) -> int:
    router = _build_router(args)
    prompt = (getattr(args, "prompt", "") or "").strip()
    if prompt:
        # A prompt makes the token estimate (and therefore the cost column)
        # reflect the actual request instead of a generic default.
        explanation = router.explain(est_input_tokens=max(kernel.estimate_tokens(prompt), 1))
    else:
        explanation = router.explain()
    if args.json:
        print(json.dumps(explanation, indent=2))
        return 0
    print(ui.bold(f"routing plan — strategy: {explanation['strategy']}"))
    rows = [
        [
            i,
            e["candidate"],
            f"{e['total']:.3f}",
            f"{e['quality']:.2f}",
            f"{e['cost_score']:.2f}",
            f"{e['latency_score']:.2f}",
            "-" if e["estimated_cost_usd"] is None else f"${e['estimated_cost_usd']:.6f}",
        ]
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
    print(
        ui.info(
            f"session {session} — {len(history)} messages loaded. /exit to quit, /new, /model <p/m>"
        )
    )
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
    users_source = args.users or settings.get("gateway.users")
    users = None
    if users_source:
        from zyko.gateway.auth import UserStore

        users = UserStore.load(users_source)
    host = args.host or settings.get("gateway.host", "127.0.0.1")
    port = int(args.port or settings.get("gateway.port", 8787))
    try:
        httpd = serve(router, host=host, port=port, api_key=api_key, users=users)
    except OSError as exc:
        # A busy/protected port used to escape as a raw OSError traceback.
        raise ConfigError(
            f"cannot start gateway on {host}:{port}: {exc.strerror or exc}",
            hint="port already in use? stop the other process or run `zyko serve --port 8788`",
        ) from exc
    mode = f"multi-user ({len(users.snapshot())} users)" if users else "single-token/open"
    print(
        ui.ok(f"gateway on http://{host}:{port}/v1  (OpenAI-compatible, {mode}) — Ctrl+C to stop")
    )
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        httpd.shutdown()
    return 0


def cmd_hash_key(args: Any) -> int:
    from getpass import getpass

    from zyko.gateway.auth import hash_key

    key = args.key or getpass("API key to hash (input hidden): ")
    if not key or not key.strip():
        print(ui.fail("empty key — nothing hashed"), file=sys.stderr)
        return 1
    print(hash_key(key))
    print(ui.info("paste this into key_hash: in your users file — never ship the plaintext key"))
    return 0


def cmd_policy(args: Any) -> int:
    if args.policy_cmd == "check":
        engine = load_policy(args.file)
        _print_policy(engine)
        for warning in engine.warnings:
            print(ui.warn(warning))
        if engine.warnings:
            print(
                ui.warn(f"policy '{engine.name}' is valid with {len(engine.warnings)} warning(s)")
            )
        else:
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
        engine.doc.setdefault("privacy", {})["redact"] = engine.doc.get("privacy", {}).get(
            "redact"
        ) or ["email", "phone", "credit_card", "iban", "ssn"]
        from zyko.policy.engine import Redactor

        engine.redactor = Redactor.from_doc(engine.doc["privacy"])
        print(engine.redact_text(args.text))
        return 0
    raise ConfigError(f"unknown policy subcommand: {args.policy_cmd}")


def _print_policy(engine: PolicyEngine) -> None:
    snap = engine.snapshot()
    print(ui.bold(f"policy: {snap['policy']}"))
    ui.kv(
        "budget remaining",
        "-" if snap["budget_remaining_usd"] is None else f"${snap['budget_remaining_usd']:.2f}",
    )
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
            raise ConfigError(
                "usage: zyko mcp tools -- <command> [args...]",
                hint="e.g. zyko mcp tools -- npx -y mcp-server-fetch",
            )
        from zyko.mcp.client import MCPClient

        client = MCPClient("cli", args.command).start_sync()
        try:
            tools = client.list_tools_sync()
        finally:
            client.close_sync()
        ui.table(
            ["tool", "description"], [[t["name"], (t["description"] or "")[:60]] for t in tools]
        )
        return 0
    raise ConfigError(f"unknown mcp subcommand: {args.mcp_cmd}")


def cmd_run(args: Any) -> int:
    router = _build_router(args)
    doc = load_agent_document(args.agent)
    agent = build_agent(doc, router, policy=router.policy, workspace=doc.get("workspace", "."))
    tools = run_sync(agent.tool_specs())
    print(
        ui.info(f"agent '{agent.name}' · tools: {', '.join(t['name'] for t in tools) or '(none)'}")
    )
    result = agent.run_sync(args.task)
    print(result.output)
    if args.trace:
        print()
        ui.table(
            ["step", "routed via", "tools"],
            [[s["step"], s["candidate"], ",".join(s["tool_calls"]) or "-"] for s in result.steps],
        )
    print(
        ui.info(
            f"{len(result.steps)} steps · {result.elapsed_s:.1f}s · tokens in={result.usage_input_tokens} out={result.usage_output_tokens}"
        ),
        file=sys.stderr,
    )
    return 0


def cmd_crew(args: Any) -> int:
    from dataclasses import asdict

    from zyko.crew.loader import load_crew

    router = _build_router(args)
    crew = load_crew(args.file, router, policy=router.policy)
    result = crew.run(args.input)
    if args.json:
        # Machine contract: stdout carries ONLY the CrewResult JSON.
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0
    tools = [t for step in crew.steps for t in step.agent.builtin_tools]
    print(
        ui.info(
            f"crew '{crew.name}' · {len(crew.steps)} step(s) · agents: "
            + ", ".join(step.agent.name for step in crew.steps)
            + (f" · tools: {len(tools)}" if tools else "")
        )
    )
    print(result.output)
    if args.trace:
        print()
        ui.table(
            ["step", "agent", "key", "agent-steps", "truncated"],
            [
                [
                    s["step"],
                    s["agent"],
                    s["key"],
                    s["agent_steps"],
                    "yes" if s["truncated"] else "-",
                ]
                for s in result.steps
            ],
        )
    print(
        ui.info(
            f"{len(result.steps)} step(s) · {result.elapsed_s:.1f}s · tokens in={result.usage_input_tokens} out={result.usage_output_tokens}"
        ),
        file=sys.stderr,
    )
    return 0


def cmd_bench(args: Any) -> int:
    from zyko.benchmarks.routing_bench import run_bench

    return run_bench(args)


def cmd_verify(args: Any) -> int:
    """`zyko verify` — recompute a receipt offline; exit 1 on any drift.

    This is the runnable half of the "verifiable routing" claim: the receipt
    is checked against its own arithmetic, the published strategy weights and
    (optionally) the quality ledger that produced it. No network, no trust in
    the process that wrote the file.
    """
    from zyko.router.verify import load_receipt, verify_receipt

    receipt = load_receipt(args.receipt)
    ledger = None
    if getattr(args, "ledger", None):
        ledger = QualityLedger.load(Path(args.ledger))
    report = verify_receipt(receipt, ledger=ledger, tolerance=float(args.tolerance))

    if getattr(args, "json", False):
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
        return 0 if report.ok else 1

    if report.ok:
        print(ui.ok(f"receipt verified — {report.checks} checks passed"))
    else:
        print(ui.fail(f"receipt INVALID — {len(report.issues)} issue(s) in {report.checks} checks"))
        ui.bullets(f"{issue.code}: {issue.message}" for issue in report.issues)
    ui.kv("strategy", report.strategy or "-")
    ui.kv("chosen", report.chosen or "-")
    if report.total is not None:
        ui.kv("total", f"{report.total:.4f}")
    if report.created is not None:
        ui.kv("created", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(report.created)))
    return 0 if report.ok else 1


def cmd_sessions(args: Any) -> int:
    """`zyko sessions list|show|rm|clear` — make stored memory visible."""
    store = MemoryStore()
    action = args.sessions_cmd
    if action == "list":
        rows = store.list_sessions()
        if not rows:
            print(ui.info("no sessions yet — start one with `zyko chat`"))
            return 0
        ui.table(
            ["session", "messages", "updated", "title"],
            [
                [
                    r["id"],
                    r["messages"],
                    time.strftime("%Y-%m-%d %H:%M", time.localtime(r["updated"])),
                    (r["title"] or "-")[:40],
                ]
                for r in rows
            ],
        )
        return 0
    if action == "show":
        history = store.history(args.session_id)
        if not history:
            print(ui.warn(f"session '{args.session_id}' is empty or missing"))
            return 1
        for message in history:
            if message.tool_calls:
                calls = ", ".join(
                    f"{tc.name}({json.dumps(tc.arguments, ensure_ascii=False)})"
                    for tc in message.tool_calls
                )
                print(f"{message.role.value:>9} | {calls}")
            else:
                text = (message.content or "").replace("\n", " ")
                print(f"{message.role.value:>9} | {text}")
        return 0
    if action == "rm":
        removed = sum(1 for sid in args.session_ids if store.delete_session(sid))
        print(ui.ok(f"removed {removed} session(s)"))
        return 0
    if action == "clear":
        if not args.yes:
            raise ConfigError(
                "refusing to wipe all sessions without --yes",
                hint="run `zyko sessions clear --yes` to confirm",
            )
        count = store.clear()
        print(ui.ok(f"removed {count} session(s)"))
        return 0
    raise ConfigError(f"unknown sessions subcommand: {action}")


def cmd_cost(args: Any) -> int:
    """`zyko cost` — spend & governance report from the policy audit log."""
    from zyko.platform.paths import audit_log

    path = Path(args.audit) if getattr(args, "audit", None) else audit_log()
    if not path.is_file():
        if args.json:
            # Machine consumers (`zyko cost --json | jq`) must always get valid
            # JSON — an [INFO] line here used to break every downstream pipe.
            print(
                json.dumps(
                    {
                        "audit_file": str(path),
                        "window_days": args.days,
                        "events": {},
                        "total_spend_usd": 0.0,
                        "spend_by_day": {},
                        "spend_by_candidate": {},
                        "denied_by_rule": {},
                        "redaction_events": 0,
                        "cost_accounting": {"vendor_reported": 0, "kernel_estimated": 0},
                    },
                    indent=2,
                )
            )
        else:
            print(
                ui.info(f"no audit log at {path} — entries appear once a policy processes traffic")
            )
        return 0
    cutoff = time.time() - args.days * 86400 if args.days else 0.0
    events: dict[str, int] = {}
    spend_by_day: dict[str, float] = {}
    spend_by_candidate: dict[str, float] = {}
    denied_by_rule: dict[str, int] = {}
    redaction_events = 0
    estimated_entries = 0
    vendor_entries = 0
    total_spend = 0.0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            if cutoff and float(entry.get("ts") or 0) < cutoff:
                continue
            event = entry.get("event") or "unknown"
            events[event] = events.get(event, 0) + 1
            if event == "usage":
                cost = float(entry.get("cost") or 0.0)
                total_spend += cost
                day = time.strftime("%Y-%m-%d", time.localtime(float(entry.get("ts") or 0)))
                spend_by_day[day] = spend_by_day.get(day, 0.0) + cost
                candidate = entry.get("candidate") or "(unknown)"
                spend_by_candidate[candidate] = spend_by_candidate.get(candidate, 0.0) + cost
                if entry.get("estimated"):
                    estimated_entries += 1
                else:
                    vendor_entries += 1
            elif event == "deny":
                rule = entry.get("rule") or "unknown"
                denied_by_rule[rule] = denied_by_rule.get(rule, 0) + 1
            elif event == "allow" and entry.get("redactions"):
                redaction_events += 1
    if args.json:
        print(
            json.dumps(
                {
                    "audit_file": str(path),
                    "window_days": args.days,
                    "events": events,
                    "total_spend_usd": round(total_spend, 6),
                    "spend_by_day": {d: round(v, 6) for d, v in sorted(spend_by_day.items())},
                    "spend_by_candidate": {
                        c: round(v, 6) for c, v in sorted(spend_by_candidate.items())
                    },
                    "denied_by_rule": denied_by_rule,
                    "redaction_events": redaction_events,
                    "cost_accounting": {
                        "vendor_reported": vendor_entries,
                        "kernel_estimated": estimated_entries,
                    },
                },
                indent=2,
            )
        )
        return 0
    print(ui.bold(f"ZYKO cost & governance report — last {args.days or 'all'} day(s)"))
    ui.kv("audit file", str(path))
    for event in sorted(events):
        ui.kv(f"event {event}", events[event])
    ui.kv("total spend", f"${total_spend:.6f}")
    ui.kv(
        "cost accounting",
        f"vendor={vendor_entries}, estimated={estimated_entries}",
    )
    if spend_by_day:
        ui.table(
            ["day", "spend (USD)"],
            [[day, f"${value:.6f}"] for day, value in sorted(spend_by_day.items())],
        )
    if spend_by_candidate:
        top = sorted(spend_by_candidate.items(), key=lambda pair: pair[1], reverse=True)[:10]
        ui.table(
            ["candidate", "spend (USD)"],
            [[cand, f"${value:.6f}"] for cand, value in top],
        )
    if denied_by_rule:
        ui.table(
            ["deny rule", "count"],
            [[rule, count] for rule, count in sorted(denied_by_rule.items())],
        )
    if redaction_events:
        ui.kv("redaction events", redaction_events)
    return 0


def cmd_cache(args: Any) -> int:
    """`zyko cache` — inspect or clear the policy-gated response cache."""
    router = _build_router(args)
    cache = router.cache
    if cache is None:
        if args.json:
            # Machine consumers (`zyko cache --json | jq`) must always get valid
            # JSON — the same contract `zyko cost --json` holds.
            print(json.dumps({"enabled": False, "entries": 0, "hit_rate": 0.0}, indent=2))
            return 0
        print(
            ui.warn(
                "response cache is disabled — enable it in the policy:\n"
                "  cache:\n"
                "    enabled: true\n"
                "    ttl_s: 300        # seconds an entry stays valid\n"
                "    max_entries: 512  # LRU bound"
            )
        )
        return 0
    if getattr(args, "clear", False):
        removed = cache.clear()
        print(ui.ok(f"cleared {removed} cached response(s)"))
        return 0
    snap = cache.snapshot()
    if args.json:
        print(json.dumps(snap, indent=2))
        return 0
    print(bold("Response cache"))
    ui.kv("entries", f"{snap['entries']} / {snap['max_entries']}")
    ui.kv("ttl", f"{snap['ttl_s']:.0f}s")
    ui.kv("hits", snap["hits"])
    ui.kv("misses", snap["misses"])
    ui.kv("hit rate", f"{snap['hit_rate'] * 100:.1f}%")
    ui.kv(
        "stores / evictions / expiries",
        f"{snap['stores']} / {snap['evictions']} / {snap['expiries']}",
    )
    ui.kv(
        "bypass hints",
        "metadata={'cache': 'bypass'} skips the cache; 'refresh' revalidates a single call",
    )
    return 0


def cmd_traces(args: Any) -> int:
    """`zyko traces` — inspect the built-in span log (one JSON object per line)."""
    from zyko.observability.tracer import TraceSpan
    from zyko.platform.paths import trace_log

    path = Path(args.file) if getattr(args, "file", None) else trace_log()
    if getattr(args, "clear", False):
        removed = 0
        for p in (path, path.with_suffix(path.suffix + ".1")):
            if p.is_file():
                p.unlink()
                removed += 1
        if not args.json:
            print(ui.ok(f"cleared {removed} trace file(s)"))
        return 0
    if not path.is_file():
        if args.json:
            # Same machine contract as `zyko cost --json` / `zyko cache --json`:
            # pipes and scripts always get valid JSON, never an [INFO] line.
            print(json.dumps({"trace_file": str(path), "spans": [], "traces": []}, indent=2))
        else:
            print(
                ui.info(
                    f"no trace log at {path} — spans appear once you route traffic "
                    "(disable with ZYKO_TRACING=0)"
                )
            )
        return 0

    spans: list[TraceSpan] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                spans.append(TraceSpan(**json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue  # skip torn/corrupt lines instead of failing the report
    if args.trace:
        spans = [s for s in spans if s.trace_id == args.trace]
    if args.last and args.last > 0:
        spans = spans[-args.last :]

    traces: dict[str, list[TraceSpan]] = {}
    for s in spans:
        traces.setdefault(s.trace_id, []).append(s)

    if args.json:
        print(
            json.dumps(
                {
                    "trace_file": str(path),
                    "spans": [s.to_dict() for s in spans],
                    "traces": sorted(traces, key=lambda t: min(s.started_at for s in traces[t])),
                },
                indent=2,
            )
        )
        return 0

    if args.trace and not spans:
        print(ui.warn(f"no spans found for trace {args.trace}"))
        return 0
    rows = []
    for s in spans:
        rows.append(
            [
                time.strftime("%H:%M:%S", time.localtime(s.started_at)),
                s.trace_id[:8],
                s.name,
                "-" if s.duration_ms is None else f"{s.duration_ms:.0f}ms",
                s.status,
                str(s.attributes.get("provider") or s.attributes.get("error") or ""),
            ]
        )
    ui.table(["time", "trace", "span", "duration", "status", "provider/error"], rows)
    print()
    print(
        ui.info(
            f"{len(spans)} span(s) across {len(traces)} trace(s) — "
            "drill into one with: zyko traces --trace <id>"
        )
    )
    return 0


def cmd_doctor(args: Any) -> int:
    print(bold("ZYKO doctor"))
    p = platform_info()
    ui.kv("os", p.describe())
    if p.os.value in ("termux", "android"):
        ui.kv("mobile", "yes — ZYKO runs natively; see android/README.md for tips")
    ui.kv("kernel", kernel.backend())
    settings = Settings.load()
    ui.kv(
        "config",
        str(settings.source) if settings.source else "(defaults only — no config file found)",
    )
    print()
    print(bold("Provider keys"))
    any_key = False
    for name in provider_names():
        cls = get_provider_class(name)
        section = settings.provider_setting(name)
        configured = is_configured(name, section)
        env = (
            cls.KEY_ENV
            if isinstance(cls.KEY_ENV, str)
            else (", ".join(cls.KEY_ENV) if cls.KEY_ENV else "local")
        )
        any_key = any_key or configured
        print(f"  {'OK ' if configured else '-- '} {name:<12} ({env})")
    if not any_key:
        print(
            ui.warn(
                "no provider keys found — set one, install Ollama, or try --demo for an offline keyless run"
            )
        )
    print()
    print(bold("Local inference"))
    try:
        import httpx

        resp = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2.0)
        models = [m.get("name") for m in resp.json().get("models", [])]
        print(ui.ok(f"ollama reachable — models: {', '.join(models) or '(none pulled)'}"))
    except Exception:
        print(
            ui.warn("ollama not reachable at 127.0.0.1:11434 (optional, but great on Termux/phone)")
        )
    print()
    print(bold("Observability"))
    tracing_on = bool(settings.get("tracing.enabled", True))
    env_tracing = os.environ.get("ZYKO_TRACING")
    if env_tracing is not None:
        tracing_on = env_tracing.strip().lower() not in {"0", "false", "off", "no"}
    print(f"  {'OK ' if tracing_on else '-- '} tracing   (spans: JSONL log + in-memory)")
    otlp_endpoint = os.environ.get("ZYKO_OTLP_ENDPOINT") or settings.get("tracing.otlp.endpoint")
    if otlp_endpoint:
        print(ui.ok(f"otlp export → {otlp_endpoint}"))
    else:
        print(
            "  --  otlp     (set ZYKO_OTLP_ENDPOINT or tracing.otlp.endpoint to "
            "bridge spans to Langfuse/Tempo/Jaeger/Collector)"
        )
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


# ------------------------------------------------------------------ new (coder)
def cmd_new(args: Any) -> int:
    """المرحلة 1 — توليد مشروع من وصف عربي: مخطط → موافقة → توليد → فحص.

    Same flow as ``python -m zyko.coder new``. With ``--json`` it only
    prints the plan (preview); otherwise nothing is written before the
    plan is shown and approved (explicitly or via --yes).
    """
    from zyko.coder.generate import build_all_files, materialize
    from zyko.coder.heuristics import draft_plan
    from zyko.coder.plan import PlanValidationError, ProjectPlan, safe_slug
    from zyko.coder.precheck import check_source_tree, full_gate

    plan = draft_plan(args.plan)
    overrides: dict[str, str] = {}
    if getattr(args, "name", None):
        overrides["name"] = safe_slug(args.name, fallback=plan.name)
    if getattr(args, "template", None):
        overrides["template"] = args.template
    if overrides:
        try:
            plan = ProjectPlan.from_dict(plan.to_dict() | overrides)
        except PlanValidationError as exc:
            ui.error(str(exc))
            return 2

    if getattr(args, "json", False):
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
        return 0

    # بوابة الموافقة — لا يُكتب أي ملف قبل رؤية المخطط وقبوله
    print(plan.summary_ar())
    if not getattr(args, "yes", False):
        try:
            answer = input("\nهل توافق على هذا المخطط؟ [نعم/y] ")
        except (EOFError, KeyboardInterrupt):
            print("\nأُلغي — لم يُكتب أي ملف")
            return 1
        # قائمتان متجانستان النصوص — الخلط العربي/اللاتيني في مجموعة واحدة
        # يفجّر RTL-PY-001 (أداة المرحلة 0 اصطادته في ذاتها هنا)
        latin_ok = answer.strip().lower() in {"y", "yes"}
        arabic_ok = answer.strip() in {"ن", "نعم"}
        if not (latin_ok or arabic_ok):
            print("أُلغي — لم يُكتب أي ملف")
            return 1

    out = Path(args.out) if getattr(args, "out", None) else Path.cwd() / plan.name
    try:
        result = materialize(plan, out, git_init=not getattr(args, "no_git", False))
    except FileExistsError as exc:
        ui.error(str(exc))
        return 2

    static = check_source_tree(build_all_files(plan))
    print(f"\nوُلّد {len(result.files)} ملفًا في {result.root}")
    if result.git_committed:
        print("git: التزام أول عربي ✓")
    elif result.git_skipped_reason:
        print(f"git: تخطّي ({result.git_skipped_reason})")

    if not static.ok:
        for pr in static.problems:
            print(f"  - {pr}", file=sys.stderr)
        ui.error("الفحص الثابت رفض المشروع")
        return 1
    print(ui.ok("فحص ثابت (ast + RTL): نظيف"))

    if getattr(args, "run_tests", False):
        full = full_gate(plan, result.root, run_tests=True)
        if full.problems:
            for pr in full.problems:
                print(f"  - {pr}", file=sys.stderr)
            ui.error("اختبارات المشروع لم تمر")
            return 1
        print(ui.ok("اختبارات المشروع: مرّت"))
    return 0


def cmd_factory(args: Any) -> int:
    """البوابة الموحدة للمصنع (المرحلة 7) — تفويض حرفي إلى zyko.factory.cli.

    بلا أمر فرعي ⇒ خريطة المصنع؛ ومع أمر فرعي ينفَّذ في وحدات المحرك
    نفسها (نفس الحجج، نفس أكواد الخروج، نفس الحتمية البايتية).
    """
    from zyko.factory.cli import handle_factory

    return handle_factory(args)
