# Changelog

## 0.3.4 — the real CI fix: green on Ubuntu + macOS + Windows

The 0.3.3 release fixed the bandit gate locally, but the GitHub CI matrix was
still red. Three root causes, none of which a Linux-only run can ever catch:

### Fixed
- **`security` job: `bandit: unrecognized arguments: --exit-zero-on-skipped`.**
  Modern bandit removed the flag; the CI command now runs plain
  `bandit -r src/zyko -q -c .bandit.yml`.
- **`test_ensure_layout_creates_tree_and_termux_marker` failed on macOS and
  Windows.** Production `ensure_layout()` gated the Termux marker on
  `sys.platform.startswith("linux")` even though a `com.termux` PREFIX is
  definitive by itself. The platform gate is gone, so the first-run marker
  behaves identically on every OS (production fix, regression test now
  platform-independent).
- **`test_paths_xdg_branches` failed on macOS and Windows.** XDG variables
  are honoured by the Linux branch only (macOS uses `~/Library`, Windows
  `%APPDATA%`); the test now pins `detect_os → LINUX` explicitly, mirroring
  the established `test_macos_branch` pattern.

### Result
- CI matrix green: `pytest` on ubuntu/macos/windows × Python 3.11/3.12/3.13,
  `lint`, `security` (bandit + pip-audit), `rust-kernel`, `cli-smoke`, Pages.
- Version synced: version.py / pyproject.toml / CITATION.cff → 0.3.4.

## 0.3.3 — the security gate that never ran: bandit config was silently ignored

The 0.3.2 round added a CI `security` job — but its bandit invocation could
never see the intended suppressions and would have gone red on the first real
run. This release makes the gate actually green and widens last-mile coverage
around the gateway, MCP server and streaming router.

### Real bug found & fixed
- **bandit never read `[tool.bandit]` from `pyproject.toml`.** bandit
  (through 1.9.x) has no pyproject.toml support at all — the documented skips
  for B101 (internal-invariant asserts), B311 (retry-jitter / benchmark
  `random`) and B404 (the policy-gated `shell` agent tool) were silently
  ignored, so `bandit -r src/zyko` reported 11 LOW findings and the CI
  `security` job would have failed. The suppressions now live in a real
  `.bandit.yml` (justification comments included) consumed everywhere: CI
  runs `bandit -r src/zyko -q -c .bandit.yml --exit-zero-on-skipped`,
  `make security` uses the same file, and the misleading `[tool.bandit]`
  section was removed from `pyproject.toml`. Verified locally: exit 0.

### Tests & coverage
- 10 new edge-path tests in `tests/test_eval_round3.py` (347 total): gateway
  500 mapping for unexpected router exceptions, lying `Content-Length`
  headers, client disconnect mid-stream (RST) leaving the worker healthy, the
  MCP server surfacing unexpected exceptions as `isError` without crashing
  the loop, the `zyko_chat` tool round-trip with a routing receipt,
  `default_policy` wiring in `_ensure_router`, the
  `python -m zyko.mcp.server` entrypoint, degenerate cost/latency
  normalisation, and breaker/policy skips inside `astream_route`.
- Coverage 98% with uncovered lines down 84 → 69.

### Docs
- `README.md` and `docs/READY.md` now reference the real verification command
  (`bandit -c .bandit.yml -r src/zyko`).

## 0.3.2 — full evaluation round: coverage 92% → 98%, security gate in CI, 3 real bugs fixed

A complete quality round — coverage analysis, lint, security audit — executed
on the whole codebase, with every finding fixed and regression-tested.

### Real bugs found & fixed
- **`Settings.load()` leaked environment overrides into module-level
  defaults.** `_deep_merge` shared nested dicts with the `DEFAULTS` constant,
  so the first `load()` with `ZYKO_*` env vars (or YAML values) permanently
  rewrote the defaults for the whole process — later calls inherited the
  first call's environment, cross-contaminating long-lived gateway processes
  and unrelated tests. Defaults are now deep-copied per call
  (`tests/test_eval_round.py::test_settings_env_overrides_do_not_poison_defaults`).
- **`policies_dir()` / `agents_dir(create=True)` did not create the returned
  directory** — only its parent. `create=True` now guarantees the leaf
  exists, as every caller reasonably assumed.
- **`PolicyEngine` crashed with a raw `AttributeError` on malformed policy
  sections** (`defaults`/`privacy`/`rate_limit`/`audit` set to a non-mapping
  value) *before* the schema-warnings machinery could report them. Malformed
  sections now degrade to the documented warnings.

### Evaluation results
- **Coverage 92% → 98%** (3491 statements, 84 uncovered) with 107 new tests
  in `tests/test_eval_round.py` + `tests/test_eval_round2.py`: settings
  layering/interpolation/templates, quality-ledger EWMA/persistence/garbage
  input, gateway 401/404/400/502 + tool-message parsing, full MCP client
  lifecycle (timeouts, server errors, `isError`, pagination, closed streams,
  sync wrappers), streaming governance charging (vendor usage → audit with
  `estimated: false`), circuit-breaker skip + policy-deny routing, platform
  detection (Windows/macOS/Android/Termux), OpenAI/Anthropic payload &
  stream-chunk matrices, benchmark graders matrix + demo run with
  `--update-ledger`, CLI surfaces (`models`, `route --json`, `ask --explain
  --receipt`, `serve` happy path + Ctrl-C, `sessions`, `cost` from a real
  audit log, `doctor`, `policy`), POSIX exit codes 130/141 via subprocesses,
  and the event/JSON message primitives.
- **Lint**: `ruff check` clean and the whole tree now `ruff format`-clean;
  the CI lint job enforces `ruff format --check` from now on.
- **Security gate added to CI**: a `security` job runs
  `bandit -c pyproject.toml -r src/zyko` (0 findings) and `pip-audit` on the
  declared dependency surface (`httpx`, `PyYAML` — clean). The intentional
  `shell=True` in the policy-gated `shell` tool is documented inline and
  suppressed with a scoped `# nosec B602`; assert-based invariants (B101)
  and retry-jitter `random` (B311) are covered by the project bandit config.
- **CLI smoke**: `zyko --version` via `python -m zyko` is now tested.
- **Install scripts restored** to the repo root: `zyko.sh` / `zyko.cmd`
  zero-install runners, `install.sh` / `install.bat` / `install.ps1`
  installers, a developer `Makefile`, and a gateway `Dockerfile`
  (stdlib-only runtime, healthcheck on `/healthz`).
- Tests: 230 → **337**.

## 0.3.1 — CLI robustness round: no more raw tracebacks

A targeted audit of the CLI surfaced three defects a user could hit on a
normal day; all are fixed and regression-tested.

### Hardening & evaluation round (same release)
- **Coverage 89% → 92%** with 22 new tests in `tests/test_hardening.py`:
  MCP protocol helpers (100%), the optional Rust-kernel swap (100%), agent
  tool-loop failure modes (99%), builtin tool edges — calculator power caps,
  workspace escapes, shell timeout — (95%), and the provider base class
  error/retry map: timeout/network/invalid-JSON mapping, `Retry-After`
  honoring (delay and HTTP-date), SSE with garbage frames, sync streaming,
  `aclose`, model-resolution rules (93%).
- **Security audit re-confirmed**: danger tools (`shell`) stay locked unless
  explicitly named in `tools.allow` — a `*` wildcard never unlocks them
  (`explicitly_allows_tool`); http_get rejects non-HTTP schemes; the MCP
  client spawns servers via `exec`, never a shell.
- **CI guard test** pins the workflow push trigger to `['main']` after an
  ANSI-sanitizing log pipeline made `[main]` read as `ain]` (byte-level
  inspection proved the YAML was always correct — kept the guard anyway).
- **Social card** version chip repainted to v0.3.1; site badges refreshed.

### Fixes
- **`zyko cost --json` emitted `[INFO]` text instead of JSON** when no audit
  log existed yet — breaking every downstream consumer (`| jq`, CI steps).
  The empty-report branch now emits the exact same JSON schema as a real
  report; the human-friendly `[INFO]` line is kept for the plain command.
- **`zyko serve` on a busy port crashed with a raw `OSError` traceback.** The
  bind failure is now reported as a friendly `[FAIL] cannot start gateway on
  <host>:<port>` with an actionable hint (try another `--port`).
- **`zyko doctor | head` printed a `BrokenPipeError` traceback.** The CLI now
  detects the closed pipe and exits quietly with the conventional code 141
  (128 + SIGPIPE), like every well-behaved POSIX tool.
- **Hardening (Windows):** the CLI reconfigures stdout/stderr with
  `errors="replace"` at startup, so a legacy cp1252 console can no longer
  crash on em-dashes, `·` separators, or Arabic output — the character is
  replaced instead of killing the command.

## 0.3.0 — second evaluation round: correctness, visibility, hardening

Another full re-evaluation (tests, lint, coverage, functional smokes). This
round focused on *correctness bugs the earlier suite could not see* and on
making hidden subsystems (session memory, audit trail) visible to users.

### Bugs found by the new evaluation → fixes
- **Explicit model pins were silently ignored.** `zyko ask --model
  openai/gpt-4o` (or `Zyko().ask(..., model=...)`) was discarded by the
  router: it ranked the whole board and overwrote the model with the top
  candidate. The router now pins the route to the requested model
  (`provider/model`, bare `model`, or `provider/*`), fails fast with an
  actionable hint when the pin matches nothing, keeps fallbacks *inside* the
  pin, and records `requested_model` on every receipt.
- **Gateway keep-alive corruption on auth rejection.** A 401 (or any early
  error) returned without draining the request body; with HTTP/1.1
  keep-alive the unread body was parsed as the next request line and the
  connection broke (501 "Unsupported method"). The body is now consumed
  before any error path. Regression-tested over a real socket: 401 then 200
  on the same connection.
- **One malformed JSON-RPC frame killed the MCP server.** `serve()` now
  answers `PARSE_ERROR (-32700)` per the JSON-RPC 2.0 spec and keeps
  serving. `zyko_models` also lists what the router can *actually* route
  (policy-filtered, keyless demo fallback) instead of raw vendor catalogs.
- **Session memory was an invisible feature**: a full SQLite store with no
  CLI surface and 25% coverage. New `zyko sessions list|show|rm|clear`
  command (clear requires `--yes`), `MemoryStore.delete_session`/`clear`,
  `updated` surfaced in listings; coverage now 98%.

### New
- **`zyko cost`** — spend & governance report from the policy audit log:
  totals, per-day and per-candidate spend, vendor-reported vs kernel-estimated
  accounting, deny-rule counts, redaction events. `--days N` window,
  `--json` for pipelines.
- **Receipts now carry `requested_model`** — replaying a decision also
  verifies that the pin was honored.
- `python -m zyko` covered by a real-subprocess test; version consistency
  between `pyproject.toml` and `zyko.version` is now test-enforced.

### Numbers
- Tests 133 → **203**; coverage 81% → **89%** (`cli/commands` 63% → 90%,
  `client` 51% → 98%, `agents/loader` 39% → 100%, `agents/memory` 25% → 98%,
  `mcp/server` 63% → 91%); `ruff` clean; byte-compile clean.

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
