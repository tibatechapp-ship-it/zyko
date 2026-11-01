<!-- ZYKO pull-request checklist -->

## What

<!-- One paragraph: what does this PR change? -->

## Why

<!-- Link the issue (#123) or describe the motivation. -->

## How

<!-- Key design decisions, trade-offs, alternatives rejected. -->

## Platform impact

<!-- ZYKO ships to Linux, Windows, macOS, Android and Termux. -->

- [ ] Pure Python only (no new compiled/mandatory dependency — Termux-safe)
- [ ] No behaviour change for the keyless first-run (`--demo` / auto-fallback)

## Checklist

- [ ] `pytest -q` passes locally
- [ ] `ruff check src tests benchmarks` is clean
- [ ] Docs / README updated for user-facing changes
- [ ] New routing/policy behaviour is covered by tests
- [ ] No secrets or tokens committed
