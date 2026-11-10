"""المكوّن 5 — swarm: مهام متوازية بحد أعلى، نتائج بترتيب المدخل حتمياً.

يستقبل سلسلة مهام (هدف نصي أو ``Plan`` جاهز) وينفّذها عبر العقل الحتمي
(classify → route → run) بألاكثر من ``max_parallel`` خيوط عمل، ثم يجمع
النتائج **بترتيب المدخل** دائماً — التوازي يقلّل الزمن فقط، ولا يلمس
القرار ولا الترتيب ولا الإيصال.

القواعد الحاكمة (من تكليف العقل):
* حتمية بالبايت (R2): لا ``datetime`` ولا ``random`` ولا ``os.environ``
  في القرار ولا في الإيصال — نفس المهام تعطي نفس ``SwarmResult`` بالبايت
  (مُثبت باختبار 100 تشغيل). الخيوط تنفّذ، لا تقرّر.
* قراءة فقط (P4): ``run`` يُستدعى دائماً بـ ``dry_run=True`` — السرب
  يلاحظ ويوقّع، لا يكتب؛ الكتابة الصريحة قرار منفصل يحتاج ``dry_run=False``
  على خطوة بعينها.
* عزل الأخطاء: فشل مهمة لا يحرق السرب — تُوثَّق في مكانها بـ ``error_ar``
  وتكمل البقية؛ ``ok`` صاد فقط إذا نجحت كل المهام.
* إيصال موحّد: سرب واحد إيصال واحد — ``kind: "swarm"`` يحوي إيصالات
  المهام و``chain_hash`` فوق سلسلة بصماتها بترتيب المدخل (عقد run نفسه).
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Sequence

from zyko.exceptions import ConfigError
from zyko.orchestrator.classify import classify
from zyko.orchestrator.context import extract_context
from zyko.orchestrator.route import Plan, route
from zyko.orchestrator.run import chain_hash_of, run

RECEIPT_VERSION = 1
RECEIPT_KIND = "swarm"

# حد أعلى معلن لخيوط العمل — حماية للمنصات الضعيفة (Termux) من ذلاة الموارد.
MAX_PARALLEL_CAP = 16


def _canonical(payload: Any) -> str:
    """تسلسل JSON كنسي — نفس الدالة في run وverify وcompress (عقد بايت واحد)."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TaskResult:
    """نتيجة مهمة واحدة داخل السرب — بترتيب مدخلها، بلا استثناء حر."""

    index: int
    task: str  # نص الهدف أو «plan:#i» إن أُعطيت خطة جاهزة
    ok: bool
    classification: Any | None  # Classification أو None إن فشل قبل التصنيف
    plan: Any | None  # Plan أو None إن فشل قبل التوجيه
    run_result: Any | None  # RunResult أو None إن فشل قبل التنفيذ
    error_ar: str | None

    def to_dict(self) -> dict[str, Any]:
        """ممثل JSON كامل — إيصال المهمة إن وُجد وإلا السبب العربي."""
        payload: dict[str, Any] = {
            "index": self.index,
            "task": self.task,
            "ok": self.ok,
            "error_ar": self.error_ar,
        }
        if self.plan is not None:
            payload["plan"] = self.plan.to_dict()
        if self.run_result is not None:
            payload["receipt"] = self.run_result.receipt
        return payload


@dataclass(frozen=True)
class SwarmResult:
    """نتيجة السرب كاملاً: نتائج بترتيب المدخل + إيصال موقَّع قابل للتحقق."""

    results: tuple[TaskResult, ...]
    max_parallel: int
    ok: bool
    receipt: dict
    summary_ar: str
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        """ممثل JSON كامل — مفاتيح ثابتة وقيم قابلة للتسلسل."""
        return {
            "results": [r.to_dict() for r in self.results],
            "max_parallel": self.max_parallel,
            "ok": self.ok,
            "receipt": self.receipt,
            "summary_ar": self.summary_ar,
            "fingerprint": self.fingerprint,
        }


def _run_one(index: int, task: str | Plan) -> TaskResult:
    """نفّذ مهمة واحدة كاملة — عزل الاستثناءات برسالة عربية موثقة."""
    try:
        if isinstance(task, Plan):
            plan = task
            label = f"plan:#{index}"
        else:
            goal = "" if task is None else str(task)
            label = goal
            classification = classify(goal)
            plan = route(classification, context=extract_context(goal))
        run_result = run(plan, dry_run=True)  # P4: السرب يلاحظ ولا يكتب
        return TaskResult(
            index=index,
            task=label,
            ok=run_result.ok,
            classification=plan.classification,
            plan=plan,
            run_result=run_result,
            error_ar=None,
        )
    except Exception as exc:  # noqa: BLE001 — فشل المهمة يوثَّق لا يحرق السرب
        return TaskResult(
            index=index,
            task=task if isinstance(task, str) else f"plan:#{index}",
            ok=False,
            classification=None,
            plan=None,
            run_result=None,
            error_ar=f"استثناء داخل المهمة: {type(exc).__name__}: {exc}",
        )


def swarm(tasks: Sequence[str | Plan], *, max_parallel: int = 3) -> SwarmResult:
    """نفّذ المهام عبر العقل الحتمي بالتوازي المحدود — النتائج بترتيب المدخل.

    ``dry_run=True`` دائماً؛ حد الخيوط معلن ومحدود بـ ``MAX_PARALLEL_CAP``؛
    الفشل معزول لكل مهمة؛ الإيصال واحد للسرب فوق سلسلة بصمات المهام.
    """
    tasks_list = list(tasks)
    if not tasks_list:
        raise ConfigError("لا مهام في السرب — مرّر هدفاً واحداً على الأقل")
    if max_parallel < 1:
        raise ConfigError(f"حد التوازي أصغر من 1: {max_parallel}")

    workers = min(max_parallel, MAX_PARALLEL_CAP, len(tasks_list))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run_one, i, t) for i, t in enumerate(tasks_list)]
        ordered = [f.result() for f in futures]  # فشل المستقبل استثناء برمجي — لا يحدث

    results = tuple(ordered)
    ok_all = all(r.ok for r in results)
    task_receipts = [r.run_result.receipt for r in results if r.run_result is not None]
    chain = chain_hash_of([rc["chain_hash"] for rc in task_receipts])
    receipt = {
        "version": RECEIPT_VERSION,
        "kind": RECEIPT_KIND,
        "ok": ok_all,
        "dry_run": True,
        "max_parallel": workers,
        "total": len(results),
        "ok_count": sum(1 for r in results if r.ok),
        "fail_count": sum(1 for r in results if not r.ok),
        "tasks": [
            {
                "index": r.index,
                "ok": r.ok,
                "error_ar": r.error_ar,
                **({"receipt": r.run_result.receipt} if r.run_result is not None else {}),
            }
            for r in results
        ],
        "chain_hash": chain,
    }
    summary_ar = (
        f"سرب حتمي: {len(results)} مهام بحد توازي {workers}، نجحت "
        f"{sum(1 for r in results if r.ok)} وفشلت {sum(1 for r in results if not r.ok)} "
        f"— وضع تجريبي بلا كتابة، الإيصال {len(task_receipts)} إيصال تنفيذ وسلسلة موقَّعة"
    )
    fingerprint = _sha256(_canonical(receipt))
    return SwarmResult(
        results=results,
        max_parallel=workers,
        ok=ok_all,
        receipt=receipt,
        summary_ar=summary_ar,
        fingerprint=fingerprint,
    )
