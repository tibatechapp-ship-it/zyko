"""مجمّع العدّة: البنّاؤون العشرون بإمارتهم المعلنة — العقد 1000 حالة."""

from __future__ import annotations

from typing import Any, Callable

from zyko.benchmarks.eval1000_cases_a import (
    build_gates,
    build_pii_iban_cards,
    build_pii_names,
    build_pii_nid,
    build_pii_phone,
    build_pii_redact,
    build_rtl,
)
from zyko.benchmarks.eval1000_cases_b import (
    build_audit,
    build_contracts,
    build_jail,
    build_patch_run,
)
from zyko.benchmarks.eval1000_cases_c import (
    build_classify_route,
    build_factory,
    build_ledger,
    build_reflect,
)
from zyko.benchmarks.eval1000_cases_d import (
    build_kernel_core,
    build_policy,
    build_receipts,
    build_review_fix,
    build_structured,
)
from zyko.benchmarks.eval1000_cases_extra import EXTRA_BUILDERS

# الترتيب المعلن — نفسه في CATEGORY_LABELS داخل eval1000
CASE_BUILDERS: dict[str, Callable[[], list[tuple[str, str, Any]]]] = {
    "pii-phone": build_pii_phone,
    "pii-nid": build_pii_nid,
    "pii-iban-cards": build_pii_iban_cards,
    "pii-names": build_pii_names,
    "pii-redact": build_pii_redact,
    "rtl": build_rtl,
    "gates": build_gates,
    "contracts": build_contracts,
    "audit": build_audit,
    "patch-run": build_patch_run,
    "jail": build_jail,
    "reflect": build_reflect,
    "ledger": build_ledger,
    "classify-route": build_classify_route,
    "factory": build_factory,
    "review-fix": build_review_fix,
    "structured": build_structured,
    "policy": build_policy,
    "kernel-core": build_kernel_core,
    "receipts": build_receipts,
}

CATEGORY_ORDER: tuple[str, ...] = tuple(CASE_BUILDERS.keys())


def _builder_with_extra(category: str, base: Callable[[], list]) -> Callable[[], list]:
    """بنّاء موحد: الأساس + المكمّل إن وُجد — الترتيب ثابت بالبايت."""
    extra = EXTRA_BUILDERS.get(category)

    def build():
        cases = list(base())
        if extra is not None:
            cases.extend(extra())
        return cases

    return build


CASE_BUILDERS = {cat: _builder_with_extra(cat, builder) for cat, builder in CASE_BUILDERS.items()}
