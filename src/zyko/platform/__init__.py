"""Platform detection and per-OS filesystem layout.

ZYKO is engineered to run unchanged on Linux, Windows, macOS, Android
(Chaquopy/Kivy builds of Python) and Termux. Everything that differs between
those environments — OS identification, config/cache/data directories — is
centralised here so the rest of the codebase never branches on the OS.
"""

from __future__ import annotations

from .detect import OSKind, PlatformInfo, detect_os, is_android, is_mobile, is_termux, platform_info
from .paths import (
    agents_dir,
    audit_log,
    budget_file,
    cache_dir,
    config_dir,
    config_file,
    data_dir,
    ledger_file,
    policies_dir,
    policies_search_dirs,
    sessions_db,
)

__all__ = [
    "OSKind",
    "PlatformInfo",
    "detect_os",
    "is_android",
    "is_mobile",
    "is_termux",
    "platform_info",
    "audit_log",
    "budget_file",
    "cache_dir",
    "agents_dir",
    "config_dir",
    "config_file",
    "data_dir",
    "ledger_file",
    "policies_dir",
    "policies_search_dirs",
    "sessions_db",
]
