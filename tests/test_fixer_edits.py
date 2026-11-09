"""اختبارات طبقة التحرير: الإحداثيات والقطع — حصينة «فخ المبايت» العربية.

كل ما يخص تحويل إحداثيات AST (إزاحات بايت UTF-8) إلى مواضع حرفية،
وتطبيق القطع من النهاية إلى البداية، وإسقاط المتداخل بأسباب عربية.
"""

from __future__ import annotations

import ast

from zyko.fixer.edits import (
    Edit,
    SourceText,
    apply_edits,
    indent_of,
    parses,
    shift_lines,
)


# ------------------------------------------------------------- المصدر
def test_char_col_ascii_identity():
    # سطر ASCII خالص: العمود البايتي = العمود الحرفي
    assert SourceText.char_col("x = 1", 4) == 4


def test_char_col_arabic_line():
    # «قيمة = "مرحبا"» — الحروف العربية بايتان لكل حرف
    line = 'label = "مرحبا"'
    byte_col = len('label = "'.encode())  # داخل النص العربي
    char_col = SourceText.char_col(line, byte_col)
    assert line[char_col] == "م"


def test_char_col_clamps_out_of_range():
    assert SourceText.char_col("abc", 99) == 3
    assert SourceText.char_col("abc", -5) == 0


def test_abs_pos_multiline_arabic():
    src = 's = "مرحبا"\nx = 1\n'
    st = SourceText(src)
    # عمود بايت 4 في السطر الثاني = موضع '1' تقريبًا — نتحقق من النهاية
    assert src[st.abs_pos(2, 4)] == "1"


def test_segment_preserves_author_bytes():
    src = "def f(قيمة):\n    return قيمة\n"
    st = SourceText(src)
    tree = ast.parse(src)
    func = tree.body[0]
    arg = func.args.args[0]
    assert st.segment(arg.lineno, arg.col_offset, arg.end_lineno, arg.end_col_offset) == "قيمة"
    header_end = st.segment(func.lineno, func.col_offset, func.body[0].lineno, 0)
    assert header_end.splitlines()[0] == "def f(قيمة):"


def test_segment_reversed_span_returns_empty():
    st = SourceText("abcdef\n")
    assert st.segment(1, 4, 1, 2) == ""


def test_line_text_clamps():
    st = SourceText("a\nb\n")
    assert st.line_text(99) == ""  # فوق النطاق ⇒ آخر سطر فيزيائي (خالٍ)
    assert st.line_text(0) == "a"
    assert st.line_count() == 3  # سطر خالٍ ثالث بعد آخر \n


# ------------------------------------------------------- تطبيق القطع
def mk(line, col, end_line, end_col, repl, rid="X"):
    return Edit(line, col, end_line, end_col, repl, rid, "تجربة")


def test_apply_single_replacement():
    out, applied, skipped = apply_edits("aaa\nbbb\nccc\n", [mk(2, 0, 2, 3, "BBB")])
    assert out == "aaa\nBBB\nccc\n"
    assert len(applied) == 1 and not skipped


def test_apply_whole_line_deletion_includes_newline():
    out, _, _ = apply_edits("a\nb\nc\n", [mk(2, 0, 3, 0, "")])
    assert out == "a\nc\n"


def test_apply_last_line_without_trailing_newline():
    out, _, _ = apply_edits("a\nlast", [mk(2, 0, 2, 4, "")])
    assert out == "a\n"


def test_apply_order_independent_of_input_order():
    e1 = mk(1, 0, 1, 1, "X")
    e2 = mk(3, 0, 3, 1, "Z")
    out1, _, _ = apply_edits("a\nb\nc\n", [e1, e2])
    out2, _, _ = apply_edits("a\nb\nc\n", [e2, e1])
    assert out1 == out2 == "X\nb\nZ\n"


def test_apply_zero_width_insertion():
    out, _, _ = apply_edits("ab\n", [mk(1, 1, 1, 1, "-")])
    assert out == "a-b\n"


def test_overlapping_edits_skipped_with_arabic_reason():
    # التطبيق من النهاية: القطعة الأبعد بداية تُطبق أولاً، والمتقاطعة تُسقط
    e1 = Edit(1, 0, 1, 5, "ONE", "A", "تجربة")
    e2 = Edit(1, 3, 1, 8, "TWO", "B", "تجربة")
    out, applied, skipped = apply_edits("0123456789\n", [e1, e2])
    assert out == "012TWO89\n"
    assert [e.rule_id for e in applied] == ["B"]
    assert len(skipped) == 1 and skipped[0][0].rule_id == "A"
    assert "تداخل" in skipped[0][1]


def test_identical_span_edits_second_skipped():
    e1 = mk(1, 0, 1, 2, "A")
    e2 = mk(1, 0, 1, 2, "B")
    out, applied, skipped = apply_edits("xyz\n", [e1, e2])
    assert out == "Az\n"  # xy استُبدلت بـ A
    assert len(applied) == 1 and len(skipped) == 1


def test_reversed_span_edit_dropped_silently():
    out, applied, skipped = apply_edits("abc\n", [mk(1, 3, 1, 1, "?")])
    assert out == "abc\n" and not applied and not skipped


def test_out_of_bounds_positions_clamped_not_crash():
    out, applied, _ = apply_edits("abc\n", [mk(99, 0, 99, 99, "!")])
    assert applied and out.endswith("!")


def test_edit_to_dict_human_columns():
    d = mk(1, 0, 2, 4, "x").to_dict()
    assert d["col"] == 1 and d["end_col"] == 5  # أعمدة بشرية تبدأ من 1


# ------------------------------------------------------ المساعدات
def test_indent_of_mixed():
    assert indent_of("    x = 1") == "    "
    assert indent_of("\t\tx") == "\t\t"
    assert indent_of("x") == ""


def test_shift_lines_positive():
    assert shift_lines("a\n\nb", 4) == "    a\n\n    b"


def test_shift_lines_negative_stops_at_zero_indent():
    assert shift_lines("    a\n  b", -6) == "a\nb"


def test_shift_lines_zero_noop():
    assert shift_lines(" a ", 0) == " a "


def test_parses_accepts_and_rejects():
    assert parses("x = 1\n")
    assert parses("")  # وحدة فارغة صالحة نحويًا
    assert not parses("def broken(:\n")
