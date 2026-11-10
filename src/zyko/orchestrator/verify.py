"""التحقق بلا ثقة من إيصالات العقل — إعادة حساب كل بصمة، شبكةً بلا ثقة.

``zyko verify receipt.json`` يكتشف إيصال العقل عبر ``"kind": "orchestrator"``
ويستدعي هذا الملف: يعيد حساب sha256 لكل خطوة من حقولها المسجلة نفسها، ثم
يعيد حساب ``chain_hash`` من سلسلة البصمات. أي تعديل في الوسائط أو المخرجات
أو البصمات يُكتشف بأكواد مشاكل ثابتة:

* ``SCHEMA_INVALID``       — البنية ليست إيصال عقل أصلاً.
* ``VERSION_UNSUPPORTED``  — نسخة إيصال غير معروفة.
* ``PLAN_MISSING``         — الخطة مفقودة أو فاسدة.
* ``STEP_SHA_MISMATCH``    — حقول خطوة عُدّلت بعد التوقيع.
* ``CHAIN_HASH_MISMATCH``  — سلسلة البصمات لا تجتمع إلى chain_hash المسجل.

الحتمية كاملة: الدالة نقية على dict مقروء — نفس الإيصال يعطي نفس التقرير.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from zyko.orchestrator.run import RECEIPT_KIND, RECEIPT_VERSION, _canonical, chain_hash_of


@dataclass
class VerifyIssue:
    """مشكلة واحدة بأكواد ثابتة للسكربتات ورسالة عربية للبشر."""

    code: str
    message_ar: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message_ar": self.message_ar}


@dataclass
class OrchestratorVerifyReport:
    """تقرير التحقق: عدد الفحوصات + المشاكل + حكم نهائي."""

    ok: bool
    checks: int = 0
    chain_hash: str | None = None
    issues: list[VerifyIssue] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "kind": RECEIPT_KIND,
            "checks": self.checks,
            "chain_hash": self.chain_hash,
            "issues": [issue.as_dict() for issue in self.issues],
        }


def verify_orchestration_receipt(receipt: dict[str, Any]) -> OrchestratorVerifyReport:
    """أعد حساب كل البصمات من الحقول المسجلة نفسها — بلا ثقة بمن كتبها."""
    issues: list[VerifyIssue] = []
    checks = 0

    if not isinstance(receipt, dict) or receipt.get("kind") != RECEIPT_KIND:
        return OrchestratorVerifyReport(
            False,
            0,
            None,
            [VerifyIssue("SCHEMA_INVALID", "البنية ليست إيصال عقل (kind مفقود أو مخالف)")],
        )

    chain_hash = receipt.get("chain_hash")
    if receipt.get("version") != RECEIPT_VERSION:
        issues.append(
            VerifyIssue("VERSION_UNSUPPORTED", f"نسخة إيصال غير مدعومة: {receipt.get('version')!r}")
        )
    checks += 1

    plan = receipt.get("plan")
    if not isinstance(plan, dict) or "steps" not in plan:
        issues.append(VerifyIssue("PLAN_MISSING", "الخطة مفقودة أو فاسدة داخل الإيصال"))
    checks += 1

    steps = receipt.get("steps")
    step_hashes: list[str] = []
    if not isinstance(steps, list):
        issues.append(VerifyIssue("SCHEMA_INVALID", "قائمة الخطوات مفقودة أو ليست قائمة"))
    else:
        for index, entry in enumerate(steps):
            checks += 1
            if not isinstance(entry, dict) or "sha256" not in entry:
                issues.append(VerifyIssue("STEP_SHA_MISMATCH", f"الخطوة {index}: بلا بصمة مسجلة"))
                step_hashes.append("")
                continue
            payload = {k: v for k, v in entry.items() if k != "sha256"}
            recomputed = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
            if recomputed != entry["sha256"]:
                issues.append(
                    VerifyIssue(
                        "STEP_SHA_MISMATCH",
                        f"الخطوة {index}: الحقول عُدّلت بعد التوقيع (البصمة لا تجتمع)",
                    )
                )
            step_hashes.append(entry["sha256"])
        checks += 1
        recomputed_chain = chain_hash_of(step_hashes)
        if recomputed_chain != chain_hash:
            issues.append(
                VerifyIssue(
                    "CHAIN_HASH_MISMATCH",
                    "سلسلة البصمات لا تجتمع إلى chain_hash المسجل — الإيصال مُعدَّل",
                )
            )

    return OrchestratorVerifyReport(
        not issues, checks, chain_hash if isinstance(chain_hash, str) else None, issues
    )
