"""Tests for ``zyko py`` — the daad gateway (المرحلة 3).

ضاد لغة مستقلة (tibatechapp-ship-it/daad): البوابة تستدعيها بعملية
منفصلة ولا تستوردها أبدًا. الاختبارات تُتخطى تلقائيًا إذا لم تكن ضاد
مثبتة في البيئة (CI يعمل بلا ضاد ويبقى أخضر).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from zyko.cli import main

DAAD_INSTALL_HINT = "pip install git+https://github.com/tibatechapp-ship-it/daad.git"

HELLO_DAAD = 'اطبع("مرحبا من ضاد")\n'


def _daad_available() -> bool:
    try:
        return (
            subprocess.run(  # nosec B607
                [sys.executable, "-m", "daad", "version"], capture_output=True
            ).returncode
            == 0
        )
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _daad_available(), reason="daad not installed")


@pytest.fixture()
def hello_file(tmp_path):
    f = tmp_path / "hello.daad"
    f.write_text(HELLO_DAAD, encoding="utf-8")
    return f


def test_py_transpile_writes_file_next_to_source(hello_file, capsys):
    rc = main(["py", str(hello_file)])
    assert rc == 0
    out_file = hello_file.with_suffix(".py")
    assert out_file.exists()
    generated = out_file.read_text(encoding="utf-8")
    # الضاد تصدر الاسم العربي مع prelude يربطه ببايثون — حتمي دائمًا
    assert 'اطبع("مرحبا من ضاد")' in generated
    assert "اطبع = print" in generated
    assert "تم توليده بواسطة daad" in generated


def test_py_transpile_is_byte_deterministic(hello_file):
    a = hello_file.with_suffix(".py")
    assert main(["py", str(hello_file)]) == 0
    first = a.read_bytes()
    a.unlink()
    assert main(["py", str(hello_file)]) == 0
    assert a.read_bytes() == first


def test_py_stdout_prints_python_without_writing(hello_file, tmp_path, capfd):
    rc = main(["py", str(hello_file), "--stdout"])
    assert rc == 0
    captured = capfd.readouterr().out
    assert 'اطبع("مرحبا من ضاد")' in captured
    assert "اطبع = print" in captured
    assert not (tmp_path / "hello.py").exists()


def test_py_stdout_deterministic(hello_file, capfd):
    main(["py", str(hello_file), "--stdout"])
    first = capfd.readouterr().out
    main(["py", str(hello_file), "--stdout"])
    assert capfd.readouterr().out == first


def test_py_run_executes(hello_file, capfd):
    rc = main(["py", str(hello_file), "--run"])
    assert rc == 0
    # البرنامج يعمل في عملية ضاد منفصلة — الخرج يلتقط على مستوى الواصفات
    assert "مرحبا من ضاد" in capfd.readouterr().out


def test_py_check_valid_file(hello_file, capfd):
    rc = main(["py", str(hello_file), "--check"])
    assert rc == 0
    assert "صالح" in capfd.readouterr().out


def test_py_check_rejects_broken_file(tmp_path, capsys):
    bad = tmp_path / "bad.daad"
    bad.write_text('دالة مرحة(\n    اطبع("ناقص"\n', encoding="utf-8")
    rc = main(["py", str(bad), "--check"])
    assert rc == 1


def test_py_out_writes_custom_path(hello_file, tmp_path, capsys):
    target = tmp_path / "nested" / "hello.py"
    target.parent.mkdir()
    rc = main(["py", str(hello_file), "--out", str(target)])
    assert rc == 0
    assert target.exists()
    generated = target.read_text(encoding="utf-8")
    assert 'اطبع("مرحبا من ضاد")' in generated
    assert "اطبع = print" in generated
    # الافتراضي لم يُكتب — المسار المخصص فقط
    assert not hello_file.with_suffix(".py").exists()


def test_py_missing_file_exits_1(tmp_path, capsys):
    rc = main(["py", str(tmp_path / "غير_موجود.daad")])
    assert rc == 1
    assert "غير موجود" in capsys.readouterr().err


def test_py_invalid_program_propagates_daad_exit_code(tmp_path, capsys):
    bad = tmp_path / "bad.daad"
    bad.write_text("اطبع(ناقص\n", encoding="utf-8")
    rc = main(["py", str(bad)])
    assert rc == 1
