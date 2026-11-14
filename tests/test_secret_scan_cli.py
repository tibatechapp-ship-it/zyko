# -*- coding: utf-8 -*-
"""اختبارات بوابة الأسرار على سطر الأوامر — الحزمة 0.5 في دورة النشر.

العقد: النمط الواحد من ``zyko.utils.secret_scan``، الإثبات بالبصمة لا
بالقيمة، الخروج 1 عند الحرجة وحدها، ووضعيا ``--tree`` و``--diff`` حرفياً
كما يستدعيهما ``scripts/publish-release-cycle.sh``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "secret_scan.py"


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=cwd, check=False
    )


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _init_repo(tmp_path):
    _git("init", "-q", cwd=tmp_path)
    _git("config", "user.email", "t@t", cwd=tmp_path)
    _git("config", "user.name", "t", cwd=tmp_path)


def test_tree_clean_exits_zero(tmp_path):
    (tmp_path / "ok.py").write_text("value = 1\n", encoding="utf-8")
    p = _run("--tree", str(tmp_path))
    assert p.returncode == 0
    payload = json.loads(p.stdout)
    assert payload["hit_count"] == 0 and payload["files_scanned"] == 1
    assert payload["schema"] == "zyko.secret_scan_cli/1"


def test_tree_token_exits_one_without_leaking_value(tmp_path):
    fake36 = "A" * 36  # عينة مبنية برمجياً — اتفاقية لا قيمة حية في المصدر
    (tmp_path / "bad.py").write_text(f"token = 'ghp_{fake36}'\n", encoding="utf-8")
    p = _run("--tree", str(tmp_path))
    assert p.returncode == 1
    payload = json.loads(p.stdout)
    assert payload["hit_count"] == 1
    assert payload["hits"][0]["name"] == "github-token"
    assert payload["hits"][0]["severity"] == "critical"
    assert fake36 not in p.stdout and "ghp_" not in p.stdout  # الإثبات بالبصمة لا بالقيمة


def test_tree_exempt_marker_line_passes(tmp_path):
    fake36 = "A" * 36
    (tmp_path / "doc.py").write_text(
        f"token = 'ghp_{fake36}'  # zyko:secret-ok عينة موثقة\n", encoding="utf-8"
    )
    p = _run("--tree", str(tmp_path))
    assert p.returncode == 0
    assert json.loads(p.stdout)["hit_count"] == 0


def test_diff_range_clean_exits_zero(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "clean.py").write_text("value = 1\n", encoding="utf-8")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-q", "-m", "base", cwd=tmp_path)
    (tmp_path / "clean.py").write_text("value = 2\n", encoding="utf-8")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-q", "-m", "bump", cwd=tmp_path)
    p = _run("--diff", "HEAD~1..HEAD", cwd=tmp_path)
    assert p.returncode == 0
    payload = json.loads(p.stdout)
    assert payload["added_count"] == 1 and payload["hit_count"] == 0


def test_diff_range_token_commit_blocked(tmp_path):
    fake36 = "A" * 36
    _init_repo(tmp_path)
    (tmp_path / "clean.py").write_text("value = 1\n", encoding="utf-8")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-q", "-m", "base", cwd=tmp_path)
    (tmp_path / "leak.py").write_text(f"token = 'ghp_{fake36}'\n", encoding="utf-8")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-q", "-m", "leak", cwd=tmp_path)
    p = _run("--diff", "HEAD~1..HEAD", cwd=tmp_path)
    assert p.returncode == 1
    payload = json.loads(p.stdout)
    assert payload["hit_count"] == 1
    # السر المحذوف لا يظهر — الأسطر المحذوفة ليست جريمة والعقد موثق
    assert "value = 1" not in p.stdout


def test_diff_toplevel_resolution_from_subdir(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "clean.py").write_text("value = 1\n", encoding="utf-8")
    _git("add", ".", cwd=tmp_path)
    _git("commit", "-q", "-m", "base", cwd=tmp_path)
    sub = tmp_path / "sub"
    sub.mkdir()
    p = _run("--diff", "HEAD", cwd=sub)  # من داخل مجلد فرعي — الجذر يُحسم بـ rev-parse
    assert p.returncode == 0
    assert json.loads(p.stdout)["added_count"] == 0
