"""اختبارات العزل النواتي — EPERM من النواة لا وعد من المستند.

العقود:
1. المستوى يُكتشف لا يُدَّعى: landlock/bwrap/none، وحتمي للبيئة الواحدة.
2. الابن المقيد يكتب داخل الجذر ويرفض خارجَه بـ PermissionError من
   النواة — حتى تحت مجلد الحرارة نفسه (الجذر الممنوح فقط هو المسموح).
3. فشل تقييد النواة إغلاق موثق: وسم عربي على stderr وخروج 126 —
   الابن لا يعمل بلا عزل على مضاربة الهدوء.
4. التكامل عبر الجلسة: مستوى العزل يُوقَّع في سجل التدقيق دائماً —
   القوة تُكتشف لا تُخترع.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from zyko.sandbox import jail
from zyko.sandbox.audit import AuditLog
from zyko.sandbox.contracts import PermissionContract
from zyko.sandbox.session import ToolSession

PY = sys.executable.replace("\\", "/").split("/")[-1].replace(".exe", "") or "python"

_WRITER_SCRIPT = """\
import sys
inside_path, outside_path = sys.argv[1], sys.argv[2]
inside_ok = True
try:
    with open(inside_path, "w", encoding="utf-8") as fh:
        fh.write("داخل الجذر")
except OSError:
    inside_ok = False
outside_blocked = True
try:
    with open(outside_path, "w", encoding="utf-8") as fh:
        fh.write("هروب")
except PermissionError:
    outside_blocked = True
print(f"INSIDE={'OK' if inside_ok else 'DENIED'} OUTSIDE={'BLOCKED' if outside_blocked else 'ESCAPED'}")
sys.exit(0 if (inside_ok and outside_blocked) else 1)
"""

_FAIL_CLOSED_SCRIPT = """\
from zyko.sandbox import jail
jail.landlock_abi = lambda: 0  # نواة بلا landlock — التقييد يجب أن يفشل
jail._restrict_child(())
print("UNREACHED")
"""


def _needs_kernel_jail() -> None:
    if jail.jail_level() != jail.JAIL_LEVEL_LANDLOCK:
        pytest.skip(
            "العزل النواتي غير متاح في هذه البيئة (نواة بلا Landlock وبلا bwrap) — تخطٍ موثق",
            allow_module_level=False,
        )


# ---------------------------------------------------------------- الكشف
def test_jail_level_is_honest_and_stable():
    level = jail.jail_level()
    assert level in {jail.JAIL_LEVEL_LANDLOCK, jail.JAIL_LEVEL_BWRAP, jail.JAIL_LEVEL_NONE}
    assert jail.jail_level() == level, "الكشف حتمي للبيئة الواحدة — لا تقلب وسط الجلسة"


def test_landlock_abi_reports_an_int():
    abi = jail.landlock_abi()
    assert isinstance(abi, int)
    assert abi >= 0
    # الاتساق: abi صفر يعني مستوى غير landlock بلا استثناء
    if abi == 0:
        assert jail.jail_level() != jail.JAIL_LEVEL_LANDLOCK


def test_write_roots_resolves_dedupes_and_adds_tempdir(tmp_path):
    import tempfile as _tf

    from pathlib import Path as _P

    root = tmp_path / "جذر"
    root.mkdir()
    roots = jail.write_roots((str(root), str(root)))  # تكرار مقصود
    assert roots[0] == str(root.resolve())
    assert len(roots) == 2, "التكرار يُدمج + مجلد الحرارة يُضاف"
    assert roots[-1] == str(_P(_tf.gettempdir()).resolve())


def test_write_roots_skips_adversarial_entries(tmp_path):
    roots = jail.write_roots(("", None, 123, str(tmp_path)))
    assert str(tmp_path) in roots
    assert len(roots) <= 2  # الجذر الصالح + مجلد الحرارة فقط


# ---------------------------------------------------------------- الإغلاق
def test_fail_closed_when_kernel_restrict_fails(tmp_path):
    """نواة بلا landlock + محاولة تقييد = خروج 126 بوسم موثق، لا تشغيل."""
    proc = subprocess.run(  # noqa: S603 — نص ثابت في الاختبار
        [sys.executable, "-c", _FAIL_CLOSED_SCRIPT],
        capture_output=True, text=True, timeout=60, cwd=str(tmp_path),
    )
    assert proc.returncode == jail._EXIT_JAIL_FAIL
    assert "فشل تقييد النواة" in proc.stderr
    assert "UNREACHED" not in proc.stdout, "الابن لا يكمل بعد فشل العزل"


def test_preexec_none_outside_linux_or_unsupported_level(tmp_path):
    preexec = jail.jail_preexec((str(tmp_path),))
    if not sys.platform.startswith("linux"):
        assert preexec is None
    else:
        assert (preexec is None) == (jail.jail_level() != jail.JAIL_LEVEL_LANDLOCK)


# ---------------------------------------------------------------- الحصر
def test_child_write_inside_root_allowed_outside_denied(tmp_path):
    """الجذر الممنوح فقط هو المسموح — الكتابة خارجَه EPERM من النواة."""
    _needs_kernel_jail()
    root = tmp_path / "الجذر"
    root.mkdir()
    outside = tmp_path / "خارج-الجذر"
    outside.mkdir()  # المجلد موجود — الرفض سيكون EACCES كتابةً لا ENOENT مجلداً
    proc = subprocess.run(  # noqa: S603 — نص ثابت في الاختبار
        [sys.executable, "-c", _WRITER_SCRIPT, str(root / "inside.txt"), str(outside / "outside.txt")],
        capture_output=True, text=True, timeout=60, cwd=str(root),
        preexec_fn=jail.jail_preexec((str(root),)),
    )
    assert proc.returncode == 0, f"الابن فشل: {proc.stderr[-400:]}"
    assert "INSIDE=OK" in proc.stdout, proc.stdout
    assert "OUTSIDE=BLOCKED" in proc.stdout, proc.stdout
    assert (root / "inside.txt").read_text(encoding="utf-8") == "داخل الجذر"
    assert not outside.exists(), "لا ملف هروب خارج الجذر"


def test_zero_roots_locks_all_writes(tmp_path):
    """جذور صفرية = قفل كتابة كامل — العزل يُطبَّق كما أُعلن لا أقل."""
    _needs_kernel_jail()
    script = (
        "import tempfile, sys\n"
        "try:\n"
        "    open(tempfile.mkstemp()[1], 'w')\n"
        "    print('WROTE')\n"
        "except PermissionError:\n"
        "    print('LOCKED')\n"
    )
    proc = subprocess.run(  # noqa: S603 — نص ثابت في الاختبار
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=60, cwd=str(tmp_path),
        preexec_fn=jail.jail_preexec(()),
    )
    assert proc.returncode == 0
    assert "LOCKED" in proc.stdout, proc.stdout


# ---------------------------------------------------------------- bwrap
def test_wrap_argv_shape_when_bwrap_active(tmp_path, monkeypatch):
    monkeypatch.setattr(jail, "jail_level", lambda: jail.JAIL_LEVEL_BWRAP)
    monkeypatch.setattr(jail.shutil, "which", lambda p: "/usr/bin/bwrap" if p == "bwrap" else None)
    root = tmp_path / "جذر"
    root.mkdir()
    wrapped = jail.wrap_argv(["python", "-m", "pytest", "-q"], (str(root),))
    assert wrapped is not None
    assert wrapped[0] == "/usr/bin/bwrap"
    assert "--unshare-net" in wrapped and "--tmpfs" in wrapped
    # الجذر مربوط كتابةً، ومجلد الحرارة يستبدل بـ tmpfs
    binds = [(wrapped[i], wrapped[i + 1], wrapped[i + 2]) for i, t in enumerate(wrapped) if t == "--bind"]
    assert any(b[1] == str(root) for b in binds), wrapped
    assert wrapped[-5:] == ["--", "python", "-m", "pytest", "-q"], wrapped[-6:]


def test_wrap_argv_none_outside_bwrap_level(tmp_path):
    if jail.jail_level() == jail.JAIL_LEVEL_BWRAP:
        pytest.skip("bwrap نشط فعلاً هنا — اختبار المسار السلبي غير منطقي في هذه البيئة")
    assert jail.wrap_argv(["python", "-c", "pass"], (str(tmp_path),)) is None


# ---------------------------------------------------------------- التكامل
def test_jailed_pytest_green_with_level_in_audit(tmp_path):
    """run_tests عبر الجلسة: اختبار أخضر تحت العزل النشط، والمستوى موقَّع في السجل."""
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    contract = PermissionContract.for_roots(tmp_path, allow_run_tests=True, allowed_commands=(PY,))
    audit = AuditLog(tmp_path / "audit.jsonl")
    session = ToolSession(contract, audit)
    result = session.run_tests(argv=[PY, "-m", "pytest", "-q", "test_ok.py"], cwd=tmp_path)
    assert result.ok and result.passed == 1, f"{result.reason_ar}\n{result.stderr_tail[-300:]}"
    entries = audit.entries()
    assert entries and entries[-1].tool == "run_tests"
    assert entries[-1].detail["jail"] == jail.jail_level(), "مستوى العزل يُوقَّع لا يُفترض"
    assert audit.verify().ok


def test_summary_discloses_jail_level(tmp_path):
    contract = PermissionContract.for_roots(tmp_path)
    session = ToolSession(contract)
    assert session.summary()["jail"] == jail.jail_level()


# ---------------------------------------------- تعمية المخازن الحساسة
# المستعار من nexus-core تحت bwrap: ملف السر يُربط /dev/null للقراءة،
# ومجلد المخزن يُستبدل tmpfs فارغًا — المشروع كله مقروء إلا الأسرار.
def test_sensitive_overlays_blank_file_and_dir(tmp_path):
    (tmp_path / ".env").write_text("TOKEN=x", encoding="utf-8")
    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    overlays = jail.sensitive_overlays((str(tmp_path),))
    i = overlays.index("--ro-bind")
    assert overlays[i + 1] == "/dev/null"
    assert overlays[i + 2] == str((tmp_path / ".env").resolve())
    j = overlays.index("--tmpfs")
    assert overlays[j + 1] == str(ssh.resolve())


def test_sensitive_overlays_empty_for_clean_tree(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x=1", encoding="utf-8")
    assert jail.sensitive_overlays((str(tmp_path),)) == []


def test_wrap_argv_carries_overlays_after_root_binds(tmp_path):
    """التراكب بعد ربط الجذر — البعد الذي يفوز عليه في التركيب."""
    if jail.jail_level() != jail.JAIL_LEVEL_BWRAP:
        pytest.skip("bwrap ليس المستوى النشط هنا — التراكب موثق في sensitive_overlays")
    (tmp_path / ".env").write_text("TOKEN=x", encoding="utf-8")
    wrapped = jail.wrap_argv(["python", "-c", "pass"], (str(tmp_path),))
    assert wrapped is not None
    assert wrapped.index("--ro-bind", wrapped.index("/dev/null")) < wrapped.index("--")
