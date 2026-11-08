"""zyko.tools — الأدوات الحتمية للطبقة-1 (بلا نماذج، صفر اعتماديات).

Deterministic Layer-1 tools: they never call a model, run on Termux,
and are fully pytest-tested. Model failure or absence never stops them —
only the smart generation depends on models, never the checks.

- pii_ar: Arabic PII detection & redaction (phones, national IDs, IBAN,
  cards, names, addresses — with math validation: mod-97 / Luhn).
- rtl: RTL problem detection for CSS / HTML / Python / text (15 rules).
"""

from . import pii_ar, rtl

__all__ = ["pii_ar", "rtl"]
