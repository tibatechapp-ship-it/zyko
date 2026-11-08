"""zyko.tools.pii_ar — كشف وحجب البيانات الشخصية العربية (حتمي 100%).

Deterministic Arabic PII detection & redaction — vendored from the
zyko-pii-ar tool (Phase 0, D1–2). Pure stdlib, no models, no I/O.
All public names re-exported here for `from zyko.tools.pii_ar import ...`.
"""

from .engine import TYPE_LABELS, Finding, PIIScanner, redact, scan
from .normalize import normalize_digits, to_arabic_digits, to_western_digits

__version__ = "0.1.0"

__all__ = [
    "Finding",
    "PIIScanner",
    "TYPE_LABELS",
    "scan",
    "redact",
    "normalize_digits",
    "to_western_digits",
    "to_arabic_digits",
    "__version__",
]
