"""zyko.benchmarks.runner — متسابق البروتوكول العام: التوسع من 6 حالات إلى 44 (الموجة 19).

الفجوة الثانية الموثقة (``docs/EVAL_2026-11-12.md`` §7.1): «التوسع من 6 حالات
إلى عينات أوسع هو الجولة القادمة». القياس أثبت أن Lite لا يضم غير ست حالات
من ``psf/requests`` — فالتوسع الصادق إلى الأب المباشر للمقياس
``princeton-nlp/SWE-bench`` الكامل بنفس المرشح: **44 حالة** بدل 6، نفس
العائلة ونفس المستودع ونفس بروتوكول البيئة، والرقعة الذهبية مستبعدة عمداً.

المتسابق يجمع بروتوكول الجولات 8→11 في أمر واحد قابل لإعادة التشغيل:

1. **بيئة لكل حالة**: شجرة عمل معزولة على الإيثاق الأساس (``git worktree``
   — نفس الكائنات لا نسخ) + رقعة الاختبارات (``test_patch``) + بيئة
   بايثون 3.9 معزولة (``uv venv`` لكل حالة: pytest وpytest-timeout و
   httpbin وgunicorn) + httpbin محلي معلن عبر ``HTTPBIN_URL``.
2. **قياس أساس** قبل أي ذكاء: عقد FAIL_TO_PASS وPASS_TO_PASS على
   البيئة نفسها — ما يفشل عند الأساس يوثَّق كما هو.
3. **حلقة الإصلاح** (بروتوكول الجولة 9 والخريطة الدلالية للجولة 11):
   اقتراح ← بوابات PII ثم RTL ثم حرس الرقعة ← تطبيق ← قياس ← تلقيم
   الفشل، بميزانية معلنة، والخريطة الدلالية ملحقة بطلب الاختيار.
4. **وثيقة حتمية بالبايت**: البروتوكول والنموذج بلصقه المعلن والبيئة
   والخلاصة وكل حالة مفصلة، وسلسلة ``sha256`` — الأزمنة خارج السلاسل
   دائمًا، والكتابة ذرية (``tmp`` ثم ``replace``) فالانقطاع لا يفسد
   الوثيقة و``--resume`` يكمل حيث توقف.

الشبكة هنا حقن لا سحر: المستودع يُستنسخ إن لم يوجد، والنموذج يُدعى عبر
``SWEBrain`` (نقطة متوافقة مع OpenAI من البيئة لا من الكود)، وكل فشل
تحضير يوثَّق بحالته العربية — لا حالة تختفي ولا فشل يُجمَّل.

    python -m zyko.benchmarks.runner --data benchmarks/data/swe_bench_full_requests.json \\
        --out benchmarks/results/swebench_full_wide_<تاريخ>.json
    # أو عبر الغلاف الموصى به في docs/PROTOCOL.md:
    python3 scripts/run_swebench_lite.py --out <وثيقة>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from zyko.ai.brains import GatedBrain
from zyko.benchmarks.repair_loop import (
    MAX_ATTEMPTS_DEFAULT,
    MAX_FILES_DEFAULT,
    RepairLoop,
)
from zyko.benchmarks.selection import DEFAULT_GOLD_PATHS, load_gold_paths, selection_accuracy
from zyko.benchmarks.swebench import (
    SWEBrain,
    SWEInstance,
    evaluate_instance,
    load_instances,
)
from zyko.reviewer.repo_map import build_repo_map

__all__ = [
    "DEFAULT_DATA",
    "DEFAULT_HTTPBIN_URL",
    "PYTHON_VERSION",
    "VENV_PACKAGES",
    "TEST_TIMEOUT_S",
    "assemble_doc",
    "atomic_write_json",
    "chain_hash_of",
    "main",
    "prep_commands_for_instance",
    "resume_plan",
]

Runner = Callable[..., Any]

# --------------------------------------------------------------- العقد
DEFAULT_DATA = Path("benchmarks/data/swe_bench_full_requests.json")
DEFAULT_HTTPBIN_URL = "http://127.0.0.1:8642/"
PYTHON_VERSION = "3.9"  # بروتوكول الجولة 8 نفسه — لا ترفيح بيئي
VENV_PACKAGES = ("pytest", "pytest-timeout", "httpbin", "gunicorn")
TEST_TIMEOUT_S = 25  # مهلة الاختبار الواحد عبر pytest-timeout — معلنة لا خفية
HTTPBIN_PORT = 8642


def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


# --------------------------------------------------------------- التحضير
def prep_commands_for_instance(state_dir: Path) -> dict[str, list[list[str]]]:
    """أوامر التحضير لكل حالة — معلنة في الوثيقة لا مضمنة في العادة.

    الترتيب ثابت: شجرة العمل على الإيثاق، رقعة الاختبارات، بيئة 3.9،
    تثبيت عدّة القياس. httpbin خدمة عامة واحدة تُدعى ولا تُبنى لكل حالة.
    """
    venvs = state_dir / "venvs"
    return {
        "worktree": [
            ["git", "worktree", "add", "--detach", "{workdir}", "{base_commit}"],
        ],
        "test_patch": [
            ["git", "apply", "--whitespace=nowarn", "-"],
        ],
        "venv": [
            ["uv", "venv", "--python", PYTHON_VERSION, "{venv_dir}"],
            ["uv", "pip", "install", "--python", "{venv_python}", *VENV_PACKAGES],
        ],
        "paths": {
            "venv_dir": str(venvs / "{instance_id}"),
            "venv_python": str(venvs / "{instance_id}" / "bin" / "python"),
        },
    }


def prepare_worktree(
    repo_path: Path,
    base_commit: str,
    workdir: Path,
    test_patch: str,
    runner: Runner,
) -> tuple[bool, str]:
    """شجرة عمل معزولة على الإيثاق الأساس + رقعة الاختبارات — فشل عربي مفصل.

    ``git worktree add --detach`` يشارك الكائنات لا ينسخها، والإيثاق
    مطلق بالهاش فلا رأي للفروع. رقعة الاختبارات جزء من الحالة (لا هي
    الرقعة الذهبية) وتُطبَّق كما في بروتوكول المقياس. سجل شجرة قديمة
    (من تشغيل قُطع) يُنظَّف قبل البناء: remove ثم prune — لا تسجيل
    زومبي يسكت الإضافة الجديدة. تفاصيل الخطأ من آخر أسطر git لا أولها:
    git يطبع تقدمه في الأولى والخطأ الحقيقي في الأخيرة.
    """
    runner(
        ["git", "-C", str(repo_path), "worktree", "remove", "--force", str(workdir)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    runner(
        ["git", "-C", str(repo_path), "worktree", "prune"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    proc = runner(
        [
            "git",
            "-C",
            str(repo_path),
            "worktree",
            "add",
            "--detach",
            str(workdir),
            base_commit,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if getattr(proc, "returncode", 1) != 0:
        detail = (getattr(proc, "stderr", "") or "").strip().splitlines()
        reason = detail[-1][:200] if detail else "git worktree رفض الإيثاق"
        return False, f"فشل تحضير شجرة العمل: {reason}"
    if test_patch.strip():
        patch = test_patch if test_patch.endswith("\n") else test_patch + "\n"
        proc = runner(
            ["git", "apply", "--whitespace=nowarn", "-"],
            cwd=str(workdir),
            input=patch,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if getattr(proc, "returncode", 1) != 0:
            detail = (getattr(proc, "stderr", "") or "").strip().splitlines()
            reason = detail[-1][:200] if detail else "رقعة الاختبارات رفضت"
            return False, f"فشل تطبيق رقعة الاختبارات: {reason}"
    return True, "جاهزة"


def build_venv(venv_dir: Path, runner: Runner) -> tuple[bool, str]:
    """بيئة 3.9 معزولة لكل حالة عبر uv — عدّة القياس معلنة.

    بيئة قديمة من تشغيل سابق تُزال قبل البناء — العزلة تعني بداية نظيفة
    كل مرة لا إعادة استخدام صامتة. تفاصيل الخطأ من آخر أسطر uv لا أولها:
    uv يطبع مقدماته في الأولى والخطأ الحقيقي في الأخيرة.
    """
    if venv_dir.exists():
        shutil.rmtree(venv_dir, ignore_errors=True)
    proc = runner(
        ["uv", "venv", "--python", PYTHON_VERSION, str(venv_dir)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if getattr(proc, "returncode", 1) != 0:
        detail = (getattr(proc, "stderr", "") or "").strip().splitlines()
        reason = detail[-1][:200] if detail else "uv venv رفض"
        return False, f"فشل بناء البيئة المعزولة: {reason}"
    proc = runner(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(venv_dir / "bin" / "python"),
            *VENV_PACKAGES,
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if getattr(proc, "returncode", 1) != 0:
        detail = (getattr(proc, "stderr", "") or "").strip().splitlines()
        reason = detail[-1][:200] if detail else "uv pip رفض التثبيت"
        return False, f"فشل تثبيت عدّة القياس: {reason}"
    return True, "بيئة جاهزة"


def remove_worktree(repo_path: Path, workdir: Path, runner: Runner) -> None:
    """تفكيك شجرة العمل — التنظيف لا يُخطئ الصمت."""
    runner(
        ["git", "-C", str(repo_path), "worktree", "remove", "--force", str(workdir)],
        capture_output=True,
        text=True,
        timeout=60,
    )


# --------------------------------------------------------------- الخلاصة
def aggregate_loop_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """خلاصة التشغيل الواسع — جمع صريح من حقول الإيصالات لا تقدير.

    ``planned_total`` يحفظ الهدف المعلن (حالات ملف البيانات) و``total``
    ما اكتمل فعلاً — الفرق موثق لا مطموس، فالتشغيل المقطوع صادق أيضاً.
    """
    total = len(results)
    # سجلات فشل التحضير (verdict=None) تُحتسب في total وbase_only_count فقط
    # — الصدق: الفشل موجود في الخلاصة بعدد الحالات لا بمحوها
    verdicts = [r["loop"]["verdict"] for r in results if r["loop"]["verdict"] is not None]
    resolved_strict = sum(1 for v in verdicts if v["resolved_strict"])
    resolved_env = sum(1 for v in verdicts if v["resolved_env"])
    f2p_repaired_total = sum(v["f2p_repaired_count"] for v in verdicts)
    f2p_total = sum(
        len(set(v["f2p_failed_at_base"]) | set(v["f2p_failed_after"]) | set(v["f2p_passed_after"]))
        for v in verdicts
    )
    applied_count = sum(1 for v in verdicts if v["patch_applied"])
    # الموجة 20: حرس التراجع والسلّم المتسامح يُحتسبان من الإيصالات — لا صمت
    reverted_count = sum(
        1 for r in results for a in r["loop"]["attempts"] if a.get("reverted", False)
    )
    partial_applies = sum(
        1
        for r in results
        for a in r["loop"]["attempts"]
        if a["applied"] and a.get("apply_mode", "") not in ("", "كاملة")
    )
    contract_rejections = sum(
        1
        for r in results
        for a in r["loop"]["attempts"]
        if a["contract_reason_ar"] not in ("", "مسموح") and not a["applied"]
    )
    gate_rejections = sum(1 for r in results for a in r["loop"]["attempts"] if not a["accepted"])
    base_only = sum(1 for r in results if not r["loop"]["attempts"])
    return {
        "planned_total": None,  # يُملأ من المتسابق بعدد ملف البيانات
        "total": total,
        "resolved_strict": resolved_strict,
        "resolved_env": resolved_env,
        "f2p_repaired_total": f2p_repaired_total,
        "f2p_total": f2p_total,
        "applied_count": applied_count,
        "contract_rejections": contract_rejections,
        "gate_rejections": gate_rejections,
        "reverted_count": reverted_count,
        "partial_applies": partial_applies,
        "base_only_count": base_only,
        "resolve_rate_env": round(resolved_env / total, 4) if total else 0.0,
    }


def chain_hash_of(doc: dict[str, Any]) -> str:
    """بصمة الوثيقة كاملة — الوثيقة نفسها بلا بصمة عند التدقيق."""
    payload = {k: v for k, v in doc.items() if k != "chain_hash"}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def assemble_doc(
    *,
    protocol: str,
    data: dict[str, Any],
    model_label: str,
    model_served_by: str,
    httpbin: str,
    python_env: str,
    loop: dict[str, Any],
    results: list[dict[str, Any]],
    planned_total: int,
) -> dict[str, Any]:
    """اجمع وثيقة النتائج — بلا أزمنة بالبناء نفسه."""
    aggregate = aggregate_loop_results(results)
    aggregate["planned_total"] = planned_total
    doc: dict[str, Any] = {
        "protocol": protocol,
        "data": data,
        "model_label": model_label,
        "model_served_by": model_served_by,
        "httpbin": httpbin,
        "python_env": python_env,
        "loop": loop,
        "aggregate": aggregate,
        "results": results,
    }
    doc["chain_hash"] = chain_hash_of(doc)
    return doc


def atomic_write_json(path: Path, doc: dict[str, Any]) -> None:
    """كتابة ذرية — ``tmp`` ثم ``replace`` فالانقطاع لا يترك نصف وثيقة."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _case_completed(record: dict) -> bool:
    """تعريف المكتمل بعقد التنفّس: حالة تُعدّ مكتملة إن طُبِّقت رقعة منها فعلاً.

    سجل بلا رقعة مطبَّقة (اقتراح فارغ خانق، أو رقع رفضها الحرس/الجرّاح قبل
    التطبيق) = منصرف جزئي — يستحق إعادة جدولة عند ``--retry-incomplete``.
    """
    attempts = (record.get("loop") or {}).get("attempts") or []
    return any(bool(a.get("applied")) for a in attempts)


def merge_result(
    results: list[dict[str, Any]], record: dict[str, Any]
) -> tuple[list[dict[str, Any]], int]:
    """دمج سجل حالة في الوثيقة — الاستبدال لا التضاعف (عقد التنفّس، الموجة 23).

    إعادة جدولة منصرف خانق ثم كتابته append كانت ستضاعف السجل ويُعدّه
    التجميع مرتين؛ العقد: وثيقة واحدة لكل حالة — القياس الأحدث يستبدل
    السابق، وعدد الاستبدالات معلن في الوثيقة (``loop.retried_records``).
    يعيد (القائمة الجديدة، عدد السجلات السابقة المستبدلة).
    """
    iid = record.get("instance_id")
    replaced = sum(1 for r in results if r.get("instance_id") == iid)
    merged = [r for r in results if r.get("instance_id") != iid]
    merged.append(record)
    return merged, replaced


def resume_plan(
    instances: tuple[SWEInstance, ...],
    out_path: Path,
    retry_incomplete: bool = False,
) -> tuple[SWEInstance, ...]:
    """خطة الاستكمال: الحالات غير المكتملة فقط — ``--resume`` يكمل حيث توقف.

    مكتمل (الافتراضي) = أي سجل في الوثيقة — سلوك الموجتين 19–22 المحافظ.
    بـ``--retry-incomplete`` (عقد التنفّس، الموجة 23): المكتمل = حالة طُبِّقت
    رقعة منها فعلاً — المنصرف الخانق ورفض ما قبل التطبيق يُعاد جدولته عند
    التعافي، كما يقتضي «بروتوكول التشغيل الثاني المتنفّس» في وثيقة الموجة 22.
    """
    if not out_path.exists():
        return instances
    try:
        doc = json.loads(out_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return instances
    records = doc.get("results", [])
    if not retry_incomplete:
        done = {r["instance_id"] for r in records}
    else:
        done = {r["instance_id"] for r in records if _case_completed(r)}
    remaining = tuple(i for i in instances if i.instance_id not in done)
    replanned = len(records) - len(done)
    print(
        f"الاستكمال: {len(done)} مكتملة — المتبقي {len(remaining)} من {len(instances)}"
        + (
            f" — أعيد جدولتها {replanned} منصرفة/غير مطبَّقة (عقد التنفّس)" if retry_incomplete else ""
        ),
        file=sys.stderr,
    )
    return remaining


# --------------------------------------------------------------- المتسابق
@dataclass(frozen=True)
class RunnerConfig:
    """إعدادات التشغيل المعلنة — كل سقف في الوثيقة لا في العادة."""

    data_path: Path
    out_path: Path
    repo_path: Path
    state_dir: Path
    protocol_version: str  # "v1" محاولة واحدة أو "v2" حلقة تلقيم الفشل
    max_attempts: int
    max_files: int
    base_only: bool
    httpbin_url: str
    model_label: str
    host_env: str
    key_env: str
    ids_filter: tuple[str, ...]


def _ensure_repo(repo_path: Path) -> Path:
    """استنساخ المستودع إن لم يوجد — مرة واحدة، ثم كل الإيثاقات محلية."""
    if (repo_path / ".git").exists():
        return repo_path
    repo_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"استنساخ psf/requests إلى {repo_path} …", file=sys.stderr)
    subprocess.run(  # nosec B603 B607 — أمر ثابت من بروتوكول المختبر: git clone بمسار معلن لا مدخل عدواني
        ["git", "clone", "https://github.com/psf/requests.git", str(repo_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=900,
    )
    return repo_path


def _run_instance(
    instance: SWEInstance,
    repo_path: Path,
    state_dir: Path,
    cfg: RunnerConfig,
    *,
    choice_brain: Any,
    diff_brain: Any,
) -> dict[str, Any]:
    """حالة واحدة من التحضير إلى الإيصال — كل فشل موثق بحالته العربية."""
    workdir = state_dir / "worktrees" / instance.instance_id
    venv_dir = state_dir / "venvs" / instance.instance_id
    record: dict[str, Any] = {"instance_id": instance.instance_id}
    prep_error: str | None = None

    ok, reason = prepare_worktree(
        repo_path, instance.base_commit, workdir, instance.test_patch, subprocess.run
    )
    if not ok:
        prep_error = reason
    else:
        ok, reason = build_venv(venv_dir, subprocess.run)
        if not ok:
            prep_error = reason
    if prep_error is not None:
        record.update(
            {
                "prep_error_ar": prep_error,
                "base": None,
                "loop": {
                    "instance_id": instance.instance_id,
                    "attempts": [],
                    "verdict": None,
                    "note_ar": "التحضير فشل — لا قياس ولا محاولات",
                },
            }
        )
        remove_worktree(repo_path, workdir, subprocess.run)
        return record

    python_bin = str(venv_dir / "bin" / "python")
    env_extra = {
        "HTTPBIN_URL": cfg.httpbin_url,
        "REQUESTS_CA_BUNDLE": "",  # httpbin المحلي http لا https — لا حزم شهادات خارجية
    }
    extra_args = (f"--timeout={int(TEST_TIMEOUT_S)}",)

    base = evaluate_instance(
        instance,
        workdir,
        python_bin,
        candidate_patch=None,
        env_extra=env_extra,
        runner=subprocess.run,
        extra_args=extra_args,
    )
    record["base"] = {
        "f2p_failed_at_base": list(base.f2p_failed_at_base),
        "p2p_failed_at_base": list(base.p2p_failed_at_base),
    }

    if cfg.base_only:
        record.update(
            {
                "prep_error_ar": None,
                "loop": {
                    "instance_id": instance.instance_id,
                    "attempts": [],
                    "verdict": None,
                    "note_ar": "قياس أساس فقط — وضع --base-only المعلن",
                },
            }
        )
        remove_worktree(repo_path, workdir, subprocess.run)
        return record

    map_lines = tuple(build_repo_map(workdir))
    loop = RepairLoop(
        choice_brain,
        diff_brain,
        max_attempts=cfg.max_attempts,
        max_files=cfg.max_files,
        map_lines=map_lines,
    )
    result = loop.run(
        instance,
        workdir,
        python_bin,
        env_extra=env_extra,
        runner=subprocess.run,
        extra_args=extra_args,
        base_verdict=base,
    )
    record.update(
        {
            "prep_error_ar": None,
            "loop": result.to_dict(),
        }
    )
    remove_worktree(repo_path, workdir, subprocess.run)
    return record


def main(argv: list[str] | None = None) -> int:
    """نقطة سطر الأوامر — البروتوكول كامل بأمر واحد قابل لإعادة التشغيل."""
    parser = argparse.ArgumentParser(
        prog="zyko.benchmarks.runner",
        description="بروتوكول SWE-bench الواسع (psf/requests، 44 حالة) — قياس أساس ثم حلقة إصلاح بعقل حقيقي خلف البوابات",
    )
    parser.add_argument(
        "--data", type=str, default=str(DEFAULT_DATA), help="ملف بيانات الحالات (المخطط الموثق)"
    )
    parser.add_argument("--out", type=str, required=True, help="مسار وثيقة النتائج JSON")
    parser.add_argument(
        "--repo",
        type=str,
        default=str(Path.home() / ".cache" / "zyko-swe" / "requests"),
        help="مسار مستودع psf/requests — يُستنسخ إن لم يوجد",
    )
    parser.add_argument(
        "--state-dir",
        type=str,
        default=str(Path.home() / ".cache" / "zyko-swe" / "state"),
        help="دليل أشجار العمل والبيئات المعزولة",
    )
    parser.add_argument(
        "--protocol",
        type=str,
        choices=("v1", "v2"),
        default="v2",
        help="v1 محاولة واحدة أحادية الملف (جولة 8) — v2 حلقة تلقيم الفشل ×3 (جولة 9)",
    )
    parser.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS_DEFAULT)
    parser.add_argument("--max-files", type=int, default=MAX_FILES_DEFAULT)
    parser.add_argument(
        "--base-only",
        action="store_true",
        help="قياس أساس فقط بلا محاولات إصلاح — وثيقة مرجعية صادقة",
    )
    parser.add_argument("--httpbin", type=str, default=DEFAULT_HTTPBIN_URL)
    parser.add_argument("--model-label", type=str, default="glm-4.7")
    parser.add_argument(
        "--resume", action="store_true", help="اكمل الحالات غير المكتملة في وثيقة موجودة"
    )
    parser.add_argument(
        "--retry-incomplete",
        action="store_true",
        help="مع --resume: المكتمل = طُبِّقت رقعة منها — المنصرف الخانق يُعاد جدولته (عقد التنفّس، الموجة 23)",
    )
    parser.add_argument(
        "--ids", type=str, default="", help="قائمة معرفات محدودة بفواصل — تشغيل مقطع موثق"
    )
    parser.add_argument(
        "--pace-s",
        type=float,
        default=0.0,
        help="ثوانٍ انتظار بين الحالات — تخفيف ضغط حصص النقاط العابرة (معلن في الوثيقة)",
    )
    parser.add_argument(
        "--gold-paths",
        type=str,
        default=str(DEFAULT_GOLD_PATHS),
        help="ملف مسارات الرقعة الذهبية (المسارات حصراً بلا محتوى) — مسطرة دقة الاختيار بعد الجولة حصراً، لا يصل للعقل",
    )
    args = parser.parse_args(argv)

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"ملف البيانات غير موجود: {data_path}", file=sys.stderr)
        return 2
    instances = load_instances(data_path)
    if args.ids.strip():
        wanted = {i.strip() for i in args.ids.split(",") if i.strip()}
        missing = wanted - {i.instance_id for i in instances}
        if missing:
            print(f"معرفات لا توجد في ملف البيانات: {sorted(missing)}", file=sys.stderr)
            return 2
        instances = tuple(i for i in instances if i.instance_id in wanted)

    out_path = Path(args.out)
    if args.resume:
        instances = resume_plan(instances, out_path, retry_incomplete=args.retry_incomplete)
    if not instances:
        print("لا حالات متبقية — وثيقة موجودة تكفي", file=sys.stderr)
        return 0

    host = os.environ.get("ZYKO_QWEN_HOST", "")
    key = os.environ.get("ZYKO_QWEN_API_KEY", "")
    if not args.base_only and not (host and key):
        print(
            "لا نقطة نموذج في البيئة (ZYKO_QWEN_HOST/ZYKO_QWEN_API_KEY) — استعمل --base-only "
            "لقياس أساس صادق بلا ذكاء، أو عيّن نقطة النهاية",
            file=sys.stderr,
        )
        return 2

    repo_path = _ensure_repo(Path(args.repo))
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    choice_brain = GatedBrain(SWEBrain(mode="choice", model=args.model_label))
    diff_brain = GatedBrain(SWEBrain(mode="diff", model=args.model_label))

    served_by = "نقطة OpenAI-Compatible من البيئة" if (host and key) else "معطل — قياس أساس فقط"
    if not args.base_only:
        served_by = (
            "z-ai-web-dev-sdk bridge (local, 127.0.0.1)" if "127.0.0.1" in host else served_by
        )

    protocol = (
        "SWE-bench (psf/requests) — قياس أساس فقط، التوسع من 6 إلى 44 حالة (الموجة 19)"
        if args.base_only
        else f"SWE-bench (psf/requests) — عقل حقيقي داخل حلقة تلقيم الفشل + خريطة دلالية + جرّاح صياغي وحرس تراجع (الموجة 20، بروتوكول {args.protocol})"
    )

    # الوثيقة موجودة من تشغيل سابق؟ نستكمل نتائجها لا نستبدلها.
    existing_results: list[dict[str, Any]] = []
    if args.resume and out_path.exists():
        try:
            prior = json.loads(out_path.read_text(encoding="utf-8"))
            existing_results = list(prior.get("results", []))
        except (json.JSONDecodeError, OSError):
            existing_results = []

    gold_map = None
    if Path(args.gold_paths).exists():
        gold_map = load_gold_paths(Path(args.gold_paths))

    results = list(existing_results)
    replaced_records = 0
    for index, instance in enumerate(instances, start=1):
        print(f"[{index}/{len(instances)}] {instance.instance_id} …", file=sys.stderr)
        try:
            record = _run_instance(
                instance,
                repo_path,
                state_dir,
                RunnerConfig(
                    data_path=data_path,
                    out_path=out_path,
                    repo_path=repo_path,
                    state_dir=state_dir,
                    protocol_version=args.protocol,
                    max_attempts=args.max_attempts,
                    max_files=args.max_files,
                    base_only=args.base_only,
                    httpbin_url=args.httpbin,
                    model_label=args.model_label,
                    host_env="ZYKO_QWEN_HOST",
                    key_env="ZYKO_QWEN_API_KEY",
                    ids_filter=(),
                ),
                choice_brain=choice_brain,
                diff_brain=diff_brain,
            )
        except subprocess.TimeoutExpired as exc:
            record = {
                "instance_id": instance.instance_id,
                "prep_error_ar": f"تجاوز المهلة في التحضير — {exc}",
                "base": None,
                "loop": {
                    "instance_id": instance.instance_id,
                    "attempts": [],
                    "verdict": None,
                    "note_ar": "التحضير أُوقِف",
                },
            }
        results, replaced_now = merge_result(results, record)
        replaced_records += replaced_now
        if args.pace_s > 0:
            time.sleep(args.pace_s)
        # كتابة ذرية بعد كل حالة — الانقطاع يفقد شيئاً لا يفسد كل شيء
        data_meta = {
            "source": data_path.name,
            "instances_sha16": _sha16(data_path.read_text(encoding="utf-8")),
        }
        doc = assemble_doc(
            protocol=protocol,
            data=data_meta,
            model_label=args.model_label,
            model_served_by=served_by,
            httpbin=args.httpbin,
            python_env=f"{PYTHON_VERSION} (uv) — بيئة معزولة لكل حالة",
            loop={
                "max_attempts": args.max_attempts,
                "max_files": args.max_files,
                "feedback": "خطأ التطبيق ورفض الحرس وعقد FAIL_TO_PASS الفاشلة تُغذّى للعقل",
                "repo_map": "repo-map بتوقيع الرموز (docstring + أعضاء الأصناف + عائلات لغات متعددة + عمل بلا git) ملحق بطلب الاختيار (الموجة 21)",
                "transport_retries": "النقل الافتراضي يعاد 3 مرات بتراجع 2s على الأخطاء العابرة (الموجة 19)",
                "patch_surgeon": "فحص صياغي محلي قبل git apply وسلّم تطبيق معلن: كاملة ← بالملفات ← بالأجزاء (الموجة 20)",
                "regression_guard": "رقعة تكسر عقداً ناجحة عند الأساس تُرجع إلى الأساس ورجعيتها تُغذّى للعقل (الموجة 20)",
                "pace_s": args.pace_s,
                "retried_records": replaced_records,
                "retry_contract": "وثيقة واحدة لكل حالة — القياس الأحدث يستبدل المنصرف السابق، والعدد معلن هنا (عقد التنفّس، الموجة 23)",
            },
            results=results,
            planned_total=len(load_instances(data_path)),
        )
        # الموجة 20: مسطرة دقة الاختيار — قياس بعد الجولة على المسارات الذهبية
        # (المسارات حصراً بلا محتوى، ولا تصل للعقل أبداً) — والبصمة تُعاد فوقها
        doc["selection"] = selection_accuracy(results, gold_map).to_dict()
        doc["chain_hash"] = chain_hash_of(doc)
        atomic_write_json(out_path, doc)
        loop_verdict = record.get("loop", {}).get("verdict") if record.get("loop") else None
        if loop_verdict:
            print(
                f"  ⇒ صارم {'✓' if loop_verdict['resolved_strict'] else '✗'} · "
                f"بيئي {'✓' if loop_verdict['resolved_env'] else '✗'}",
                file=sys.stderr,
            )
        else:
            note = record.get("prep_error_ar") or "قياس أساس أُوثق"
            print(f"  ⇒ {note[:120]}", file=sys.stderr)

    print(f"الوثيقة: {out_path} — البصمة {doc['chain_hash']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
