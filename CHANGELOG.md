# Changelog

## 0.2.0 — evaluation-driven hardening round

A full re-evaluation of the platform (tests, lint, coverage, functional smokes)
followed by targeted fixes and big-project parity improvements.

### Evaluation findings → fixes
- **Coverage gaps closed** (`platform/paths` 54%, `mcp/server` 63%, `mcp/protocol`
  67%, `google` 73%): new test groups for path resolution (env overrides +
  Windows/macOS branches), a real-subprocess MCP server round-trip, protocol
  framing edges, and the Google adapter build/parse path.
- **`zyko version`**: new first-class command (`zyko 0.2.0 (MCP protocol …)`) —
  the CLI previously only exposed `--version` / `info`.
- **`python -m zyko`** now works (proper `__main__.py`), matching how pip-installed
  CLIs are expected to behave.
- **`zyko bench --repeats N`**: repeat the deterministic suite N times for stabler
  medians; recorded in the JSON report.
- **Lint**: examples import order fixed (`ruff check` now clean across the tree).

### Resilience — patterns adopted from the big projects
- **`Retry-After` honored on HTTP 429** (LiteLLM/OpenAI-SDK pattern): the header
  is parsed (delay-seconds *and* HTTP-date), carried on `RateLimitError.retry_after`,
  and used by the retry loop instead of the generic backoff curve (clamped 0.05–30 s).
- **Streaming cost accounting closed** (governance parity with the non-streaming
  path): OpenAI/OpenRouter streams now request `stream_options.include_usage`,
  and after every stream the router charges the policy budget from the
  vendor-reported usage — falling back to the kernel token estimate when the
  vendor omits it. The audit entry records the accounting source
  (`estimated: true/false`), so budgets are enforced on *every* call shape.

### Platform
- CI matrix extended to Python 3.13 (3 OSes × 3 Pythons).

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
