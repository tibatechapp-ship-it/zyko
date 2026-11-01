# ZYKO on Android & Termux

ZYKO is a **pure-Python** core (only `httpx` + `PyYAML`), so it runs on
Android in three tiers — pick the one that fits your use case:

| Tier | What you get | How |
|------|--------------|-----|
| 1. Termux CLI | Full ZYKO: router, policy, agents, gateway, MCP | `bash install-termux.sh` |
| 2. Termux + Ollama | Fully offline local models on-device | `pkg install ollama`, pull a small model |
| 3. Kivy app | Native touch UI on top of the same core | `android/kivy_app/main.py` |

## Tier 1 — Termux install (2 minutes)

Install **Termux** (F-Droid build recommended), then:

```bash
pkg install -y git
git clone https://github.com/tibatechapp-ship-it/zyko.git
cd zyko/android
bash install-termux.sh
```

Or directly:

```bash
pkg install -y python git
pip install git+https://github.com/tibatechapp-ship-it/zyko.git
zyko doctor
```

Nothing compiles — there is no Rust requirement, no C extensions, no build
tools needed. The optional Rust kernel is skipped automatically.

## Tier 2 — Offline models on the phone

```bash
# Install an Ollama build for Termux from your preferred community source, then:
ollama pull llama3.2:1b     # ~1.3 GB, runs on most modern phones
zyko ask "لخّص فكرة الذكاء الاصطناعي الوكيل في سطرين"
zyko route "test"            # planning shows ollama candidates with $0 cost
```

ZYKO's router treats local models as first-class candidates and as
privacy-preserving fallbacks (zero data leaves the device).

## Tier 3 — Widget shortcut (always-on gateway)

With the Termux:Widget app installed:

```bash
mkdir -p ~/.shortcut
cp termux-shortcut.sh ~/.shortcut/zyko-serve.sh
chmod +x ~/.shortcut/zyko-serve.sh
```

Tapping the widget starts `zyko serve` — an OpenAI-compatible endpoint at
`http://127.0.0.1:8787/v1` that other apps on the phone (or the network,
with `--host 0.0.0.0`) can call.

## Notes & limits

- Config lives in `~/.config/zyko/` (XDG convention inside Termux).
- Wake-lock: long agent runs are best started in a `termux-wake-lock` session.
- The Kivy UI is optional (`pip install "zyko[android]"` installs Kivy).
- Chaquopy/Buildozer packaging: include the `zyko` package in your build;
  the core imports cleanly under Python-for-Android (no ctypes/libc deps).
