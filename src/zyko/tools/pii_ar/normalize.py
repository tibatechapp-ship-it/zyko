"""تطبيع الأرقام العربية/الفارسية إلى أرقام لاتينية (بنفس الطول — يحفظ الإحداثيات).

Length-preserving digit normalization so every offset in the normalized
string maps 1:1 to the original string. This lets the engine report exact
start/end spans in the ORIGINAL text even after normalization.
"""

ARABIC_INDIC = "٠١٢٣٤٥٦٧٨٩"
EXT_ARABIC_INDIC = "۰۱۲۳۴۵۶۷۸۹"  # Persian/Urdu variants

_TO_WESTERN = str.maketrans(ARABIC_INDIC + EXT_ARABIC_INDIC, "01234567890123456789")
_TO_ARABIC = str.maketrans("0123456789", ARABIC_INDIC)


def normalize_digits(text: str) -> str:
    """Return text with Arabic-Indic/Persian digits replaced by ASCII digits.

    Length is preserved (1 char -> 1 char), so indices stay valid.
    """
    return text.translate(_TO_WESTERN)


def to_western_digits(text: str) -> str:
    """Alias of normalize_digits."""
    return normalize_digits(text)


def to_arabic_digits(text: str) -> str:
    """Render ASCII digits as Arabic-Indic digits (٠-٩). Useful for Arabic output."""
    return text.translate(_TO_ARABIC)
