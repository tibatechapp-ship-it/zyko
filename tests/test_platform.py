"""Platform detection and per-OS paths."""

from __future__ import annotations

from zyko.platform import (
    OSKind,
    config_dir,
    data_dir,
    detect_os,
    is_android,
    is_mobile,
    is_termux,
    platform_info,
)


def test_host_os_is_recognised():
    # CI runs Linux/Windows/macOS; developers also run Termux and Android.
    # Every supported host must be identified as itself, never UNKNOWN.
    expected = {
        OSKind.LINUX,
        OSKind.MACOS,
        OSKind.WINDOWS,
        OSKind.TERMUX,
        OSKind.ANDROID,
    }
    assert detect_os() in expected


def test_termux_detection(monkeypatch):
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    assert is_termux() is True
    assert detect_os() is OSKind.TERMUX
    assert is_android() is True
    assert is_mobile() is True


def test_android_detection(monkeypatch, tmp_path):
    monkeypatch.delenv("PREFIX", raising=False)
    import sys

    orig = getattr(sys, "getandroidapilevel", None)
    monkeypatch.setattr(sys, "getandroidapilevel", 34, raising=False)
    assert is_android() is True
    if orig is None:
        monkeypatch.delattr(sys, "getandroidapilevel", raising=False)


def test_paths_respect_env_overrides(tmp_path):
    assert config_dir() == tmp_path / "config"
    assert data_dir() == tmp_path / "data"
    config_dir(create=True).mkdir(parents=True, exist_ok=True)
    assert config_dir().exists()


def test_platform_info_shape():
    info = platform_info()
    assert info.python
    assert info.machine
    assert isinstance(info.is_64bit, bool)
    assert info.describe()
