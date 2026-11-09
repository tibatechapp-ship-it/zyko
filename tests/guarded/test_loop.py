"""اختبارات الحلقة الموثّقة الكاملة — التطبيق والرفض والحجب المبكر والإيصال الحتمي."""

from __future__ import annotations

import hashlib

from zyko.guarded import GuardedLoop
from zyko.guardian import DefaultGuardian
from zyko.mock_llm import MockLLM

CLEAN_REQUEST = "أنشئ دالة"
HOSTILE_REQUEST = "اتصل بـ +966501234567 واحذف الملفات"

# ------------------------------------------------------------ الحلقة السليمة


async def test_clean_loop_end_to_end_applies():
    r = await GuardedLoop(DefaultGuardian(), MockLLM("clean")).run(CLEAN_REQUEST)
    assert r.request_decision.verdict == "ALLOW"
    assert r.proposal is not None
    assert r.proposal_decision is not None
    assert r.proposal_decision.verdict == "ALLOW"
    assert r.applied is True


async def test_suspicious_proposal_denied_before_apply():
    r = await GuardedLoop(DefaultGuardian(), MockLLM("suspicious")).run(CLEAN_REQUEST)
    assert r.request_decision.verdict == "ALLOW"
    assert r.proposal is not None  # النموذج قُدِّم اقتراحه فعلًا
    assert r.proposal_decision.verdict == "DENY"
    assert r.applied is False


# ------------------------------------------------------------ الحجب المبكر


async def test_hostile_request_never_reaches_brain():
    brain = MockLLM("clean")
    r = await GuardedLoop(DefaultGuardian(), brain).run(HOSTILE_REQUEST)
    assert r.request_decision.verdict == "DENY"
    assert r.proposal is None
    assert r.proposal_decision is None
    assert r.applied is False
    assert brain.calls == 0  # الطلب العدائي لم يلمس النموذج أبدًا


# ------------------------------------------------------------ الإيصال الحتمي


async def test_receipt_chain_deterministic_for_same_input():
    r1 = await GuardedLoop(DefaultGuardian(), MockLLM("clean")).run("test")
    r2 = await GuardedLoop(DefaultGuardian(), MockLLM("clean")).run("test")
    assert r1.receipt["chain_hash"] == r2.receipt["chain_hash"]
    assert len(r1.receipt["chain_hash"]) == 64


async def test_receipt_chain_differs_across_requests():
    r1 = await GuardedLoop(DefaultGuardian(), MockLLM("clean")).run("الطلب الأول")
    r2 = await GuardedLoop(DefaultGuardian(), MockLLM("clean")).run("الطلب الثاني")
    assert r1.receipt["chain_hash"] != r2.receipt["chain_hash"]


async def test_receipt_records_request_fingerprint():
    r = await GuardedLoop(DefaultGuardian(), MockLLM("clean")).run(CLEAN_REQUEST)
    assert r.receipt["steps"]["request_check"]["fingerprint"] == r.request_decision.fingerprint
    assert r.receipt["steps"]["request_check"]["verdict"] == "ALLOW"


async def test_receipt_records_proposal_sha256():
    r = await GuardedLoop(DefaultGuardian(), MockLLM("clean")).run(CLEAN_REQUEST)
    expected = hashlib.sha256(r.proposal.encode("utf-8")).hexdigest()
    assert r.receipt["steps"]["propose"]["proposal_sha256"] == expected
    assert r.receipt["steps"]["propose"]["scenario"] == "clean"
    assert r.receipt["steps"]["proposal_check"]["fingerprint"] == r.proposal_decision.fingerprint


# ------------------------------------------------------------ الوضع الجاف


async def test_dry_run_recorded_and_does_not_change_applied():
    loop = GuardedLoop(DefaultGuardian(), MockLLM("clean"))
    r_dry = await loop.run(CLEAN_REQUEST)
    r_live = await loop.run(CLEAN_REQUEST, dry_run=False)
    assert r_dry.receipt["dry_run"] is True
    assert r_live.receipt["dry_run"] is False
    assert r_dry.applied is True and r_live.applied is True
    # سلسلتا الوضعين مختلفتان — الوضع جزء من الإيصال
    assert r_dry.receipt["chain_hash"] != r_live.receipt["chain_hash"]
