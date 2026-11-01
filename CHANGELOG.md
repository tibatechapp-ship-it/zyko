# Changelog

## 0.1.0 — initial platform release

The first complete implementation of the ZYKO orchestration platform.

### Review hardening (pre-release QA pass)
- **Offline demo mode**: `zyko ask/route/chat/serve/run/bench --demo` (and `ZYKO_DEMO=1`)
  run the full pipeline — routing, policy, receipts, streaming — through a new
  deterministic `MockProvider`, with zero API keys and zero network. First-run
  experience on any platform (including Termux) now works out of the box.
- **Router scoring O(n²) → O(n)**: normalization ranges are snapshotted once per
  ranking pass instead of being recomputed per candidate; scores are bit-identical
  (parity-tested). Matters on phones where routing overhead is part of latency.
- **Prompt-aware planning**: `zyko route "<prompt>"` now estimates tokens from the
  actual prompt, and `explain()`/`--json` output includes the estimate.
- **Policy typo guard**: unknown top-level / `defaults` keys in a policy file now
  produce loud warnings in `zyko policy check` and appear in receipts via
  `policy.snapshot()` (silently-ignored YAML typos previously looked like active controls).
- **MCP governance parity**: `zyko mcp serve` now loads `default_policy`, the
  quality ledger and demo mode exactly like the CLI.
- **Bench honesty + fixes**: cost is computed from tokens vendors actually report
  (kernel estimate only as fallback); fixed `--ledger` crash (string path was never
  converted to `Path`); fixed `median ms = None` for sub-0.05 ms candidates.

### Core
- Unified provider-neutral contracts (`Message`, `ChatRequest`, `ChatResponse`, streaming events).
- Provider adapters: OpenAI (+ Groq, Mistral, DeepSeek, OpenRouter via the OpenAI-compatible base), Anthropic, Google Gemini, Ollama (local, keyless) — with retries/backoff, per-event-loop connection reuse, and HTTP error mapping.
- Shared background event loop powering thread-safe sync APIs on every platform (CLI, gateway, GUI threads).

### Routing
- Verifiable routing engine: explicit quality/cost/latency scoring with published strategy weights, full ranking receipts on every response.
- Circuit breakers + latency EWMA per candidate; automatic fallback before first token when streaming.
- Reproducible quality ledger (JSON), neutral-by-default, updated only by real benchmark runs.

### Governance (Policy-as-Code)
- YAML policies: model/provider/tool allowlists, daily USD budget (persistent), token-bucket rate limits, deterministic PII redaction (email, phone, IBAN, SSN, credit card with Luhn verification), token caps, JSONL audit trail.
- Danger-tool gating: `shell` requires an explicit (non-wildcard) policy entry.

### Agents & MCP
- ReAct agent loop with builtin tools (calculator with AST sandboxing, workspace-confined file tools, size-capped http_get, policy-gated shell), step/timeout guards, full step traces.
- YAML agent definitions with MCP server wiring; MCP client (stdio JSON-RPC, initialize/tools.list/tools.call) and ZYKO as an MCP server (`zyko mcp serve`).
- SQLite session memory.

### Platform
- `zyko` CLI (argparse, zero CLI dependencies): `ask`, `chat`, `route`, `models`, `policy`, `run`, `serve`, `mcp`, `bench`, `doctor`, `info`.
- OpenAI-compatible gateway on the Python stdlib (streaming SSE, receipts in responses, bearer auth).
- Cross-platform layout (Linux/Termux XDG, macOS, Windows), Android/Termux installer, widget shortcut, optional Kivy app.
- Optional Rust kernel (PyO3) with enforced parity against the pure-Python fallback.
- Reproducible benchmark suite (fixed seed, objective graders, `--update-ledger`).
- 90+ tests, ruff-clean, CI matrix on Linux/Windows/macOS × Python 3.11/3.12 + Rust check + CLI smoke.
