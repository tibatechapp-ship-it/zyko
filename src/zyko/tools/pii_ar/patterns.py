"""سجلات حتمية: رموز الدول، الهويات الوطنية، IBAN، البطاقات.

Country registries + validators. All deterministic (regex + checksums),
no model calls, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Phones: Arab country calling codes with mobile prefix rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhoneCountry:
    code: str  # ISO code
    label: str  # Arabic country name
    mobile_prefixes: tuple[str, ...]
    national_len: int  # length of the national (significant) number incl. prefix


PHONE_COUNTRIES: dict[str, PhoneCountry] = {
    "966": PhoneCountry("SA", "السعودية", ("5",), 9),
    "971": PhoneCountry("AE", "الإمارات", ("5",), 9),
    "20": PhoneCountry("EG", "مصر", ("1",), 10),
    "965": PhoneCountry("KW", "الكويت", ("5", "6", "9"), 8),
    "973": PhoneCountry("BH", "البحرين", ("3",), 8),
    "974": PhoneCountry("QA", "قطر", ("3", "6", "7"), 8),
    "968": PhoneCountry("OM", "عُمان", ("7", "9"), 8),
    "962": PhoneCountry("JO", "الأردن", ("7",), 9),
    "961": PhoneCountry("LB", "لبنان", ("3", "7", "8"), 7),
    "963": PhoneCountry("SY", "سوريا", ("9", "3"), 9),
    "964": PhoneCountry("IQ", "العراق", ("7",), 10),
    "967": PhoneCountry("YE", "اليمن", ("7",), 9),
    "970": PhoneCountry("PS", "فلسطين", ("5", "6", "9"), 9),
    "218": PhoneCountry("LY", "ليبيا", ("9",), 9),
    "213": PhoneCountry("DZ", "الجزائر", ("5", "6", "7"), 9),
    "212": PhoneCountry("MA", "المغرب", ("6", "7"), 9),
    "216": PhoneCountry("TN", "تونس", ("2", "4", "5", "9"), 8),
    "249": PhoneCountry("SD", "السودان", ("9",), 9),
    "222": PhoneCountry("MR", "موريتانيا", ("2", "3", "4"), 8),
    "252": PhoneCountry("SO", "الصومال", ("6", "7"), 8),
    "253": PhoneCountry("DJ", "جيبوتي", ("7",), 8),
    "269": PhoneCountry("KM", "جزر القمر", ("3",), 7),
}

# +966 5xx xxx xxx | 00966-5... | international with separators
_PHONE_INTL_RE = re.compile(r"(?<![\d@.\-])(?:\+|00)(\d{2,4})(?:(?:[\s\-]){0,2}\d){7,14}(?!\d)")

# Local mobile formats (normalized text). Distinctive prefixes only;
# ambiguous short formats (KW/LB/BH) are intentionally covered by the
# international pattern instead of risking false positives.
_PHONE_LOCAL_RULES: tuple[tuple[tuple[str, ...], re.Pattern[str]], ...] = (
    (("966", "971"), re.compile(r"(?<!\d)05\d{8}(?!\d)")),  # SA / AE
    (("20",), re.compile(r"(?<!\d)01\d{9}(?!\d)")),  # EG
    (("962",), re.compile(r"(?<!\d)07[789]\d{7}(?!\d)")),  # JO
    (("964",), re.compile(r"(?<!\d)07[3-9]\d{8}(?!\d)")),  # IQ
)

# ---------------------------------------------------------------------------
# National IDs
# ---------------------------------------------------------------------------

_EG_GOV_RE = re.compile(
    r"^(?:0[1-9]|[12]\d|3[0-3]|88)[0-9]{4}$"
)  # governorate code sanity (01..33, 88 subset; conservative)


@dataclass(frozen=True)
class IDRule:
    country: str
    label: str
    regex: re.Pattern[str]
    validator: str | None = None  # name of validator in validators module
    needs_context: bool = False  # require a nearby Arabic keyword to lower FP


_NID_KEYWORDS = re.compile(
    r"(هوية|هويه|بطاقة|بطاقه|رقم وطني|الرقم الوطني|سجل مدني|إقامة|اقامه|جواز)"
)


def _validate_eg(nid: str) -> bool:
    """Egyptian NID: century(1) YYMMDD(6) governorate(2) serial(4) check(1)."""
    century = nid[0]
    yy, mm, dd = int(nid[1:3]), int(nid[3:5]), int(nid[5:7])
    if mm < 1 or mm > 12 or dd < 1 or dd > 31:
        return False
    year = (1900 if century == "2" else 2000) + yy
    if year < 1900 or year > 2035:
        return False
    return bool(_EG_GOV_RE.match(nid[7:13]))


def _validate_sa(nid: str) -> bool:
    """Saudi NID: 10 digits, starts 1 (citizen) or 2 (resident/GCC)."""
    return nid[0] in ("1", "2")


def _validate_ae(nid: str) -> bool:
    """UAE ID: 784 + birth YY + serial + check = 15 digits."""
    return nid.startswith("784") and len(nid) == 15


_VALIDATORS = {
    "EG": _validate_eg,
    "SA": _validate_sa,
    "AE": _validate_ae,
}

# كلمات هوية تدل على دول أخرى — إذا ظهرت قرب الرقم لا يُنسب للسعودية تلقائياً
_OTHER_ID_KEYWORDS = re.compile(
    r"كويتية|الكويت|إماراتية|الإمارات|قطرية|قطر|أردنية|الأردن|بحرينية|البحرين|عُمانية|عمانية|مصرية|مصر"
)

ID_RULES: tuple[IDRule, ...] = (
    IDRule("AE", "هوية الإمارات", re.compile(r"(?<!\d)784\d{12}(?!\d)"), "AE"),
    IDRule("EG", "هوية مصر", re.compile(r"(?<!\d)[23]\d{13}(?!\d)"), "EG"),
    IDRule("SA", "هوية السعودية", re.compile(r"(?<!\d)[12]\d{9}(?!\d)"), "SA"),
    IDRule("KW", "بطاقة الكويت", re.compile(r"(?<!\d)[1234]\d{9}(?!\d)"), None, True),
    IDRule("QA", "هوية قطر", re.compile(r"(?<!\d)\d{11}(?!\d)"), None, True),
    IDRule("JO", "رقم وطني أردني", re.compile(r"(?<!\d)\d{10}(?!\d)"), None, True),
    IDRule("BH", "هوية البحرين", re.compile(r"(?<!\d)\d{8}(?!\d)"), None, True),
    IDRule("OM", "بطاقة عُمان", re.compile(r"(?<!\d)\d{8}(?!\d)"), None, True),
)

# ---------------------------------------------------------------------------
# IBAN — Arab countries only, with exact lengths + mod-97
# ---------------------------------------------------------------------------

IBAN_LENGTHS: dict[str, int] = {
    "SA": 24,
    "AE": 23,
    "EG": 29,
    "KW": 30,
    "QA": 29,
    "BH": 22,
    "OM": 23,
    "JO": 30,
    "LB": 28,
    "PS": 29,
    "TN": 24,
    "MA": 28,
    "DZ": 26,
    "IQ": 23,
    "LY": 25,
    "SD": 18,
    "MR": 27,
    "SO": 23,
    "DJ": 27,
    "KM": 27,
}

_IBAN_RE = re.compile(
    r"\b(" + "|".join(IBAN_LENGTHS) + r")(\d{2})(?:\s?[A-Z0-9]{4}){3,7}\s?[A-Z0-9]{1,7}\b"
)


def iban_mod97(iban: str) -> bool:
    """Validate IBAN check digits (ISO 13616 mod-97)."""
    s = re.sub(r"\s+", "", iban).upper()
    rearranged = s[4:] + s[:4]
    converted = "".join(str(int(ch, 36)) for ch in rearranged)
    try:
        return int(converted) % 97 == 1
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Bank cards — Luhn + brand detection
# ---------------------------------------------------------------------------

_CARD_RE = re.compile(r"(?<!\d)(?:\d{4}[ \-]?){3}\d{4}(?!\d)")

_MADA_BINS = ("9682", "440647", "440526", "421590", "411194", "468540", "446404")


def luhn_valid(number: str) -> bool:
    digits = re.sub(r"\D", "", number)
    if len(digits) < 12:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        d = int(d)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def card_brand(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if digits.startswith("4"):
        return "visa"
    if digits[:2] in ("34", "37"):
        return "amex"
    if digits[:2] in ("51", "52", "53", "54", "55") or digits[:2] in (
        "22",
        "23",
        "24",
        "25",
        "26",
        "27",
    ):
        return "mastercard"
    if any(digits.startswith(b) for b in _MADA_BINS):
        return "مدى"
    return "unknown"


# ---------------------------------------------------------------------------
# Emails
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"(?<![\w.\-])[A-Za-z0-9._%+\-]+@(?:[A-Za-z0-9\-]+\.)+[A-Za-z]{2,24}(?![\w.\-])"
)

# ---------------------------------------------------------------------------
# Addresses (heuristic, Arabic keywords)
# ---------------------------------------------------------------------------

_ADDRESS_KEYWORDS = (
    "شارع",
    "طريق",
    "جادة",
    "حي",
    "حارة",
    "منطقة",
    "مبنى",
    "برج",
    "صندوق بريد",
    "صندوق البريد",
    "الرمز البريدي",
    "مقابل",
    "بجوار",
)
_ADDRESS_RE = re.compile(
    r"(" + "|".join(_ADDRESS_KEYWORDS) + r")\s+[\u0621-\u064Aa-zA-Z0-9]{2,}"
    r"(?:\s+[\u0621-\u064Aa-zA-Z0-9\-]{1,20}){0,6}"
)
