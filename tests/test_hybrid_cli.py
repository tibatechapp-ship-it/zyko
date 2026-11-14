"""اختبار ربط الواجهة الهجينة بسطر الأوامر (الموجة 27 — التكامل).

العقد: ``--hybrid`` يعمل ملفاً ومجلداً، الخروج JSON حتمي البايتات
(باستثناء أوقات الحائط الممنوعة أصلاً)، والمحرك static الافتراضي.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

VULN = "def handle():\n    name = input('من؟ ')\n    os.system(name)\n"


def _run_cli(*cli_args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "zyko.reviewer", *cli_args],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )
    return proc.returncode, proc.stdout


def test_cli_hybrid_single_file(tmp_path):
    f = tmp_path / "vuln.py"
    f.write_text(VULN, encoding="utf-8")
    code, out = _run_cli("review", "--path", str(f), "--hybrid", "--format", "json")
    report = json.loads(out)
    assert report["schema"] == "zyko.hybrid.report/1"
    assert "هجين" in report["route_ar"]
    assert report["savings"]["findings_routed"] > 0
    assert len(report["report_sha16"]) == 16
    assert code in (0, 1)  # حسب الحد الأدنى الافتراضي 90


def test_cli_hybrid_directory_batch(tmp_path):
    (tmp_path / "a.py").write_text(VULN, encoding="utf-8")
    (tmp_path / "b.py").write_text("X = 1\n", encoding="utf-8")
    code, out = _run_cli("review", "--path", str(tmp_path), "--hybrid", "--format", "json")
    reports = json.loads(out)
    assert isinstance(reports, list)
    assert len(reports) == 2
    routes = " | ".join(r["route_ar"] for r in reports)
    assert "ثابت خالص" in routes  # الملف النظيف بقي ثابتاً


def test_cli_hybrid_engine_none_documented():
    f = REPO / "src" / "zyko" / "version.py"
    code, out = _run_cli("review", "--path", str(f), "--hybrid", "--engine", "none", "--format", "json")
    report = json.loads(out)
    assert "المحرك غير مهيأ" in report["route_ar"] or "ثابت خالص" in report["route_ar"]
    assert report["savings"]["findings_routed"] == 0
