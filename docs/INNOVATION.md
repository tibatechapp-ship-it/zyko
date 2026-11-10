# ZYKO Innovations — Defensive Publication

**Publication Date:** 2026-11-10
**License:** Apache 2.0
**Repository:** https://github.com/tibatechapp-ship-it/zyko

---

## Purpose

This document establishes **prior art** for the core architectural
innovations of ZYKO. By publishing these concepts with timestamped commits
under the Apache 2.0 license, we provide legal evidence of originality
that prevents third parties from later claiming patent rights over these
techniques.

Apache 2.0 grants patent rights to *contributors* (Section 3), but does
not prevent *third parties* from filing patents on published concepts.
This document closes that gap through defensive publication.

Every innovation listed below is pinned to:

- the exact introducing commit on `main` (verified via `git tag --contains`),
- the release that first shipped it,
- a minimal, verified CLI example.

The first commit in this repository is dated **2026-11-01** (`e5107c81`).

---

## 1. Offline Verifiable Routing Receipts (`zyko verify`)

**Introduced:** v0.8.0 — 2026-11-05 — commit
[`e6c736f`](https://github.com/tibatechapp-ship-it/zyko/commit/e6c736f3e1cdf34906a21b3092c84a2bd890a420)
**Code:** [`src/zyko/router/verify.py`](../src/zyko/router/verify.py)

### Description

Every routing decision emits a **receipt**: a JSON document carrying the
full candidate ranking, per-component scores (quality, cost, latency), the
published strategy weights, and a SHA-256 fingerprint. `zyko verify`
recomputes every total offline from the recorded components and exits
non-zero on any drift — a third party can recompute a historical routing
decision without network access and without trusting the issuer.

### Example

```bash
zyko ask "hello" --demo --receipt r.json && zyko verify r.json
```

### Novel Elements

1. Component-level recomputation, not whole-receipt hashing.
2. Ledger mode cross-checks each recorded quality score against a
   reproducible benchmark ledger — including an exact match on the
   ledger's `updated` stamp.
3. Typed failures with non-zero exit on drift, enabling CI integration.
4. The verifier caught a real bug in the router it was built to verify
   (`cost_score` could exceed 1.0 — observed 1.0441), proving the
   mechanism works against its own author.

---

## 2. Deterministic Arabic Python Transpiler (`daad`)

**Introduced:** v0.16.0 — 2026-11-09 — commit
[`9525a62`](https://github.com/tibatechapp-ship-it/zyko/commit/9525a627cebbabf6fdc5abbc692cda1e5f41bc58)
**Code:** the `zyko py` gateway in [`src/zyko/cli/`](../src/zyko/cli/) +
the standalone language repository
[`tibatechapp-ship-it/daad`](https://github.com/tibatechapp-ship-it/daad)

### Description

**Daad** (ضاد) is a byte-deterministic transpiler that converts an Arabic
Python dialect into standard CPython-parseable Python — its own lexer,
recursive-descent parser, and Python emitter, in pure stdlib with zero
dependencies. ZYKO integrates it through a **subprocess boundary**
(`zyko py`), never an internal import: same arguments, same exit codes,
same byte determinism. No programming language lives inside the AI
gateway.

### Example

```bash
zyko py hello.daad --run      # transpile, then execute
zyko py hello.daad --stdout   # print the generated Python
```

### Novel Elements

1. Arabic-Indic digit normalization (٠١٢٣٤٥٦٧٨٩ → 0-9) at the lexer level.
2. Byte-identical output across runs, verified by tests.
3. Subprocess isolation: the language and the platform evolve
   independently — neither can break the other's contract.

---

## 3. AST-Based Deterministic Taint Analysis (`zyko.reviewer.taint`)

**Introduced:** v0.15.0 — 2026-11-09 — commit
[`04039d3`](https://github.com/tibatechapp-ship-it/zyko/commit/04039d3db1048a200f7de304328a35a80ca6a068)
**Code:** [`src/zyko/reviewer/taint.py`](../src/zyko/reviewer/taint.py)
(rules R-SEC-109…119; samples: `samples/review/bad_security.py`)

### Description

A pure-stdlib dataflow analysis engine that tracks untrusted input —
`input()` / `sys.argv` and Flask/Django `request.*` data — through
assignments to a fixpoint, and fires **only on a confirmed source-to-sink
path** (e.g., a tainted value reaching `subprocess.*` or SQL
`execute()`). No shape guessing, no network, no model, no randomness.

### Example

```bash
zyko factory fix --path samples/review/bad_security.py
```

### Novel Elements

1. Pure AST fixpoint propagation — no regex, no pattern matching.
2. Two measured source families (interactive input + framework request
   data) with documented PoC limits.
3. Field-measured false-positive carve-outs ported verbatim from MIZAN
   (e.g., the `zipfile` exemption on `extractall`).
4. Every finding carries an explicit Arabic repair reason (`suggestion_ar`).

---

## 4. The Guardian: Pre-Mutation LLM Governance (`zyko.guardian`)

**Introduced:** v0.17.0 — 2026-11-10 — commit
[`5aef8a2`](https://github.com/tibatechapp-ship-it/zyko/commit/5aef8a2f94eccb7fd75e952b22ab2900ff3db732)
**Code:** [`src/zyko/guardian/`](../src/zyko/guardian/)

### Description

A standalone gate layer that intercepts every text proposal from any
model — cloud, local (Ollama), or mock — and runs it through a fixed
sequence of deterministic gates (PII → RTL → Structural) before a single
byte reaches disk. The LLM *proposes*, the Guardian *decides*, and the
decision is auditable.

### Example

```python
import asyncio
from zyko.guardian import DefaultGuardian

d = asyncio.run(DefaultGuardian().check("call +966501234567"))
d.verdict                     # "DENY" — PII refused; nothing was written
d.gate_results[0].gate_name   # "PIIGate"
d.fingerprint                 # sha256 over the proposal + every gate result
```

### Novel Elements

1. Gate ordering is fixed and part of the contract (PII → RTL →
   Structural).
2. All gates run to completion even after a failure — a full audit trail,
   not fail-fast.
3. An exception inside any gate degrades to `REVIEW` (human escalation),
   never a silent pass.
4. `Decision.fingerprint` is a SHA-256 over the proposal plus every gate
   result — recomputable by a third party.
5. Every reason is Arabic-first, not translated.

---

## 5. Time-Series Quality Baseline (`zyko.baseline`)

**Introduced:** v0.13.0 — 2026-11-09 — commit
[`5fec1ac`](https://github.com/tibatechapp-ship-it/zyko/commit/5fec1ac3771990c59e9414360134d0f2191870bd)
**Code:** [`src/zyko/baseline/`](../src/zyko/baseline/)

### Description

A **timestamp-free**, deterministic quality snapshot mechanism. Each
`update` writes exactly one JSON file (`.zyko/baseline.json`) recording
per-file scores and finding counts; every later `check` compares the
current state against it and reports — numerically — what regressed, what
improved, and what is new. The absence of timestamps is the innovation:
the monotonic `run_no` is the only clock, making baselines diffable and
mergeable across teams without clock skew.

### Example

```bash
zyko factory baseline update --src ./my-project
# ... edit code ...
zyko factory baseline check --src ./my-project
```

### Novel Elements

1. Zero clock/`datetime` calls — deterministic byte-for-byte.
2. Multi-set comparison of findings (the same finding twice is not two
   findings).
3. A corrupt baseline fails as a typed Arabic error, never a crash — and
   `update` over it self-heals by re-recording the actual disk state.
4. The HTML report mode is itself byte-deterministic.

---

## 6. Unified Factory Gates (`zyko.factory`)

**Introduced:** v0.14.0 — 2026-11-09 — commit
[`2b343da`](https://github.com/tibatechapp-ship-it/zyko/commit/2b343da40f1bfa168eba280533fcc1827e0ac735)
**Code:** [`src/zyko/factory/`](../src/zyko/factory/)

### Description

A single `zyko factory` command that delegates — literally, by calling
the same handlers — to every deterministic engine (fixer, pipeline,
workspace, baseline). `zyko factory gates` runs the four phase-acceptance
gates — 24 quantitative sub-gates over Arabic anchor projects — and signs
one verdict: «المصنع مقبول» only if every gate passes.

### Example

```bash
zyko factory gates
zyko factory baseline check --html r.html
```

### Novel Elements

1. Literal delegation — the factory path and the module path are the same
   code path, not a re-implementation.
2. Byte-determinism enforced by the test suite, not by convention.
3. HTML panels are Arabic-first RTL with zero JavaScript and zero
   external resources.
4. One signed verdict aggregates heterogeneous gates with different
   exit-code conventions.

---

## How to Cite

If you reference these innovations in academic work or patent filings,
cite [`CITATION.cff`](../CITATION.cff):

```text
tibatechapp-ship-it (2026). ZYKO: Deterministic Arabic Coding Engine
and AI Orchestration Platform. https://github.com/tibatechapp-ship-it/zyko
```

The date-stamped commit history is the authoritative record of priority.

## Contact

Security disclosures: [`SECURITY.md`](../SECURITY.md).
Contribution guidelines: [`CONTRIBUTING.md`](../CONTRIBUTING.md).
Licensing questions: [`LICENSE`](../LICENSE) (Apache 2.0).
