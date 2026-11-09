"""اختبارات واجهة طبقة الذكاء على سطر الأوامر: نفس عقد أكواد الخروج."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zyko.ai.cli import main as ai_main
from zyko.cli import main as cli_main

CLEAN_GOAL = "قائمة مهام بسيطة مع واجهة سطر أوامر ووحدة tasks"
PII_GOAL = "قائمة مهام — للتنسيق اتصل على 0501234567"


# ------------------------------------------------------------- الخريطة
def test_bare_ai_prints_map(capsys: pytest.CaptureFixture[str]) -> None:
    assert ai_main([]) == 0
    out = capsys.readouterr().out
    assert "طبقة الذكاء zyko AI" in out
    assert "planner" in out


def test_ai_map_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    assert ai_main(["map"]) == 0
    assert "بوابات المصنع نفسها" in capsys.readouterr().out


def test_ai_via_main_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["ai", "map"]) == 0
    assert "طبقة الذكاء zyko AI" in capsys.readouterr().out


# ------------------------------------------------------------- الجلسة
def test_run_clean_goal_exit0_and_writes_receipt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = ai_main(["run", "--goal", CLEAN_GOAL, "--out", str(tmp_path / "proj"), "--format", "summary"])
    assert rc == 0
    assert "مقبولة" in capsys.readouterr().out
    assert (tmp_path / "proj" / ".zyko" / "ai_receipt.json").is_file()


def test_run_json_format_is_parseable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = ai_main(["run", "--goal", CLEAN_GOAL, "--out", str(tmp_path / "p2"), "--format", "json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["brain"] == "gated:planner"


def test_run_pii_goal_exit1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = ai_main(["run", "--goal", PII_GOAL, "--out", str(tmp_path / "bad"), "--format", "summary"])
    assert rc == 1
    assert not (tmp_path / "bad").exists()


def test_run_empty_goal_exit2(tmp_path: Path) -> None:
    assert ai_main(["run", "--goal", "   ", "--out", str(tmp_path / "x"), "--format", "summary"]) == 2


def test_run_dry_run_writes_nothing(tmp_path: Path) -> None:
    rc = ai_main(
        ["run", "--goal", CLEAN_GOAL, "--out", str(tmp_path / "dry"), "--dry-run", "--format", "summary"]
    )
    assert rc == 0
    assert not (tmp_path / "dry").exists()


def test_run_md_format_prints_receipt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = ai_main(["run", "--goal", CLEAN_GOAL, "--out", str(tmp_path / "p3"), "--format", "text"])
    assert rc == 0
    assert "# إيصال جلسة zyko AI" in capsys.readouterr().out


# ------------------------------------------------------------- البوابة
def test_gate_command_exit0(capsys: pytest.CaptureFixture[str]) -> None:
    assert ai_main(["gate", "--max-seconds", "30"]) == 0
    assert "12/12" in capsys.readouterr().out
