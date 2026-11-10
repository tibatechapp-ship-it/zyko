# ZYKO Innovations — Defensive Publication

**Date of Publication:** 2026-11-10
**License:** Apache 2.0

This document establishes prior art for the core architectural innovations of ZYKO. By date-stamping these commits and publishing them under the Apache 2.0 license, we provide legal evidence of originality. This prevents third parties from patenting these concepts and claiming them as their own.

Every entry below is pinned to the exact introducing commit (verified via
`git tag --contains`) and to the release that first shipped it. The first
commit in this repository is dated **2026-11-01** (`e5107c81`).

---

## 1. Offline Verifiable Routing Receipts (`zyko verify`)
*   **First Introduced:** v0.8.0 (November 2026)
*   **Commit:** [`e6c736f`](https://github.com/tibatechapp-ship-it/zyko/commit/e6c736f3e1cdf34906a21b3092c84a2bd890a420) — 2026-11-05
*   **Code:** `src/zyko/router/verify.py`
*   **Description:** A deterministic mechanism to recompute AI routing decisions (quality, cost, latency scores) entirely offline using SHA256 integrity checks. It guarantees that an LLM's routing path cannot be tampered with post-generation.
*   **Example:** `zyko ask "hello" --demo --receipt r.json && zyko verify r.json`

## 2. Deterministic Arabic Python Transpiler (`daad`)
*   **First Introduced:** v0.16.0 (November 2026) — standalone language repository [`tibatechapp-ship-it/daad`](https://github.com/tibatechapp-ship-it/daad), integrated in ZYKO through the `zyko py` gateway
*   **Commit:** [`9525a62`](https://github.com/tibatechapp-ship-it/zyko/commit/9525a627cebbabf6fdc5abbc692cda1e5f41bc58) — 2026-11-09
*   **Code:** `src/zyko/cli/` (`zyko py` subprocess gateway) + the `daad` repository (recursive-descent parser, 28 Arabic keywords, deterministic Python emission, zero dependencies)
*   **Description:** A zero-dependency, byte-for-byte deterministic transpiler that converts an Arabic Python dialect (Daad) into standard Python. ZYKO's golden rule — *no programming language inside the AI gateway* — is preserved: `zyko py` delegates to the daad transpiler as a separate process (no internal import, same arguments, same exit codes, same byte determinism).
*   **Example:** `zyko py hello.daad --run`

## 3. AST-Based Deterministic Taint Analysis (`zyko.reviewer.taint`)
*   **First Introduced:** v0.15.0 (November 2026)
*   **Commit:** [`04039d3`](https://github.com/tibatechapp-ship-it/zyko/commit/04039d3db1048a200f7de304328a35a80ca6a068) — 2026-11-09
*   **Code:** `src/zyko/reviewer/taint.py` (rules R-SEC-109…R-SEC-119; samples: `samples/review/bad_security.py`)
*   **Description:** A pure-stdlib dataflow analysis engine that tracks untrusted input (`input()`, `sys.argv`, Flask/Django `request.*` data) through assignments to a fixpoint and fires only on a confirmed source-to-sink path (e.g., tainted value → `subprocess.*` or SQL `execute()`). No shape guessing, no network, no model, no randomness — deterministic by construction, with field-measured false-positive carve-outs.
*   **Example:** `zyko factory fix --path samples/review/bad_security.py`

## 4. The Guardian: Pre-Mutation LLM Governance (`zyko.guardian`)
*   **First Introduced:** v0.17.0 (November 2026)
*   **Commit:** [`5aef8a2`](https://github.com/tibatechapp-ship-it/zyko/commit/5aef8a2f94eccb7fd75e952b22ab2900ff3db732) — 2026-11-10
*   **Code:** `src/zyko/guardian/`
*   **Description:** A standalone, structurally independent gate layer that returns a typed `ALLOW / DENY / REVIEW` decision on any model proposal — cloud, local (Ollama), or mock — reusing ZYKO's deterministic Arabic tools (`zyko.tools.pii_ar`, `zyko.tools.rtl`) and stamping every decision with a sha256 fingerprint and an Arabic reason. It implements the "propose, then verify" paradigm: no proposed text reaches disk before passing the security gates, eliminating prompt-injection write paths.
*   **Example:** `zyko ai run --brain ollama --model «model» --goal "…"`

## 5. Time-Series Quality Baseline (`zyko.baseline`)
*   **First Introduced:** v0.13.0 (November 2026)
*   **Commit:** [`5fec1ac`](https://github.com/tibatechapp-ship-it/zyko/commit/5fec1ac3771990c59e9414360134d0f2191870bd) — 2026-11-09
*   **Code:** `src/zyko/baseline/`
*   **Description:** A timestamp-free (zero clock/`datetime` calls), deterministic JSON snapshot mechanism that compares code-quality regressions or improvements over time without relying on a server or a database.
*   **Example:** `zyko factory baseline check`

## 6. Unified Factory Gates (`zyko.factory`)
*   **First Introduced:** v0.14.0 (November 2026)
*   **Commit:** [`2b343da`](https://github.com/tibatechapp-ship-it/zyko/commit/2b343da40f1bfa168eba280533fcc1827e0ac735) — 2026-11-09
*   **Code:** `src/zyko/factory/`
*   **Description:** A single CLI aggregating the four phase-acceptance gates (fixer, pipeline, workspace, baseline) into 24 quantitative sub-gates over Arabic fixtures, with byte-deterministic, JavaScript-free HTML report panels (byte-equality-tested) for CI/CD auditing.
*   **Example:** `zyko factory gates`
