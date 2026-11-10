# ZYKO Release History

The complete release record — one entry per tag, newest first. For the full
technical detail of every release see [`CHANGELOG.md`](../CHANGELOG.md);
for the current release see [`README.md`](../README.md).

> **Note on early tags:** the tags v0.1.0–v0.11.0 were organized
> retroactively in November 2026 (their release notes were backfilled), so
> tag creation dates do not reflect when the work was written — the commits
> and this ordering do.

Three arcs run through this history:

1. **The platform (v0.1.0 → v0.7.0)** — provider-neutral orchestration:
   routing with published weights, Policy-as-Code governance, MCP in both
   directions, tracing, RAG, crews, and a governed multi-user gateway.
2. **The Arabic coding engine (v0.8.2 → v0.17.0, Phases 0 → 8)** — a
   deterministic, byte-reproducible engine built phase by phase on top of
   the platform, each phase sealed by acceptance gates.
3. **Intelligence behind the same gates (v0.18.0 → v0.19.0)** — real local
   models, then competing brains — every proposal still gated before a
   single byte is written.

---

## v0.19.0 — BestOfBrain: brains compete, gates decide

`BestOfBrain` consults candidate brains **in order** on the same goal;
every candidate is wrapped in the gates automatically, and the first
accepted proposal wins — the receipt folds the whole competition story
(who was tried, why it failed, who won). A rejected plan step now records
**every** failed gate verdict, not just the first.

## v0.18.0 — OllamaBrain: a real local model behind the same gates

`zyko.ai.ollama_brain.OllamaBrain` connects any Ollama-served model to the
`Brain` protocol over stdlib `urllib` with an injectable transport. Every
failure returns a structured Arabic refusal inside the receipt — never an
exception — and the Guardian still decides.

## v0.17.0 — Phase 8: the `zyko.ai` intelligence layer

The intelligence layer rides on the deterministic factory: `Brain`
protocol, `GatedBrain`, `PlannerBrain`, `AISession`, byte-deterministic
receipt chains, and the `zyko ai` CLI (`map` / `run` / `gate`).

## v0.16.0 — `zyko py`: the daad gateway

The platform meets its first standalone language: **daad** (ضاد), a
byte-deterministic Arabic-Python transpiler in its own repository
(`tibatechapp-ship-it/daad`). `zyko py` delegates over a subprocess
boundary — no internal import, same arguments, same exit codes.

## v0.15.0 — the MIZAN wave: reviewer grows to 38 rules with taint analysis

The reviewer absorbs field-proven security rules from the sibling **MIZAN**
project, rebuilt in ZYKO's pure-AST, byte-deterministic, Arabic-first
style: 11 new rules (R-SEC-109…119), three of them backed by the new
dataflow **taint module** that fires only on a confirmed source-to-sink
path.

## v0.14.0 — Phase 7: `zyko.factory`, the unified gate

Every deterministic engine becomes reachable from a single gate — literal
delegation (same handlers, same exit codes, same byte determinism) to
`fix` / `pipeline` / `workspace` / `baseline`, 24 quantitative sub-gates
over Arabic anchors, and one signed verdict: «المصنع مقبول».

## v0.13.0 — Phase 6: `zyko.baseline`, the quality guard over time

The engine becomes a permanent guard: timestamp-free deterministic
snapshots (`.zyko/baseline.json`) — `run_no` is the only clock — with
numeric regression/improvement detection per file.

## v0.12.0 — Phase 5: `zyko.workspace`, the engine on real projects

Review → fix on existing folders: dry-run by default, consent-gated
writes (`--out` to a new folder or `--in-place --yes`), verified-writes
only.

## v0.11.0 — Phase 4: `zyko.pipeline`, the loop in one command

Generate → review → fix → re-check with per-file score deltas, exit codes
as a contract, and byte-deterministic reports.

## v0.10.0 — Phase 3: `zyko.fixer`, deterministic Arabic auto-fix

Safe fix paths on top of the reviewer's rules; every fix is re-parsed and
verified before acceptance, and manual-only paths carry explicit Arabic
reasons.

## v0.9.2 — Phase 2: `zyko.reviewer`, deterministic Arabic code review

27 AST rules in three categories; every finding signed with rule ID, line
and column; byte-deterministic score and Arabic verdict.

## v0.9.1 — Phase 1: `zyko.coder`, deterministic project generation

Full projects from one Arabic description with three templates
(`python-cli`, `fastapi-api`, `static-site`) and a `RECEIPT.md` carrying
sha256 fingerprints.

## v0.9.0 — DeepSeek V4 models: 1M context in the router catalog

Catalog expansion with long-context, agentic models — every fact from the
vendor's official documentation.

## v0.8.2 — Phase 0: deterministic Arabic tools

`zyko_pii_ar` (national ID, mobile, IBAN) and `zyko_rtl` (text, CSS, HTML,
Python) — the Arabic-first foundation the gates reuse today.

## v0.8.1 — MCP tools honor the policy allow-list

Every tool call — including `mcp__server__tool` names — routes through
`PolicyEngine.allows_tool`, closing the last policy gap before the
dispatcher.

## v0.8.0 — the receipt becomes verifiable: `zyko verify`

Until 0.7 the receipt was informative, not verifiable. `zyko verify`
recomputes every total offline and exits non-zero on drift — and
immediately caught a real bug (`cost_score` could exceed 1.0), proof the
mechanism works against its own author.

## v0.7.0 — governed multi-user gateway: identities, not just a token

Every caller is a named identity with its own key, roles, rate limit and
daily budget; verification is constant-time.

## v0.6.0 — multi-agent crews: sequential pipeline with shared context

CrewAI-parity in simplicity, stronger in governance: safe templating,
typed failures end-to-end, full auditable receipt.

## v0.5.0 — RAG essentials: chunk → embed → search → `ask(context=…)`

The LlamaIndex-minimum, zero-dependency by default: the built-in
`HashingEmbedder` is pure-stdlib feature hashing — deterministic, offline,
phone-capable.

## v0.4.2 — the observability bridge: OTLP export

Spans flow to Langfuse, Tempo, Jaeger or any OTLP/HTTP-JSON backend —
zero new dependencies, zero vendor lock-in.

## v0.4.1 — built-in tracing: spans + a JSONL log you own

OpenTelemetry-style spans locally with `zyko traces`; tracing never breaks
a request.

## v0.4.0 — structured output: validated answers with automatic repair

Schema-constrained answers or a typed error, with a pure-Python JSON
Schema validator and an automatic repair round.

## v0.3.9 — response cache: policy-gated exact-match TTL cache

SHA-256 keyed, per-candidate, honest receipts; tool-call responses are
never cached.

## v0.3.8 — provider ecosystem: +xAI (Grok) and +Together AI

Ten registered providers; every catalog fact from each vendor's official
documentation.

## v0.3.7 — MCP: dead-server race fails typed, on every OS

A dying MCP server now produces a typed `MCPError` instead of a hang or a
raw traceback.

## v0.3.6 — ruff 0.17 format compliance

Hygiene round; zero behavior change.

## v0.3.5 — deep developer documentation

API reference, architecture and providers guide — every signature verbatim
from code.

## v0.3.4 — CI matrix green on Ubuntu + macOS + Windows

The real CI fix, proven on the full matrix.

## v0.3.3 — the security gate that never ran

`.bandit.yml` was silently ignored; now consumed by both CI and
`make security`.

## v0.3.2 — full evaluation round

Coverage 92% → 98%, security gate in CI, 3 real bugs fixed.

## v0.3.1 — CLI robustness round

No more raw tracebacks: `zyko cost --json` always JSON, busy port →
friendly message, broken pipe → exit 141.

## v0.3.0 — second evaluation round

Correctness, visibility, hardening: explicit `--model` pinning, keep-alive
integrity on 401, MCP JSON-RPC errors, session CLI.

## v0.2.0 — evaluation-driven hardening round

Fixes chosen by systematic evaluation results, not incidents.

## v0.1.0 — initial platform release

The complete ZYKO platform: verifiable routing, policies, MCP in both
directions, gateway, agents, ten providers, and the reproducible benchmark
suite.
