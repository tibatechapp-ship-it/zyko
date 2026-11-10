"""المكوّن 3 — run: تنفيذ الخطة عبر الأدوات الفعلية مع إيصال موحّد موقَّع.

القواعد (من التكليف):
1. ``dry_run=True`` افتراضياً — لا يُكتب أي ملف، وتُعاد «ما سيفعله» فقط.
2. كل خطوة تمر عبر المحرّس (Guardian: PII/RTL/بنيوية) قبل التنفيذ.
3. كل خطوة تحمل sha256 من حقولها الكنسية + المخرج (JSON مفرز مفاتيح).
4. ``chain_hash`` = sha256 لسلسلة بصمات الخطوات بترتيبها — حتمي قابل للتحقق.
5. فشل خطوة واحدة يوقف الخطة فوراً — مع ``error_ar`` واضح.
6. الإيصال ``{"version": 1, "kind": "orchestrator", ...}`` يتحقق منه
   ``zyko verify`` (انظر zyko.orchestrator.verify).

الحتمية (R2): الإيصال بلا طوابع زمنية إطلاقاً — لذلك ``duration_ms`` يقاس
على ``StepResult`` في الذاكرة فقط ولا يدخل الإيصال؛ نفس المدخل على نفس
المستودع يعطي نفس الإيصال بالبايت (مُثبت باختبارين: مقارنة كاملة + 100 تشغيل).

الأدوات تستورد الداخلي الثقيل (reviewer/fixer/coder/baseline) بشكل كسول
داخل دوالها — استيراد الوحدة يظل خفيفاً على Termux (قيد البنية).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from zyko.orchestrator.route import Plan, Step

RECEIPT_VERSION = 1
RECEIPT_KIND = "orchestrator"

_VERDICTS = ("ALLOW", "DENY", "REVIEW")


@dataclass(frozen=True)
class StepResult:
    """نتيجة خطوة واحدة: الحكم + المخرج + البصمة + زمن التنفيذ المقاس."""

    step: Step
    ok: bool
    output: str | dict | None
    error_ar: str | None
    duration_ms: int
    guardian_verdict: str | None  # ALLOW/DENY/REVIEW إن وُجد
    sha256: str  # بصمة المدخل + المخرج — كنسية وحتمية


@dataclass(frozen=True)
class RunResult:
    """نتيجة تنفيذ الخطة كاملة + الإيصال الموحّد القابل للتحقق."""

    plan: Plan
    steps: tuple[StepResult, ...]
    ok: bool
    receipt: dict


def _canonical(payload: Any) -> str:
    """تسلسل JSON كنسي: مفاتيح مفرزة، فواصل ثابتة، بلا فراغات — نفس البايت دائماً."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def step_payload(
    step: Step,
    ok: bool,
    guardian_verdict: str | None,
    error_ar: str | None,
    output: Any,
) -> dict[str, Any]:
    """حقول الخطوة التي تدخل البصمة — نفس الدالة في run وverify (عقد واحد)."""
    return {
        "tool": step.tool,
        "args": step.args,
        "reason_ar": step.reason_ar,
        "ok": ok,
        "guardian_verdict": guardian_verdict,
        "error_ar": error_ar,
        "output": output,
    }


def step_sha256(payload: dict[str, Any]) -> str:
    """بصمة الخطوة: sha256 للتمثيل الكنسي لحقولها + مخرجها."""
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def chain_hash_of(step_hashes: list[str]) -> str:
    """بصمة السلسلة: sha256 للبصمات موصولة بـ «|» بترتيب التنفيذ."""
    return hashlib.sha256("|".join(step_hashes).encode("utf-8")).hexdigest()


def _proposal_of(step: Step) -> str:
    """نص يعرض على المحرّس: الوسائط والسبب — بلا مسارات مفاتيح."""
    values = " ".join(str(v) for v in step.args.values() if isinstance(v, str))
    return f"{step.tool} {values} {step.reason_ar}".strip()


def _guardian_verdict(proposal: str) -> tuple[str, str]:
    """قرار المحرّس على اقتراح الخطوة — (الحكم، السبب العربي)."""
    from zyko.guardian import DefaultGuardian

    decision = asyncio.run(DefaultGuardian().check(proposal))
    return decision.verdict, decision.reason_ar


def _fail(step: Step, verdict: str | None, error_ar: str, started: float) -> StepResult:
    ms = int((time.perf_counter() - started) * 1000)
    payload = step_payload(step, False, verdict, error_ar, None)
    return StepResult(step, False, None, error_ar, ms, verdict, step_sha256(payload))


# ------------------------------------------------------------------ الأدوات
def _run_review(step: Step, dry_run: bool) -> tuple[bool, Any, str | None]:
    """مراجعة حتمية — قراءة فقط، تُنفَّذ فعلياً حتى في وضع التجريب."""
    path = str(step.args.get("path") or "")
    if not path:
        return False, None, "لم يُحدد مسار للمراجعة"
    target = Path(path)
    if not target.exists():
        return False, None, f"المسار غير موجود: {path}"
    from zyko.reviewer.engine import ReviewEngine

    engine = ReviewEngine()
    if target.is_dir():
        results = [r.to_dict() for r in engine.review_path(target)]
        return True, {"files": results, "count": len(results)}, None
    result = engine.review_file(target)
    return True, result.to_dict(), None


def _run_fix(step: Step, dry_run: bool) -> tuple[bool, Any, str | None]:
    """إصلاح آلي: التجريب يحسب ما سيُصلَح بلا كتابة؛ التطبيق يكتب صراحةً."""
    path = str(step.args.get("path") or "")
    if not path:
        return False, None, "لم يُحدد مسار للإصلاح"
    target = Path(path)
    if not target.exists():
        return False, None, f"المسار غير موجود: {path}"
    from zyko.fixer.engine import FixerEngine

    result = FixerEngine().fix_file(target)
    if result.parse_error is not None and not result.changed:
        return False, None, f"تعذر الإصلاح: {result.parse_error}"
    if not result.changed:
        return True, {"would_fix": 0, "changed": False, "note_ar": "لا يوجد ما يُصلَح آلياً"}, None
    if dry_run:
        return (
            True,
            {
                "would_fix": result.fixed_count,
                "changed": True,
                "score_before": result.score_before,
                "score_after": result.score_after,
                "dry_run_ar": "وضع تجريبي — لم يُكتب أي ملف؛ استخدم dry_run=False للتطبيق",
            },
            None,
        )
    target.write_text(result.fixed_source, encoding="utf-8")
    return (
        True,
        {
            "applied": True,
            "fixed": result.fixed_count,
            "score_before": result.score_before,
            "score_after": result.score_after,
        },
        None,
    )


def _run_generate(step: Step, dry_run: bool) -> tuple[bool, Any, str | None]:
    """توليد مشروع من القوالب المحققّة: التجريب يسرد الشجرة بلا كتابة."""
    description = str(step.args.get("description") or "").strip()
    if not description:
        return False, None, "لم يُحدد وصف المشروع"
    from zyko.coder.generate import build_all_files, materialize
    from zyko.coder.plan import ProjectPlan, safe_slug

    name = safe_slug(description, "zyko-project")  # R8: إعادة استخدام مُنقّح الاسم الموجود
    plan = ProjectPlan(name=name, template="python-cli", description=description, modules=("core",))
    problems = plan.validate()
    if problems:
        return False, None, "مخطط توليد غير صالح: " + "؛ ".join(problems[:3])
    tree = build_all_files(plan)
    if dry_run:
        sizes = {path: len(item.content) for path, item in sorted(tree.items())}
        return (
            True,
            {
                "name": name,
                "files": sizes,
                "total_bytes": sum(sizes.values()),
                "dry_run_ar": "لم يُكتب أي ملف — التطبيق يتطلب dry_run=False",
            },
            None,
        )
    out_dir = Path(str(step.args.get("out") or name))
    result = materialize(plan, out_dir, git_init=False)
    return True, {"applied": True, "root": str(result.root), "files": result.files}, None


def _run_transpile(step: Step, dry_run: bool) -> tuple[bool, Any, str | None]:
    """ترجمة ضاد → بايثون عبر المترجم المستقل (عملية منفصلة — نفس zyko py)."""
    file_path = str(step.args.get("file") or "")
    if not file_path:
        return False, None, "لم يُحدد ملف ضاد"
    source = Path(file_path)
    if not source.is_file():
        return False, None, f"الملف غير موجود: {file_path}"
    try:
        proc = subprocess.run(  # nosec B603
            [sys.executable, "-m", "daad", "transpile", str(source), "-"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, None, f"تعذر تشغيل مترجم ضاد: {type(exc).__name__}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:200]
        base = f"فشل مترجم ضاد (exit {proc.returncode})"
        return False, None, f"{base}: {detail}" if detail else base
    code = proc.stdout
    out = step.args.get("out")
    if not dry_run and out:
        Path(str(out)).write_text(code, encoding="utf-8")
        return True, {"applied": True, "out": str(out), "bytes": len(code)}, None
    return (
        True,
        {
            "code": code,
            "bytes": len(code),
            "dry_run_ar": "لم يُكتب أي ملف — التطبيق يتطلب dry_run=False مع out",
        },
        None,
    )


def _run_verify(step: Step, dry_run: bool) -> tuple[bool, Any, str | None]:
    """تحقق بلا ثقة: إيصال العقل يعاد حسابه كاملاً، وإيصال التوجيه كذلك."""
    receipt_path = str(step.args.get("receipt") or "")
    if not receipt_path:
        return False, None, "لم يُحدد مسار الإيصال"
    target = Path(receipt_path)
    if not target.is_file():
        return False, None, f"الملف غير موجود: {receipt_path}"
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return False, None, f"إيصال غير مقروء: {type(exc).__name__}: {exc}"
    if isinstance(data, dict) and data.get("kind") == RECEIPT_KIND:
        from zyko.orchestrator.verify import verify_orchestration_receipt

        report = verify_orchestration_receipt(data)
        return (
            True,
            {
                "ok": report.ok,
                "checks": report.checks,
                "issues": [i.as_dict() for i in report.issues],
            },
            None,
        )
    from zyko.router.verify import verify_receipt

    report = verify_receipt(data)
    return (
        True,
        {"ok": report.ok, "checks": report.checks, "issues": [i.as_dict() for i in report.issues]},
        None,
    )


def _run_baseline(step: Step, dry_run: bool) -> tuple[bool, Any, str | None]:
    """فحص خط الأساس — قراءة فقط دائماً؛ غياب الخط الأساس حالة موثقة لا فشل."""
    src = str(step.args.get("src") or ".")
    from zyko.baseline.engine import BaselineEngine

    result = BaselineEngine().check(src)
    if not result.ok:
        return False, None, result.error_ar or "فشل فحص خط الأساس"
    return (
        True,
        {
            "verdict_ar": result.verdict_ar,
            "baseline_status": result.baseline_status,
            "reviewed": result.reviewed,
            "regressed_files": result.regressed_files,
        },
        None,
    )


_RUNNERS: dict[str, Callable[[Step, bool], tuple[bool, Any, str | None]]] = {
    "review": _run_review,
    "fix": _run_fix,
    "generate": _run_generate,
    "transpile": _run_transpile,
    "verify": _run_verify,
    "baseline_check": _run_baseline,
}


def step_summary_ar(output: Any) -> str:
    """سطر ملخص عربي حتمي لنتيجة خطوة — حقول ثابتة فقط، بلا أزمنة.

    المصدر الواحد للسرد: يستخدمه سرد `zyko do` وسرد بوابة التنفيذ في
    جلسة الذكاء (`zyko ai run --mode existing`) — نفس الحقول نفس النص،
    فلا يصير للتلخيص نسختان تختلفان بين واجهتين.
    """
    if isinstance(output, dict):
        if "score" in output:
            return f"الدرجة {output.get('score')} — {output.get('verdict_ar', '')}"
        if "applied" in output and "fixed" in output:
            return (
                f"أُصلح {output.get('fixed', 0)} ملاحظة — "
                f"الدرجة {output.get('score_before')}→{output.get('score_after')}"
            )
        if "would_fix" in output:
            if output.get("applied"):
                return f"أُصلح {output.get('fixed', 0)} ملاحظة — الدرجة {output.get('score_before')}→{output.get('score_after')}"
            return f"سيُصلَح {output.get('would_fix')} ملاحظة"
        if "files" in output and "count" in output:
            return f"رُوجع {output.get('count')} ملفاً"
        if "total_bytes" in output:
            return f"شجرة {len(output.get('files', {}))} ملفاً ({output.get('total_bytes')} بايت)"
        if "code" in output:
            return f"ترجمة تمت ({output.get('bytes')} بايت)"
        if "verdict_ar" in output:
            return str(output.get("verdict_ar"))
        if "ok" in output:
            return "الإيصال صالح" if output.get("ok") else "الإيصال غير صالح"
    return "أُنجزت"


def run(plan: Plan, *, dry_run: bool = True) -> RunResult:
    """نفّذ الخطة عبر الأدوات الفعلية — حتمية، موقَّعة، وتتوقف عند أول فشل.

    كل خطوة تمر عبر المحرّس أولاً؛ DENY/REVIEW توقف الخطة كفشل موثق.
    أدوات الكتابة (fix/generate/transpile) تكتب فقط عند ``dry_run=False``.
    """
    executed: list[StepResult] = []
    for step in plan.steps:
        started = time.perf_counter()
        try:
            verdict, reason_ar = _guardian_verdict(_proposal_of(step))
        except Exception as exc:  # noqa: BLE001 — بوابات لا ترمي نظرياً؛ التوقف موثق
            executed.append(
                _fail(step, "REVIEW", f"تعذر تشغيل المحرّس: {type(exc).__name__}", started)
            )
            break
        if verdict not in _VERDICTS:
            executed.append(_fail(step, None, f"حكم محرّس غير معروف: {verdict!r}", started))
            break
        if verdict != "ALLOW":
            executed.append(
                _fail(step, verdict, f"المحرّس منع الخطوة ({verdict}): {reason_ar}", started)
            )
            break
        runner = _RUNNERS.get(step.tool)
        try:
            if runner is None:
                ok, output, error_ar = False, None, f"أداة غير معروفة في الخطة: {step.tool}"
            else:
                ok, output, error_ar = runner(step, dry_run)
        except Exception as exc:  # noqa: BLE001 — استثناء الأداة يوثَّق لا يَحرِق
            ok, output, error_ar = False, None, f"استثناء داخل الأداة: {type(exc).__name__}: {exc}"
        ms = int((time.perf_counter() - started) * 1000)
        payload = step_payload(step, ok, verdict, error_ar, output)
        executed.append(StepResult(step, ok, output, error_ar, ms, verdict, step_sha256(payload)))
        if not ok:
            break

    hashes = [s.sha256 for s in executed]
    ok_all = bool(executed) and all(s.ok for s in executed)
    receipt = {
        "version": RECEIPT_VERSION,
        "kind": RECEIPT_KIND,
        "ok": ok_all,
        "dry_run": dry_run,
        "plan": plan.to_dict(),
        "steps": [
            {
                **step_payload(s.step, s.ok, s.guardian_verdict, s.error_ar, s.output),
                "sha256": s.sha256,
            }
            for s in executed
        ],
        "chain_hash": chain_hash_of(hashes),
    }
    return RunResult(plan, tuple(executed), ok_all, receipt)
