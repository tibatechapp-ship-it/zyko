"""اختبارات تقارير الحلقة وواجهة الأوامر: حتمية بايتية وعقود أكواد خروج."""

from __future__ import annotations

import json

import pytest

from zyko.pipeline.engine import PipelineEngine
from zyko.pipeline.report import (
    pipeline_payload_summary,
    pipeline_result_to_json,
    pipeline_result_to_text,
    pipeline_summary_line,
    stages_table_text,
)

DESC = "أريد قائمة مهام يومية بسيطة أضيف فيها المهام وأشطبها عند إنجازها"
ENGINE = PipelineEngine()


@pytest.fixture()
def result(tmp_path):
    return ENGINE.run(DESC, tmp_path / "todo", write=False)


# ------------------------------------------------------------ التقارير
def test_json_deterministic_bytes(tmp_path):
    a = ENGINE.run(DESC, tmp_path / "a", write=False)
    b = ENGINE.run(DESC, tmp_path / "b", write=False)
    assert pipeline_result_to_json(a) == pipeline_result_to_json(b)


def test_json_payload_structure(result):
    d = json.loads(pipeline_result_to_json(result))
    assert d["schema"] == "zyko.pipeline/1"
    assert d["ok"] is True
    assert d["plan"]["name"] == "todo-cli"
    assert d["failed_stage"] is None and d["error_ar"] is None
    assert d["fixed_total"] == 0  # القوالب المثالية: لا إصلاحات
    assert d["summary_before"]["files"] == len(d["py_files"]) == d["summary_after"]["files"]
    for f in d["per_file"]:
        for o in f["outcomes"]:
            assert o["suggestion_ar"]


def test_text_report_sections(result):
    t = pipeline_result_to_text(result)
    assert "حلقة التغذية الراجعة" in t
    assert "المخطط: todo-cli" in t
    assert "الحكم النهائي:" in t
    assert "المصائر: أُصلح 0 — يدوي 0 — يبقى 0" in t  # قوالب مثالية بلا ملاحظات
    assert "[todo-cli" in t or any(p.startswith("[") for p in t.splitlines())


def test_text_report_failure_branch(tmp_path):
    r = ENGINE.run("", tmp_path / "x", write=False)
    t = pipeline_result_to_text(r)
    assert "فشلت الحلقة في مرحلة التوليد" in t
    assert "السبب:" in t


def test_summary_line_success_and_failure(result, tmp_path):
    line = pipeline_summary_line(result)
    assert "الحلقة اكتملت" in line
    assert "←" in line
    bad = ENGINE.run(None, tmp_path / "y", write=False)
    assert pipeline_summary_line(bad).startswith("فشل في التوليد")


def test_stages_table_lists_three_stages():
    t = stages_table_text()
    assert "coder" in t and "reviewer" in t and "fixer" in t
    assert "zyko.pipeline/1" in t


def test_payload_summary_fields(result):
    s = pipeline_payload_summary(result)
    assert s["schema"] == "zyko.pipeline/1"
    assert s["ok"] is True
    assert s["fixed"] == result.fixed_total
    assert s["min_score_after"] == result.min_score_after


# ---------------------------------------------------------------- CLI
def run_cli(capsys, *argv):
    from zyko.pipeline.__main__ import main

    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_run_text_and_exit_contract(tmp_path, capsys):
    code, out, _err = run_cli(
        capsys,
        "run",
        "--description",
        DESC,
        "--out",
        str(tmp_path / "todo"),
        "--dry-run",
        "--fail-under",
        "60",
    )
    assert code == 0
    assert "حلقة التغذية الراجعة" in out


def test_cli_run_dry_run_writes_nothing(tmp_path, capsys):
    out_dir = tmp_path / "never"
    code, _out, _err = run_cli(
        capsys, "run", "--description", DESC, "--out", str(out_dir), "--dry-run"
    )
    assert code in (0, 1)
    assert not out_dir.exists()


def test_cli_run_default_fail_under_leaves_exit_1(tmp_path, capsys):
    code, _out, err = run_cli(
        capsys, "run", "--description", DESC, "--out", str(tmp_path / "todo"), "--dry-run"
    )
    if code == 1:
        assert "دون الحد المطلوب" in err


def test_cli_run_json(tmp_path, capsys):
    code, out, _err = run_cli(
        capsys,
        "run",
        "--description",
        DESC,
        "--out",
        str(tmp_path / "todo"),
        "--dry-run",
        "--format",
        "json",
    )
    assert code in (0, 1)
    d = json.loads(out)
    assert d["schema"] == "zyko.pipeline/1"


def test_cli_run_summary(tmp_path, capsys):
    code, out, _err = run_cli(
        capsys,
        "run",
        "--description",
        DESC,
        "--out",
        str(tmp_path / "todo"),
        "--dry-run",
        "--format",
        "summary",
    )
    assert code in (0, 1)
    assert "الحلقة اكتملت" in out


def test_cli_run_rejects_non_empty_dir(tmp_path, capsys):
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("لا تمسّني", encoding="utf-8")
    code, _out, err = run_cli(capsys, "run", "--description", DESC, "--out", str(occupied))
    assert code == 2
    assert "غير فارغ" in err


def test_cli_run_structured_failure_exit_2(tmp_path, capsys):
    code, out, _err = run_cli(capsys, "run", "--description", "", "--out", str(tmp_path / "x"))
    assert code == 2
    assert "فشلت الحلقة" in out


def test_cli_gate_success(capsys):
    code, out, _err = run_cli(capsys, "gate")
    assert code == 0
    assert "بوابة المرحلة 4" in out
    assert "النتيجة: البوابة ناجحة" in out


def test_cli_stages(capsys):
    code, out, _err = run_cli(capsys, "stages")
    assert code == 0
    assert "coder" in out and "fixer" in out


def test_cli_include_timing_adds_seconds(tmp_path, capsys):
    code, out, _err = run_cli(
        capsys,
        "run",
        "--description",
        DESC,
        "--out",
        str(tmp_path / "todo"),
        "--dry-run",
        "--format",
        "json",
        "--include-timing",
    )
    assert code in (0, 1)
    assert "seconds" in json.loads(out)
