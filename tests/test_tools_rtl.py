"""اختبارات zyko.tools.rtl — كاشف مشاكل الاتجاه الحتمي (D3–4 + D6)."""

import json

from zyko.tools.rtl import (
    RULE_CATALOG,
    SEVERITY_AR,
    Finding,
    RTLChecker,
    check_css,
    check_html,
    check_python,
    check_text,
    has_arabic,
)


def rules(src: str, fn=check_css) -> list[str]:
    return [f.rule for f in fn(src)]


# ------------------------------------------------------------ CSS


def test_css_001_left_in_rtl_context():
    fs = check_css("[dir=rtl] .a { text-align: left; }")
    assert [f.rule for f in fs] == ["RTL-CSS-001"] and fs[0].severity == "error"


def test_css_001_via_direction_rtl():
    assert "RTL-CSS-001" in rules(".a { direction: rtl; text-align: left; }")


def test_css_002_physical_align_without_context():
    assert "RTL-CSS-002" in rules(".a { text-align: right; }")


def test_css_003_physical_margin():
    fs = check_css("[dir=rtl] .a { margin-left: 4px; }")
    assert fs[0].rule == "RTL-CSS-003" and fs[0].severity == "error"
    assert "margin-inline" in fs[0].suggestion


def test_css_003_logical_clean():
    assert check_css(".a { margin-inline-start: 4px; }") == []


def test_css_004_float_physical():
    assert "RTL-CSS-004" in rules(".a { float: left; }")


def test_css_005_positional_info():
    fs = check_css(".a { left: 3px; }")
    assert fs[0].rule == "RTL-CSS-005" and fs[0].severity == "info"


def test_css_comments_ignored():
    assert check_css(".a { /* text-align: left; */ }") == []


def test_css_media_nesting_line_accurate():
    css = "@media screen {\n  [dir=rtl] .a { text-align: left; }\n}"
    fs = check_css(css)
    assert fs[0].line == 2


# ------------------------------------------------------------ HTML


def test_html_001_missing_dir():
    fs = check_html("<html><body><p>مرحبا بالعالم العربي</p></body></html>")
    f = next(f for f in fs if f.rule == "RTL-HTML-001")
    assert f.severity == "error"


def test_html_001_rtl_clean():
    src = '<html dir="rtl" lang="ar"><body><p>مرحبا</p></body></html>'
    assert "RTL-HTML-001" not in rules(src, check_html)


def test_html_002_rtl_without_lang():
    assert "RTL-HTML-002" in rules('<html dir="rtl"></html>', check_html)


def test_html_003_arabic_element_in_ltr():
    src = '<html dir="ltr"><body><p>نص عربي واضح هنا</p></body></html>'
    assert "RTL-HTML-003" in rules(src, check_html)


def test_html_004_inline_align_left_rtl():
    src = '<html dir="rtl"><body><p style="text-align:left">نص</p></body></html>'
    assert "RTL-HTML-004" in rules(src, check_html)


def test_html_style_block_inherits_rtl():
    src = '<html dir="rtl"><style>.a { text-align: left; }</style></html>'
    fs = check_html(src)
    assert "RTL-CSS-001" in [f.rule for f in fs]


# ------------------------------------------------------------ Python


def test_py_000_syntax_error():
    fs = check_python("def broken(:\n    pass")
    assert [f.rule for f in fs] == ["RTL-PY-000"]


def test_py_001_arabic_vs_latin_const():
    fs = check_python('if "يسار" == "left":\n    pass')
    assert [f.rule for f in fs] == ["RTL-PY-001"] and fs[0].severity == "error"


def test_py_001_digits_mismatch():
    assert "RTL-PY-001" in rules('if "١٢٣" == "123":\n    pass', check_python)


def test_py_001_mixed_membership_list():
    assert "RTL-PY-001" in rules('if x in ("يسار", "left"):\n    pass', check_python)


def test_py_001_translation_table_clean():
    assert check_python('LABELS = {"left": "يسار"}') == []


def test_py_002_mixed_message_info():
    fs = check_python('msg = "تم تحديث الملف saved بنجاح"')
    assert [f.rule for f in fs] == ["RTL-PY-002"] and fs[0].severity == "info"


def test_py_003_trojan_source_bidi():
    fs = check_python("x = 1  # innocent \u202e comment")
    assert [f.rule for f in fs] == ["RTL-PY-003"] and fs[0].severity == "error"


def test_py_004_identifier_issues():
    assert "RTL-PY-004" in rules("العدد٢ = 5", check_python)
    assert "RTL-PY-004" in rules("countالعدد = 5", check_python)


def test_py_clean_file():
    src = 'def greet(name):\n    """يرحب."""\n    return f"مرحبا {name}"\n'
    assert check_python(src) == []


# ------------------------------------------------------------ نصوص ونواة


def test_txt_mixed_line():
    fs = check_text("سطر عربي مع latin words هنا")
    assert [f.rule for f in fs] == ["RTL-TXT-001"] and fs[0].severity == "info"


def test_txt_code_fence_skipped():
    src = "```\nmixed عربي وlatin معا\n```\nسطر عربي خالص"
    assert check_text(src) == []


def test_has_arabic():
    assert has_arabic("مرحبا") and not has_arabic("hello")


def test_finding_dataclass_roundtrip():
    f = Finding("RTL-TXT-001", "info", "رسالة", "f.md", 1, 1, "مقتطف", "اقتراح")
    assert f.to_dict()["rule"] == "RTL-TXT-001"


def test_checker_path_and_min_severity(tmp_path):
    f = tmp_path / "s.css"
    f.write_text(".a { text-align: left; }", encoding="utf-8")
    checker = RTLChecker(min_severity="warning")
    findings, scanned = checker.check_path(f)
    assert scanned == 1 and findings[0].rule == "RTL-CSS-002"
    assert RTLChecker(min_severity="error")._keep(findings) == []


def test_checker_dir_skips_binary_and_unknown(tmp_path):
    (tmp_path / "a.css").write_text(".a { float: left; }", encoding="utf-8")
    (tmp_path / "x.xyz").write_text("float: left;", encoding="utf-8")
    (tmp_path / "bin.py").write_bytes(b"x=1\x00\x00")
    findings, scanned = RTLChecker().check_path(tmp_path)
    assert scanned == 1


def test_catalog_15_rules_all_reachable():
    assert len(RULE_CATALOG) == 15
    c = RTLChecker()
    fired: set[str] = set()
    samples = [
        ("[dir=rtl] .a { text-align: left; }", "css"),
        (".a { text-align: left; }", "css"),
        (".a { margin-left: 1px; }", "css"),
        (".a { float: left; }", "css"),
        (".a { left: 4px; }", "css"),
        ("<html><p>مرحبا بالعالم العربي جميعا</p></html>", "html"),
        ('<html dir="rtl"><p>مرحبا</p></html>', "html"),
        ('<html dir="ltr"><p>مرحبا بالعالم العربي</p></html>', "html"),
        ('<html dir="rtl"><p style="text-align:left">مرحبا</p></html>', "html"),
        ("def (:\n", "python"),
        ('if "يسار" == "left":\n    pass', "python"),
        ('m = "تم تحديث الملف saved بنجاح"', "python"),
        ("x = 1  # \u202e", "python"),
        ("العدد٢ = 5", "python"),
        ("هذا نص عربي مع English words هنا", "text"),
    ]
    for src, lang in samples:
        fired |= {f.rule for f in c.check_source(src, lang)}
    assert fired == set(RULE_CATALOG)


def test_severity_labels_arabic():
    assert SEVERITY_AR == {"error": "خطأ", "warning": "تحذير", "info": "معلومة"}


# ------------------------------------------------------------ CLI


def _main(argv):
    from zyko.tools.rtl.__main__ import main

    return main(argv)


def test_cli_check_text_finds_and_exits_1(capsys):
    assert _main(["check", "--text", "[dir=rtl] .a { text-align: left; }", "--lang", "css"]) == 1
    assert "RTL-CSS-001" in capsys.readouterr().out


def test_cli_check_clean_exit_zero(capsys):
    assert _main(["check", "--text", ".a { text-align: start; }", "--lang", "css"]) == 0
    assert "لا ملاحظات" in capsys.readouterr().out


def test_cli_check_json(capsys):
    _main(["check", "--text", ".a { margin-left: 1px; }", "--lang", "css", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool"] == "zyko_rtl" and payload["count"] == 1


def test_cli_rules_command(capsys):
    assert _main(["rules"]) == 0
    assert "RTL-CSS-001" in capsys.readouterr().out


def test_cli_missing_input_exit_two(capsys):
    assert _main(["check"]) == 2
    assert "خطأ" in capsys.readouterr().err


def test_cli_unknown_ext_exit_two(tmp_path, capsys):
    f = tmp_path / "a.xyz"
    f.write_text("x", encoding="utf-8")
    assert _main(["check", "--path", str(f)]) == 2
