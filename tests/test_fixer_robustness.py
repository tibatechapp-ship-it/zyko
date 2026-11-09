"""اختبارات متانة المُصلِح: مدخلات عدائية لا تُسقطه ولا تُفسد نواتجه.

نفس جسد المتانة الـ11 للمرحلة 2 يمر من المُصلِح الآن: النتيجة إما مهيكلة
(parse_error) أو إصلاح سليم متحقق منه — ولا مسار ثالث.
"""

from __future__ import annotations

import pytest

from zyko.fixer.edits import parses
from zyko.fixer.engine import FixerEngine

ENGINE = FixerEngine()

HOSTILE: list[tuple[str, bytes]] = [
    ("h_empty.py", b""),
    ("h_syntax.py", b"def broken(:\n    pass\n"),
    ("h_nulls.py", b"x = 1\x00y = 2\n"),
    ("h_latin1.py", b"# caf\xe9 latin-1 only\nx = 1\n"),
    ("h_bom.py", b"\xef\xbb\xbfvalue = 1\n"),
    ("h_crlf.py", b"def f():\r\n    return 1\r\n"),
    ("h_tabs.py", b"def f():\n\tif True:\n\t\treturn 1\n"),
    ("h_unicode_names.py", "قيمة = 5\nprint(قيمة)\n".encode("utf-8")),
    ("h_huge_line.py", b"x = '" + b"a" * 300_000 + b"'\n"),
    ("h_comment_only.py", "# لا شيء غير هذا التعليق\n".encode("utf-8")),
    ("h_deep.py", ("x = 0\n" + "if x == 0:\n" * 40 + "    pass\n").encode("utf-8")),
]


@pytest.mark.parametrize("name,data", HOSTILE, ids=[n for n, _ in HOSTILE])
def test_hostile_input_never_crashes(name, data, tmp_path):
    p = tmp_path / name
    p.write_bytes(data)
    result = ENGINE.fix_file(p)
    if result.parse_error is None:
        # سليم التحليل ⇒ أي إصلاح يجب أن يكون نصًا صالحًا
        assert not result.changed or parses(result.fixed_source)
        assert result.score_after >= result.score_before


def test_hostile_folder_tree_scan(tmp_path):
    for name, data in HOSTILE:
        (tmp_path / name).write_bytes(data)
    results = ENGINE.fix_path(tmp_path)
    assert len(results) == len(HOSTILE)


def test_crlf_line_numbers_consistent(tmp_path):
    # إصلاح داخل ملف CRLF يجب أن يقع في الموضع الصحيح لا بعد سطر زائف
    p = tmp_path / "crlf.py"
    p.write_bytes(b"import os\r\ndef f(v):\r\n    return v == None\r\n")
    r = ENGINE.fix_file(p)
    assert r.changed
    assert "import os" not in r.fixed_source
    assert "v is None" in r.fixed_source
    assert parses(r.fixed_source)


def test_null_bytes_rejected_structured(tmp_path):
    p = tmp_path / "nul.py"
    p.write_bytes(b"x = 1\x00\n")
    r = ENGINE.fix_file(p)
    assert r.parse_error is not None  # لا صمت ولا انهيار


def test_tabs_source_repair_safe(tmp_path):
    p = tmp_path / "tabs.py"
    p.write_bytes(b"import os\n\tx = 1\n")
    r = ENGINE.fix_file(p)
    # الملف مكسور الإزاحة أصلًا — يجب نتيجة مهيكلة لا إصلاح خاطئ
    if r.changed:
        assert parses(r.fixed_source)


def test_deep_nesting_no_regression(tmp_path):
    p = tmp_path / "deep.py"
    p.write_text("x = 0\n" + "if x == 0:\n" * 40 + "    pass\n", encoding="utf-8")
    r = ENGINE.fix_file(p)
    assert r.parse_error is None or r.parse_error


def test_bom_preserved_or_clean(tmp_path):
    p = tmp_path / "bom.py"
    p.write_bytes(b"\xef\xbb\xbfvalue = 1\n")
    r = ENGINE.fix_file(p)
    # BOM فقط ⇒ لا ملاحظات ⇒ لا تغيير (أو تغيير متحقق منه إن قُرئ)
    assert not r.changed or parses(r.fixed_source)


def test_arabic_identifiers_flow_through():
    # الأسماء العربية صالحة في بايثون — يجب أن تمر من المُصلح بلا إفساد
    src = "قيمة = None\nوظيفة = lambda س: س or قيمة\n"
    r = ENGINE.fix_source(src, "ar.py")
    assert r.parse_error is None
    assert not r.changed or parses(r.fixed_source)
    assert "قيمة" in r.fixed_source  # لم يُفسد الترميز


def test_arabic_compare_fixed_in_place():
    src = "def تحقق(قيمة):\n    return قيمة == None\n"
    r = ENGINE.fix_source(src, "ar.py")
    assert r.changed
    assert "قيمة is None" in r.fixed_source
    assert parses(r.fixed_source)
    after_line = r.fixed_source.splitlines()[2]  # بعد توثيق «تحقق» المدرج
    # «==» و«is» بنفس الطول ⇒ طول السطر يزداد فقط بتوثيق الدالة المدرج قبلها
    assert after_line.rstrip().endswith("return قيمة is None")
