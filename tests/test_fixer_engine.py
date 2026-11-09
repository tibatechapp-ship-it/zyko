"""اختبارات محرك الإصلاح: الجولات، التحقق، الاعتدال، والمتانة التعاقدية."""

from __future__ import annotations

import textwrap
from pathlib import Path

from zyko.fixer.engine import (
    MAX_PASSES,
    SCHEMA,
    FixerEngine,
    review_of,
    summarize_fix,
)
from zyko.fixer.fixes import AUTO_FIXABLE
from zyko.reviewer.engine import MAX_SOURCE_BYTES

ENGINE = FixerEngine()


def fix(source: str, path: str = "<text>"):
    return ENGINE.fix_source(textwrap.dedent(source), path)


# ------------------------------------------------------------ العقدة
def test_schema_constant():
    assert SCHEMA == "zyko.fix/1"


def test_max_passes_bound():
    assert MAX_PASSES == 3


def test_parse_error_structured_no_crash():
    r = ENGINE.fix_source("def broken(:\n", "x.py")
    assert r.parse_error is not None
    assert r.changed is False
    assert r.fixed_source == "def broken(:\n"
    assert r.outcomes == []
    d = r.to_dict()
    assert "parse_error_ar" in d


def test_empty_source_untouched():
    r = ENGINE.fix_source("", "empty.py")
    assert r.changed is False
    assert r.score_before == 100 and r.score_after == 100


def test_chain_lambda_then_docstring_three_pass_value():
    # 209 ⇒ (دالة بلا توثيق) ⇒ 204 — السلسلة تُدار داخليًا
    r = fix("greet = lambda name: 'مرحبًا ' + name\n")
    assert "lambda" not in r.fixed_source
    assert '"""دالة greet' in r.fixed_source
    assert {o.rule_id: o.status for o in r.outcomes}["R-QLT-209"] == "fixed"


def test_outcomes_carry_suggestion_ar_always():
    r = fix(
        """
        import os

        def f(v):
            return v == None
        """
    )
    assert r.outcomes
    for o in r.outcomes:
        assert o.suggestion_ar, o.rule_id


def test_idempotence_on_result():
    src = "import os\ndef f(v):\n    return v == None\n"
    first = ENGINE.fix_source(src, "a.py")
    assert first.changed
    second = ENGINE.fix_source(first.fixed_source, "a.py")
    assert second.changed is False
    assert second.outcomes == [] or all(o.status == "manual" for o in second.outcomes)


def test_score_never_drops():
    samples = [
        "try:\n    x=1\nexcept:\n    pass\n",
        "import subprocess\nsubprocess.run('ls', shell=True)\n",
        "def f(a=[]):\n    return a\n",
    ]
    for s in samples:
        r = ENGINE.fix_source(s, "s.py")
        assert r.score_after >= r.score_before, s


def test_rules_filter_restricts_active_paths():
    e = FixerEngine(rules=("R-SEC-106",))
    src = "import hashlib\nimport os\ndef f(t):\n    return hashlib.md5(t)\n"
    r = e.fix_source(src, "h.py")
    assert "sha256" in r.fixed_source
    assert "import os" in r.fixed_source  # 207 خارج القيود ⇒ لم يُمس


def test_unknown_rule_in_filter_is_ignored():
    e = FixerEngine(rules=("R-SEC-106", "R-XXX-999"))
    r = e.fix_source("import hashlib\nhashlib.md5(b'x')\n", "h.py")
    assert "sha256" in r.fixed_source


def test_planner_injection_for_tests():
    class Boom:
        def __call__(self, ctx):
            raise RuntimeError("انفجار مقصود")

    e = FixerEngine(planners={"R-QLT-206": Boom()})
    r = e.fix_source("def f(v):\n    return v == None\n", "n.py")
    assert status_open(r, "R-QLT-206")
    assert "v == None" in r.fixed_source  # التعبير لم يُمس رغم الجار المكسور


def status_open(r, rid):
    return any(o.rule_id == rid and o.status == "open" for o in r.outcomes)


def test_batch_verification_fallback_keeps_good_groups():
    # مخطط مكسور يولّد قطعة مقلوبة ⇒ الدفعة تفشل ⇒ المجموعات السليمة تبقى
    from zyko.fixer.edits import Edit

    class Bad:
        def __call__(self, ctx):
            return [Edit(1, 99, 1, 3, "كسر", "R-QLT-206", "خبيث")]

    e = FixerEngine(planners={"R-QLT-206": Bad()})
    src = "import hashlib\ndef f(v):\n    return hashlib.md5(v) == None\n"
    r = e.fix_source(src, "m.py")
    assert "sha256" in r.fixed_source  # مجموعة سليمة عبرت رغم الجار المكسور
    assert r.changed is True


def test_to_dict_shape_and_determinism():
    src = "import os\ndef f(v):\n    return v == None\n"
    a = ENGINE.fix_source(src, "d.py").to_dict()
    b = ENGINE.fix_source(src, "d.py").to_dict()
    assert a == b
    assert a["schema"] == SCHEMA
    for key in (
        "path",
        "changed",
        "score_before",
        "score_after",
        "verdict_before_ar",
        "verdict_after_ar",
        "counts_before",
        "counts_after",
        "edits",
        "outcomes",
        "fixed_source",
        "source_sha256",
        "fixed_sha256",
    ):
        assert key in a, key
    assert "seconds" not in a  # التوقيت مستبعد افتراضيًا


def test_include_timing_flag():
    r = ENGINE.fix_source("x = 1\n", "t.py")
    assert "seconds" not in r.to_dict()
    assert "seconds" in r.to_dict(include_timing=True)


def test_outcome_columns_are_human():
    r = fix("def f(v):\n    return v == None\n")
    o = next(o for o in r.outcomes if o.rule_id == "R-QLT-206")
    d = o.to_dict()
    assert d["col"] >= 1 and d["status_ar"]


# ------------------------------------------------------------- الملف
def test_fix_file_missing_structured(tmp_path):
    r = ENGINE.fix_file(tmp_path / "لا_يوجد.py")
    assert r.parse_error is not None and "غير موجود" in r.parse_error
    assert r.fixed_source == ""


def test_fix_file_non_utf8(tmp_path):
    p = tmp_path / "latin.py"
    p.write_bytes(b"# caf\xe9\nx = 1\n")
    r = ENGINE.fix_file(p)
    assert r.parse_error is not None and "UTF-8" in r.parse_error


def test_fix_file_oversized(tmp_path, monkeypatch):
    import zyko.fixer.engine as eng

    p = tmp_path / "big.py"
    p.write_bytes(b"x = 1\n" * 50)
    monkeypatch.setattr(eng, "MAX_SOURCE_BYTES", 10)
    r = ENGINE.fix_file(p)
    assert r.parse_error is not None and "يتجاوز الحد" in r.parse_error


def test_fix_file_ok_roundtrip(tmp_path):
    p = tmp_path / "ok.py"
    p.write_text("import os\ndef f(v):\n    return v == None\n", encoding="utf-8")
    r = ENGINE.fix_file(p)
    assert r.changed and "sha256" not in r.fixed_source  # لا شيء هنا يخص 106
    assert "import os" not in r.fixed_source


def test_fix_path_sorted_and_skips_junk(tmp_path):
    (tmp_path / "b.py").write_text("def f(v):\n    return v == None\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("import os\n", encoding="utf-8")
    junk = tmp_path / "__pycache__"
    junk.mkdir()
    (junk / "c.py").write_text("import json\n", encoding="utf-8")
    results = ENGINE.fix_path(tmp_path)
    names = [Path(r.path).name for r in results]
    assert names == ["a.py", "b.py"]  # مرتبة والمخلجات متخطاة


def test_fix_path_missing_dir():
    results = ENGINE.fix_file("/لا/يوجد/إطلاقًا.py")
    assert results.parse_error is not None


# ------------------------------------------------------------ الملخص
def test_summarize_fix_counts():
    results = [
        ENGINE.fix_source("import os\n", "a.py"),
        ENGINE.fix_source("x = 1\n", "b.py"),
    ]
    s = summarize_fix(results)
    assert s["schema"] == SCHEMA
    assert s["files"] == 2
    assert s["changed_files"] == 1
    assert s["fixed"] == 1  # استيراد os
    assert s["min_score_after"] == 100


def test_review_of_helper():
    r = ENGINE.fix_source("import os\n", "a.py")
    rev = review_of(r)
    assert rev is not None and rev.score == 100
    err = ENGINE.fix_source("def broken(:\n", "x.py")
    assert review_of(err) is None


def test_constant_limits_alignment():
    # نفس سقوف المراجع: لا انحراف في الحدود بين الطبقتين
    assert MAX_SOURCE_BYTES == 5_000_000
    assert set(AUTO_FIXABLE) <= {
        r
        for r in (
            "R-ERR-001",
            "R-ERR-003",
            "R-ERR-004",
            "R-ERR-005",
            "R-ERR-006",
            "R-SEC-103",
            "R-SEC-106",
            "R-SEC-107",
            "R-QLT-204",
            "R-QLT-206",
            "R-QLT-207",
            "R-QLT-209",
        )
    }
