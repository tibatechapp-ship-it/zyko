"""محرك الكشف والحجب — حتمي 100% (regex + معاجم + تحقق رياضي).

Detection engine pipeline:
  original text
    -> normalize_digits          (length-preserving)
    -> strip harakat/tatweel     (with index map)
    -> join "عبد الله" splits    (with index map)
  every detector runs on the final cleaned string and reports spans that are
  mapped back to ORIGINAL offsets via the composed index map.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass

from .names_ar import (
    _HONORIFIC_RE,
    _IBN_RE,
    _JOIN_ABD_WORDS,
    _NAME_TOKEN,
    _in_family,
    _in_first,
    _is_nameish,
)
from .normalize import normalize_digits
from .patterns import (
    _ADDRESS_RE,
    _CARD_RE,
    _EMAIL_RE,
    _IBAN_RE,
    _NID_KEYWORDS,
    _OTHER_ID_KEYWORDS,
    _PHONE_INTL_RE,
    _PHONE_LOCAL_RULES,
    IBAN_LENGTHS,
    ID_RULES,
    PHONE_COUNTRIES,
    card_brand,
    iban_mod97,
    luhn_valid,
)

TYPE_LABELS = {
    "person_name": "اسم شخص",
    "phone": "هاتف",
    "national_id": "هوية وطنية",
    "iban": "آيبان",
    "bank_card": "بطاقة بنكية",
    "email": "بريد إلكتروني",
    "address": "عنوان",
}

PLACEHOLDERS = {
    "person_name": "[اسم]",
    "phone": "[هاتف]",
    "national_id": "[هوية]",
    "iban": "[آيبان]",
    "bank_card": "[بطاقة]",
    "email": "[بريد]",
    "address": "[عنوان]",
}

PRIORITY = {
    "bank_card": 6,
    "iban": 5,
    "national_id": 4,
    "phone": 3,
    "email": 2,
    "address": 1,
    "person_name": 0,
}

# هويات عامة بلا تحقق رياضي (KW/QA/JO/BH/OM): أدنى أولوية من الهاتف
_WEAK_ID_COUNTRIES = {"KW", "QA", "JO", "BH", "OM"}


def _finding_priority(f: "Finding") -> tuple:
    base = PRIORITY.get(f.type, 0)
    if f.type == "national_id" and f.country in _WEAK_ID_COUNTRIES:
        base = 2  # تحتها الهاتف مباشرة
    return (base, f.confidence, f.end - f.start)


_ABD_JOIN_AT = re.compile(r"عبد\s+(" + _JOIN_ABD_WORDS + r")")


@dataclass
class Finding:
    type: str
    value: str
    start: int
    end: int
    country: str | None = None
    valid: bool | None = None
    confidence: float = 1.0
    hint: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _strip_marks_with_map(text: str) -> tuple[str, list[int]]:
    """Remove tatweel + combining harakat, keeping an index map to input."""
    out: list[str] = []
    cmap: list[int] = []
    for i, ch in enumerate(text):
        if ch == "\u0640" or unicodedata.combining(ch):
            continue
        out.append(ch)
        cmap.append(i)
    return "".join(out), cmap


def _join_abd_with_map(text: str) -> tuple[str, list[int]]:
    """Join "عبد X" -> "عبدX". Returns (joined, map) where map[k] is the
    index in `text` that produced output char k."""
    out: list[str] = []
    cmap: list[int] = []
    i = 0
    n = len(text)
    while i < n:
        m = _ABD_JOIN_AT.match(text, i)
        if m:
            for j in range(3):  # ع ب د
                out.append(text[i + j])
                cmap.append(i + j)
            g1_start = m.start(1)
            for j in range(m.end(1) - g1_start):
                out.append(text[g1_start + j])
                cmap.append(g1_start + j)
            i = m.end()
        else:
            out.append(text[i])
            cmap.append(i)
            i += 1
    return "".join(out), cmap


def _clean_pipeline(text: str) -> tuple[str, list[int]]:
    """original -> clean string + map: clean_index -> original_index."""
    norm = normalize_digits(text)  # طبقة 0: بنفس الطول
    stripped, cmap1 = _strip_marks_with_map(norm)  # cmap1: stripped -> norm
    clean, cmap2 = _join_abd_with_map(stripped)  # cmap2: clean -> stripped
    final_map = [cmap1[j] for j in cmap2]  # تركيب الطبقتين: clean -> norm/original
    return clean, final_map


class PIIScanner:
    """Deterministic Arabic PII scanner."""

    def __init__(self, min_confidence: float = 0.5):
        self.min_confidence = min_confidence

    # ------------------------------------------------------------------ #
    # detectors — every span is already in ORIGINAL coordinates
    # ------------------------------------------------------------------ #

    def _detect_phones(self, clean: str, text: str, cmap: list[int]) -> list[Finding]:
        out: list[Finding] = []
        covered: list[tuple[int, int]] = []

        def is_covered(s: int) -> bool:
            return any(s < e and s >= st for st, e in covered)

        for m in _PHONE_INTL_RE.finditer(clean):
            raw = m.group(0)
            prefix_len = 1 if raw.startswith("+") else 2
            full = re.sub(r"\D", "", raw[prefix_len:])
            result = None
            # حاول أطول رمز دولة أولاً (4 → 3 → 2 خانات)
            for cl in (4, 3, 2):
                cc = full[:cl]
                pc = PHONE_COUNTRIES.get(cc)
                if pc is None:
                    continue
                body = full[cl:]
                valid = body.startswith(pc.mobile_prefixes) and len(body) == pc.national_len
                candidate = (cc, valid, 0.95 if valid else 0.7, pc)
                if valid:
                    result = candidate
                    break
                if result is None:
                    result = candidate
            if result is None:
                cc = full[:3]
                result = (cc, len(full) - 3 >= 9, 0.55, None)
            cc, valid, conf, pc = result
            s, e = cmap[m.start()], cmap[m.end() - 1] + 1
            out.append(
                Finding(
                    "phone",
                    text[s:e],
                    s,
                    e,
                    country=cc,
                    valid=valid,
                    confidence=conf,
                    hint=(pc.label if pc else "رمز دولي غير عربي"),
                )
            )
            covered.append((m.start(), m.end()))
        for codes, rx in _PHONE_LOCAL_RULES:
            for m in rx.finditer(clean):
                if is_covered(m.start()):
                    continue
                body = re.sub(r"\D", "", m.group(0))[1:]  # اسحب الصفر البادئ
                valid, hit = False, codes[0]
                for code in codes:
                    pc = PHONE_COUNTRIES[code]
                    if body.startswith(pc.mobile_prefixes) and len(body) == pc.national_len:
                        valid, hit = True, code
                        break
                s, e = cmap[m.start()], cmap[m.end() - 1] + 1
                out.append(
                    Finding(
                        "phone",
                        text[s:e],
                        s,
                        e,
                        country=hit,
                        valid=valid,
                        confidence=0.85 if valid else 0.6,
                        hint=PHONE_COUNTRIES[hit].label,
                    )
                )
        return out

    def _detect_national_ids(self, clean: str, text: str, cmap: list[int]) -> list[Finding]:
        out: list[Finding] = []
        for rule in ID_RULES:
            for m in rule.regex.finditer(clean):
                valid, conf = True, 0.85
                if rule.validator:
                    from .patterns import _VALIDATORS

                    valid = _VALIDATORS[rule.country](m.group(0))
                    conf = 0.9 if valid else 0.65
                if rule.needs_context:
                    # نافذة ضيقة (±40) حتى لا يلتقط سياق هوية أخرى مجاورة
                    window = clean[max(0, m.start() - 40) : m.end() + 40]
                    if not _NID_KEYWORDS.search(window):
                        continue  # بدون سياق: خطر إيجابيات كاذبة عالٍ
                if rule.country == "SA":
                    window = clean[max(0, m.start() - 40) : m.end() + 40]
                    if _OTHER_ID_KEYWORDS.search(window):
                        continue  # السياق يشير لدولة أخرى: لا تنسبه للسعودية
                s, e = cmap[m.start()], cmap[m.end() - 1] + 1
                out.append(
                    Finding(
                        "national_id",
                        text[s:e],
                        s,
                        e,
                        country=rule.country,
                        valid=valid,
                        confidence=conf,
                        hint=rule.label,
                    )
                )
        return out

    def _detect_ibans(self, clean: str, text: str, cmap: list[int]) -> list[Finding]:
        out: list[Finding] = []
        for m in _IBAN_RE.finditer(clean):
            raw = re.sub(r"\s+", "", m.group(0))
            country = m.group(1)
            expected = IBAN_LENGTHS.get(country)
            if len(raw) != expected or not iban_mod97(raw):
                continue  # آيبان ناقص/مشوّه = ضجيج نصي
            s, e = cmap[m.start()], cmap[m.end() - 1] + 1
            out.append(
                Finding(
                    "iban",
                    text[s:e],
                    s,
                    e,
                    country=country,
                    valid=True,
                    confidence=0.95,
                    hint="IBAN",
                )
            )
        return out

    def _detect_cards(self, clean: str, text: str, cmap: list[int]) -> list[Finding]:
        out: list[Finding] = []
        for m in _CARD_RE.finditer(clean):
            digits = re.sub(r"\D", "", m.group(0))
            if len(digits) != 16 or not luhn_valid(digits):
                continue
            s, e = cmap[m.start()], cmap[m.end() - 1] + 1
            out.append(
                Finding(
                    "bank_card",
                    text[s:e],
                    s,
                    e,
                    valid=True,
                    confidence=0.95,
                    hint=card_brand(digits),
                )
            )
        return out

    def _detect_emails(self, clean: str, text: str, cmap: list[int]) -> list[Finding]:
        out: list[Finding] = []
        for m in _EMAIL_RE.finditer(clean):
            s, e = cmap[m.start()], cmap[m.end() - 1] + 1
            out.append(
                Finding(
                    "email",
                    text[s:e],
                    s,
                    e,
                    valid=True,
                    confidence=0.95,
                    hint="email",
                )
            )
        return out

    def _detect_addresses(self, clean: str, text: str, cmap: list[int]) -> list[Finding]:
        out: list[Finding] = []
        for m in _ADDRESS_RE.finditer(clean):
            s, e = cmap[m.start()], cmap[m.end() - 1] + 1
            out.append(
                Finding(
                    "address",
                    text[s:e].strip(),
                    s,
                    e,
                    confidence=0.6,
                    hint="كلمة مفتاحية عنوانية",
                )
            )
        return out

    def _detect_names(self, clean: str, text: str, cmap: list[int]) -> list[Finding]:
        out: list[Finding] = []

        def span(m: re.Match) -> tuple[int, int]:
            return cmap[m.start()], cmap[m.end() - 1] + 1

        # 1) لقب + 1..3 أسماء  (مثل: الأستاذ محمد العمري)
        for m in _HONORIFIC_RE.finditer(clean):
            toks = m.group(2).split()
            if not toks or not _is_nameish(toks[0]):
                continue
            s, e = span(m)
            out.append(Finding("person_name", text[s:e], s, e, confidence=0.85, hint="لقب + اسم"))
        # 2) نمط بن/بنت
        for m in _IBN_RE.finditer(clean):
            t1, t2, t3 = m.group(1), m.group(2), m.group(3)
            if _is_nameish(t1) and _is_nameish(t2) and (t3 is None or _is_nameish(t3)):
                s, e = span(m)
                out.append(
                    Finding("person_name", text[s:e], s, e, confidence=0.8, hint="نمط بن/بنت")
                )
        # 3) اسم ثلاثي/مركب: FIRST [middle] FAMILY — مسح بنوافذ الرموز
        #    (finditer يبتلع الأسماء عندما يفشل تطابق سابق طويل)
        tokens = [(m.start(), m.end(), m.group(0)) for m in re.finditer(_NAME_TOKEN, clean)]
        for i in range(len(tokens)):
            t1s, t1e, t1 = tokens[i]
            if i + 1 < len(tokens):
                t2s, t2e, t2 = tokens[i + 1]
                # ثنائي: اسم أول + عائلة
                if _in_first(t1) and _in_family(t2):
                    s, e = cmap[t1s], cmap[t2e - 1] + 1
                    out.append(
                        Finding("person_name", text[s:e], s, e, confidence=0.75, hint="اسم + عائلة")
                    )
                # ثلاثي: اسم أول + وسط + عائلة
                if i + 2 < len(tokens):
                    t3s, t3e, t3 = tokens[i + 2]
                    if _in_first(t1) and _is_nameish(t2) and _in_family(t3):
                        s, e = cmap[t1s], cmap[t3e - 1] + 1
                        out.append(
                            Finding(
                                "person_name",
                                text[s:e],
                                s,
                                e,
                                confidence=0.75,
                                hint="اسم ثلاثي/مركب",
                            )
                        )
        return out

    # ------------------------------------------------------------------ #

    def scan(self, text: str, types: list[str] | None = None) -> list[Finding]:
        """Scan text; returns non-overlapping findings sorted by position."""
        if not text:
            return []
        clean, cmap = _clean_pipeline(text)

        findings: list[Finding] = []
        findings += self._detect_phones(clean, text, cmap)
        findings += self._detect_national_ids(clean, text, cmap)
        findings += self._detect_ibans(clean, text, cmap)
        findings += self._detect_cards(clean, text, cmap)
        findings += self._detect_emails(clean, text, cmap)
        findings += self._detect_addresses(clean, text, cmap)
        findings += self._detect_names(clean, text, cmap)

        findings = [f for f in findings if f.confidence >= self.min_confidence]
        if types:
            allowed = set(types)
            findings = [f for f in findings if f.type in allowed]

        return self._resolve_overlaps(findings)

    @staticmethod
    def _resolve_overlaps(findings: list[Finding]) -> list[Finding]:
        findings.sort(key=lambda f: (f.start, -(f.end - f.start), -f.confidence))
        picked: list[Finding] = []
        for f in findings:
            if not picked or f.start >= picked[-1].end:
                picked.append(f)
                continue
            prev = picked[-1]
            f_key = _finding_priority(f)
            p_key = _finding_priority(prev)
            if f_key > p_key:
                picked[-1] = f
            elif (
                f_key == p_key
                and f.type == prev.type
                and f.start == prev.start
                and f.end > prev.end
            ):
                picked[-1] = f
        picked.sort(key=lambda f: f.start)
        return picked


def _mask_value(value: str) -> str:
    """Show first 25% and last 25%, mask the middle."""
    n = len(value)
    if n <= 6:
        return "*" * n
    head = max(1, n // 4)
    tail = max(1, n // 4)
    return value[:head] + "*" * (n - head - tail) + value[n - tail :]


def _hash_value(value: str) -> str:
    return "#" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def redact(
    text: str,
    mode: str = "mask",
    types: list[str] | None = None,
    scanner: PIIScanner | None = None,
) -> tuple[str, list[Finding]]:
    """Redact PII from text. Modes: mask | placeholder | hash."""
    sc = scanner or PIIScanner()
    findings = sc.scan(text, types=types)
    if not findings:
        return text, []
    out: list[str] = []
    last = 0
    for f in findings:
        out.append(text[last : f.start])
        if mode == "placeholder":
            rep = PLACEHOLDERS[f.type]
        elif mode == "hash":
            rep = _hash_value(f.value)
        else:
            rep = _mask_value(f.value)
        out.append(rep)
        last = f.end
    out.append(text[last:])
    return "".join(out), findings


def scan(text: str, types: list[str] | None = None) -> list[Finding]:
    """Convenience wrapper."""
    return PIIScanner().scan(text, types=types)
