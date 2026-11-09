# Changelog

## 0.13.0 — Phase 6 of the coding engine: `zyko.baseline` — the quality guard over time

The engine so far was a one-shot: review, fix, goodbye. This release makes
it a **permanent guard**: it records your project's actual on-disk state in
a deterministic baseline file (`.zyko/baseline.json`) and every later
`check` compares the current tree against it and answers with numbers —
what regressed, what improved, what is new, what is gone. Same three
contracts as every phase: byte determinism (no timestamps anywhere — the
monotonic `run_no` is the only clock), structured failures instead of
exceptions, and honest skip documentation. Disk discipline is explicit and
tested: `update` writes exactly one file (the baseline) and never touches
a project file; `check` and `show` are read-only, always; the HTML report
is written only when `--html` is requested.

### Added
- **`zyko.baseline.engine`** — `BaselineEngine.update(src)`: deterministic
  tree walk (reusing the Phase-5 collector: sorted relative paths, no
  symlinks, system dirs skipped, 500-file cap) → per-file UTF-8 read with
  documented skips → 27-rule review → per-file record `{sha256, score,
  findings}` stored under schema `zyko.baseline/1` with a capped run
  history (last 20 runs). `BaselineEngine.check(src)`: re-reviews the tree
  and compares multiset-of-rule-ids per file — score drop **or** new
  findings ⇒ regression (exit 1, file named, counts exact); score rise or
  resolved findings ⇒ improvement (exit 0 + "update the baseline" advice);
  new/gone/skipped files are reported per file; a missing baseline is a
  documented state (exit 1, "run update first"), not an error; a corrupt
  or invalid baseline (bad JSON, bad encoding, wrong schema, files not an
  object, non-int/bool/out-of-range score, findings not strings, sha not a
  string, history not a list, baseline is a directory — 12 hostile cases)
  ⇒ structured `failed_stage` + Arabic reason + exit 2, never an
  exception. `update` over a corrupt baseline recovers by recreating it
  with an Arabic note. All-zero-review states ("لا مراجعة", "القياس
  متوقف") are honest documented exits.
- **`zyko.baseline.report`** — deterministic JSON/text emitters plus a
  one-line summary and the guarantees table, and **`baseline_check_to_html`**:
  a full Arabic RTL report (`dir="rtl"`, embedded CSS, no JavaScript, no
  external resources, no timestamps) with summary cards, the run-history
  trend table, and a per-file status table — every dynamic value passed
  through `html.escape`, and byte-identical across runs on the same state.
- **`zyko.baseline.gate`** — six quantitative gates on the same three
  Phase-5 anchor trees (flat CLI, nested package, mixed tree): **W1**
  update⇒check completes with zero regressions, **W2** byte-identical
  baseline files across identical copies + identical check payloads
  (paths normalized), **W3** regression detection (an injected `eval`
  ⇒ exit 1, file named, new findings counted), **W4** improvement
  detection (removing the worst file ⇒ announced per file), **W5**
  robustness (12 hostile inputs ⇒ structured Arabic failures), **W6**
  the full update+check cycle under 5 seconds per anchor.
- **`zyko.baseline.__main__`** — `python -m zyko.baseline
  update|check|show|gate|promise` with `--src/--baseline/--format
  text|json|summary/--html/--include-timing`; exit contract 0/1/2
  (0 = no regression, 1 = regression or missing baseline or stopped
  measurement, 2 = usage error or structured failure); `--html` writes
  the deterministic report only where explicitly asked.
- **MCP tool `baseline_check`** (10th tool, 7th deterministic one) —
  read-only baseline comparison over MCP with the same payload
  guarantees; missing-baseline answers as structured JSON, not errors.
- 94 new tests (`tests/test_baseline_{engine,report_cli,gate,robustness,mcp}.py`)
  — **1324 tests passing**; workspace/MCP tool-count regressions updated.

### Gates
- Phase-6 gate green: 3 anchors × 6 gates (complete / deterministic /
  detects-regression / detects-improvement / robust 12/12 / <5s).
- CI job `phase6-baseline`: baseline-module coverage ≥85%, the full gate,
  and a CLI cycle (update → check exit 0 → corrupt a file → check exit 1
  → `--html` report parses as valid RTL HTML).

## 0.12.0 — Phase 5 of the coding engine: `zyko.workspace` — the engine on existing projects

Final slice of the 90-day plan (Phase 5, D73–D90). Until now the engine
only improved code it had generated itself. This release opens it onto
**any Python directory on your disk**: review (27 rules) → fix (12 safe
paths) → re-review, with the same three contracts every phase shipped —
byte determinism, structured failures instead of exceptions, and every
finding keeping its original `suggestion_ar`. Caution around the user's
disk is a first-class feature: the default is a **dry run that writes
nothing**; `--out` writes a fixed copy into a new empty directory only;
`--in-place` demands an explicit `--yes`; and no file is written unless
its final source survives `ast`.

### Added
- **`zyko.workspace.engine`** — `WorkspaceEngine.run(src)`: deterministic
  scan (sorted relative paths, no symlinks, system directories skipped,
  500-file cap with an Arabic note) → per-file UTF-8 read (bad encoding /
  oversized files become documented skips, never crashes) → 27-rule
  review → fix rounds (0 = review-only, cap 3, convergence stop) →
  re-review → verified writes only (re-checked with `parses()` before
  the first byte lands). Hostile input — wrong type, empty path, missing
  directory, file instead of directory, negative/non-int/bool rounds,
  occupied output directory, in-place without confirmation, copy and
  in-place together, unknown write mode (12 cases) — ⇒ structured
  `failed_stage` (scan/reviewer/fixer/write/workspace) + Arabic reason +
  exit 2, never an exception. A crashing injected reviewer/fixer is
  exported the same way. Empty or all-unreadable directories are honest
  successes (`لا مراجعة`, exit 0), not errors.
- **`zyko.workspace.report`** — deterministic JSON/text emitters
  (schema `zyko.workspace/1`) plus a one-line summary and the
  guarantees table; every outcome line shows
  `الإصلاح: suggestion_ar`, every skip shows its Arabic reason; timing
  only with `include_timing=True`.
- **`zyko.workspace.gate`** — six quantitative gates on three Arabic
  anchor trees (flat CLI, nested package, mixed tree with a broken-syntax
  file and a UTF-16 file): **W1** end-to-end completion with real fixes,
  **W2** byte determinism across identical copies (paths normalized),
  **W3** idempotence (the engine on its own final output changes
  nothing), **W4** no-regression, **W5** robustness (12/12 hostile
  inputs → structured failures), **W6** performance (<5s per anchor).
- **`zyko.workspace.__main__`** — `run` (`--src`, `--out`, `--in-place`
  + `--yes`, `--rounds`, `--fail-under`, `--format text|json|summary`),
  `gate`, `promise`. Exit codes 0/1/2 — the same convention as reviewer,
  fixer and pipeline.
- **MCP tool `fix_workspace`** — the engine on an existing directory as
  a dry-run tool (never writes), joining the five deterministic tools
  (now 6 of 9 total).
- **Sample** — `samples/workspace/small_tool/` (three files: two with
  planted findings, one perfectly clean) + a generated `manifest.json`
  pinning per-file scores and per-rule fates; a test re-runs the engine
  on the sample and fails if reality drifts from the manifest.

### Fixed
- **Stale metadata the 0.11.0 pass missed**: the English half of the
  README still headlined «v0.8.0» and both halves still claimed
  «579 tests» in the quick-start while the suite had reached 1230; all
  synced to 0.12.0 (badge, AR/EN headers, quick-start counts).

### Gates
`python -m zyko.workspace gate` → ✅ (3 anchors × 6 gates, robustness
12/12); `zyko.workspace` coverage 94% (≥85% enforced in CI); full suite
1230 passed; ruff check/format clean.

## 0.11.0 — Phase 4 of the coding engine: `zyko.pipeline` — the feedback loop in one command

Fifth slice of the 90-day plan (Phase 4, D59–D72): coder → reviewer →
fixer wired into **one deterministic command**. One Arabic description
in, a **fixed** project out — not a raw scaffold — plus a byte-deterministic
Arabic report (text or JSON, schema `zyko.pipeline/1`) documenting every
file's score before/after and every finding's fate with its original
`suggestion_ar` untouched. Still no model, no network — the loop is
what LLM pipelines advertise and cannot prove.

### Added
- **`zyko.pipeline.engine`** — `PipelineEngine.run(description, out_dir)`:
  heuristic plan (injectable) → in-memory generation → 27-rule review →
  fix rounds (0 = review-only, cap 3 with an Arabic note, convergence
  stop) → re-review → verified writes only (files whose fixed source
  re-parsed). Contract, same spirit as phases 2–3: hostile input (wrong
  type, empty/oversized description, negative/non-int/bool rounds,
  occupied target dir) ⇒ structured `failed_stage` + Arabic reason +
  exit 2 — never an exception; a crashing injected planner/reviewer/
  fixer is exported the same way. Every outcome keeps `suggestion_ar`.
- **`zyko.pipeline.report`** — deterministic JSON/text emitters plus a
  one-line summary and a stages table; every outcome line shows
  `الإصلاح: suggestion_ar`; timing only with `include_timing=True`.
- **`zyko.pipeline.gate`** — six quantitative gates on four Arabic
  anchors covering the three templates: **G1** end-to-end completion,
  **G2** byte determinism (two runs, identical payloads), **G3**
  idempotence (the fixer on the loop's final output changes nothing),
  **G4** no-regression (no file scores lower) + real fixes present,
  **G5** robustness (9/9 hostile inputs → structured failures), **G6**
  performance (<5s per anchor).
- **`zyko.pipeline.__main__`** — `run` (the one command: `--dry-run`,
  `--rounds`, `--git`, `--fail-under`, `--format text|json|summary`),
  `gate`, `stages`. Exit codes 0/1/2 — same convention as reviewer
  and fixer (0 accepted, 1 findings remain, 2 structured failure).
- **MCP tool `run_pipeline`** — the loop as a dry-run MCP tool (never
  writes files), joining `code_review` and `auto_fix` (now 5
  deterministic tools).

### Fixed
- **Stale repo metadata**: README still announced «النسخة 0.8.0» and a
  579-tests badge while the suite had grown to 1125; the Phase 2/3
  surfaces (`zyko.reviewer`, `zyko.fixer`) had no "what's new" section
  at all; `CITATION.cff` still cited 0.8.0. All synced to 0.11.0.

### Gates
`python -m zyko.pipeline gate` → ✅ (4 anchors × 6 gates, robustness
9/9); `zyko.pipeline` coverage 94% (≥85% enforced in CI); full suite
1131 passed; ruff check/format clean; bandit clean.

## 0.10.0 — Phase 3 of the coding engine: `zyko.fixer` — deterministic Arabic auto-fix

Fourth slice of the 90-day plan (Phase 3, D41–D58): the fix half of
generate → review → **fix**. 12 safe, deterministic repair paths over
the reviewer's 27 rules — every finding, fixed or not, keeps its
Arabic `suggestion_ar`; every applied fix is re-parsed with `ast`
before acceptance and the whole output is idempotent by gate. No
model, no network, byte-identical runs — what LLM fixers cannot
promise.

### Added
- **`zyko.fixer.edits`** — anchored text surgery, not `ast.unparse`
  regeneration: comments and formatting outside the touched span stay
  byte-identical. Includes the UTF-8 byte-column ↔ character-column
  conversion (a trap that silently corrupts Arabic source lines) and
  overlap-safe, end-to-start application with per-edit Arabic skip
  reasons.
- **`zyko.fixer.fixes`** — the 12 auto-fixable paths (bare `except`,
  raise-from with handler naming, `open` → `with` block wrapping,
  `shell=True` removal on list commands, mutable-default → `None` +
  in-body guard with docstring-preserving placement, unsafe yaml →
  `safe_load` (+unsafe `Loader` kw removal), md5/sha1 → sha256,
  TLS verify restore, Arabic docstring insertion, `== None` →
  `is None` (operator located by gap search — AST op nodes carry no
  positions), dead imports (strings- and `__all__`-aware, `__init__`
  exempt), lambda → def with bracket-aware head splitting) plus an
  explicit Arabic reason for each of the 15 manual rules.
- **`zyko.fixer.engine`** — `FixerEngine.fix_source/fix_file/
  fix_path`: up to 3 chained passes (fixing the lambda surfaces its
  missing docstring — the engine finishes the chain), per-rule
  fallback when a batch fails verification, structured results for
  hostile input, score before/after, statuses fixed/manual/open with
  Arabic action text. JSON schema `zyko.fix/1`, timing off by default.
- **`zyko.fixer.report`** — deterministic JSON and Arabic text
  emitters; every outcome line carries `الإصلاح: suggestion_ar`.
- **`zyko.fixer.gate`** — six quantitative gates on anchor samples
  (`samples/fix`): **G1** expected auto fixes fully resolved, **G2**
  no damage + idempotence (second run changes nothing, score never
  drops), **G3** byte determinism, **G4** 11 hostile inputs, **G5**
  performance (<5s), **G6** no dead path (12/12 auto rules fix
  somewhere; 15/15 manual rules surface with their suggestion).
  Current state: **6/6**.
- **`python -m zyko.fixer`** — CLI (`fix` / `check` / `gate` /
  `rules`): dry-run by default, `--write` stores only parse-verified
  output, `--diff`, `--rules` filter, linter exit codes (0/1/2).
- **MCP `auto_fix` tool** — the fourth no-model deterministic tool,
  always dry-run (never writes from MCP), joins `pii_ar_scan`,
  `rtl_check`, `code_review`.
- **`samples/fix/`** — anchor corpus: the three defective review
  samples + `fix_edges.py` (edge cases incl. parenthesized imports,
  multiline lambda, single-line defs, chain comparisons) +
  `manifest.json` generated by `scripts/gen_phase3_manifest.py`
  (hand-authored expectations verified before writing).
- **CI job `phase3-fixer`** — coverage ≥85% (local: ~97%), the
  six-gate run, and the CLI contract (dry-run → `--write` → clean
  `check`).

### Notes
- 190+ new tests; full suite green; ruff + RTL + Arabic typography
  gates unchanged and passing.
- The fixer refuses what it cannot prove: string `shell=True` stays
  manual, indirect `open()` stays manual, imports in `__init__.py`
  are never auto-removed — refusing safely is the feature LLM fixers
  cannot offer.
- GitGuardian follow-up: the two training "secret" values in
  `samples/review/bad_security.py` are reworded to clearly-fake
  Arabic text; detection is name-based so R-SEC-105 still fires.

## 0.9.2 — Phase 2 of the coding engine: `zyko.reviewer` — deterministic Arabic code review

Third slice of the 90-day plan (Phase 2, D22–D40): the review half of
generate → **review** → fix. 27 AST-only rules in three categories
(error handling, security, quality) score any Python file 0–100 with
an Arabic verdict and a suggested fix for every finding — no model, no
network, byte-identical output on every run.

### Added
- **`zyko.reviewer.rules`** — the rule registry: `R-ERR-001..010`
  (bare except, swallowed exceptions, raise-without-from, open outside
  `with`, `shell=True`, mutable defaults, assert-validation,
  return-in-finally, broad `Exception`, `BaseException`),
  `R-SEC-101..108` (eval/exec, pickle, unsafe yaml.load, SQL string
  building, hardcoded secrets, weak hashes, TLS verify off, os.system),
  `R-QLT-201..209` (long functions, deep nesting, too many args,
  missing docstrings, missing type hints, `== None`, unused imports,
  builtin shadowing, lambda assignment). Every rule carries an Arabic
  message and an Arabic suggested fix.
- **`zyko.reviewer.engine`** — `ReviewEngine.review_source/review_file/
  review_path`: score = 100 − severity weights (critical 15, high 8,
  medium 4, low 2), Arabic verdicts (مقبول/يحتاج تحسينًا/يحتاج
  إصلاحًا/مرفوض), structured results for hostile input — syntax errors,
  non-UTF-8, null bytes, oversized files never raise.
- **`zyko.reviewer.report`** — deterministic JSON (`zyko.review/1`)
  and Arabic text emitters; timing excluded by default so reports are
  byte-reproducible.
- **`zyko.reviewer.gate`** — the first-by-first acceptance harness,
  six quantitative gates on anchor samples (`samples/review`):
  **G1** 29/29 planted defects recalled (±2-line window), **G2** zero
  findings on clean samples (no false positives), **G3** byte
  determinism, **G4** 11 hostile inputs without a crash, **G5**
  performance (<5s), **G6** no dead rules. Current state: **6/6**.
- **`python -m zyko.reviewer`** — CLI (`review` / `gate` / `rules`)
  with linter exit codes: 0 clean, 1 findings or failed gate, 2 usage.
- **MCP `code_review` tool** — same engine over MCP (`text` or `path`,
  optional `fail_under`), joining `pii_ar_scan` and `rtl_check` as the
  third no-model deterministic tool.
- **`samples/review/`** — anchor corpus: three defective files with 29
  marker-tracked planted defects + two spotless files (100/100) +
  `manifest.json` generated by `scripts/gen_phase2_manifest.py`.
- **CI job `phase2-reviewer`** — coverage ≥85% (local: 96%), the
  six-gate run, and the CLI exit-code contract.

### Notes
- 162 new tests; full suite now 886 tests, all green; ruff + RTL +
  Arabic typography gates unchanged and passing.
- The reviewer deliberately reports, it does not guess: every finding
  is bound to a rule id + line + column, verifiable by hand — the
  anti-hallucination property LLM-based reviewers cannot offer.

## 0.9.1 — Phase 1 of the coding engine: `zyko.coder` — deterministic project generation

Second slice of the 90-day plan (Phase 1, D8–D21): from an Arabic
description to a complete, tested, receipted project — models *fill the
plan*, everything else is deterministic and byte-reproducible.

### Added
- **`zyko.coder.plan` (D10–11)** — validated `ProjectPlan` dataclass:
  name (latin slug), template, Arabic description, modules (safe python
  identifiers), PEP 508 dependencies, run commands. Strict `from_dict`
  rejects unknown keys and non-string fields and reports *all* problems
  at once in Arabic — model drift is caught, never silently defaulted.
- **`zyko.coder.templates` (D8–9)** — three Jinja-less templates:
  `python-cli` (src-layout stores + argparse CLI), `fastapi-api`
  (in-memory CRUD + /health), `static-site` (RTL-first HTML with
  logical CSS properties only). Each generated file carries its Arabic
  reason (for the receipt).
- **`zyko.coder.generate` (D12–13)** — plan → full file tree + `git
  init` + Arabic initial commit with pinned identity and fixed dates:
  same plan ⇒ byte-identical repository. Refuses to write into a
  non-empty directory.
- **`zyko.coder.precheck` (D14)** — nothing broken reaches the user:
  `ast.parse` + `compile()` on every python file, `zyko.tools.rtl`
  gate (errors block), optional pytest run with a hard timeout.
- **`zyko.coder.receipt` (D19)** — `RECEIPT.md` per project: original
  description, validated plan, every file with its reason and a sha256
  manifest (16-hex). Offline-verifiable via `sha256sum`.
- **`zyko.coder.crew_prompts` (D15–16)** — Arabic system prompts for
  the three roles (planner → coder → checker) over `zyko.crew`; the
  checker consumes the deterministic precheck report, never replaces it
  (hybrid order: deterministic first).
- **`zyko.coder.heuristics`** — deterministic Arabic-description →
  draft plan (10 intents: todo/notes/expenses/pomodoro/blog/restaurant/
  gallery/bookings/store/school) — the model-free stand-in used by CI
  and `zyko new` previews.
- **`zyko.coder.gate` (D20–21)** — the acceptance harness: 10 realistic
  Arabic descriptions, end-to-end. Phase gate: 10/10 generate, ≥8/10
  pass their first test run. Current state: **10/10 · 10/10**.
- **CLI** — `zyko new --plan "وصف عربي"` (plan preview → explicit
  approval → build; `--json` previews without writing) and
  `python -m zyko.coder plan|new|check|gate`.
- **CI** — new `phase1-coder` job: zyko.coder coverage ≥85% (90%), the
  full 10-description gate, and a `zyko new` end-to-end smoke.

## 0.9.0 — DeepSeek V4 models: 1M context in the router catalog

Platform-track release between 0.8.2 and 0.9.1, outside the 90-day engine
plan. It shipped with a git tag and a GitHub release but never received a
CHANGELOG section — added retroactively during the repository
tag-organization pass (November 2026), with content taken verbatim from
its release notes.

### Added
- Two DeepSeek V4 models in the catalog: `deepseek-v4-pro` — 1M context,
  $1.32/$3.96 per MTok, tagged `agentic`, `long-context`; and
  `deepseek-v4.1-flash-1017` — 1M context, $0.96/$1.91 per MTok, tagged
  `cheap`, `long-context`. Both feed directly into router scoring
  (cost / latency) and into `zyko models`.

### Caveats
- `max_output` set conservatively to 65,536; DeepSeek may allow more.
- Slugs and prices should be re-verified against api-docs.deepseek.com
  before using them for production cost estimates.

### Tests
- 584 passing (was 581).

## 0.8.2 — Phase 0 of the coding engine: deterministic Arabic tools

First slice of the 90-day "coding engine" plan (Phase 0, D1–D7): two
model-free Arabic tools vendored as Layer-1 `zyko.tools`, wired into the
policy engine, the MCP server, and CI. Deterministic means: no model calls,
no randomness, byte-identical results — model outage never stops them.

### Added
- **`zyko.tools.pii_ar`** — deterministic Arabic PII detection & redaction:
  phones across 22 country rules (Arabic-Indic digits preserved as-is),
  8 national-ID formats with math validation (Egyptian birthdate check,
  Saudi 1/2 prefix, UAE 784+15), IBAN with mod-97 (20 countries), Luhn cards
  including **mada**, dictionary-based names, addresses, emails.
  CLI: `python -m zyko.tools.pii_ar scan|redact` (exit 0/1/2).
- **`zyko.tools.rtl`** — deterministic RTL problem detector, 15 rules across
  CSS (`text-align:left` in RTL context, physical margins/floats),
  HTML (missing `dir` on Arabic documents, `rtl` without `lang`,
  inline `text-align:left` inside RTL), Python (Arabic-vs-Latin string
  comparisons that can never match, Arabic-Indic vs ASCII digit comparisons,
  mixed-script membership lists, Trojan-Source bidi controls
  CVE-2021-42574, unparseable files, mixed-script identifiers) and
  mixed-direction text lines. CLI: `python -m zyko.tools.rtl check|rules`.
- **Policy (D5)** — `privacy.redact` now accepts **`pii_ar`**: a
  function-based redactor (checksums and dictionaries cannot be one regex)
  that runs *before* the generic patterns, so Arabic PII is masked first
  and the Latin regexes only see what it left behind.
  Example: `examples/policies/pii_ar.yaml` —
  `zyko policy check examples/policies/pii_ar.yaml`,
  `zyko policy redact "اسمي محمد أحمد ورقمي 0501234567" examples/policies/pii_ar.yaml`.
- **MCP (D6)** — two new tools on `zyko mcp serve`: **`pii_ar_scan`**
  (text → typed, checksum-validated findings) and **`rtl_check`**
  (text+lang or path → rule, severity, message, suggestion per finding).
  Both return JSON text content and need no router/model.
- **CI (D7)** — new `phase0-tools` job: coverage gate ≥85% for
  `zyko.tools` (measured 92%), 20/20 planted-PII gate on
  `samples/arabic_mix.txt`, policy validation gate, RTL self-gate
  (`zyko.tools.rtl check --path src --fail-on warning`), and an Arabic
  typography scan (`scripts/check_arabic_typography.py`: Latin comma /
  question mark / semicolon between Arabic words).
- **82 new tests** — across `tests/test_tools_pii_ar.py`,
  `tests/test_tools_rtl.py`, `tests/test_tools_policy_mcp.py`, plus the
  MCP tools-list regression update (repo total: 666).

## 0.8.1 — MCP tools now honor the policy allow-list

Security patch between 0.8.0 and 0.8.2. It shipped with a git tag and a
GitHub release but never received a CHANGELOG section — added retroactively
during the repository tag-organization pass (November 2026), with content
taken verbatim from its release notes.

### Fixed
- **Agent tool policy now applies to MCP tools too.** `Agent._execute()`
  gated only built-in tools through `PolicyEngine.allows_tool()`; MCP tool
  calls bypassed the policy entirely. The allow-list is now enforced for
  every tool name (built-in and `mcp__server__tool`), closing the last
  policy gap before the tool dispatcher. Found during the post-0.8.0
  security review; verified with two regression tests in
  `tests/test_agent_mcp_policy.py`.

### Tests
- 581 passing (was 579).

## 0.8.0 — the receipt becomes verifiable: `zyko verify`

The "verifiable routing" pillar had a receipt but no verifier: a third party
could read the ranking, components and weights, and nothing more. This release
makes the strongest claim in the README runnable.

### Added
- **`zyko verify RECEIPT`** — recomputes a receipt offline and exits non-zero
  on any drift. Checks: supported `receipt_version`, known strategy, weights
  exactly equal to the published `STRATEGY_WEIGHTS[strategy]`, every component
  inside `[0, 1]`, every `total` recomputed from its own components, ranking
  sorted descending, `chosen` present when the ranking is complete, and — with
  `--ledger` — quality scores plus the `ledger_updated` stamp matching the
  supplied quality ledger. `--json` emits a machine-readable report
  (`{"ok": …, "checks": …, "issues": [{"code", "message"}]}`), `--tolerance`
  tightens the float comparison.
- **`zyko.router.verify`** — the reusable core (`load_receipt`,
  `verify_receipt`, `VerifyReport`, `VerifyIssue`) so embedders can gate their
  own pipelines without shelling out.
- **14 tests** — 13 in `tests/test_verify.py` (happy path, ledger cross-check,
  tampered total, invented weights, quality drift, ledger stamp mismatch,
  out-of-range component, unsorted ranking, unknown version/strategy,
  malformed input, CLI exit codes and JSON) plus a router regression test.

### Fixed
- **`cost_score` could exceed 1.0** (observed 1.0441) for short prompts. The
  board snapshot used to be normalised at the 800/400-token default while the
  request was scored with its own estimate, so a cheap candidate could land
  below the board minimum. The estimate now flows into `_board_snapshot()`,
  and both normalisers clamp to `[0, 1]` as defence in depth. Found by the new
  verifier — the invariant it enforces was silently broken.
- **Platform tests assumed Linux/Windows/macOS.** `test_sandbox_is_linux` and
  `test_detect_windows_macos_android` now account for `OSKind.TERMUX` and the
  Android `sys.getandroidapilevel` marker, so a Termux run is 579/579 instead
  of 577/579 — the platform the README advertises first-class no longer has
  second-class tests.
- **`pip install -e ".[dev]"` on Python 3.14 / Termux.** `pydantic>=2.0` has
  no `pydantic-core` wheel there, so the documented dev install failed on the
  platform ZYKO advertises. The extra now carries
  `python_version < '3.14'`; the pydantic-specific tests already use
  `pytest.importorskip`.

### Changed
- **Docs version-synced** — README header `0.5.0` → `0.8.0`, tests badge
  `438` → `579`, Python badge gains 3.14, `zyko route --explain` (a flag that
  never existed) → `zyko ask --explain` in `docs/API.md`,
  `docs/ARCHITECTURE.md`, `client.py` and the router docstring, and
  `docs/READY.md` is explicitly marked as the archived v0.3.3 snapshot.
- Python 3.14 classifier added (the suite runs green there, including on
  Termux/Android).


## 0.7.0 — governed multi-user gateway: identities, not just a token

Roadmap item from the pre-broad-production order in `docs/STRATEGY.md`
("مصادقة متعددة المستخدمين للبوابة"): until 0.6 the gateway knew exactly one
bearer token. ZYKO now ships a **governed multi-user gateway** — a
declarative users file where every caller is a named identity with its own
key, roles, rate limit and daily budget. Verification is constant-time
(`hmac.compare_digest` over *every* entry, no early exit, so request timing
never reveals which key matched); keys can be stored as stdlib scrypt records
(`zyko hash-key`) so the users file never has to hold a usable secret; and
governance is enforced per user, not just globally: per-user RPM (token
bucket), per-user daily USD budget persisted across restarts (same pattern
as the policy engine's budget), role scopes (`chat` for `/v1/*`, `admin`),
and every response receipt carries `"user"`. Configuration problems raise
the new typed `GatewayAuthError` (a `ConfigError`) **before** the server
binds — a broken users file never half-starts a gateway.

```python
from zyko import Zyko
from zyko.gateway.auth import UserStore
from zyko.gateway.server import serve

store = UserStore.load("users.yaml")  # named users: key or scrypt key_hash
zk = Zyko()
serve(zk.router, host="127.0.0.1", port=8787, users=store)
# GET /v1/users/me → identity + usage today + remaining budget
```

### Added
- **`zyko.gateway.auth`** — new public module: `UserStore` (YAML loading
  with the same search rules as agents/crews), `GatewayUser`, `hash_key`
  (stdlib scrypt: `scrypt$n$r$p$salt$hash`, fresh salt per call) and
  `verify_key` (constant-time; malformed records verify as False, never
  raise).
- **Users file** — each user: `name` (unique), exactly one of `key`
  (plaintext, dev) or `key_hash` (production), `roles` (subset of
  `chat`/`admin`), `enabled` (default true), optional `rpm` and optional
  `daily_budget_usd`. Everything is validated up front; duplicate names,
  unknown roles, bad rpm/budget or a missing key raise `GatewayAuthError`
  before the gateway binds.
- **HTTP governance** — 401 invalid/missing token, 403 disabled user,
  429 `zyko_rate_limit` when the user's RPM bucket is empty, 429
  `zyko_budget_exceeded` when the user's daily budget is spent. Every
  response's `zyko.receipt` carries `"user"`; usage (requests, tokens,
  estimated USD) is persisted per user per day to
  `~/.local/share/zyko/gateway_users_state.json` and survives restarts.
- **`GET /v1/users/me`** — a user inspects their own identity, today's
  usage and remaining budget (no key material ever leaves the store).
- **CLI** — `zyko serve --users users.yaml` (or `gateway.users` in
  settings / `ZYKO_GATEWAY_USERS`), and `zyko hash-key [--key …]` to emit
  scrypt records for `key_hash:` entries (hidden prompt without `--key`).
- **Legacy modes unchanged** — single `--api-key` (now also constant-time)
  and the open gateway behave exactly as before; legacy receipts carry no
  `"user"` key. `serve` announces its mode: `multi-user (N users)` vs
  `single-token/open`.

### العربية
بند خارطة الطريق من قائمة ما قبل الإنتاج الواسع في `docs/STRATEGY.md`
("مصادقة متعددة المستخدمين للبوابة"): حتى 0.6 كانت البوابة تعرف رمزًا حاملًا
واحدًا فقط. الآن تأتي **بوابة متعددة المستخدمين محكومة** — ملف مستخدمين
تصريحي، كل منشئ طلب هوية مُسمّاة بمفتاحها وأدوارها وحدّ معدلها وميزانيتها
اليومية. التحقق بزمن ثابت (`hmac.compare_digest` على كل مدخل بلا خروج
مبكر، فالتوقيت لا يكشف أي مفتاح وَافق)؛ ويمكن تخزين المفاتيح كسجلات scrypt
قياسية (`zyko hash-key`) فلا يحمل الملف سرًا صالحًا للاستخدام؛ والحوكمة
تُفرض لكل مستخدم: حد معدل لكل مستخدم (دلو توكن)، وميزانية يومية بالدولار
تُخزَّن وتنجو من إعادة التشغيل، ونطاقات أدوار (`chat` لـ`/v1/*` و`admin`)،
وكل إيصال استجابة يحمل `"user"`. أخطاء الإعداد ترفع `GatewayAuthError`
المكتوبة النوع (فرع من `ConfigError`) **قبل** ربط الخادم — ملف مستخدمين
معطوب لا يُشغّل بوابة نصف جاهزة أبدًا.

```yaml
name: team-gateway
users:
  - name: alice
    key: zk-dev-only              # تطوير فقط
    roles: [chat]
    rpm: 60
  - name: ops
    key_hash: scrypt$16384$8$1$…$…   # من `zyko hash-key`
    roles: [chat, admin]
    daily_budget_usd: 5.0
```

- **`zyko.gateway.auth`** — `UserStore` + `GatewayUser` + `hash_key` +
  `verify_key`؛ التحقق بزمن ثابت والسجلات المشوّهة ترفض بصمت ولا ترفع 500.
- **حوكمة HTTP**: ‏401 رمز غير صالح، ‏403 مستخدم معطّل، ‏429 تجاوز حد
  المعدل (`zyko_rate_limit`)، ‏429 تجاوز الميزانية اليومية
  (`zyko_budget_exceeded`)؛ وكل إيصال يحمل هوية المستخدم والاستخدام اليومي
  (طلبات/توكنات/دولار مقدّر) يُخزَّن لكل مستخدم وينجو من إعادة التشغيل.
- **`GET /v1/users/me`** — يفحص المستخدم هويته واستخدامه ومتبقّي ميزانيته
  (لا مادة سرية تترك المخزن أبدًا).
- **الطرفية**: ‏`zyko serve --users users.yaml` (أو `gateway.users` في
  الإعدادات) و`zyko hash-key` لتوليد سجلات scrypt.
- **الأنماط القديمة كما هي**: رمز واحد (`--api-key`، أصبح بزمن ثابت أيضًا)
  والبوابة المفتوحة؛ إيصالاتها بلا مفتاح `"user"`.

28 اختبارًا جديدًا (`tests/test_gateway_auth.py`) — **565 اختبارًا ناجحًا**،
‏ruff نظيف، ‏bandit صفر نتائج، ‏CI ‏14/14 على Linux/Windows/macOS × Python
‏3.11–3.13.

## 0.6.0 — multi-agent crews: a sequential pipeline with shared context — CrewAI-parity in simplicity, stronger in governance

Roadmap step 4 from `docs/STRATEGY.md` ("الوكلاء المتعددون"): ZYKO now
**coordinates a crew of agents**. An ordered list of steps, each step one
configured agent plus a task template that may reference the crew input
(`{task}`), the previous step's output (`{output}`) or any earlier
`output_key`. Formatting is safe by construction — unknown placeholders
stay literal, substituted values are never re-formatted (JSON and braces
survive round-trips), and templates are validated when a step is added, so
malformed tasks fail fast instead of mid-run. Governance is stronger than
CrewAI's: no hidden prompts — every agent keeps its own system prompt,
tools and policy; every step runs inside a `crew.step` span nested under a
`crew.run` span; the result is a full auditable receipt.

```python
from zyko import Zyko

zk = Zyko()
crew = zk.crew("triage.yaml")  # declarative YAML: inline or file agents
res = crew.run("my invoice is late")
print(res.output)  # final agent's answer
print(res.outputs["class"])  # any declared step output
```

### Added
- **`zyko.crew`** — new public package: `Crew` (chainable `add(agent, task,
  output_key=…)`), `CrewStep`, `CrewResult` and `fill_template`.
- **Safe shared-context templates** — three references only: `{task}` (the
  crew input), `{output}` (previous step's output, empty for step 1) and
  any earlier `{output_key}`. Unknown keys stay literal (`{json}` in prose
  is text, never a crash); positional or malformed placeholders (`{}`,
  `{0}`, `{a!}`) raise the new typed **`CrewError`** (exported from the
  `zyko` root) at `add()` time — fail fast, not mid-run. Default
  `output_key` is the agent name, deduped as `name_2`, `name_3`, …;
  duplicate explicit keys raise immediately instead of silently corrupting
  the shared context later steps depend on.
- **Declarative YAML** (`load_crew` / `zk.crew("file.yaml")`) — steps
  reference agent files (searched like `zyko run` does) or inline agent
  mappings (`name`, `system`, `model`, `max_steps`, `tools`, `mcp_servers`);
  config problems raise `ConfigError` before anything runs.
- **CLI**: `zyko crew crew.yaml --input "…" [--json] [--trace]` — `--json`
  prints ONLY the full `CrewResult` JSON on stdout (machine contract);
  `--trace` adds the per-step table.
- **Auditable receipt** — `CrewResult`: `output`, `outputs` (insertion
  ordered), per-step records (agent, key, filled task, output, agent
  steps, truncated flag, elapsed), aggregated token usage, `trace_id`.
  Every step is a `crew.step` span under `crew.run` — visible in
  `zyko traces` and any OTLP backend.
- **Typed failures end-to-end** — crew bugs raise `CrewError`; provider
  outages propagate as their real typed error (`ProviderError`, …) after
  the router's retry budget, never as a bare string; the `crew.run` span
  is marked `error` automatically.

### Notes
- Zero new dependencies; the crew layer is stdlib + the existing stack.
- 34 new tests (`tests/test_crew.py`) — **537 tests passing**, `ruff` clean,
  `bandit` 0 findings, CI 14/14 on Linux/Windows/macOS × Python 3.11–3.13.

## 0.5.0 — RAG essentials: chunk → embed → search → `ask(context=…)` — the LlamaIndex-minimum, zero-dependency by default

Roadmap step 3 from `docs/STRATEGY.md` ("أقل ما يرضي مستخدم LlamaIndex"):
ZYKO can now ground answers in your own documents. A chunker, three
embedders behind one contract, a local vector store whose **persistence is
a JSON file you own** (same philosophy as the trace log), and a `context=`
parameter on `ask`. The default embedder is pure-stdlib feature hashing —
deterministic, offline, phone-capable — so the whole story works with zero
keys, zero network and zero new dependencies; swap in Ollama (local, real
semantics, no keys) or OpenAI embeddings when you want them.

```python
from zyko import Zyko
from zyko.rag import HashingEmbedder, VectorStore

store = VectorStore(HashingEmbedder(), path="kb.json")
store.add(open("handbook.md").read(), meta={"source": "handbook"})
hits = store.search("refund policy", k=4)
answer = Zyko().ask("what is the refund policy?", context=[h.text for h in hits])
```

### Added
- **`zyko.rag`** — new public package: `chunk_text` (paragraph-first,
  hard-split with overlap, never empty chunks), `cosine` (zero-vector
  safe), `Hit` and `VectorStore`.
- **Three embedders, one contract** (`embed`/`aembed` → vectors, `name`,
  `dim`): `HashingEmbedder` (blake2b feature hashing — deterministic across
  machines, ideal for tests/demos/Termux), `OllamaEmbedder`
  (`nomic-embed-text` locally — real semantics, no keys), `OpenAIEmbedder`
  (`text-embedding-3-small` or any OpenAI-compatible endpoint). All
  failures raise the new typed **`EmbedderError`** (exported from the
  `zyko` root) — never a raw `httpx` exception.
- **`VectorStore(embedder, path=None)`** — in-memory cosine index;
  `path` auto-loads on construction and atomic-saves (tmp + replace) after
  every `add`. `add(text, meta=…) → chunk count`, `search(query, k=4,
  min_score=0.0)` (default gate keeps only positively-correlated chunks;
  `min_score=-1.0` shows everything), `aadd`/`asearch` async mirrors,
  thread-safe. A saved store searched with a different embedder loads with
  a loud warning; a dimension mismatch raises `EmbedderError` instead of
  corrupting the index; an unreadable store file starts empty instead of
  crashing.
- **`Zyko.ask(prompt, context=[...])`** (and `aask`) — non-empty context
  becomes its own grounding system message ("answer from the context; say
  so if insufficient") after any explicit `system`, before the user
  prompt. Works with plain strings — the store is optional.
- **`docs/API.md` §15** documents the whole flow.

### Notes
- Zero new dependencies (the default embedder is stdlib; vendor embedders
  ride the existing `httpx`).
- 26 new tests (`tests/test_rag.py`) — **503 tests passing**, `ruff` clean,
  `bandit` 0 findings, CI 14/14 on Linux/Windows/macOS × Python 3.11–3.13.

## 0.4.2 — observability bridge: spans now flow to Langfuse, Tempo, Jaeger or any OTLP backend — still zero new dependencies

Roadmap step 2 from `docs/STRATEGY.md` (the competitive benchmark): LangChain
sells observability as LangSmith; CrewAI needs AgentOps; ZYKO's spans already
lived on your disk (0.4.1) and now they **flow into the stack your team
already runs**. `OtlpSink` speaks OTLP/HTTP with JSON encoding — the
OpenTelemetry Collector's standard wire protocol — over the `httpx` ZYKO
already ships, so OTel Collector, Langfuse, Grafana Tempo, Jaeger, Honeycomb,
New Relic and Datadog all work with **zero new dependencies and zero vendor
lock-in**. One environment variable turns it on:

```console
ZYKO_OTLP_ENDPOINT=http://localhost:4318/v1/traces zyko ask "hello"
```

### Added
- **`zyko.observability.OtlpSink`** — OTLP/HTTP-JSON exporter: one daemon
  worker batches up to `batch_size` spans per POST (default 64), so a busy
  gateway pays one request per batch, not one per span. The same spans keep
  flowing to the local JSONL log in parallel — export is additive, never a
  replacement.
- **Never-breaks/slow contract, enforced**: `write()` only enqueues — network
  latency never touches the caller's request path; a full queue **drops**
  (counted in `.dropped`) instead of blocking; endpoint outages degrade to
  one warning line per outage (debug afterwards, re-warns on recovery);
  `close()` drains pending spans and is safe to call twice.
- **Spec-exact OTLP mapping** — 16-byte trace ids / 8-byte span ids derived
  **deterministically** (`sha256` of a tagged id) from ZYKO's shorter ids, so
  the same id always maps to the same OTLP id and parent links survive the
  trip; originals ride along as `zyko.trace_id`/`zyko.span_id`/
  `zyko.parent_id` attributes so `zyko traces --trace <id>` drill-down stays
  lossless. Full AnyValue typing: strings, ints (as decimal strings per the
  OTLP/JSON spec), floats, bools, arrays, nested key-values, null. Status
  mapping: `ok` → `STATUS_CODE_OK`, `error`/`cancelled` →
  `STATUS_CODE_ERROR` + reason as the status message.
- **Settings + env** — `tracing.otlp.{endpoint,headers,timeout_s,
  service_name,batch_size,queue_size}` with the `ZYKO_OTLP_ENDPOINT`
  override (env wins, whitespace-trimmed); `zyko doctor` gained an
  **Observability** section showing the tracing state and the OTLP target.
- **MCP determinism, finished** — the macOS/py3.11 race from 0.3.7 had one
  last corner: a server dying right after the `initialize` reply could blow
  up `start()` itself when the `notifications/initialized` write raced the
  process death. Notifications are now fire-and-forget by contract (the
  reader loop stays the single source of truth for server death; `_request`
  keeps raising the same typed `MCPError`) — `start()` is deterministic on
  every OS, pinned by a new regression test.

### Recipes (documented in `docs/API.md`)
- **Langfuse cloud**: endpoint
  `https://cloud.langfuse.com/api/public/otel/v1/traces` with
  `authorization: "Basic ${LANGFUSE_BASIC}"` (base64 of `pk:sk`) — config
  files interpolate `${ENV_VARS}`, so the secret never lands on disk.
- **Self-hosted stack**: OTel Collector `http://localhost:4318/v1/traces`,
  Grafana Tempo `:4318`, Jaeger `:4318` — same variable, no code.

### Notes
- Zero new dependencies (OTLP/JSON rides the existing `httpx`).
- 14 new tests (13 OTLP + 1 MCP regression pin) — **477 tests passing**,
  `ruff` clean, `bandit` 0 findings, CI 14/14 on Linux/Windows/macOS ×
  Python 3.11–3.13.

## 0.4.1 — built-in tracing: what competitors sell as a hosted service, ZYKO ships locally with zero dependencies

A strategic benchmark against LangChain (148,848★, sells observability as
LangSmith), CrewAI, AutoGen, LangGraph, LlamaIndex and PydanticAI (live GitHub
numbers, 2026-11-02, full report in `docs/STRATEGY.md`) identified
**observability** as the biggest remaining capability gap. ZYKO now traces
every routed call with OpenTelemetry-style spans — zero new required
dependencies, JSON lines you own on your disk, inspected by the same CLI.

### Added
- **`zyko.observability`** — new public package: `TraceSpan` (trace/parent
  ids, name, started_at, duration_ms, status `ok|error|cancelled`,
  attributes), `Tracer` (context-manager `span()` + manual
  `start_span`/`end_span` + one-shot `emit()`), `JsonlSink` (append-only,
  thread-safe, parent dirs, **bounded shift rotation**: live + `.1` + `.2`
  backups so a long-lived gateway can never fill the disk) and
  `InMemorySink`. Parent/child linking via `contextvars` — wrap any call in
  `zk.tracer.span("my-rag")` and the router span nests under it
  automatically, no propagation wiring.
- **Router spans** — `router.route` (ask/chat/structured/agents) carries
  `provider`, `cached`, `input_tokens`, `output_tokens`, `attempts[]`,
  `strategy`; `router.stream` closes even when the client disconnects
  (status `cancelled`). Failures set status `error` + the failure reason —
  routing behaviour is untouched.
- **`zyko traces`** — CLI over the trace log: time table, `--last N`,
  `--trace <id>` drill-down, `--file`, `--clear`, and `--json` that is
  always valid JSON (the `cost`/`cache` machine contract). Corrupt/torn
  lines are skipped, never fatal.
- **Settings**: `tracing.enabled` (default on) / `tracing.file` (default
  `<data dir>/traces.jsonl` via the new `paths.trace_log()`), with the
  `ZYKO_TRACING=0` environment override.
- **Never-breaks-requests guarantee**: sink I/O failures degrade to one log
  line; a disabled tracer keeps the identical API with no writes.

### Notes
- Zero new dependencies (stdlib `json`/`time`/`uuid`/`contextvars` only).
- 25 new tests (`tests/test_observability.py`) — **463 tests passing**.
- The full competitive benchmark and the 18–24-month roadmap now live in
  `docs/STRATEGY.md` (the file the README roadmap always referenced).

## 0.4.0 — structured output: the most-competitive feature LangChain/CrewAI/AutoGen had and ZYKO didn't

A capability review against LangChain (`with_structured_output`), CrewAI
(Pydantic task outputs), AutoGen (`response_format`) and LiteLLM
(`response_format` passthrough) found the single biggest remaining gap:
**schema-constrained answers**. ZYKO now returns *validated data or a typed
error* — never a raw string the caller must `json.loads` by hand — with a
repair loop that feeds validation problems back to the model. Zero new
required dependencies (the validator is pure Python); Pydantic is an
optional interop, not a requirement.

### Added
- **`zyko.structured`** — new public package:
  `validate_against_schema` (JSON-Schema subset validator: types, enum,
  const, numeric/string/array/object keywords, `allOf`/`anyOf`/`oneOf`,
  local `$ref`/`$defs` resolution with cycle guards — the part Pydantic
  schemas always need), `extract_json` (survives prose, markdown fences and
  `<think>` blocks), `json_schema_of` (dict or Pydantic v2/v1 model),
  `StructuredEngine` and `StructuredResult`.
- **`Zyko().structured(prompt, schema)`** (+ `astructured`,
  `structured_messages`, `astructured_messages`) — guided mode rides the
  prompt, validates, and on failure runs **one automatic repair round** that
  quotes the exact validation errors back to the model
  (`max_repairs` configurable, `0` disables). `native=True` sends OpenAI
  `response_format: {"type": "json_schema", …}` for vendors that support it
  and lets the router fall back for vendors that don't.
- **Typed failures** — `SchemaSpecError` for malformed schemas (caller bug,
  fail fast) vs `StructuredOutputError` carrying `errors` + `text` after the
  repair budget is exhausted. Both exported from the `zyko` root.
- **`ChatRequest.response_format`** — OpenAI passthrough on every
  OpenAI-compatible adapter (openai, groq, mistral, deepseek, openrouter,
  together, xai); **Google maps it** to `generationConfig.responseMimeType`
  (+ `responseSchema` for `json_schema`); providers without native support
  ignore it (documented). The gateway parses `response_format` from
  OpenAI-shaped bodies and 400s on non-object values.
- **Cache keys are schema-aware (basis v2)** — `response_format` is part of
  the cache key, so a cached free-text answer is never served for a
  structured call.
- **`zyko[structured]` extra** — optional Pydantic v2 support; also added to
  `dev` so CI exercises the interop path. The core stays httpx+PyYAML only.

### Fixed
- **Policy rewrites now carry `response_format`** — both the
  `max_tokens_per_request` cap and the PII-redaction rebuilds of
  `ChatRequest` preserve the field; before this release the field could not
  exist, and a naive addition would have been silently dropped at the policy
  layer (covered by dedicated regression tests).

63 new tests (`tests/test_structured.py`) — **438 tests passing**.

## 0.3.9 — response cache: the #1 capability ZYKO lacked vs LiteLLM/Portkey

A competitive-matrix review against LiteLLM and Portkey Gateway showed ZYKO
already matched their retry/backoff, failover, circuit breakers, budget and
PII governance — but shipped **no response cache**. This release adds a
policy-gated, exact-match TTL cache so identical requests inside the window
are answered from memory instead of billing the vendor again.

### Added
- **`zyko.cache.ResponseCache`** — thread-safe, bounded, exact-match cache:
  SHA-256 key over the canonical outbound payload (provider, model,
  messages, temperature, max_tokens, tools, tool_choice via
  `messages_to_openai`), TTL expiry on a monotonic clock (default 300 s),
  LRU eviction at `max_entries` (default 512), hit/miss/store/bypass/
  eviction/expiry statistics.
- **Policy section `cache:`** — `cache: {enabled: true, ttl_s: 300,
  max_entries: 512}` in any policy YAML builds the cache and hands it to the
  router through `PolicyEngine.cache`. No policy section → no cache → zero
  behaviour change for existing users. Unknown `cache.*` keys and malformed
  sections degrade to the same schema warnings as every other control.
- **Router integration** (`Router(cache=...)`, wired automatically by
  `Zyko()` and the CLI): lookup happens *after* the policy rewrite, so the
  key covers the exact outbound payload (redactions included); keys are
  per-candidate, so a cached `openai/*` answer is never served for a request
  that routed to `anthropic/*`. Cache hits produce a `cache-hit` attempt, a
  `"cached": true` receipt flag, **no vendor call, no budget charge, no
  health-tracker write**. Responses carrying `tool_calls` are never stored
  (agent replay hazard). Streaming bypasses the cache in v1.
- **Request-level overrides** — `metadata={"cache": "bypass"}` skips read
  and write for one call; `metadata={"cache": "refresh"}` skips the read but
  stores the fresh answer (revalidation).
- **CLI `zyko cache`** — inspect entries/TTL/hit-rate (`--json` always valid
  JSON, mirroring `zyko cost --json`) and `--clear`. Disabled state prints an
  actionable policy snippet.

### Fixed
- **Empty-cache truthiness trap** — an early draft kept `__len__` on
  `ResponseCache`, which made an *empty* cache falsy and silently disabled
  `if cache:` fast paths. Removed `__len__` in favour of an explicit
  `size()`; every router/policy call site now uses `is not None`.

### Tests & docs
- 20 new tests (`tests/test_cache.py`): key stability/sensitivity, TTL
  expiry, LRU eviction + touch protection, thread-safety smoke (8 threads),
  policy gating (missing section, typos, malformed section, invalid values),
  router hit/bypass/refresh/redaction-key/failover-shadowing/tool-call
  skip/stream-bypass, CLI disabled hint + JSON + clear.
- Docs: README (AR+EN), `docs/API.md` (policy section + CLI map), policy
  schema example `examples/policies/strict.yaml` untouched (cache is opt-in).
- Suite: **375 passed** (355 + 20) · `ruff check` clean · `ruff format --check` clean.

## 0.3.8 — provider ecosystem: +xAI (Grok) and +Together AI

Two new OpenAI-compatible vendors built on the same ~30-line subclass lever,
taking the registry from 8 to **10 registered providers** (plus the internal
demo mock). Every catalog fact below was taken from the vendor's official
documentation at the time of writing — slugs, context windows and list prices
— with `max_output` left at the `ModelInfo` default where a vendor publishes
no per-model cap.

### Added
- **`xai`** (`XAI_API_KEY`, `https://api.x.ai/v1`) — `grok-4.7` (500k ctx,
  $2/$6), `grok-4.3` (1M ctx, $1.25/$2.50), `grok-build-0.1` (256k ctx,
  $1/$2). Short-context list prices from docs.x.ai; long-context prompts
  bill higher and the YAML override is the knob for that.
- **`together`** (`TOGETHER_API_KEY`, `https://api.together.ai/v1`) —
  `moonshotai/Kimi-K3`, `zai-org/GLM-5.3`, `zai-org/GLM-5.3-Flash`,
  `deepseek-ai/DeepSeek-V4.1-Flash`, `openai/gpt-oss-120b`,
  `Qwen/Qwen3.5-9B` — slugs, contexts and prices from the
  docs.together.ai serverless table (function calling confirmed for all).

### Tests & docs
- 8 new tests (`tests/test_providers_new.py`): registry size, request shape
  against both base URLs with default-model resolution, catalog integrity
  (provider prefix / positive prices / tags / tool support / cost math),
  exact model-ID sets, key-env resolution for both vendors.
- Docs updated everywhere the vendor list appears: README (AR+EN),
  `docs/PROVIDERS.md` table, `docs/API.md` registry table, landing site.
- Suite: **355 passed** (347 + 8) · `ruff check` clean · `ruff format --check .`
  clean (98 files).
Version synced: version.py / pyproject.toml / CITATION.cff → 0.3.8.

## 0.3.7 — MCP: dead-server race now fails typed, on every OS

Caught by the macOS py3.11 CI leg after 0.3.6: `test_mcp_closed_stream_fails_pending_request`
failed with a raw `ConnectionResetError: Connection lost` from
`StreamWriter.drain()`. When an MCP server dies between the client's
`write()` and `drain()`, the drain-raises path wins the race against the
reader loop's EOF path on some platforms — leaking an untyped transport
error instead of the documented `MCPError`.

### Fixed
- **`MCPClient._request` / `_notify`**: a transport already closed by a dead
  server (`ConnectionResetError` / `BrokenPipeError` from `drain()`) now maps
  to the same typed `MCPError("mcp server 'X' closed the stream")` the reader
  loop produces on EOF — deterministic on Linux, macOS and Windows alike.
  The pending future is popped first, which also removes the
  "Future exception was never retrieved" warning this race used to emit.

### Result
Same suite, deterministic everywhere: **347 passed**, `ruff check` clean,
`ruff format --check .` clean (97 files).
Version synced: version.py / pyproject.toml / CITATION.cff → 0.3.7.

## 0.3.6 — ruff 0.17 format compliance (hygiene, zero behavior change)

Ruff 0.17 changed formatting behaviour (and now formats Python code blocks
inside Markdown). Running the current toolchain over the whole tree flagged
four files that CI's `src tests benchmarks` scope did not cover — fixed now,
so a future CI scope extension or ruff upgrade cannot break `lint`:

- `README.md`, `docs/API.md`, `docs/PROVIDERS.md` — Python code blocks
  normalized (trailing-comment alignment collapsed to two spaces, blank line
  after imports).
- `examples/04_agent_tools.py` — long f-string line split per line-length 100.

No source under `src/` or `tests/` was touched; the full suite passes
unchanged: **347 passed**, `ruff check` clean, `ruff format --check .` now
clean across the entire tree (97 files), CI 14/14 green.
Version synced: version.py / pyproject.toml / CITATION.cff → 0.3.6.

## 0.3.5 — deep developer documentation

Three new reference documents, every signature taken verbatim from the code:

- **`docs/API.md`** — the `Zyko` client, `Router` + receipt, all nine
  providers, `PolicyEngine`, gateway, MCP (server & client), agents,
  settings/paths, the exception tree, and the full CLI map.
- **`docs/ARCHITECTURE.md`** — mermaid diagrams of the request lifecycle,
  the verifiable-by-construction receipt, measured quality, per-call
  governance, platform portability, and extension points.
- **`docs/PROVIDERS.md`** — discovery, per-provider YAML, any
  OpenAI-compatible vendor, pricing feeding the router, resilience
  (retries / breaker / fallbacks), keyless workflows.

README now links all three from its Arabic and English sections.
Version synced: version.py / pyproject.toml / CITATION.cff → 0.3.5.

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
