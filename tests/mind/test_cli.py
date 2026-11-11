"""اختبارات سطر الأوامر: zyko mind run / map و python -m zyko.mind."""

from __future__ import annotations

import subprocess
import sys

import pytest

from zyko.mind.cli import EXIT_FINDINGS, EXIT_OK, handle_mind, main as mind_main, mind_map_text


class _Args:
    def __init__(self, **kw):
        self.mind_cmd = kw.get("mind_cmd", "run")
        self.goal = kw.get("goal", "انشئ مشروع قائمة مهام مع واجهة سطر أوامر")
        self.out = kw.get("out", "جديد")
        self.rounds = kw.get("rounds", 2)
        self.fail_under = kw.get("fail_under", 75)
        self.dry_run = kw.get("dry_run", False)
        self.json = kw.get("json", False)


class TestMap:
    def test_map_text_deterministic(self):
        assert mind_map_text() == mind_map_text()

    def test_map_handler(self, capsys):
        assert handle_mind(_Args(mind_cmd="map")) == EXIT_OK
        out = capsys.readouterr().out
        assert "نواة العقل المستقل" in out

    def test_default_command_is_map(self, capsys):
        args = _Args(mind_cmd=None)
        args.mind_cmd = None
        assert handle_mind(args) == EXIT_OK


class TestRun:
    def test_run_happy_path(self, tmp_path, capsys):
        args = _Args(out=str(tmp_path / "proj"))
        assert handle_mind(args) == EXIT_OK
        out = capsys.readouterr().out
        assert "الحلقة مقبولة" in out
        assert "سلسلة الأدلة" in out

    def test_run_json_output(self, tmp_path, capsys):
        args = _Args(out=str(tmp_path / "proj"), json=True)
        assert handle_mind(args) == EXIT_OK
        import json

        data = json.loads(capsys.readouterr().out)
        assert data["schema"] == "zyko.mind/receipt-v1"

    def test_run_pii_rejected_exit_code(self, tmp_path, capsys):
        args = _Args(goal="انشئ مشروع — للتواصل 0501234567", out=str(tmp_path / "pii"))
        assert handle_mind(args) == EXIT_FINDINGS
        out = capsys.readouterr().out
        assert "مرفوضة" in out

    def test_run_dry_run_no_dir(self, tmp_path, capsys):
        args = _Args(out=str(tmp_path / "dry"), dry_run=True)
        assert handle_mind(args) == EXIT_OK
        assert not (tmp_path / "dry").exists()


class TestModuleMain:
    def test_python_m_mind_map(self, capsys):
        assert mind_main(["map"]) == EXIT_OK

    def test_python_m_mind_run(self, tmp_path):
        code = mind_main(["run", "انشئ مشروع قائمة مهام مع واجهة سطر أوامر", "-o", str(tmp_path / "proj")])
        assert code == EXIT_OK


class TestSubprocess:
    def test_cli_entry_z_mind(self, tmp_path):
        """`zyko mind run …` عبر نقطة الدخول الرسمية — بلا شبكة."""
        proc = subprocess.run(
            [sys.executable, "-m", "zyko", "mind", "run", "انشئ مشروع قائمة مهام مع واجهة سطر أوامر",
             "-o", str(tmp_path / "proj")],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == EXIT_OK
        assert "الحلقة مقبولة" in proc.stdout

    def test_python_dash_m_dash_zyko_dot_mind(self, tmp_path):
        proc = subprocess.run(
            [sys.executable, "-m", "zyko.mind", "run", "انشئ مشروع قائمة مهام مع واجهة سطر أوامر",
             "-o", str(tmp_path / "proj")],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == EXIT_OK


class TestTopLevelWiring:
    def test_zyko_mind_help(self):
        from zyko.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["mind", "map"])
        assert args.mind_cmd == "map"
