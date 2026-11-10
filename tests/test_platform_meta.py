"""Platform meta-invariants: the detection and paths layer must keep
identifying the five advertised platforms and routing state safely."""

from __future__ import annotations

import sys
from pathlib import Path

from zyko.platform.detect import (
    OSKind,
    detect_os,
    is_android,
    is_mobile,
    is_termux,
    platform_info,
)
from zyko.platform.paths import cache_dir, config_dir, data_dir

EXPECTED_HOST_KINDS = {
    OSKind.LINUX,
    OSKind.MACOS,
    OSKind.WINDOWS,
    OSKind.TERMUX,
    OSKind.ANDROID,
}


def test_oskind_has_five_platforms_plus_unknown():
    members = {kind.name for kind in OSKind}
    assert members == {
        "ANDROID",
        "TERMUX",
        "LINUX",
        "MACOS",
        "WINDOWS",
        "UNKNOWN",
    }


def test_oskind_values_are_lowercase_strings():
    for kind in OSKind:
        assert kind.value == kind.value.lower()
        assert isinstance(kind.value, str)


def test_detect_os_identifies_the_current_host():
    assert detect_os() in EXPECTED_HOST_KINDS, "a supported host must never fall through to UNKNOWN"


def test_is_mobile_only_for_android_and_termux():
    assert is_mobile() == (detect_os() in (OSKind.ANDROID, OSKind.TERMUX))


def test_is_mobile_false_on_desktop_hosts():
    if sys.platform in ("win32", "darwin") or (
        sys.platform.startswith("linux")
        and not is_termux()
        and not hasattr(sys, "getandroidapilevel")
        and not Path("/system/build.prop").exists()
    ):
        assert is_mobile() is False


def test_termux_detected_via_sys_prefix(monkeypatch):
    monkeypatch.delenv("PREFIX", raising=False)
    monkeypatch.setattr(sys, "prefix", "/data/data/com.termux/files/usr", raising=False)
    assert is_termux() is True
    assert detect_os() is OSKind.TERMUX


def test_android_detected_via_api_level_marker(monkeypatch):
    monkeypatch.delenv("PREFIX", raising=False)
    monkeypatch.setattr(sys, "getandroidapilevel", 34, raising=False)
    assert is_android() is True
    assert detect_os() is OSKind.ANDROID
    assert is_mobile() is True


def test_android_matches_its_ground_truth():
    expected = (
        is_termux() or hasattr(sys, "getandroidapilevel") or Path("/system/build.prop").exists()
    )
    assert is_android() is expected


def test_platform_info_describe_includes_os_and_python():
    info = platform_info()
    text = info.describe()
    assert info.os.value in text
    assert "Python" in text
    assert info.machine in text


def test_platform_info_shape_is_stable():
    info = platform_info()
    assert isinstance(info.is_64bit, bool)
    assert info.python
    assert info.machine
    assert isinstance(info.termux, bool)
    assert info.android_api is None or isinstance(info.android_api, int)


def test_all_three_state_dirs_respect_env_overrides(tmp_path):
    assert config_dir() == tmp_path / "config"
    assert data_dir() == tmp_path / "data"
    assert cache_dir() == tmp_path / "cache"


def test_state_dirs_are_absolute_paths():
    for path in (config_dir(), data_dir(), cache_dir()):
        assert isinstance(path, Path)
        assert path.is_absolute()
