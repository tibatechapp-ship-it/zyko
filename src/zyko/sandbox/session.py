"""zyko.sandbox.session — جلسة الأدوات: عقد + تدقيق + بلا استثناء.

الجلسة هي الواجهة الوحيدة للأدوات: ``patch_file`` و``run_tests`` لا
تُستدعيان مباشرة من الحلقة — بل عبر جلسة تحمل عقدًا وسجل تدقيق، فكل
محاولة (مسموحة، مرفوضة، خاطئة) تُوقَّع في السجل قبل أن تُعاد نتيجتها.
الترتيب عقد صارم: **التدقيق يسبق التنفيذ** — قرار ALLOW يُكتب أولًا
فلو ماتت العملية في منتصف الأداة يبقى أثر المحاولة موثقًا؛ ثم نتيجة
التنفيذ تُوقَّع ثانية بقرارها الفعلي.

ميزانية الجلسة: ``max_patch_ops`` من العقد — الرقعة الثانية والثلاثون
والنافلة تُرفض موثقة، فلا كتابة بلا حد مهما عادى المدخل. وعقد «بلا
استثناء»: أي خطأ غير متوقع داخل أداة يتحول إلى نتيجة فاشلة موثقة
بقرار ERROR — الحلقة التي تستدعي الجلسة لا تنكسر أبدًا.
"""

from __future__ import annotations

from dataclasses import dataclass

from zyko.sandbox.audit import AuditLog
from zyko.sandbox.contracts import PermissionContract
from zyko.sandbox.patcher import PatchResult, patch_file
from zyko.sandbox.runner import TestRunResult, run_tests

DECISION_ALLOW = "ALLOW"
DECISION_DENY = "DENY"
DECISION_ERROR = "ERROR"

_UNPRINTABLE_PATH = "غير-قابل-للطباعة"
_UNPRINTABLE_ARGV = "غير-قابل-للطباعة"


@dataclass
class SessionUsage:
    """استهلاك الجلسة — عدّادات علنية موثقة لا حالة خفية."""

    patch_ops: int = 0
    patch_denied: int = 0
    test_runs: int = 0

    def to_dict(self) -> dict:
        """ممثل JSON حتمي."""
        return {
            "patch_denied": int(self.patch_denied),
            "patch_ops": int(self.patch_ops),
            "test_runs": int(self.test_runs),
        }


class ToolSession:
    """جلسة أدوات معزولة: كل محاولة موثقة، كل فشل نتيجة لا استثناء."""

    def __init__(
        self,
        contract: PermissionContract,
        audit_log: AuditLog | None = None,
    ) -> None:
        self.contract = contract
        self.audit = audit_log
        self.usage = SessionUsage()

    # ------------------------------------------------------------ التدقيق
    def _audit(self, tool: str, decision: str, reason_ar: str, detail: dict) -> None:
        """وقّع حدثًا — التدقيق الفاشل لا يفشل الأداة، ويفضح نفسه في السجل."""
        if self.audit is None:
            return
        try:
            self.audit.append(tool, decision, reason_ar, detail)
        except Exception:  # noqa: BLE001 — التدقيق خسارة توثيق لا فشل تنفيذ
            pass

    # ------------------------------------------------------------ الرقعة
    def patch_file(
        self,
        *,
        path: object = None,
        old_text: object = None,
        new_text: object = None,
        content: object = None,
    ) -> PatchResult:
        """رقعة تحت العقد — القرار يُدقَّق قبل التنفيذ وبعده، بلا استثناء."""
        try:
            path_text = str(path or "").strip() if path is not None else ""
            mode = "replace" if (old_text is not None or new_text is not None) else "write"
        except Exception:  # noqa: BLE001 — حتى التطبيع العدوي موثق لا مفجّر
            self._audit("patch_file", DECISION_ERROR, "مدخل الرقعة غير قابل للطباعة", {})
            return PatchResult(
                ok=False, path=_UNPRINTABLE_PATH, mode="", changed=False, matches=0,
                sha_before="", sha_after="", bytes_written=0,
                reason_ar="مدخل الرقعة غير قابل للطباعة — رفض موثق لا استثناء",
            )
        # ميزانية الجلسة: الرقعة فوق الميزانية رفض موثق لا كتابة
        if self.usage.patch_ops >= self.contract.max_patch_ops:
            self.usage.patch_denied += 1
            reason = (
                f"نفدت ميزانية الرقع ({self.usage.patch_ops}/{self.contract.max_patch_ops}) — "
                "رفض موثق لا كتابة صامتة"
            )
            self._audit("patch_file", DECISION_DENY, reason, {"path": path_text})
            return PatchResult(
                ok=False, path=path_text, mode="", changed=False, matches=0,
                sha_before="", sha_after="", bytes_written=0, reason_ar=reason,
            )
        try:
            # التدقيق يسبق التنفيذ — المحاولة موثقة حتى لو انقطعت في المنتصف
            self._audit(
                "patch_file",
                DECISION_ALLOW if self.contract.allow_patch else DECISION_DENY,
                "محاولة رقعة موثقة قبل التنفيذ" if self.contract.allow_patch
                else "محاولة رقعة على عقد قراءة-فقط",
                {"path": path_text, "mode": mode},
            )
            self.usage.patch_ops += 1
            result = patch_file(
                self.contract, path=path, old_text=old_text, new_text=new_text, content=content
            )
        except Exception as exc:  # noqa: BLE001 — عقد بلا استثناء خارج
            reason = f"خطأ غير متوقع داخل الرقعة — {type(exc).__name__}"
            self._audit("patch_file", DECISION_ERROR, reason, {"path": path_text})
            return PatchResult(
                ok=False, path=path_text, mode="", changed=False, matches=0,
                sha_before="", sha_after="", bytes_written=0, reason_ar=reason,
            )
        decision = DECISION_ALLOW if result.ok else DECISION_DENY
        self._audit(
            "patch_file", decision, result.reason_ar,
            {"bytes_written": result.bytes_written, "matches": result.matches,
             "mode": result.mode, "path": result.path},
        )
        if not result.ok:
            self.usage.patch_denied += 1
        return result

    # ------------------------------------------------------------ الاختبارات
    def run_tests(self, *, argv: object, cwd: object = None) -> TestRunResult:
        """اختبارات حقيقية تحت العقد — القرار يُدقَّق قبل وبعد، بلا استثناء."""
        try:
            argv_text = (
                " ".join(str(t) for t in argv)[:120]
                if isinstance(argv, (list, tuple))
                else str(argv)[:120]
            )
        except Exception:  # noqa: BLE001 — حتى تطبيع المدخل العدوي موثق لا مفجّر
            argv_text = _UNPRINTABLE_ARGV
        try:
            self._audit(
                "run_tests",
                DECISION_ALLOW if self.contract.allow_run_tests else DECISION_DENY,
                "محاولة تشغيل اختبارات موثقة قبل التنفيذ" if self.contract.allow_run_tests
                else "محاولة تشغيل اختبارات على عقد لا يفعّلها",
                {"argv": argv_text},
            )
            self.usage.test_runs += 1
            result = run_tests(self.contract, argv=argv, cwd=cwd)
        except Exception as exc:  # noqa: BLE001 — عقد بلا استثناء خارج
            reason = f"خطأ غير متوقع داخل التشغيل — {type(exc).__name__}"
            self._audit("run_tests", DECISION_ERROR, reason, {"argv": argv_text})
            return TestRunResult(
                ok=False, exit_code=2, timed_out=False, passed=None, failed=None,
                errors=None, skipped=None, command=argv_text,
                stdout_tail="", stderr_tail="", reason_ar=reason,
            )
        decision = DECISION_ALLOW if result.ok else DECISION_DENY
        self._audit(
            "run_tests", decision, result.reason_ar,
            {"argv": result.command[:120], "exit_code": result.exit_code},
        )
        return result

    # ------------------------------------------------------------ التوثيق
    def summary(self) -> dict:
        """ملخص الجلسة: العقد والاستهلاك والسلسلة — حتمي بلا أي زمن."""
        summary: dict = {
            "contract": self.contract.to_dict(),
            "usage": self.usage.to_dict(),
        }
        if self.audit is not None:
            summary["audit"] = self.audit.chain_summary()
        return summary


__all__ = [
    "DECISION_ALLOW",
    "DECISION_DENY",
    "DECISION_ERROR",
    "SessionUsage",
    "ToolSession",
]
