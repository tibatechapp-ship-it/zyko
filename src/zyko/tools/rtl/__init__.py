"""zyko_rtl — كاشف مشاكل الاتجاه RTL (حتمي 100%، بدون نماذج).

Deterministic RTL problem detector for CSS / HTML / Python / text.
Pure Python 3.11+, zero external dependencies, Termux-ready.
"""

from .core import (
    ARABIC_INDIC_DIGITS_RE,
    ARABIC_LETTER_RE,
    ARABIC_RE,
    BIDI_CONTROL_RE,
    LANG_BY_EXT,
    LATIN_LETTER_RE,
    RULE_CATALOG,
    SEVERITIES,
    SEVERITY_AR,
    SEVERITY_RANK,
    Finding,
    RTLChecker,
    arabic_letter_ratio,
    has_arabic,
)
from .css_rules import check_css
from .html_rules import check_html
from .py_rules import check_python
from .text_rules import check_text

__version__ = "0.1.0"

__all__ = [
    "Finding",
    "RTLChecker",
    "check_css",
    "check_html",
    "check_python",
    "check_text",
    "has_arabic",
    "arabic_letter_ratio",
    "RULE_CATALOG",
    "SEVERITIES",
    "SEVERITY_AR",
    "SEVERITY_RANK",
    "LANG_BY_EXT",
    "ARABIC_RE",
    "ARABIC_LETTER_RE",
    "ARABIC_INDIC_DIGITS_RE",
    "LATIN_LETTER_RE",
    "BIDI_CONTROL_RE",
    "__version__",
]
