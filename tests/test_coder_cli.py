"""اختبارات واجهة zyko.coder (سطر الأوامر) + أمر zyko new."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zyko.coder.__main__ import main as coder_main


def test_plan_preview_json_and_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert coder_main(["plan", "مدونة عربية لمقالاتي"]) == 0
    out = capsys.readouterr().out
    assert "blog-site" in out and "static-site" in out

    assert coder_main(["plan", "مدونة عربية لمقالاتي", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["name"] == "blog-site"
    assert data["modules"] == ["posts", "about"]


def test_new_generates_with_approval_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "proj"
    code = coder_main(
        [
            "new",
            "--plan",
            "قائمة مهام بسيطة",
            "--name",
            "my-tasks",
            "--out",
            str(out),
            "--yes",
            "--no-git",
        ]
    )
    assert code == 0, capsys.readouterr().out
    assert (out / "src" / "my_tasks" / "core.py").is_file()
    assert (out / "RECEIPT.md").is_file()
    assert "فحص ثابت" in capsys.readouterr().out


def test_new_aborts_without_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda *a: "لا")
    out = tmp_path / "proj"
    code = coder_main(["new", "--plan", "قائمة مهام بسيطة", "--out", str(out)])
    assert code == 1
    assert not out.exists()


def test_new_overrides_template(tmp_path: Path) -> None:
    out = tmp_path / "proj"
    code = coder_main(
        [
            "new",
            "--plan",
            "قائمة مهام بسيطة",
            "--template",
            "static-site",
            "--out",
            str(out),
            "--yes",
            "--no-git",
        ]
    )
    assert code == 0
    assert (out / "index.html").is_file()


def test_check_command_reports_clean_and_broken(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "proj"
    coder_main(["new", "--plan", "قائمة مهام", "--out", str(out), "--yes", "--no-git"])
    assert coder_main(["check", str(out)]) == 0

    (out / "bad.py").write_text("def (:", encoding="utf-8")
    assert coder_main(["check", str(out)]) == 1
    assert "bad.py" in capsys.readouterr().err


def test_gate_command_no_tests_mode(capsys: pytest.CaptureFixture[str]) -> None:
    assert coder_main(["gate", "--no-tests"]) == 0
    out = capsys.readouterr().out
    assert "10/10" in out and "مقبول" in out


# ------------------------------------------------------------------- zyko new


def test_zyko_new_json_preview(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from zyko.cli import main as zyko_main

    code = zyko_main(["new", "--plan", "واجهة حجوزات عيادة", "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["template"] == "fastapi-api"
    # المعاينة لا تكتب شيئًا
    assert not (tmp_path / "bookings-api").exists()


def test_zyko_new_end_to_end_no_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from zyko.cli import main as zyko_main

    monkeypatch.chdir(tmp_path)
    code = zyko_main(["new", "--plan", "قائمة مهام", "--yes", "--no-git"])
    assert code == 0, capsys.readouterr().out
    assert (tmp_path / "todo-cli" / "RECEIPT.md").is_file()
