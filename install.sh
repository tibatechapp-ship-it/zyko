#!/usr/bin/env bash
# ZYKO installer — Linux / macOS / Termux.
#
#   ./install.sh              # install into an isolated venv (~/.zyko/venv)
#   ./install.sh --dev        # + test/lint tooling (pytest, ruff)
#   ./install.sh --system     # pip install --user (no venv)
#
# Every path is pure Python: nothing compiles, on any platform.
set -euo pipefail

cd "$(dirname "$0")"

MODE="venv"
for arg in "$@"; do
    case "$arg" in
        --dev) DEV=1 ;;
        --system) MODE="system" ;;
        *) echo "usage: ./install.sh [--dev] [--system]" >&2; exit 2 ;;
    esac
done
DEV="${DEV:-0}"

if ! command -v python3 >/dev/null 2>&1; then
    echo "error: python3 is required (3.11+). On Termux: pkg install python" >&2
    exit 1
fi

PYTHON_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
MINOR="$(python3 -c 'import sys; print(sys.version_info[1])')"
if [ "$(python3 -c 'import sys; print(sys.version_info[0])')" != "3" ] || [ "$MINOR" -lt 11 ]; then
    echo "error: Python 3.11+ required, found $PYTHON_VERSION" >&2
    exit 1
fi

if [ "$MODE" = "system" ]; then
    echo "==> Installing ZYKO $PYTHON_VERSION (user site)"
    python3 -m pip install --user .
else
    VENV="${ZYKO_VENV:-$HOME/.zyko/venv}"
    echo "==> Creating isolated environment at $VENV"
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --upgrade pip -q
    if [ "$DEV" = "1" ]; then
        "$VENV/bin/pip" install -q -e ".[dev]"
    else
        "$VENV/bin/pip" install -q .
    fi
    BIN="$VENV/bin"
fi

echo ""
echo "==> ZYKO installed."
if [ -n "${BIN:-}" ]; then
    echo "    Run it with:            $BIN/zyko --version"
    echo "    Or add it to PATH:      export PATH=\"$BIN:\$PATH\""
else
    echo "    Run it with:            zyko --version"
fi
echo "    First try, keyless:     zyko ask \"hello\" --demo"
echo "    Verify your machine:    zyko doctor"
