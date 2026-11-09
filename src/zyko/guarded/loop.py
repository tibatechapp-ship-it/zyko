"""الحلقة الموثّقة الكاملة: طلب → محرس → نموذج وهمي → محرس → إيصال sha256.

المرحلة A — أصغر حلقة صحيحة:
  1. guardian.check(الطلب)     — هل الطلب نفسه مشروع؟
     الطلب غير المسموح لا يصل النموذج أبدًا (حجب عند البوابة الأولى).
  2. brain.propose(الطلب)      — النموذج يقترح.
  3. guardian.check(الاقتراح)  — هل الاقتراح مقبول؟
  4. ALLOW → applied=True وإلا applied=False.
  5. إيصال sha256 بسلسلة حتمية: نفس المدخلات = نفس chain_hash دائمًا
     (بلا طوابع زمنية ولا عشوائية — مطابق لنهج إيصالات المصنع).

دلالات applied: «الاقتراح اجتاز المحرس وقُبل». الوضع الجاف (dry_run،
الافتراضي) لا يكتب شيئًا على القرص — ربط الكتابة بمحركات المصنع يأتي
في الخطوة التالية بعد هذه المرحلة.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from zyko.guardian.contracts import Decision, Guardian
from zyko.mock_llm.brain import MockLLM

RECEIPT_SCHEMA = "zyko.guarded/receipt-v1"


@dataclass
class GuardedResult:
    """نتيجة الحلقة الكاملة مع إيصالها الحتمي."""

    request: str
    request_decision: Decision
    proposal: str | None
    proposal_decision: Decision | None
    applied: bool
    receipt: dict = field(default_factory=dict)


class GuardedLoop:
    """حلقة موثّقة: لا شيء يدخل النموذج أو يخرج منه دون مرور بالمحرّس."""

    def __init__(self, guardian: Guardian, brain: MockLLM) -> None:
        self.guardian = guardian
        self.brain = brain

    async def run(self, request: str, *, dry_run: bool = True) -> GuardedResult:
        """تشغيل الحلقة كاملة وإعادة النتيجة الموثّقة بالإيصال."""
        request_decision = await self.guardian.check(request)
        proposal: str | None = None
        proposal_decision: Decision | None = None
        if request_decision.verdict == "ALLOW":
            proposal = await self.brain.propose(request)
            proposal_decision = await self.guardian.check(proposal)
        applied = proposal_decision is not None and proposal_decision.verdict == "ALLOW"
        receipt = self._build_receipt(
            request_decision, proposal, proposal_decision, applied, dry_run
        )
        return GuardedResult(
            request=request,
            request_decision=request_decision,
            proposal=proposal,
            proposal_decision=proposal_decision,
            applied=applied,
            receipt=receipt,
        )

    def _build_receipt(
        self,
        request_decision: Decision,
        proposal: str | None,
        proposal_decision: Decision | None,
        applied: bool,
        dry_run: bool,
    ) -> dict:
        """إيصال بسلسلة sha256 حتمية — نفس المدخلات تعطي نفس chain_hash."""
        proposal_sha = (
            hashlib.sha256(proposal.encode("utf-8")).hexdigest() if proposal is not None else None
        )
        steps: dict = {
            "request_check": {
                "verdict": request_decision.verdict,
                "fingerprint": request_decision.fingerprint,
            }
        }
        if proposal is not None and proposal_decision is not None:
            steps["propose"] = {
                "brain": type(self.brain).__name__,
                "scenario": getattr(self.brain, "scenario", ""),
                "proposal_sha256": proposal_sha,
            }
            steps["proposal_check"] = {
                "verdict": proposal_decision.verdict,
                "fingerprint": proposal_decision.fingerprint,
            }
        chain_payload = "|".join(
            [
                RECEIPT_SCHEMA,
                request_decision.fingerprint,
                proposal_sha or "-",
                proposal_decision.fingerprint if proposal_decision is not None else "-",
                "1" if applied else "0",
                "1" if dry_run else "0",
            ]
        )
        return {
            "schema": RECEIPT_SCHEMA,
            "dry_run": dry_run,
            "applied": applied,
            "steps": steps,
            "chain_hash": hashlib.sha256(chain_payload.encode("utf-8")).hexdigest(),
        }
