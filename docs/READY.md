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
