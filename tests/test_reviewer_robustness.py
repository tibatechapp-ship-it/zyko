"""اختبارات المتانة: مدخلات عدائية يجب أن تُستقبل بنتائج مهيكلة لا بانتهارات.

هذه المجموعة هي ضمان «لا يسقط المراجع أمام أي ملف» — أصعب ما تواجهه
أدوات المراجعة على الهاتف حيث يكون الانهيار مكلفًا.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zyko.reviewer import ReviewEngine
from zyko.reviewer.gate import _robustness_corpus
from zyko.reviewer.report import result_to_json, result_to_text

ENGINE = ReviewEngine()


def _corpus(tmp_path: Path) -> list[Path]:
    tmp = tmp_path / "hostile"
    tmp.mkdir()
    return _robustness_corpus(tmp)


def test_corpus_has_eleven_hostiles(tmp_path):
    paths = _corpus(tmp_path)
    assert len(paths) == 11
    assert all(p.is_file() for p in paths)


def test_every_hostile_returns_structured_result(tmp_path):
    for p in _corpus(tmp_path):
        result = ENGINE.review_file(p)  # أي انهيار هنا فشل الاختبار
        assert 0 <= result.score <= 100, p
        assert result.verdict_ar


def test_hostile_results_never_crash_batch(tmp_path):
    root = _corpus(tmp_path)[0].parent
    results = ENGINE.review_path(root)
    assert len(results) == 11


def test_empty_file_is_perfect(tmp_path):
    p = tmp_path / "empty.py"
    p.write_bytes(b"")
    result = ENGINE.review_file(p)
    assert result.parse_error is None
    assert result.score == 100


def test_syntax_error_is_structured(tmp_path):
    p = tmp_path / "broken.py"
    p.write_text("def f(:\n", encoding="utf-8")
    result = ENGINE.review_file(p)
    assert result.parse_error is not None
    assert result.score == 0


def test_null_bytes_structured(tmp_path):
    p = tmp_path / "nulls.py"
    p.write_bytes(b"a = 1\x00b = 2\n")
    result = ENGINE.review_file(p)
    assert result.parse_error is not None


def test_invalid_utf8_structured(tmp_path):
    p = tmp_path / "latin.py"
    p.write_bytes(b"# caf\xe9\nx = 1\n")
    result = ENGINE.review_file(p)
    assert result.parse_error is not None
    assert "UTF-8" in result.parse_error


def test_bom_structured(tmp_path):
    p = tmp_path / "bom.py"
    p.write_bytes(b"\xef\xbb\xbfvalue = 1\n")
    result = ENGINE.review_file(p)
    # إما يُحلل بنظافة أو يُرفض مهيكلًا — المهم لا انهيار ولا درجة عشوائية
    assert result.parse_error is not None or result.score >= 0


def test_crlf_parses_clean(tmp_path):
    p = tmp_path / "crlf.py"
    p.write_bytes("def f():\r\n    '''توثيق.'''\r\n    return 1\r\n".encode("utf-8"))
    result = ENGINE.review_file(p)
    assert result.parse_error is None
    assert result.score == 100


def test_deep_nesting_bounded_findings(tmp_path):
    lines = ["x = 0"]
    for level in range(1, 41):
        lines.append("    " * (level - 1) + f"if x == {level}:")
    lines.append("    " * 40 + "pass")
    p = tmp_path / "deep.py"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = ENGINE.review_file(p)
    assert result.parse_error is None
    deep = [f for f in result.findings if f.rule_id == "R-QLT-202"]
    # نُرسّي عند مستوى العمق 5 فقط (مرة واحدة لكل فرع يعبر العتبة) — لا انفجار
    assert len(deep) == 1


def test_huge_line_survives(tmp_path):
    p = tmp_path / "huge.py"
    p.write_bytes(b"x = '" + b"a" * 300_000 + b"'\n")
    result = ENGINE.review_file(p)
    assert result.parse_error is None
    assert result.score == 100


def test_unicode_identifiers_ok(tmp_path):
    p = tmp_path / "unicode.py"
    p.write_text("قيمة = 5\n", encoding="utf-8")
    result = ENGINE.review_file(p)
    assert result.parse_error is None
    assert result.score == 100


def test_determinism_across_hostile_corpus(tmp_path):
    for p in _corpus(tmp_path):
        a_json = result_to_json(ENGINE.review_file(p))
        b_json = result_to_json(ENGINE.review_file(p))
        a_text = result_to_text(ENGINE.review_file(p))
        b_text = result_to_text(ENGINE.review_file(p))
        assert a_json == b_json, p
        assert a_text == b_text, p


NASTY_SNIPPETS = (
    "x = 'نص لم يُغلق\n",
    "x = \\\n",
    "class (\n",
    "def f(a=1, a=2): pass\n",
    "x = f'{x:{width}}'\n",
    "🎉 = 'رمز في الاسم'\n",
    "x = '‏‎ bidi chars ‎‏'\n",
    "if x:\n    if y:\n        if z:\n            if w:\n                if q:\n                    pass\n",
    "lambda: lambda: lambda\n",
    "x = (((((1))))))\n",
    "import\n",
    "@decorator\n",
    "x: = 5\n",
)


def test_fuzz_snippets_never_raise():
    for snippet in NASTY_SNIPPETS:
        try:
            ENGINE.review_source(snippet)
        except RecursionError:
            pytest.fail(f"RecursionError تسرب من المحرك: {snippet!r}")
        except Exception as exc:  # أي استثناء آخر غير مقبول أيضًا
            pytest.fail(f"انهيار غير متوقع {type(exc).__name__}: {snippet!r}")


def test_fuzz_snippets_deterministic():
    for snippet in NASTY_SNIPPETS:
        a = result_to_json(ENGINE.review_source(snippet))
        b = result_to_json(ENGINE.review_source(snippet))
        assert a == b
