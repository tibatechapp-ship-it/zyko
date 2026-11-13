"""اختبارات التوسع الواسع (الموجة 19) — من 6 حالات إلى 44 على الأب المباشر للمقياس.

الفجوة الثانية الموثقة (``docs/EVAL_2026-11-12.md`` §7.1): «التوسع من 6
حالات إلى عينات أوسع هو الجولة القادمة». هذه الاختبارات تحكم ثلاث حقائق:
ملف البيانات الواسع حقيقي موثق بلا رقعة ذهبية، والمتسابق يجمع البروتوكول
في وثيقة حتمية بالبايت، والاستكمال يكمل حيث توقف لا يعيد ما تم.

كلها بلا شبكة: ``Runner`` وهمي أو git حقيقي على مستودع مصغّر محلي.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

from zyko.benchmarks.runner import (
    assemble_doc,
    atomic_write_json,
    chain_hash_of,
    prep_commands_for_instance,
    prepare_worktree,
    remove_worktree,
    resume_plan,
)
from zyko.benchmarks.swebench import load_instances

LITE = Path(__file__).resolve().parents[1] / "benchmarks" / "data" / "swe_bench_lite_requests.json"
FULL = Path(__file__).resolve().parents[1] / "benchmarks" / "data" / "swe_bench_full_requests.json"
RUNNER_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_swebench_lite.py"


# --------------------------------------------------------------- البيانات
def test_wide_file_has_44_instances_sorted():
    """الوثيقة الواسع 44 حالة — مرتبة بالمعرّف حتمياً."""
    instances = load_instances(FULL)
    ids = [i.instance_id for i in instances]
    assert len(instances) == 44
    assert ids == sorted(ids)


def test_wide_file_provenance_and_no_gold_patch():
    """الإثبات: المصدر الأب المباشر، الرقعة الذهبية مستبعدة عمداً — نصاً وبنيوياً."""
    raw = json.loads(FULL.read_text(encoding="utf-8"))
    assert raw["source"].startswith("princeton-nlp/SWE-bench")
    assert "SWE-bench_Lite" not in raw["source"]
    assert raw["repo_filter"] == "psf/requests"
    assert raw["gold_patch_excluded"].strip()
    for item in raw["instances"]:
        assert "patch" not in item, "الرقعة الذهبية تسربت إلى ملف البيانات!"
        assert item["problem_statement"].strip()
        assert item["test_patch"].strip()


def test_wide_file_all_instances_requests_repo():
    instances = load_instances(FULL)
    assert all(i.repo == "psf/requests" for i in instances)
    assert all(len(i.base_commit) == 40 for i in instances)


def test_lite_six_are_subset_of_full_forty_four():
    """العائلة واحدة: حالات الجولة 8 الست كلها داخل التوسع الواسع — المقارنة عادلة."""
    lite_ids = {i.instance_id for i in load_instances(LITE)}
    full_ids = {i.instance_id for i in load_instances(FULL)}
    assert lite_ids <= full_ids
    assert len(full_ids - lite_ids) == 38


def test_wide_instances_have_non_empty_contracts():
    instances = load_instances(FULL)
    for inst in instances:
        assert inst.fail_to_pass, f"{inst.instance_id}: FAIL_TO_PASS فارغ"
        assert inst.pass_to_pass == tuple(sorted(inst.pass_to_pass))
        assert inst.fail_to_pass == tuple(sorted(inst.fail_to_pass))


def test_wide_versions_span_documented_range():
    """التوسع يمتد عبر تاريخ المستودع: 0.13 حتى 2.27 — عمق حقيقي لا نسخ لجيران."""
    instances = load_instances(FULL)
    versions = {i.version for i in instances}
    assert "0.13" in versions and "2.27" in versions
    assert len(versions) >= 15


# --------------------------------------------------------------- المتسابق
def test_prep_commands_declared_not_hidden(tmp_path):
    """أوامر التحضير معلنة بالوثيقة — لا سقف خفي ولا عادة مضمنة."""
    cmds = prep_commands_for_instance(tmp_path)
    assert cmds["worktree"][0][:5] == ["git", "worktree", "add", "--detach", "{workdir}"]
    assert "{base_commit}" in cmds["worktree"][0]
    assert any("uv" == c[0] for c in cmds["venv"])
    joined = " ".join(c for c in cmds["venv"][1])
    assert "pytest" in joined and "pytest-timeout" in joined and "httpbin" in joined


def test_prepare_worktree_real_git_mini_repo(tmp_path):
    """شجرة عمل حقيقية على مستودع مصغّر — الإيثاق مرجعي ورقعة الاختبارات تُطبَّق."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args, cwd=repo):
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@zyko.local")
    git("config", "user.name", "zyko")
    (repo / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "test_src.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "seed")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    workdir = tmp_path / "wt"
    ok, reason = prepare_worktree(repo, head, workdir, "", subprocess.run)
    assert ok, reason
    assert (workdir / "src.py").read_text(encoding="utf-8") == "VALUE = 1\n"

    patch = (
        "--- a/test_src.py\n+++ b/test_src.py\n"
        "@@ -1,2 +1,3 @@\n def test_ok():\n     assert True\n+def test_two():\n+    assert 1 == 1\n"
    )
    ok, reason = prepare_worktree(repo, head, workdir, patch, subprocess.run)
    assert ok, reason
    assert "test_two" in (workdir / "test_src.py").read_text(encoding="utf-8")
    remove_worktree(repo, workdir, subprocess.run)
    assert not workdir.exists()


def test_prepare_worktree_bad_commit_fails_arabic(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    ok, reason = prepare_worktree(repo, "f" * 40, tmp_path / "wt", "", subprocess.run)
    assert not ok
    assert "فشل" in reason or "شجرة" in reason


def _sample_result(resolved: bool) -> dict:
    verdict = {
        "instance_id": "psf__requests-0000",
        "patch_applied": resolved,
        "apply_error_ar": None,
        "patch_sha16": "a" * 16,
        "contract_reason_ar": "مسموح",
        "f2p_failed_at_base": ["n1"],
        "p2p_failed_at_base": [],
        "f2p_passed_after": ["n1"] if resolved else [],
        "f2p_failed_after": [],
        "p2p_failed_after": [],
        "runs_error_ar": None,
        "resolved_strict": resolved,
        "resolved_env": resolved,
        "f2p_repaired_count": 1 if resolved else 0,
        "attempts_note_ar": "طُبِّقت وقِيست",
    }
    attempt = {
        "index": 1,
        "feedback_sha16": "",
        "file_choice": "src.py",
        "patch_sha16": "a" * 16,
        "accepted": True,
        "contract_reason_ar": "مسموح",
        "applied": resolved,
        "apply_error_ar": None,
        "stop_reason_ar": "انصراف — حلّ" if resolved else "متابعة",
    }
    return {
        "instance_id": "psf__requests-0000",
        "prep_error_ar": None,
        "base": {"f2p_failed_at_base": ["n1"], "p2p_failed_at_base": []},
        "loop": {"instance_id": "psf__requests-0000", "attempts": [attempt], "verdict": verdict},
    }


def test_assemble_doc_deterministic_no_times():
    """الوثيقة حتمية بالبايت: نفس المدخلات نفس المحارف — والأزمنة غائبة بالبناء."""
    r = _sample_result(True)
    doc1 = assemble_doc(
        protocol="p",
        data={"source": "x.json", "instances_sha16": "b" * 16},
        model_label="glm-4.7",
        model_served_by="bridge",
        httpbin="http://127.0.0.1:8642/",
        python_env="3.9 (uv)",
        loop={"max_attempts": 3, "max_files": 3},
        results=[r],
        planned_total=44,
    )
    doc2 = assemble_doc(
        protocol="p",
        data={"source": "x.json", "instances_sha16": "b" * 16},
        model_label="glm-4.7",
        model_served_by="bridge",
        httpbin="http://127.0.0.1:8642/",
        python_env="3.9 (uv)",
        loop={"max_attempts": 3, "max_files": 3},
        results=[r],
        planned_total=44,
    )
    assert doc1 == doc2
    text = json.dumps(doc1)
    for forbidden in ("created_at", "timestamp", "now", "datetime"):
        assert forbidden not in text
    assert doc1["aggregate"]["planned_total"] == 44
    assert doc1["aggregate"]["total"] == 1
    assert doc1["aggregate"]["resolved_env"] == 1


def test_chain_hash_changes_with_content():
    r = _sample_result(True)
    doc1 = assemble_doc(
        protocol="p",
        data={"s": "1"},
        model_label="m",
        model_served_by="b",
        httpbin="h",
        python_env="3.9",
        loop={"x": 1},
        results=[r],
        planned_total=44,
    )
    r2 = _sample_result(False)
    r2["instance_id"] = "psf__requests-9999"
    doc2 = assemble_doc(
        protocol="p",
        data={"s": "1"},
        model_label="m",
        model_served_by="b",
        httpbin="h",
        python_env="3.9",
        loop={"x": 1},
        results=[r, r2],
        planned_total=44,
    )
    assert doc1["chain_hash"] != doc2["chain_hash"]


def test_atomic_write_and_resume(tmp_path):
    """الكتابة الذرية والاستكمال: ``--resume`` يعرف المكتمل ويرفض إعادة تشغيله."""
    out = tmp_path / "doc.json"
    doc = assemble_doc(
        protocol="p",
        data={"s": "1"},
        model_label="m",
        model_served_by="b",
        httpbin="h",
        python_env="3.9",
        loop={"x": 1},
        results=[_sample_result(True)],
        planned_total=44,
    )
    atomic_write_json(out, doc)
    assert json.loads(out.read_text(encoding="utf-8"))["chain_hash"] == chain_hash_of(doc)

    instances = load_instances(FULL)[:3]
    remaining = resume_plan(instances, out)
    assert len(remaining) == 3  # الوثيقة لا تعرف هذه المعرفات بعد

    doc2 = assemble_doc(
        protocol="p",
        data={"s": "1"},
        model_label="m",
        model_served_by="b",
        httpbin="h",
        python_env="3.9",
        loop={"x": 1},
        results=[dict(_sample_result(True), instance_id=instances[0].instance_id)],
        planned_total=44,
    )
    atomic_write_json(out, doc2)
    remaining = resume_plan(instances, out)
    assert [i.instance_id for i in remaining] == [i.instance_id for i in instances[1:]]


def test_resume_missing_doc_returns_all(tmp_path):
    instances = load_instances(FULL)[:2]
    assert resume_plan(instances, tmp_path / "absent.json") == instances


def test_runner_script_exists_and_is_thin_wrapper():
    """الغلاف الموصى به في PROTOCOL حقيقي متعقّب — ثغرة القابلية للإعادة سدّت."""
    assert RUNNER_SCRIPT.is_file()
    source = RUNNER_SCRIPT.read_text(encoding="utf-8")
    assert "from zyko.benchmarks.runner import main" in source


def test_runner_module_help():
    spec = importlib.util.find_spec("zyko.benchmarks.runner")
    assert spec is not None
    proc = subprocess.run(
        ["python3", "-m", "zyko.benchmarks.runner", "--help"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert proc.returncode == 0
    assert "--data" in proc.stdout and "--out" in proc.stdout


def test_runner_requires_out(tmp_path):
    proc = subprocess.run(
        ["python3", "-m", "zyko.benchmarks.runner", "--data", str(FULL)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert proc.returncode != 0
    assert "--out" in (proc.stderr + proc.stdout)


def test_runner_base_only_offline_deterministic(tmp_path):
    """قياس الأساس بلا ذكاء مقصود ومعلن — المسار كامل بلا شبكة: مستودع مصغّر
    بلا الإيثاق المطلوب ⇒ فشل تحضير عربي موثق في الوثيقة لا انهيار."""
    repo = tmp_path / "mini-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    proc = subprocess.run(
        [
            "python3",
            "-m",
            "zyko.benchmarks.runner",
            "--data",
            str(FULL),
            "--out",
            str(tmp_path / "o.json"),
            "--base-only",
            "--ids",
            "psf__requests-1142",
            "--repo",
            str(repo),
            "--state-dir",
            str(tmp_path / "st"),
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-400:]
    doc = json.loads((tmp_path / "o.json").read_text(encoding="utf-8"))
    assert doc["aggregate"]["planned_total"] == 44
    assert doc["aggregate"]["total"] == 1
    record = doc["results"][0]
    assert record["instance_id"] == "psf__requests-1142"
    assert record["prep_error_ar"], "فشل الإيثاق يجب أن يوثَّق عربياً لا يختفي"
    assert record["loop"]["attempts"] == []
