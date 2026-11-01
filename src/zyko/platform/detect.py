"""OS identification for the five target platforms."""

from __future__ import annotations

import os
import platform as _pyplatform
import sys
from dataclasses import dataclass
from enum import Enum


class OSKind(str, Enum):
    ANDROID = "android"
    TERMUX = "termux"
    LINUX = "linux"
    MACOS = "macos"
    WINDOWS = "windows"
    UNKNOWN = "unknown"


def is_termux() -> bool:
    """True when running inside the Termux environment on Android."""
    prefix = os.environ.get("PREFIX", "")
    if "com.termux" in prefix:
        return True
    if "com.termux" in getattr(sys, "prefix", ""):
        return True
    return os.path.exists(os.path.join(prefix, "bin", "pkg")) and "com.termux" in prefix


def is_android() -> bool:
    """True when running Python on Android (Termux or an embedded build)."""
    if is_termux():
        return True
    # CPython on Android exposes sys.getandroidapilevel.
    if hasattr(sys, "getandroidapilevel"):
        return True
    return sys.platform.startswith("linux") and os.path.exists("/system/build.prop")


def detect_os() -> OSKind:
    if is_termux():
        return OSKind.TERMUX
    if is_android():
        return OSKind.ANDROID
    if sys.platform.startswith("win"):
        return OSKind.WINDOWS
    if sys.platform == "darwin":
        return OSKind.MACOS
    if sys.platform.startswith("linux"):
        return OSKind.LINUX
    return OSKind.UNKNOWN


def is_mobile() -> bool:
    return detect_os() in (OSKind.ANDROID, OSKind.TERMUX)


@dataclass(frozen=True)
class PlatformInfo:
    os: OSKind
    python: str
    machine: str
    is_64bit: bool
    termux: bool
    android_api: int | None

    def describe(self) -> str:
        api = f" (API {self.android_api})" if self.android_api is not None else ""
        bits = "64-bit" if self.is_64bit else "32-bit"
        return f"{self.os.value}{api} · Python {self.python} · {self.machine} · {bits}"


def platform_info() -> PlatformInfo:
    android_api: int | None = None
    try:
        android_api = int(sys.getandroidapilevel())  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError):
        android_api = None
    return PlatformInfo(
        os=detect_os(),
        python=_pyplatform.python_version(),
        machine=_pyplatform.machine() or "unknown",
        is_64bit=sys.maxsize > 2**32,
        termux=is_termux(),
        android_api=android_api,
    )
