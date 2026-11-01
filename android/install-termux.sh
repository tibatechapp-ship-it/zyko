#!/data/data/com.termux/files/usr/bin/bash
# ZYKO — one-command install on Termux (Android).
# Usage:  bash install-termux.sh
set -euo pipefail

echo "[zyko] Termux installer"

# 1. Base packages (pure-Python stack — nothing to compile)
pkg update -y
pkg install -y python git

# 2. ZYKO from source (or: pip install git+https://github.com/tibatechapp-ship-it/zyko.git)
pip install --upgrade pip wheel
pip install .

# 3. Verify
zyko --version
zyko doctor || true

cat <<'TIP'

[zyko] installed. Next steps:
  zyko doctor                 # environment check
  zyko info                   # paths + providers

Optional — local models on your phone (no API keys, fully offline):
  # install Ollama for Termux from your preferred community build, then:
  ollama pull llama3.2:1b     # small model that runs on-device
  zyko ask "مرحبا"            # routed straight to your local model

Optional — always-on gateway:
  zyko serve --port 8787      # OpenAI-compatible endpoint on your phone

TIP
