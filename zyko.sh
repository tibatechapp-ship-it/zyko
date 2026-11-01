#!/usr/bin/env bash
# ZYKO zero-install runner — Linux / macOS / Termux.
#
# Usage:
#   ./zyko.sh --version
#   ./zyko.sh ask "hello" --demo
#
# Behaviour:
#   1. If `zyko` is already on PATH, just run it.
#   2. Otherwise create an isolated venv under ~/.zyko/venv, install ZYKO from
#      this directory (or from GitHub when run outside a clone) and exec zyko.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v zyko >/dev/null 2>&1; then
    exec zyko "$@"
fi

VENV="${ZYKO_VENV:-$HOME/.zyko/venv}"
if [ ! -x "$VENV/bin/zyko" ]; then
    echo "[zyko.sh] first run — creating an isolated environment at $VENV" >&2
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --upgrade pip -q
    if [ -f "$REPO_DIR/pyproject.toml" ]; then
        "$VENV/bin/pip" install -q "$REPO_DIR"
    else
        "$VENV/bin/pip" install -q "git+https://github.com/tibatechapp-ship-it/zyko.git"
    fi
    echo "[zyko.sh] done. Tip: 'pipx install $REPO_DIR' avoids this step next time." >&2
fi

exec "$VENV/bin/zyko" "$@"
