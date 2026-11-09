"""اختبارات المخرجات (JSON/نص عربي) وواجهة سطر الأوامر وأكواد الخروج."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zyko.reviewer import ReviewEngine
from zyko.reviewer.__main__ import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, main
from zyko.reviewer.report import (
    result_to_json,
    result_to_text,
    results_to_json,
    results_to_text,
    rules_table_text,
)
from zyko.reviewer.rules import RULES

REPO = Path(__file__).resolve().parents[1]
SAMPLES = REPO / "samples" / "review"
ENGINE = ReviewEngine()

BAD = SAMPLES / "bad_security.py"
CLEAN = SAMPLES / "clean_good.py"


# ------------------------------------------------------------------ JSON
def test_result_json_keys_and_arabic():
    payload = json.loads(result_to_json(ENGINE.review_file(BAD)))
    assert payload["schema"] == "zyko.review/1"
    assert payload["score"] < 60
    assert payload["verdict_ar"] in {"مرفوض", "يحتاج إصلاحًا"}
    assert payload["findings"]
    first = payload["findings"][0]
    for key in (
        "rule_id",
        "severity",
        "severity_ar",
        "category_ar",
        "line",
        "col",
        "message_ar",
        "suggestion_ar",
    ):
        assert key in first


def test_result_json_deterministic_bytes():
    a = result_to_json(ENGINE.review_file(BAD))
    b = result_to_json(ENGINE.review_file(BAD))
    assert a == b


def test_result_json_excludes_timing_by_default():
    assert "seconds" not in json.loads(result_to_json(ENGINE.review_file(BAD)))


def test_results_json_batch_shape():
    results = ENGINE.review_path(SAMPLES)
    payload = json.loads(results_to_json(results))
    assert payload["files"]  # قائمة
    assert len(payload["files"]) == len(results)
    assert payload["summary"]["files"] == len(results)


# ------------------------------------------------------------------- النص
def test_result_text_arabic_labels():
    text = result_to_text(ENGINE.review_file(BAD))
    assert "الملف:" in text
    assert "الدرجة:" in text
    assert "الحكم:" in text
    assert "الإصلاح:" in text
    assert "حرج" in text


def test_result_text_parse_error_branch(tmp_path):
    p = tmp_path / "broken.py"
    p.write_text("def (:", encoding="utf-8")
    text = result_to_text(ENGINE.review_file(p))
    assert "غير قابل للتحليل" in text


def test_results_text_batch_has_footer():
    text = results_to_text(ENGINE.review_path(SAMPLES))
    assert "أسوأ الملفات:" in text
    assert "مجموع الملاحظات" in text


def test_rules_table_text_contains_all_rules():
    text = rules_table_text(RULES)
    assert "المعرف | الخطورة | الفئة | الرسالة" in text
    for rule in RULES:
        assert rule.rule_id in text


# ------------------------------------------------------------------- CLI
def test_cli_review_clean_passes(capsys):
    code = main(["review", "--path", str(CLEAN), "--fail-under", "95"])
    assert code == EXIT_OK
    assert "100/100" in capsys.readouterr().out


def test_cli_review_bad_fails_with_text(capsys):
    code = main(["review", "--path", str(BAD)])
    out = capsys.readouterr().out
    assert code == EXIT_FINDINGS
    assert "R-SEC-101" in out


def test_cli_review_bad_json_payload(capsys):
    code = main(["review", "--path", str(BAD), "--format", "json"])
    assert code == EXIT_FINDINGS
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["critical"] >= 2  # eval + exec + os.system


def test_cli_review_summary_format(capsys):
    code = main(["review", "--path", str(SAMPLES), "--format", "summary"])
    assert code == EXIT_FINDINGS
    out = capsys.readouterr().out
    assert "الملفات:" in out
    assert "أقل درجة" in out


def test_cli_review_missing_path_exit_two(capsys):
    code = main(["review", "--path", "/لا/يوجد/هكذا.py"])
    err = capsys.readouterr().err
    assert code == EXIT_USAGE
    assert "غير موجود" in err


def test_cli_review_empty_dir_exit_two(tmp_path, capsys):
    code = main(["review", "--path", str(tmp_path)])
    assert code == EXIT_USAGE
    assert "لا ملفات بايثون" in capsys.readouterr().err


def test_cli_include_timing_adds_seconds(capsys):
    main(["review", "--path", str(CLEAN), "--format", "json", "--include-timing"])
    payload = json.loads(capsys.readouterr().out)
    assert "seconds" in payload


def test_cli_max_critical_allows_one(capsys, tmp_path):
    src = tmp_path / "one_eval.py"
    src.write_text("def f(e):\n    '''توثيق.'''\n    return eval(e)\n", encoding="utf-8")
    code = main(
        [
            "review",
            "--path",
            str(src),
            "--format",
            "json",
            "--fail-under",
            "50",
            "--max-critical",
            "1",
        ]
    )
    assert code == EXIT_OK


def test_cli_gate_passes_on_anchor_samples(capsys):
    code = main(["gate", "--samples", str(SAMPLES)])
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "G6" in out
    assert "الحكم: مقبول" in out


def test_cli_gate_missing_samples_fails(capsys, tmp_path):
    code = main(["gate", "--samples", str(tmp_path)])
    assert code == EXIT_FINDINGS
    assert "manifest" in capsys.readouterr().out


def test_cli_rules_text(capsys):
    assert main(["rules"]) == EXIT_OK
    assert "R-SEC-101" in capsys.readouterr().out


def test_cli_rules_json_count(capsys):
    main(["rules", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == len(RULES)


def test_cli_requires_command():
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == EXIT_USAGE
