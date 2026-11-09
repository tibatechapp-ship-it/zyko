"""اختبارات المحرك: الدرجة والحكم والحدود والملفات والمجلدات والملخص."""

from __future__ import annotations

import textwrap

import zyko.reviewer.engine as engine_mod
from zyko.reviewer import RULES, ReviewEngine
from zyko.reviewer.engine import (
    SCHEMA,
    SKIP_PARTS,
    summarize,
    verdict_for_score,
)
from zyko.reviewer.engine import (
    ReviewEngine as EngineAlias,
)
from zyko.reviewer.rules import SEVERITIES, RuleConfig

ENGINE = ReviewEngine()

CLEAN_SRC = textwrap.dedent(
    '''
    """وحدة نظيفة تمامًا."""

    def total(values: list[int]) -> int:
        """يجمع القيم."""
        return sum(values)
    '''
)

DIRTY_SRC = "value = eval('1')\n"


def test_clean_source_is_perfect():
    result = ENGINE.review_source(CLEAN_SRC)
    assert result.score == 100
    assert result.verdict_ar == "مقبول"
    assert result.findings == []
    assert result.parse_error is None
    assert all(result.counts[s] == 0 for s in SEVERITIES)


def test_score_single_critical():
    result = ENGINE.review_source(DIRTY_SRC)
    assert result.counts["critical"] == 1
    assert result.score == 85  # 100 - 15
    assert result.verdict_ar == "يحتاج تحسينًا"


def test_score_mixed_weights():
    src = (
        "value = eval('1')\n"  # حرج 15
        "try:\n    a = 1\nexcept ValueError:\n    pass\n"  # عالي 8
        "def f(x):\n    'doc'\n    return x == None\n"  # متوسط 0? لا — ==None منخفض 2
    )
    result = ENGINE.review_source(src)
    # حرج 15 + عالي 8 + منخفض 2 = 25
    assert result.score == 75
    assert result.verdict_ar == "يحتاج تحسينًا"


def test_score_floors_at_zero():
    src = "\n".join(f"value{i} = eval('{i}')" for i in range(8))
    result = ENGINE.review_source(src)
    assert result.score == 0
    assert result.verdict_ar == "مرفوض"


def test_verdict_boundaries():
    assert verdict_for_score(100) == "مقبول"
    assert verdict_for_score(90) == "مقبول"
    assert verdict_for_score(89) == "يحتاج تحسينًا"
    assert verdict_for_score(75) == "يحتاج تحسينًا"
    assert verdict_for_score(74) == "يحتاج إصلاحًا"
    assert verdict_for_score(50) == "يحتاج إصلاحًا"
    assert verdict_for_score(49) == "مرفوض"
    assert verdict_for_score(0) == "مرفوض"


def test_parse_error_structured():
    result = ENGINE.review_source("def broken(:\n    pass\n")
    assert result.score == 0
    assert result.verdict_ar == "غير قابل للتحليل"
    assert result.parse_error is not None
    assert "صياغة" in result.parse_error
    assert result.findings == []


def test_empty_source_is_perfect():
    result = ENGINE.review_source("")
    assert result.score == 100
    assert result.verdict_ar == "مقبول"


def test_sha256_deterministic():
    a = ENGINE.review_source(CLEAN_SRC)
    b = ENGINE.review_source(CLEAN_SRC)
    assert a.source_sha256 == b.source_sha256
    assert len(a.source_sha256) == 16


def test_findings_sorted_by_line_col_rule():
    src = (
        "import os\n"  # سطر 1: R-QLT-207
        "value = eval('1')\n"  # سطر 2: R-SEC-101
        "other = value == None\n"  # سطر 3: R-QLT-206
    )
    result = ENGINE.review_source(src)
    keys = [(f.line, f.col, f.rule_id) for f in result.findings]
    assert keys == sorted(keys)
    assert [f.line for f in result.findings] == sorted(f.line for f in result.findings)


def test_counts_keys_complete():
    result = ENGINE.review_source(DIRTY_SRC)
    assert set(result.counts) == set(SEVERITIES)


def test_to_dict_schema_and_shape():
    result = ENGINE.review_source(DIRTY_SRC)
    payload = result.to_dict()
    assert payload["schema"] == SCHEMA == "zyko.review/1"
    assert {"path", "score", "verdict_ar", "counts", "findings", "source_sha256"} <= set(payload)
    assert "seconds" not in payload


def test_include_timing_optional():
    result = ENGINE.review_source(CLEAN_SRC)
    assert "seconds" not in result.to_dict()
    assert "seconds" in result.to_dict(include_timing=True)
    assert result.seconds >= 0.0


def test_review_file_missing(tmp_path):
    result = ENGINE.review_file(tmp_path / "لا_يوجد.py")
    assert result.parse_error is not None
    assert "غير موجود" in result.parse_error


def test_review_file_invalid_utf8(tmp_path):
    p = tmp_path / "binary.py"
    p.write_bytes(b"x = '\xff\xfe'\n")
    result = ENGINE.review_file(p)
    assert result.parse_error is not None
    assert "UTF-8" in result.parse_error


def test_review_file_oversized(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod, "MAX_SOURCE_BYTES", 16)
    p = tmp_path / "big.py"
    p.write_text("# " + "a" * 64 + "\n", encoding="utf-8")
    result = ENGINE.review_file(p)
    assert result.parse_error is not None
    assert "الحد" in result.parse_error


def test_review_path_single_file(tmp_path):
    p = tmp_path / "ok.py"
    p.write_text(CLEAN_SRC, encoding="utf-8")
    results = ENGINE.review_path(p)
    assert len(results) == 1
    assert results[0].score == 100


def test_review_path_tree_sorted_and_filtered(tmp_path):
    (tmp_path / "b.py").write_text(CLEAN_SRC, encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "a.py").write_text(CLEAN_SRC, encoding="utf-8")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "c.py").write_text(CLEAN_SRC, encoding="utf-8")
    (tmp_path / "notes.txt").write_text("نص عادي", encoding="utf-8")
    results = ENGINE.review_path(tmp_path)
    names = [r.path for r in results]
    assert len(names) == 2
    assert names == sorted(names)
    assert all("__pycache__" not in n for n in names)


def test_review_path_missing_returns_error():
    results = ENGINE.review_path("/غير/موجود/إطلاقًا")
    assert len(results) == 1
    assert "المسار غير موجود" in results[0].parse_error


def test_skip_parts_constant():
    for required in ("__pycache__", ".git", "node_modules", ".venv"):
        assert required in SKIP_PARTS


def test_summarize_batch():
    engine = EngineAlias()
    r1 = engine.review_source(DIRTY_SRC, "bad.py")
    r2 = engine.review_source(CLEAN_SRC, "good.py")
    s = summarize([r1, r2])
    assert s["files"] == 2
    assert s["total_findings"] == 1
    assert s["min_score"] == 85
    assert s["worst_files"][0]["path"] == "bad.py"
    assert s["counts"]["critical"] == 1


def test_summarize_empty_batch():
    s = summarize([])
    assert s["files"] == 0
    assert s["min_score"] == 0
    assert s["worst_files"] == []


def test_engine_custom_rules_subset():
    rule_206 = next(r for r in RULES if r.rule_id == "R-QLT-206")
    engine = ReviewEngine(rules=(rule_206,))
    result = engine.review_source("value = eval('1')\nx = y == None\n")
    assert [f.rule_id for f in result.findings] == ["R-QLT-206"]


def test_engine_config_passed_to_rules():
    engine = ReviewEngine(RuleConfig(max_args=2))
    result = engine.review_source("def f(a, b, c):\n    '''موثقة.'''\n    return a\n")
    assert any(f.rule_id == "R-QLT-203" for f in result.findings)


def test_engine_rules_default_is_registry():
    assert len(ENGINE.rules) == len(RULES)


def test_finding_col_is_one_based_in_payload():
    result = ENGINE.review_source("value = eval('1')")
    assert result.findings[0].col == 8  # الحقل الخام يبقى صفري الارتكاز
    assert result.findings[0].to_dict()["col"] == 9  # والمخرجات للبشر تبدأ من 1
