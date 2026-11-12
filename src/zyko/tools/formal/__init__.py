"""zyko_formal — الحاكم الشكلي الحتمي (قياسي فقط، بلا تنفيذ للمقترح).

المُقترح يبحث، والحاكم يحكم: توجيهات `zyko:requires/ensures/domain`
تُحاكم سكونياً بـ`ast` — بلا شبكة ولا نماذج ولا عشوائية.
"""

from .engine import (
    ALLOWED_BUILTINS,
    ContractFinding,
    FormalReport,
    VerdictKind,
    check_source,
    evidence_lines,
    summarize,
)

__version__ = "0.1.0"

__all__ = [
    "ALLOWED_BUILTINS",
    "ContractFinding",
    "FormalReport",
    "VerdictKind",
    "check_source",
    "evidence_lines",
    "summarize",
]
