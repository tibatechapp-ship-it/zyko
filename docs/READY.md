# ZYKO v0.1.0 — Readiness Report (release QA)

Status: **READY** — all gates green on the reference environment (Linux, Python 3.12.16),
and the CI-blocking defects found by the release review are fixed.

## Gates

| Gate | Command | Result |
|---|---|---|
| Unit/integration tests (plain `pytest`, same as CI) | `pytest -q` | **106 passed** (0 failed, 0 skipped) |
| Lint | `ruff check src tests benchmarks` | **0 findings** |
| Byte-compile | `python -m compileall src tests` | clean |
| Secret scan | `git grep` for token/key patterns | clean — no credentials in tree |
| CLI smoke (all commands) | `zyko info/doctor/models/route/ask/policy/mcp/bench` | all exit 0 or fail cleanly with hints |
| Keyless first run (no flags) | `zyko route "hello"` with zero keys | exit 0 — auto-fallback to the demo provider with a notice |
| MCP stdio protocol | `initialize` → `tools/list` → `tools/call` | correct JSON-RPC 2.0 responses, real subprocess test |
| Gateway | OpenAI-compatible `/v1/chat/completions` incl. SSE streaming + receipts | covered by tests |
| Cross-platform paths | XDG (Linux/Termux), macOS, Windows layouts | covered by `platform/paths.py` + tests |
| Landing site | `docs/site` rendered AR(RTL)/EN via Playwright | verified both languages + install tabs |

## Review findings fixed in the release pass

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
pytest -q                 # 106 passed
ruff check src tests benchmarks
zyko ask "hello" --demo --explain
zyko route "hello"        # no keys needed — auto demo fallback
zyko bench --demo
```
