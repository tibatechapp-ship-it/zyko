"""اختبارات سجل أهداف النشر (الموجة 23) — الجاهزية تُقاس من الشجرة لا تُدَّعى."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zyko.cli import main
from zyko.platform.deploy import (
    DEPLOY_TARGETS,
    DeployTarget,
    deployment_report,
    format_report_lines,
    repo_root,
    target_readiness,
)


def test_registry_has_the_four_targets():
    """GitHub + Hugging Face + Vercel + Lobe — الأهداف الأربعة موثّقة لا مستنتَجة."""
    keys = [t.key for t in DEPLOY_TARGETS]
    assert keys == ["github", "huggingface", "vercel", "lobe"]
    assert len({t.key for t in DEPLOY_TARGETS}) == len(DEPLOY_TARGETS)
    for t in DEPLOY_TARGETS:
        assert isinstance(t, DeployTarget)
        assert t.required_assets, "كل هدف يحتاج أصولاً معلنة"
        assert t.summary_ar.strip(), "الوصف العربي إلزامي"


def test_report_on_real_repo_all_ready():
    """في شجرة التطوير الحقيقية الأربعة مكتملة — الأصول تُقاس من القرص."""
    report = deployment_report()
    assert report["measured"] is True
    assert report["root"] is not None
    assert report["ready_count"] == report["total"]
    assert report["all_ready"] is True
    for t in report["targets"]:
        assert t["ready"] is True, f"{t['key']} ناقص: {t['missing_assets']}"
        assert t["missing_assets"] == []


def test_report_lists_missing_assets_honestly(tmp_path: Path):
    """جذر فارغ: الأصول المفقودة تُذكر بالاسم — لا خفاء ولا ادعاء."""
    root = tmp_path / "repo"
    (root / "src" / "zyko").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "zyko"\n', encoding="utf-8")
    report = deployment_report(root=root)
    assert report["measured"] is True
    assert report["all_ready"] is False
    by_key = {t["key"]: t for t in report["targets"]}
    assert ".github/workflows/ci.yml" in by_key["github"]["missing_assets"]
    assert "deploy/huggingface/Dockerfile" in by_key["huggingface"]["missing_assets"]
    assert "deploy/vercel/api/zyko.py" in by_key["vercel"]["missing_assets"]
    assert "deploy/lobe/manifest.json" in by_key["lobe"]["missing_assets"]
    assert all(t["ready"] is False for t in report["targets"])


def test_repo_root_finds_tree(tmp_path: Path):
    """الجذر يُكتشف بالمشية للأعلى حتى العلامة، ويرجع None بلا شجرة."""
    root = tmp_path / "repo"
    (root / "src" / "zyko").mkdir(parents=True)
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    assert repo_root(root / "src" / "zyko") == root.resolve()
    assert repo_root(tmp_path / "empty") is None


def test_format_lines_name_gaps():
    """الأسطر المطبوعة: OK للكامل، واسم الفاقد للناقص — بلا ادعاء."""
    report = {
        "measured": True,
        "targets": [
            target_readiness(DEPLOY_TARGETS[0], root=repo_root()),
            {
                "key": "fake",
                "title": "Fake",
                "missing_assets": ["deploy/fake/asset.txt"],
                "guide": "docs/PLATFORMS.md#fake",
                "ready": False,
                "summary_ar": "",
                "required_assets": [],
                "env_vars": [],
                "measured": True,
            },
        ],
    }
    lines = format_report_lines(report)
    assert any(line.startswith("  OK  github") for line in lines)
    assert any("deploy/fake/asset.txt" in line and "fake" in line for line in lines)


def test_format_lines_installed_copy():
    """نسخة مثبَّتة بلا شجرة مصدر: سطر واحد صادق بلا OK زور."""
    lines = format_report_lines({"measured": False, "targets": []})
    assert len(lines) == 1
    assert "نسخة مثبَّتة" in lines[0]


def test_doctor_prints_deployment_targets(capsys: pytest.CaptureFixture[str]):
    """``zyko doctor`` يطبع قسم أهداف النشر من السجل نفسه."""
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "Deployment targets" in out
    assert "github" in out and "vercel" in out
    # الأهداف الأربعة تظهر — شجرة التطوير كاملة الأصول
    assert out.count("  OK  ") >= 4


def test_required_assets_are_declared_json_round_trippable(tmp_path: Path):
    """السجل ينسكب JSON بلا فقد — عقد البيانات للمستهلكين الخارجيين."""
    report = deployment_report()
    dumped = json.dumps(report, ensure_ascii=False)
    loaded = json.loads(dumped)
    assert loaded["total"] == 4
