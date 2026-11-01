# ZYKO v0.3.2 — Readiness Report (release QA)

Status: **READY** — all gates green on the reference environment (Linux, Python 3.12),
after a **full evaluation round**: coverage analysis, lint, and a security audit,
with every finding fixed and regression-tested.

## Gates

| Gate | Command | Result |
|---|---|---|
| Unit/integration tests (plain `pytest`, same as CI) | `pytest` | **337 passed** (0 failed, 0 skipped, ~19s) |
| Lint | `ruff check src tests benchmarks` | **0 findings** |
| Formatting | `ruff format --check src tests benchmarks` | **clean** (79 files) — now enforced in CI |
| Coverage (reference platform) | `pytest --cov=src/zyko` | **98% total** (3491 stmts, 84 uncovered; `router/quality` 100%, `utils/loop` 98%, `providers/base` 98%, `gateway` 93%+, `mcp/client` 94%+) |
| Security (SAST) | `bandit -c pyproject.toml -r src/zyko` | **0 findings** — new CI `security` job; intentional policy-gated `shell=True` documented with scoped `# nosec B602` |
| Security (dependencies) | `pip-audit --skip-editable` | `httpx` + `PyYAML` **clean** at release time — new CI `security` job |
| Byte-compile | `python -m compileall src tests` | clean |
| Secret scan | `git grep` for token/key patterns | clean — no credentials in tree |
| Version sync | `src/zyko/version.py` ↔ `pyproject.toml` | both **0.3.2** (enforced by `test_pyproject_version_matches_package`) |
| CLI smoke (all commands, demo mode) | `zyko version/info/doctor/models/route/ask/chat/sessions/policy/mcp/run/serve+curl/bench/cost` | all exit 0 or fail cleanly with hints |
| CLI failure paths | busy port · closed pipe · `--json` without audit log · Ctrl-C | exit 141/130 quiet · valid empty-report JSON · friendly `[FAIL]` + hint |
| Danger-tool lock | `allow: ["*"]` + `shell` call | blocked — wildcard never unlocks danger tools; explicit `tools.allow` entry required |
| Keyless first run (no flags) | `zyko route "hello"` with zero keys | exit 0 — auto-fallback to the demo provider with a notice |
| MCP stdio protocol | `initialize` → `tools/list` → `tools/call` + malformed-frame probe | correct JSON-RPC 2.0; bad frames get `-32700`, server survives |
| Gateway | OpenAI-compatible `/v1/chat/completions` incl. SSE, real socket, keep-alive | 401 then 200 on the same connection; 502 with typed `zyko_upstream_error` on total upstream failure |
| Install scripts (restored) | `./zyko.sh --version` · `ZYKO_VENV=/tmp/x ./install.sh` | runner execs `zyko 0.3.2`; clean-venv install verified end-to-end |
| Landing site | `docs/site` AR(RTL)/EN | badges refreshed (337 · 98% · bandit 0) |
| Social card | `docs/assets/social-card.png` | version chip repainted **v0.3.2** (in-place patch, pixel-verified) |

## Fixed in the v0.3.2 round (real bugs from the evaluation)

1. **`Settings.load()` global-state leak** — `_deep_merge` shared nested dicts
   with the module-level `DEFAULTS`, so the first `load()` with `ZYKO_*` env
   vars (or YAML values) permanently rewrote the defaults for the whole
   process; later calls inherited the first call's environment
   (cross-contaminating long-lived gateway processes and tests). Defaults are
   now deep-copied per call, pinned by a dedicated regression test.
2. **`policies_dir()` / `agents_dir(create=True)` returned a directory that
   did not exist** — only the parent was created. `create=True` now
   guarantees the leaf itself exists.
3. **`PolicyEngine` crashed with a raw `AttributeError` on malformed policy
   sections** (`defaults`/`privacy`/`rate_limit`/`audit` set to a non-mapping)
   before the schema-warnings machinery could run. Malformed sections now
   degrade to the documented warnings.

## Added in v0.3.2

- **CI `security` job**: bandit (SAST) + pip-audit (declared deps), plus
  `ruff format --check` in the lint job.
- **107 new tests** (`tests/test_eval_round.py`, `tests/test_eval_round2.py`):
  settings layering/interpolation/templates + the defaults-poisoning
  regression, quality-ledger EWMA/persistence/garbage input, gateway
  401/404/400/502 and tool-message parsing, full MCP client lifecycle
  (timeouts, server errors, `isError`, pagination, closed streams, sync
  wrappers), streaming governance charging (vendor usage → audit
  `estimated: false`), circuit-breaker skip and policy-deny routing paths,
  platform detection (Windows/macOS/Android/Termux), OpenAI/Anthropic payload
  and stream-chunk matrices, benchmark graders matrix + demo run with
  `--update-ledger`, CLI surfaces (`models`, `route --json`, `ask --explain
  --receipt`, `serve` happy path + Ctrl-C, `sessions`, `cost` from a real
  audit log, `doctor`, `policy`), POSIX exit codes 130/141 via subprocesses,
  and the event/JSON message primitives.
- **Install scripts restored** to the repo root: `zyko.sh` / `zyko.cmd`
  zero-install runners, `install.sh` / `install.bat` / `install.ps1`, a
  developer `Makefile` (test/coverage/lint/format/security/bench), and a
  gateway `Dockerfile` with a `/healthz` healthcheck.

---

# ZYKO v0.3.1 — Readiness Report (release QA)

Status: **READY** — all gates green on the reference environment (Linux, Python 3.12),
after a CLI-robustness audit (every command exercised for real) and a coverage
hardening round.

## Gates

| Gate | Command | Result |
|---|---|---|
| Unit/integration tests (plain `pytest`, same as CI) | `pytest` | **230 passed** (0 failed, 0 skipped, ~12.7s) |
| Lint | `ruff check src tests benchmarks` | **0 findings** |
| Coverage (reference platform) | `pytest --cov=zyko` | **92% total** (`mcp/protocol` 100%, `kernel` 100%, `core/tools` 100%, `agents/agent` 99%, `tools_builtin` 95%, `providers/base` 93%) |
| Byte-compile | `python -m compileall src tests` | clean |
| Secret scan | `git grep` for token/key patterns | clean — no credentials in tree |
| Workflow/config validity | YAML workflows + policy/agent examples + bench schema | all parse clean |
| CLI smoke (all commands, demo mode) | `zyko version/info/doctor/models/route/ask/chat/sessions/policy/mcp/run/serve+curl/bench/cost` | all exit 0 or fail cleanly with hints |
| **CLI failure paths (new gate)** | busy port · closed pipe · `--json` without audit log | `[FAIL] cannot start gateway…` + hint · exit 141 quietly · valid empty-report JSON |
| Broken-pipe hygiene | `zyko doctor \| head -1` | stderr stays **empty** (was a `BrokenPipeError` traceback) |
| Windows encoding guard | stdout/stderr `errors=replace` at startup | legacy cp1252 consoles cannot crash on `—`/`·`/Arabic |
| Danger-tool lock | `allow: ["*"]` + `shell` call | blocked — wildcard never unlocks danger tools; explicit `tools.allow` entry required |
| Keyless first run (no flags) | `zyko route "hello"` with zero keys | exit 0 — auto-fallback to the demo provider with a notice |
| MCP stdio protocol | `initialize` → `tools/list` → `tools/call` + malformed-frame probe | correct JSON-RPC 2.0; bad frames get `-32700`, server survives |
| Gateway | OpenAI-compatible `/v1/chat/completions` incl. SSE, real socket, keep-alive | 401 then 200 on the same connection |
| Landing site | `docs/site` AR(RTL)/EN | badges/tests refreshed to 0.3.1 (230 · 92%) |
| Social card | `docs/assets/social-card.png` | version chip repainted **v0.3.1** (in-place patch, verified pixel-level) |

## Fixed in the v0.3.1 round

1. **`zyko cost --json` broke every pipeline** — printed `[INFO]` text instead of
   JSON when no audit log existed; now emits the exact report schema (empty),
   and the `[INFO]` stays for human mode.
2. **`zyko serve` on a busy port crashed with a raw `OSError` traceback** —
   now a friendly `[FAIL] cannot start gateway on <host>:<port>` + hint.
3. **`zyko doctor | head` printed a `BrokenPipeError` traceback** — the CLI
   detects the closed pipe and exits 141 (128 + SIGPIPE) quietly.
4. **Windows console hardening** — `errors="replace"` on stdout/stderr so a
   legacy code page cannot kill a command over an em-dash or Arabic text.
5. **Version-consistency trap** — bumping `version.py` alone leaves
   `pyproject.toml` stale; the existing sync test caught it during this round
   (kept as the guard).

## Evaluation notes (no action needed)

- A suspected corrupted CI trigger (`branches: ain]`) was investigated at the
  byte level (`od -c`): the YAML was always `[main]` — an ANSI-sanitizing log
  pipeline had swallowed `[m`. A trigger guard test was added anyway.
- Security posture re-verified: MCP clients spawn via `exec` (no shell),
  `http_get` rejects non-HTTP schemes, `shell` requires explicit allowlisting,
  calculator is AST-walled (no names/functions/bools, exponent cap).

---

# ZYKO v0.3.0 — Readiness Report (release QA)

Status: **READY** — all gates green on the reference environment (Linux, Python 3.12),
after a second full evaluation round that found and fixed three real correctness bugs.

## Gates

| Gate | Command | Result |
|---|---|---|
| Unit/integration tests (plain `pytest`, same as CI) | `pytest -q` | **203 passed** (0 failed, 0 skipped) |
| Lint | `ruff check .` | **0 findings** |
| Coverage (reference platform) | `pytest --cov=zyko` | **89% total** (`cli/commands` 90%, `client` 98%, `agents/loader` 100%, `agents/memory` 98%, `mcp/server` 91%) |
| Byte-compile | `python -m compileall src tests` | clean |
| Secret scan | `git grep` for token/key patterns | clean — no credentials in tree |
| CLI smoke (all commands) | `zyko version/info/doctor/models/route/ask/sessions/cost/policy/mcp/bench` | all exit 0 or fail cleanly with hints |
| Keyless first run (no flags) | `zyko route "hello"` with zero keys | exit 0 — auto-fallback to the demo provider with a notice |
| **Model pinning (new gate)** | `zyko ask --model provider/model --explain` | route honours the pin; receipt records `requested_model`; unknown pins fail fast with a hint |
| MCP stdio protocol | `initialize` → `tools/list` → `tools/call` + malformed-frame probe | correct JSON-RPC 2.0 responses; bad frames get `-32700` and the server survives |
| Gateway | OpenAI-compatible `/v1/chat/completions` incl. SSE + receipts, **over a real socket with keep-alive** | 401 then 200 on the same connection (regression test for the body-drain fix) |
| Cross-platform paths | XDG (Linux/Termux), macOS, Windows layouts | covered by `platform/paths.py` + tests |
| Landing site | `docs/site` AR(RTL)/EN | version/badge refs refreshed to 0.3.0 |

## Correctness bugs fixed in the v0.3.0 evaluation round

1. **Explicit model pins were ignored** — the router now enforces
   `--model provider/model` (bare-model and `provider/*` forms too), keeps
   fallbacks inside the pin, and records `requested_model` on receipts.
2. **Gateway keep-alive corruption on 401** — request bodies are drained
   before any early error response; verified over a real HTTP socket.
3. **Malformed JSON-RPC frame killed the MCP server** — now answered with
   `PARSE_ERROR (-32700)` per spec; `zyko_models` lists policy-filtered,
   availability-aware models instead of static catalogs.

## Added in v0.3.0

4. **`zyko sessions list|show|rm|clear`** — SQLite session memory is now
   user-visible and manageable (`clear` requires `--yes`).
5. **`zyko cost`** — spend & governance report from the audit log (per day,
   per candidate, vendor vs estimated accounting, deny rules, redactions).
6. **Receipts carry `requested_model`**; version consistency between
   `pyproject.toml` and `zyko.version` is test-enforced.

---

# ZYKO v0.2.0 — Readiness Report (release QA)

Status: **READY** — all gates green on the reference environment (Linux, Python 3.12.16),
and the CI-blocking defects found by the release review are fixed.

## Gates

| Gate | Command | Result |
|---|---|---|
| Unit/integration tests (plain `pytest`, same as CI) | `pytest -q` | **133 passed** (0 failed, 0 skipped) |
| Lint | `ruff check src tests benchmarks` | **0 findings** |
| Coverage (reference platform) | `pytest --cov=zyko` | **81% total** (core paths ≥ 94%) |
| Byte-compile | `python -m compileall src tests` | clean |
| Secret scan | `git grep` for token/key patterns | clean — no credentials in tree |
| CLI smoke (all commands) | `zyko info/doctor/models/route/ask/policy/mcp/bench` | all exit 0 or fail cleanly with hints |
| Keyless first run (no flags) | `zyko route "hello"` with zero keys | exit 0 — auto-fallback to the demo provider with a notice |
| MCP stdio protocol | `initialize` → `tools/list` → `tools/call` | correct JSON-RPC 2.0 responses, real subprocess test |
| Gateway | OpenAI-compatible `/v1/chat/completions` incl. SSE streaming + receipts | covered by tests |
| Cross-platform paths | XDG (Linux/Termux), macOS, Windows layouts | covered by `platform/paths.py` + tests |
| Landing site | `docs/site` rendered AR(RTL)/EN via Playwright | verified both languages + install tabs |

## Review findings fixed in the v0.2.0 evaluation round

1. **`Retry-After` was ignored on HTTP 429** — the header is now parsed
   (delay-seconds and HTTP-date), carried on `RateLimitError.retry_after`, and
   the retry loop honors the vendor's own backoff instruction (LiteLLM pattern).
2. **Streaming calls bypassed the budget** — streams now request
   `stream_options.include_usage` (OpenAI/OpenRouter), and the router charges
   the policy budget after every stream from vendor-reported usage, falling
   back to the kernel estimate; the audit entry records the accounting source.
3. **Coverage gaps** (`platform/paths` 54%, `mcp/server` 63%, `mcp/protocol`
   67%, `google` 73%) — new test groups incl. a real-subprocess MCP server
   round-trip; overall coverage 80% → 81% with the suite growing 106 → 133.
4. **`zyko version` missing** — added as a first-class command; `python -m zyko`
   now works too (`__main__.py`).
5. **`zyko bench --repeats N`** — repeat the deterministic suite for stabler medians.
6. **`ZYKO_GATEWAY_PORT` stayed a string** — `_coerce` now converts `*port` keys.
7. **CI matrix extended to Python 3.13** (3 OSes × 3 Pythons).

## Review findings fixed in the v0.1.0 release pass

1. **Plain `pytest` could not collect 4 test modules** — tests imported `tests.fakes`
   which only resolved under `python -m pytest` (cwd on sys.path). `tests/` is now a
   regular package (`tests/__init__.py`), so collection works under every invocation
   style on every OS. *(This is what was red in the previous CI runs.)*
2. **Keyless `zyko route` exited 1** — the CLI now falls back to the built-in
   deterministic demo provider with a visible notice, matching the project promise:
   first run works with zero keys on every platform. `zyko bench --demo` unchanged.
3. **`cargo check` failed** — `PyList::new` does not exist in pyo3 0.22; `top_k` now
   builds the list with `PyList::empty` + `append` (same semantics, parity-tested).
4. **Router O(n²) → O(n)** — normalization ranges snapshotted once per ranking pass;
   parity-tested bit-identical scores. *(earlier pass)*
5. **`zyko route <prompt>` ignored the prompt** — token/cost estimate now reflects the
   actual prompt. *(earlier pass)*
6. **Policy YAML typos were silently ignored** — unknown keys now warn in
   `zyko policy check` and surface in routing receipts. *(earlier pass)*
7. **MCP server governance gap** — `zyko mcp serve` honors `default_policy`, the
   quality ledger and demo mode, matching the CLI. *(earlier pass)*

## Repository page (this release)

- Bilingual README (AR-first RTL + EN) with CI/tests/platform badges and a social card.
- GitHub Pages landing site (`docs/site`, EN/AR toggle, RTL) deployed by `pages.yml`.
- Community kit: issue templates (platform-aware), PR template, Code of Conduct,
  `CITATION.cff`, Discussions link.
- Repo metadata: description, topics, homepage, Pages enabled via API.

## Known limitations (documented, non-blocking)

- Catalog prices are public list-price approximations for routing estimates; override
  via config for exact accounting.
- `zyko bench` measures only providers with configured keys; the mock provider lets
  you validate the pipeline deterministically.
- The optional Rust kernel must be built per-platform (`maturin`); the pure-Python
  kernel is the default everywhere and parity is test-enforced.

## Reproduce

```bash
pip install -e .[dev]
pytest -q                 # 133 passed
ruff check src tests benchmarks
zyko ask "hello" --demo --explain
zyko route "hello"        # no keys needed — auto demo fallback
zyko bench --demo
```
