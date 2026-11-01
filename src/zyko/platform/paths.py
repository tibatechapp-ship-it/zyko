"""Per-OS filesystem layout.

Every artifact ZYKO persists (config, policies, agents, ledger, budget state,
audit trail, sessions) resolves through this module:

+-----------+----------------------------------------------+
| OS        | Config / Policies                            |
+===========+==============================================+
| Linux     | ``$XDG_CONFIG_HOME/zyko`` or ``~/.config``   |
| Termux    | ``$XDG_CONFIG_HOME/zyko`` or ``~/.config``   |
| macOS     | ``~/Library/Application Support/zyko``       |
| Windows   | ``%APPDATA%\\zyko``                          |
+-----------+----------------------------------------------+

Data/cache follow the same conventions (XDG data/cache, ``%LOCALAPPDATA%``).
The ``ZYKO_CONFIG_DIR`` / ``ZYKO_DATA_DIR`` / ``ZYKO_CACHE_DIR`` environment
variables override everything, which keeps tests hermetic.
"""

from __future__ import annotations

import os
from pathlib import Path

from .detect import OSKind, detect_os


def _home() -> Path:
    return Path.home()


def config_dir(create: bool = False) -> Path:
    env = os.environ.get("ZYKO_CONFIG_DIR")
    if env:
        p = Path(env)
    else:
        kind = detect_os()
        if kind is OSKind.WINDOWS:
            base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
            p = Path(base) / "zyko"
        elif kind is OSKind.MACOS:
            p = _home() / "Library" / "Application Support" / "zyko"
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or str(_home() / ".config")
            p = Path(base) / "zyko"
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir(create: bool = False) -> Path:
    env = os.environ.get("ZYKO_DATA_DIR")
    if env:
        p = Path(env)
    else:
        kind = detect_os()
        if kind is OSKind.WINDOWS:
            base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
            p = Path(base) / "zyko" / "data"
        elif kind is OSKind.MACOS:
            p = _home() / "Library" / "Application Support" / "zyko" / "data"
        else:
            base = os.environ.get("XDG_DATA_HOME") or str(_home() / ".local" / "share")
            p = Path(base) / "zyko"
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir(create: bool = False) -> Path:
    env = os.environ.get("ZYKO_CACHE_DIR")
    if env:
        p = Path(env)
    else:
        kind = detect_os()
        if kind is OSKind.WINDOWS:
            base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
            p = Path(base) / "zyko" / "cache"
        elif kind is OSKind.MACOS:
            p = _home() / "Library" / "Caches" / "zyko"
        else:
            base = os.environ.get("XDG_CACHE_HOME") or str(_home() / ".cache")
            p = Path(base) / "zyko"
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def config_file() -> Path:
    return config_dir() / "config.yaml"


def policies_dir(create: bool = False) -> Path:
    p = config_dir(create=create) / "policies"
    if create:
        # create=True must guarantee the *returned* directory exists, not only
        # its parent — the previous behaviour left callers with a missing leaf.
        p.mkdir(parents=True, exist_ok=True)
    return p


def agents_dir(create: bool = False) -> Path:
    p = config_dir(create=create) / "agents"
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def policies_search_dirs() -> list[Path]:
    """Directories searched (in order) when resolving a policy/agent name."""
    dirs = [Path.cwd() / "policies", Path.cwd()]
    dirs.append(policies_dir())
    dirs.append(config_dir())
    dirs.append(Path.cwd() / "examples" / "policies")
    return dirs


def ledger_file() -> Path:
    return data_dir(create=True) / "quality_ledger.json"


def budget_file() -> Path:
    return data_dir(create=True) / "budget_state.json"


def sessions_db() -> Path:
    return data_dir(create=True) / "sessions.db"


def audit_log() -> Path:
    return data_dir(create=True) / "audit.jsonl"


def ensure_layout() -> dict[str, Path]:
    paths = {
        "config": config_dir(create=True),
        "data": data_dir(create=True),
        "cache": cache_dir(create=True),
    }
    # Give a friendly hint when running under Termux for the first time.
    # A Termux PREFIX is definitive on its own — do not gate on sys.platform,
    # so the marker logic is identical on every OS (and unit-testable).
    if "com.termux" in os.environ.get("PREFIX", ""):
        marker = data_dir() / ".termux-ok"
        if not marker.exists():
            try:
                marker.write_text("zyko initialised on Termux\n", encoding="utf-8")
            except OSError:
                pass
    return paths
