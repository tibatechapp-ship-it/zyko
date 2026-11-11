"""اختبارات عقود الصلاحيات — أين، ماذا، وبكم، بلا استثناء وعدوي مُقيَّد."""

from __future__ import annotations

import json

import pytest

from zyko.sandbox.contracts import (
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_TIMEOUT_S,
    ENV_DENY_TOKENS,
    ENV_EXAMPLE_NAME,
    MAX_TIMEOUT_S,
    SENSITIVE_DIR_NAMES,
    PermissionContract,
    is_sensitive_dir,
    is_sensitive_file,
    sensitive_paths_in_roots,
)


# ---------------------------------------------------------------- الجذور
def test_for_roots_stores_absolute_paths(tmp_path):
    contract = PermissionContract.for_roots(tmp_path / "proj")
    assert contract.roots and str(tmp_path) in contract.roots[0]


def test_for_roots_empty_yields_no_roots():
    contract = PermissionContract.for_roots("", None, "  ")
    assert contract.roots == ()


def test_for_roots_caps_count(tmp_path):
    many = [str(tmp_path / f"d{i}") for i in range(20)]
    contract = PermissionContract.for_roots(*many)
    assert len(contract.roots) <= 8


def test_check_path_inside_root_passes(tmp_path):
    contract = PermissionContract.for_roots(tmp_path)
    target, reason = contract.check_path(tmp_path / "src" / "app.py")
    assert target is not None and reason is None
    assert target.name == "app.py"


def test_check_path_root_itself_passes(tmp_path):
    contract = PermissionContract.for_roots(tmp_path)
    target, reason = contract.check_path(str(tmp_path))
    assert target is not None and reason is None


def test_check_path_outside_root_rejected(tmp_path):
    contract = PermissionContract.for_roots(tmp_path)
    target, reason = contract.check_path(tmp_path.parent / "خارج.txt")
    assert target is None and reason and "خارج" in reason


def test_check_path_dotdot_folds_then_rejects(tmp_path):
    contract = PermissionContract.for_roots(tmp_path / "proj")
    sneaky = tmp_path / "proj" / ".." / ".." / "escape.txt"
    target, reason = contract.check_path(str(sneaky))
    assert target is None and reason


def test_check_path_symlink_escape_rejected(tmp_path):
    """رمز ارتباط داخل الجذر يشير للخارج — الحسم يكشف الهدف الحقيقي."""
    proj = tmp_path / "proj"
    proj.mkdir()
    outside = tmp_path / "خارج-الجذر.txt"
    outside.write_text("سر", encoding="utf-8")
    contract = PermissionContract.for_roots(proj)
    link = proj / "link.txt"
    link.symlink_to(outside)
    target, reason = contract.check_path(str(link))
    assert target is None and reason


def test_check_path_nul_rejected(tmp_path):
    contract = PermissionContract.for_roots(tmp_path)
    target, reason = contract.check_path("bad\x00path")
    assert target is None and reason and "NUL" in reason


def test_check_path_empty_rejected(tmp_path):
    contract = PermissionContract.for_roots(tmp_path)
    target, reason = contract.check_path("   ")
    assert target is None and reason


def test_check_path_none_rejected(tmp_path):
    contract = PermissionContract.for_roots(tmp_path)
    target, reason = contract.check_path(None)
    assert target is None and reason


def test_check_path_without_roots_rejected_everything():
    contract = PermissionContract.for_roots()
    target, reason = contract.check_path("/anything")
    assert target is None and reason and "بلا جذور" in reason


def test_check_path_multiple_roots_any_match_passes(tmp_path):
    a, b = tmp_path / "أ", tmp_path / "ب"
    contract = PermissionContract.for_roots(a, b)
    target, reason = contract.check_path(b / "file.py")
    assert target is not None and reason is None


# ---------------------------------------------------------------- الأوامر
def test_check_command_requires_flag():
    contract = PermissionContract.for_roots(".")
    argv, reason = contract.check_command(["python", "-m", "pytest"])
    assert argv is None and reason and "تشغيل الاختبارات" in reason


def test_check_command_whitelisted_passes():
    contract = PermissionContract.for_roots(".", allow_run_tests=True)
    argv, reason = contract.check_command(["python", "-m", "pytest", "-q"])
    assert argv == ("python", "-m", "pytest", "-q") and reason is None


def test_check_command_outside_whitelist_rejected():
    contract = PermissionContract.for_roots(".", allow_run_tests=True, allowed_commands=("pytest",))
    argv, reason = contract.check_command(["bash", "-c", "rm -rf /"])
    assert argv is None and reason and "القائمة البيضاء" in reason


def test_check_command_string_not_list_rejected():
    contract = PermissionContract.for_roots(".", allow_run_tests=True)
    argv, reason = contract.check_command("python -m pytest")
    assert argv is None and reason and "قائمة" in reason


def test_check_command_shell_metachar_rejected():
    contract = PermissionContract.for_roots(".", allow_run_tests=True)
    for sneaky in (
        ["python", "-c", "import os; os.system('evil')"],
        ["pytest", "-q", "a;b"],
        ["pytest", "a|b"],
        ["pytest", "a>b"],
        ["pytest", "`whoami`"],
        ["pytest", "$(id)"],
        ["pytest", "a\nb"],
        ["pytest", "a\\b"],
    ):
        argv, reason = contract.check_command(sneaky)
        assert argv is None and reason, f"تسرب: {sneaky}"


def test_check_command_empty_or_blank_rejected():
    contract = PermissionContract.for_roots(".", allow_run_tests=True)
    for sneaky in ([], [""], ["  "]):
        argv, reason = contract.check_command(sneaky)
        assert argv is None and reason


def test_check_command_nul_rejected():
    contract = PermissionContract.for_roots(".", allow_run_tests=True)
    argv, reason = contract.check_command(["python", "a\x00b"])
    assert argv is None and reason


# ---------------------------------------------------------------- السقوف
def test_negative_limits_clamped_to_zero():
    contract = PermissionContract.for_roots(
        ".", max_file_bytes=-5, timeout_s=-1.0, max_patch_ops=-3, max_output_chars=-2
    )
    assert contract.max_file_bytes == 0
    assert contract.timeout_s == 0.0
    assert contract.max_patch_ops == 0
    assert contract.max_output_chars == 0


def test_nonsense_limits_fall_back_to_defaults():
    contract = PermissionContract.for_roots(".", max_file_bytes="كثير", timeout_s="سريع")
    assert contract.max_file_bytes == DEFAULT_MAX_FILE_BYTES
    assert contract.timeout_s == DEFAULT_TIMEOUT_S


def test_timeout_capped_at_absolute_ceiling():
    contract = PermissionContract.for_roots(".", timeout_s=10_000.0)
    assert contract.timeout_s == MAX_TIMEOUT_S


def test_nan_and_inf_timeouts_fall_back():
    contract = PermissionContract.for_roots(".", timeout_s=float("nan"))
    assert contract.timeout_s == DEFAULT_TIMEOUT_S
    contract = PermissionContract.for_roots(".", timeout_s=float("inf"))
    assert contract.timeout_s == DEFAULT_TIMEOUT_S


def test_file_size_capped_at_absolute_ceiling():
    contract = PermissionContract.for_roots(".", max_file_bytes=10**12)
    assert contract.max_file_bytes <= 8 * 1024 * 1024


# ---------------------------------------------------------------- البيئة
def test_sanitized_env_strips_secrets(monkeypatch):
    monkeypatch.setenv("ZYKO_API_KEY", "sk-secret-value")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_leaked")
    monkeypatch.setenv("DB_PASSWORD", "hunter2")
    monkeypatch.setenv("SESSION_COOKIE", "abc")
    monkeypatch.setenv("MY_SECRET_TOKEN", "zzz")
    contract = PermissionContract.for_roots(".")
    env = contract.sanitized_env()
    for name in ("ZYKO_API_KEY", "GITHUB_TOKEN", "DB_PASSWORD", "SESSION_COOKIE", "MY_SECRET_TOKEN"):
        assert name not in env
    joined = json.dumps(env)
    for secret in ("sk-secret-value", "ghp_leaked", "hunter2", "abc", "zzz"):
        assert secret not in joined


def test_sanitized_env_keeps_essentials(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", "/home/z")
    contract = PermissionContract.for_roots(".")
    env = contract.sanitized_env()
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["HOME"] == "/home/z"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_sanitize_env_false_passes_through(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    raw = PermissionContract(roots=(".",), sanitize_env=False)
    assert raw.sanitized_env().get("GITHUB_TOKEN") == "ghp_x"


def test_denied_env_tokens_cover_common_secrets():
    for token in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH"):
        assert token in ENV_DENY_TOKENS


def test_is_secret_name_matches_case_insensitive():
    assert PermissionContract._is_secret_name("openai_api_key")
    assert PermissionContract._is_secret_name("ANTHROPIC_AUTH_TOKEN")
    assert not PermissionContract._is_secret_name("PATH")
    assert not PermissionContract._is_secret_name("PYTHONPATH")


# ---------------------------------------------------------------- التوثيق
def test_to_dict_deterministic_and_sorted(tmp_path):
    a = PermissionContract.for_roots(tmp_path, allow_patch=True)
    b = PermissionContract.for_roots(tmp_path, allow_patch=True)
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(b.to_dict(), sort_keys=True)
    keys = list(json.loads(json.dumps(a.to_dict()), object_pairs_hook=list))
    assert keys == sorted(keys, key=lambda kv: kv[0])


def test_contract_is_frozen(tmp_path):
    contract = PermissionContract.for_roots(tmp_path)
    with pytest.raises(Exception):
        contract.allow_patch = True  # type: ignore[misc]


def test_allowed_commands_deduped_and_stripped():
    contract = PermissionContract.for_roots(".", allowed_commands=("pytest", " pytest ", "pytest", ""))
    assert contract.allowed_commands == ("pytest",)


# ------------------------------------------------- حرس الاعتماد الحساس
# المستعار من nexus-core: حصر الجذر لا يكفي لأن ``.env`` في الجذر
# مخزن أسرار لا ملف مشروع — والقراءة الحساسة تُرفض حتى داخل الجذور.
def test_is_sensitive_file_catches_named_stores(tmp_path):
    for name in (
        ".env", ".env.bak", ".env.staging", ".env.local",
        "id_rsa", "id_ed25519", "credentials.json",
        "secrets.yaml", ".netrc", ".pgpass", ".git-credentials",
        "server.pem", "privkey.key", "bundle.p12",
    ):
        assert is_sensitive_file(tmp_path / name), name


def test_is_sensitive_file_allows_example_and_code(tmp_path):
    assert not is_sensitive_file(tmp_path / ENV_EXAMPLE_NAME)  # وثيقة أسماء لا قيم
    assert not is_sensitive_file(tmp_path / "app.py")
    assert not is_sensitive_file(tmp_path / "keyring.py")  # اللاحقة داخل الاسم لا تُحسب


def test_is_sensitive_dir_names_store_directories():
    assert is_sensitive_dir("/home/u/.ssh")
    assert is_sensitive_dir("/home/u/.aws")
    assert not is_sensitive_dir("/home/u/src")


def test_check_read_path_denies_secret_inside_root(tmp_path):
    secret = tmp_path / ".env"
    secret.write_text("TOKEN=x", encoding="utf-8")
    contract = PermissionContract.for_roots(tmp_path)
    target, reason = contract.check_read_path(secret)
    assert target is None
    assert "حساس" in (reason or "") and ".env" in (reason or "")


def test_check_read_path_allows_regular_file_inside_root(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("x = 1", encoding="utf-8")
    target, reason = PermissionContract.for_roots(tmp_path).check_read_path(f)
    assert target == f.resolve() and reason is None


def test_check_read_path_still_enforces_roots(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "app.py"
    outside.write_text("x = 1", encoding="utf-8")
    contract = PermissionContract.for_roots(tmp_path)
    target, reason = contract.check_read_path(outside)
    assert target is None and "خارج" in (reason or "")


def test_sensitive_paths_in_roots_finds_files_and_dirs_sorted(tmp_path):
    (tmp_path / ".env").write_text("X=1", encoding="utf-8")
    (tmp_path / ".ssh").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x=1", encoding="utf-8")
    found = sensitive_paths_in_roots((str(tmp_path),))
    assert str((tmp_path / ".env").resolve()) in found
    assert str((tmp_path / ".ssh").resolve()) in found
    assert found == tuple(sorted(found))  # حتمي بالترتيب


def test_sensitive_paths_in_roots_empty_for_clean_tree(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x=1", encoding="utf-8")
    (tmp_path / ".env.example").write_text("X=", encoding="utf-8")  # الاستثناء موثق
    assert sensitive_paths_in_roots((str(tmp_path),)) == ()


def test_sensitive_paths_in_roots_skips_missing_root(tmp_path):
    assert sensitive_paths_in_roots((str(tmp_path / "not-there"),)) == ()
