# ZYKO v0.1.0 — Readiness Report (pre-release QA)

Status: **READY** — all gates green on the reference environment (Linux, Python 3.12.16).

## Gates

| Gate | Command | Result |
|---|---|---|
| Unit/integration tests | `pytest -q` | **106 passed** (0 failed, 0 skipped) |
| Lint | `ruff check src tests` | **0 findings** |
| Byte-compile | `python -m compileall src tests` | clean |
| Secret scan | `git grep` for token/key patterns | clean — no credentials in tree |
| CLI smoke (all commands) | `zyko info/doctor/models/route/ask/policy/mcp/bench` | all exit 0 or fail cleanly with hints |
| Keyless demo | `zyko ask --demo`, `zyko route --demo`, `zyko bench --demo` | full pipeline (routing → policy → receipt) with zero keys/network |
| MCP stdio protocol | `initialize` → `tools/list` → `tools/call` | correct JSON-RPC 2.0 responses, real subprocess test |
| Gateway | OpenAI-compatible `/v1/chat/completions` incl. SSE streaming + receipts | covered by tests |
| Cross-platform paths | XDG (Linux/Termux), macOS, Windows layouts + `--demo` (nothing compiles) | covered by `platform/paths.py` + tests |

## Review findings fixed in this pass

1. **Router O(n²) → O(n)** — normalization ranges snapshotted once per ranking pass; parity-tested bit-identical scores.
2. **`zyko route <prompt>` ignored the prompt** — now the token/cost estimate reflects the actual prompt; `explain()` exposes the estimate.
3. **No keyless first-run path** — added deterministic `MockProvider` + `--demo`/`ZYKO_DEMO=1` across `ask/route/chat/serve/run/bench`; first-run now works out of the box on every platform including Termux.
4. **Policy YAML typos were silently ignored** — unknown top-level/`defaults` keys now warn in `zyko policy check` and surface in routing receipts (`policy.snapshot()`).
5. **MCP server governance gap** — `zyko mcp serve` now honors `default_policy`, the quality ledger and demo mode, matching the CLI.
6. **Bench**: cost now uses vendor-reported token usage (kernel estimate only as fallback); fixed `--ledger` crash (str never converted to `Path`); fixed `median ms = None` for sub-0.05 ms candidates; dead code removed from `cmd_ask`.

## Known limitations (documented, non-blocking)

- Catalog prices are public list-price approximations for routing estimates; override via config for exact accounting.
- `zyko bench` measures only providers with configured keys; the mock provider lets you validate the pipeline deterministically.
- The optional Rust kernel must be built per-platform (`maturin`); the pure-Python kernel is the default everywhere and parity is test-enforced.

## Reproduce

```bash
pip install -e .[dev]
pytest -q
ruff check src tests
zyko ask "hello" --demo --explain
zyko bench --demo
```
