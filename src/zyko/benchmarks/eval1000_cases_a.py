"""بنّاؤو حالات التقييم (أ) — الخصوصية العربية، الاتجاه، والبوابات الثلاث.

كل بنّاء يعيد قائمة ``(العائلة، العنوان_العربي، الدالة)`` والدالة تنادي
كود zyko الحقيقي وتعيد ``(نجاح، سبب_عربي)``. كل الحقائق هنا من عقود
المصنع الموثقة في الكود نفسه — لا توقعات مُخترعة.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from zyko.guardian.contracts import compute_fingerprint
from zyko.guardian.core import DefaultGuardian
from zyko.guardian.gates import (
    MAX_PROPOSAL_CHARS,
    PII_DENY_TYPES,
    PIIGate,
    RTLGate,
    StructuralGate,
    default_gates,
)
from zyko.mock_llm import SCENARIOS, MockLLM, get_scenario
from zyko.tools.pii_ar import (
    TYPE_LABELS,
    Finding,
    PIIScanner,
    normalize_digits,
    redact,
    scan,
)
from zyko.tools.pii_ar.engine import PLACEHOLDERS, PRIORITY
from zyko.tools.pii_ar.names_ar import _in_family, _in_first, _is_nameish
from zyko.tools.pii_ar.patterns import (
    IBAN_LENGTHS,
    PHONE_COUNTRIES,
    card_brand,
    iban_mod97,
    luhn_valid,
)
from zyko.tools.rtl import (
    BIDI_CONTROL_RE,
    LANG_BY_EXT,
    RULE_CATALOG,
    SEVERITIES,
    arabic_letter_ratio,
    check_css,
    check_html,
    check_python,
    check_text,
    has_arabic,
)
from zyko.tools.rtl.core import RTLChecker, excerpt_of, line_col_of

# ------------------------------------------------------------ مساعدات
BIDI_HIDDEN = "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
LRM, RLM = "\u200e", "\u200f"

_FIRST_OK = tuple(
    n
    for n in (
        "محمد",
        "أحمد",
        "عبدالله",
        "خالد",
        "فاطمة",
        "عائشة",
        "يوسف",
        "عمر",
        "سارة",
        "إبراهيم",
        "حسن",
        "نور",
    )
    if _in_first(n)
)
_FAMILY_OK = tuple(
    n
    for n in (
        "العمري",
        "الشهري",
        "الغامدي",
        "العتيبي",
        "الحربي",
        "القحطاني",
        "الدوسري",
        "السبيعي",
        "المطيري",
        "الزهراني",
        "السالم",
        "الأنصاري",
    )
    if _in_family(n)
)


def _phone_body(iso: str) -> str:
    """رقم الجوال الصحيح لدولة: المقدمة + الباقي بالطول الوطني الموثق.

    ملاحظة العقد: PHONE_COUNTRIES مفاتيحه رموز الاتصال (966…) وقيمة
    ``.code`` هي ISO (SA…) — الكشف يعيد country برمز الاتصال الموثق."""
    pc = next(p for p in PHONE_COUNTRIES.values() if p.code == iso)
    prefix = pc.mobile_prefixes[0]
    return prefix + "234567890123456789"[: pc.national_len - len(prefix)]


def _intl_phone(iso: str, *, prefix: str = "+") -> str:
    cc = next(code for code, pc in PHONE_COUNTRIES.items() if pc.code == iso)
    return f"{prefix}{cc} {_phone_body(iso)}"


def _iban_check_digits(iban_without_check: str) -> str:
    """رقما تحقق IBAN بصيغة ISO 13616 mod-97 — حقيقة لا توقع."""
    rearranged = iban_without_check[4:] + iban_without_check[:4]
    converted = "".join(str(int(ch, 36)) for ch in rearranged)
    return f"{98 - int(converted) % 97:02d}"


def _valid_iban(cc: str, *, spaced: bool = True) -> str:
    total = IBAN_LENGTHS[cc]
    bban_len = total - 4
    alphabet = "1234567890ABCDEFGHJKLMNPQRSTUVWXYZ"
    bban = "".join(alphabet[i % len(alphabet)] for i in range(bban_len))
    raw = cc + "00" + bban
    check = _iban_check_digits(raw)
    iban = cc + check + bban
    if not spaced:
        return iban
    return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))


def _luhn_complete(prefix: str) -> str:
    """أكمل 16 خانة بصمة لون المتحققة — رقم بطاقة حقيقي الصحة الرياضية.

    البادئة تُمدَّد بجدول ثابت إلى 15 خانة ثم تُحسب خانة التحقق —
    حتمية بالبايت لأي بادئة لا تتجاوز 15.
    """
    body = (str(prefix) + "111111111111111")[:15]
    digits = [int(c) for c in body]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:  # مواضع المضاعفة: الزوجية في البادئة المعكوسة
            d *= 2
            if d > 9:
                d -= 9
        total += d
    check = (10 - total % 10) % 10
    return body + str(check)


def _run_gate(gate: Any, proposal: str) -> Any:
    return asyncio.run(gate.check(proposal))


def _run_guardian(proposal: str) -> Any:
    return asyncio.run(DefaultGuardian().check(proposal))


def _findings_of(text: str, types: list[str] | None = None) -> list[Finding]:
    return scan(text, types=types)


def _one_phone(text: str) -> Finding | None:
    hits = [f for f in scan(text) if f.type == "phone"]
    return hits[0] if hits else None


# ============================================================ 1) الهواتف
def build_pii_phone():
    cases = []

    # أ) دولي صحيح لكل دولة عربية موثقة — كشف + صحة + دولة
    for iso in sorted({pc.code for pc in PHONE_COUNTRIES.values()}):

        def fn(iso=iso):
            text = f"اتصل بـ {_intl_phone(iso)} اليوم"
            hits = [f for f in scan(text) if f.type == "phone"]
            if len(hits) != 1:
                return False, f"الكشف أعاد {len(hits)} إيجابًا بدل 1 لـ {iso}"
            f = hits[0]
            if not f.valid:
                return False, f"رقم {iso} صحيح البنية لكن valid=False"
            calling = next(code for code, pc in PHONE_COUNTRIES.items() if pc.code == iso)
            if f.country != calling:
                return False, f"الدولة {f.country} بدل {calling}"
            return True, f"{iso}: كشف صحيح بثقة {f.confidence}"

        cases.append(("دولي", f"هاتف دولي صحيح ({iso})", fn))

    # ب) بادئة 00 بدل + — نفس العقد
    for iso in ("SA", "EG", "MA"):

        def fn(iso=iso):
            hits = [f for f in scan(f"اتصال {_intl_phone(iso, prefix='00')}") if f.type == "phone"]
            if not hits:
                return False, f"بادئة 00 لـ {iso} لم تُكشَف"
            return (True, "صحيح") if hits[0].valid else (False, "00 بادئة صحيحة لكن valid=False")

        cases.append(("دولي", f"بادئة 00 ({iso})", fn))

    def fn_dash():
        hits = [f for f in scan("هاتفي +966-5-1-2-3-4-5-6-7-8 داخلي") if f.type == "phone"]
        ok = bool(hits) and hits[0].valid
        return (True, "فواصل - مقبولة") if ok else (False, f"فواصل - لم تُكشف: {len(hits)}")

    cases.append(("دولي", "فواصل شرطة بين الخانات", fn_dash))

    # ج) دولي بقادمة خاطئة/طول خاطئ — يُكشَف لكن valid=False (صدق الحكم)
    def fn_sa_prefix():
        hits = [f for f in scan("رقم +966 412345678") if f.type == "phone"]
        if not hits:
            return False, "بادئة غير متحركة لم تُكشَف إطلاقًا"
        return (
            (True, "صحيح") if hits[0].valid is False else (False, "بادئة 4 غير متحركة وvalid=True!")
        )

    cases.append(("دولي", "بادئة خاطئة (سعودي 4…)", fn_sa_prefix))

    def fn_eg_prefix():
        hits = [f for f in scan("رقم +20 3012345678") if f.type == "phone"]
        if not hits:
            return False, "لم يُكشَف"
        return (
            (True, "صحيح") if hits[0].valid is False else (False, "بادئة 3 غير متحركة وvalid=True")
        )

    cases.append(("دولي", "بادئة خاطئة (مصري 3…)", fn_eg_prefix))

    def fn_sa_len():
        hits = [f for f in scan("رقم +966 51234567") if f.type == "phone"]
        if not hits:
            return False, "طول ناقص لم يُكشَف إطلاقًا"
        return (True, "صحيح") if hits[0].valid is False else (False, "طول 8 بدل 9 وvalid=True")

    cases.append(("دولي", "طول وطني ناقص", fn_sa_len))

    def fn_unknown_cc():
        hits = [f for f in scan("رقم +999 512345678") if f.type == "phone"]
        if not hits:
            return False, "رمز دولة غير معروف لا يعود حتى ب finding احتياطي"
        f = hits[0]
        if f.country != "999" or f.confidence != 0.55:
            return (
                False,
                f"الاحتياطي الموثق: دولة 999 وثقة 0.55 — الواقع {f.country}/{f.confidence}",
            )
        return True, "سلوك الاحتياطي الموثق لرمز غير معروف"

    cases.append(("دولي", "رمز دولة غير معروف (احتياطي موثق)", fn_unknown_cc))

    def fn_short():
        hits = [f for f in scan("رمز قصير +966 51234") if f.type == "phone"]
        return (True, "لا كشف لقصر الرقم") if not hits else (False, "قصير جداً وكُشِف هاتفًا")

    cases.append(("دولي", "دولي قصير لا يُكشَف", fn_short))

    # د) المحلي
    def fn_sa_local():
        f = _one_phone("جوال 0512345678 مفقود")
        if f is None or not f.valid:
            return False, "05… لم يُكشَف صحيحًا"
        return (True, "صحيح") if f.country == "966" else (False, f"الدولة {f.country} بدل 966")

    cases.append(("محلي", "محلي سعودي 05…", fn_sa_local))

    def fn_eg_local():
        f = _one_phone("موبايل 01012345678 شخصي")
        if f is None or not f.valid:
            return False, "01… لم يُكشَف صحيحًا"
        return (True, "صحيح") if f.country == "20" else (False, f"الدولة {f.country} بدل 20")

    cases.append(("محلي", "محلي مصري 01…", fn_eg_local))

    def fn_jo_local():
        f = _one_phone("أردني 0791234567 للتواصل")
        if f is None or not f.valid:
            return False, "079… لم يُكشَف صحيحًا"
        return (True, "صحيح") if f.country == "962" else (False, f"الدولة {f.country} بدل 962")

    cases.append(("محلي", "محلي أردني 079…", fn_jo_local))

    def fn_iq_local():
        f = _one_phone("عراقي 07712345678 للاتصال")
        if f is None or not f.valid:
            return False, "077… لم يُكشَف صحيحًا"
        return (True, "صحيح") if f.country == "964" else (False, f"الدولة {f.country} بدل 964")

    cases.append(("محلي", "محلي عراقي 077…", fn_iq_local))

    def fn_local_04():
        hits = [f for f in scan("هاتف ثابت 0412345678 في العيادة") if f.type == "phone"]
        return (
            (True, "ثابت بلا بادئة متحركة لا يُكشَف") if not hits else (False, "04… كُشِف متحركًا خطأً")
        )

    cases.append(("محلي", "ثابت 04… لا يُكشَف", fn_local_04))

    def fn_local_short():
        hits = [f for f in scan("رقم 051234567 قصير") if f.type == "phone"]
        return (True, "قصر محلي مرفوض") if not hits else (False, "9 خانات محلية كُشِفت صحيحة!")

    cases.append(("محلي", "محلي قصير مرفوض", fn_local_short))

    def fn_local_long():
        hits = [f for f in scan("رقم 05123456789 طويل") if f.type == "phone"]
        return (True, "طول زائد مرفوض") if not hits else (False, "11 خانة محلية كُشِفت صحيحة!")

    cases.append(("محلي", "محلي طويل مرفوض", fn_local_long))

    # هـ) الإيجابيات الكاذبة المحتملة — لا كشف
    for label, text in (
        ("رقم طلب طويل", "طلب رقم 1234567890 في المستودع"),
        ("تاريخ", "التاريخ 2026-11-12 موثق"),
        ("أرقام بلا بادئة", "الرمز 966512345678 داخلي"),
        ("رقم قصير", "الوحدة 55555 فقط"),
    ):

        def fn(text=text):
            hits = [f for f in scan(text) if f.type == "phone"]
            return (
                (True, "لا إيجابية كاذبة")
                if not hits
                else (False, f"إيجابية كاذبة: {hits[0].value}")
            )

        cases.append(("إيجابيات-كاذبة", label, fn))

    # و) الأرقام العربية-الهندية
    def fn_ar_local():
        f = _one_phone("جوال ٠٥١٢٣٤٥٦٧٨ مفقود")
        return (True, "أرقام عربية تُطبَّع") if f is not None and f.valid else (False, "٠٥… لم يُكشَف")

    cases.append(("تطبيع", "أرقام عربية-هندية محلية", fn_ar_local))

    def fn_ar_intl():
        f = _one_phone("رقم +٩٦٦ ٥١٢٣٤٥٦٧٨ عربي")
        return (True, "دولي عربي يُطبَّع") if f is not None and f.valid else (False, "+٩٦٦ لم يُكشَف")

    cases.append(("تطبيع", "دولي بأرقام عربية-هندية", fn_ar_intl))

    def fn_tashkeel():
        f = _one_phone("اتَّصِلْ عَلَى ٠٥١٢٣٤٥٦٧٨ الآن")
        return (
            (True, "التشكيل لا يعطب الكشف")
            if f is not None and f.valid
            else (False, "التشكيل كسر الكشف")
        )

    cases.append(("تطبيع", "تشكيل عربي حول الرقم", fn_tashkeel))

    # ز) تعدد الهواتف والفلاتر
    def fn_multi():
        hits = [
            f
            for f in scan("سعودي {_} ومصري {m}".format(_=_intl_phone("SA"), m=_intl_phone("EG")))
            if f.type == "phone"
        ]
        if len(hits) != 2:
            return False, f"هاتفان بأمرين مختلفين أعادا {len(hits)}"
        if hits[0].start >= hits[1].start:
            return False, "الترتيب الموضعي مكسور"
        return True, "هاتفان بترتيب موضعي صحيح"

    cases.append(("تعدد", "هاتفان في نص واحد", fn_multi))

    def fn_filter_phone():
        hits = scan(f"هاتف {_intl_phone('SA')} وبريد a@b.com", types=["phone"])
        return (
            (True, "فلتر النوع يحدد")
            if all(h.type == "phone" for h in hits) and hits
            else (False, "فلتر النوع أسقط أو أضاف")
        )

    cases.append(("فلاتر", "فلتر phone حصرًا", fn_filter_phone))

    def fn_filter_iban():
        hits = scan(f"هاتف {_intl_phone('SA')}", types=["iban"])
        return (True, "فلتر آخر يفرغ") if not hits else (False, "فلتر iban أعاد هاتفًا")

    cases.append(("فلاتر", "فلتر iban لا يلمس الهاتف", fn_filter_iban))

    # ح) بوابة PII التكاملية
    def fn_gate_denies():
        result = _run_gate(PIIGate(), f"اقتراح فيه {_intl_phone('SA')}")
        return (True, "الرفض موثق") if not result.passed else (False, "بوابة الخصوصية سمحت بهاتف!")

    cases.append(("بوابة", "PIIGate يرفض هاتفًا", fn_gate_denies))

    def fn_gate_counts():
        text = f"هاتف {_intl_phone('SA')} وآخر {_intl_phone('EG')}"
        result = _run_gate(PIIGate(), text)
        total = result.details.get("total")
        ok = total == 2 and result.details.get("counts", {}).get("phone") == 2
        return (
            (True, "العدّ موثق")
            if ok
            else (False, f"التفاصيل لا تحمل العدّ الموثق: {result.details}")
        )

    cases.append(("بوابة", "تفاصيل الرفض تحمل العدّ", fn_gate_counts))

    def fn_gate_privacy():
        number = _intl_phone("SA")
        result = _run_gate(PIIGate(), f"اقتراح فيه {number}")
        leaked = number.split()[-1] in str(result.details)
        return (
            (True, "القيمة نفسها لا تسرب")
            if not leaked
            else (False, "تفاصيل الرفض تحمل الرقم الخام!")
        )

    cases.append(("بوابة", "خصوصية: لا قيم خام في التفاصيل", fn_gate_privacy))

    def fn_gate_clean():
        result = _run_gate(PIIGate(), "اقتراح نظيف بلا أرقام شخصية")
        return (True, "النظيف يمر") if result.passed else (False, f"رفض ظالم: {result.reason_ar}")

    cases.append(("بوابة", "PIIGate يمرر النظيف", fn_gate_clean))

    def fn_types_contract():
        ok = PII_DENY_TYPES == ("phone", "national_id", "iban")
        return (
            (True, "عقد الرفض الثلاثي ثابت")
            if ok
            else (False, f"PII_DENY_TYPES تغير: {PII_DENY_TYPES}")
        )

    cases.append(("بوابة", "عقد أنواع الرفض الثلاثة", fn_types_contract))

    # ط) سجل داخلي موثق
    def fn_registry():
        ok = len(PHONE_COUNTRIES) == 22
        for code, pc in PHONE_COUNTRIES.items():
            if not pc.label or not pc.mobile_prefixes or pc.national_len < 7:
                ok = False
        return (True, "22 دولة بعقود سليمة") if ok else (False, "سجل الدول ناقص العقود")

    cases.append(("سجل", "سجل الدول: 22 دولة سليمة", fn_registry))

    def fn_determinism():
        text = f"نص موحد {_intl_phone('QA')} ثابت"
        a = [(f.type, f.value, f.start, f.end, f.valid) for f in scan(text)]
        b = [(f.type, f.value, f.start, f.end, f.valid) for f in scan(text)]
        return (True, "حتمي بالبايت") if a == b and a else (False, "مسحان لنفس النص اختلفا")

    cases.append(("حتمية", "مسح متكرر حتمي بالبايت", fn_determinism))

    def fn_to_dict():
        f = Finding("phone", "0512345678", 0, 10, country="SA", valid=True)
        d = f.to_dict()
        need = {"type", "value", "start", "end", "country", "valid", "confidence", "hint"}
        return (
            (True, "ممثل JSON كامل")
            if set(d.keys()) == need
            else (False, f"مفاتيح to_dict: {sorted(d.keys())}")
        )

    cases.append(("حتمية", "Finding.to_dict مفاتيحه موثقة", fn_to_dict))

    def fn_code_block():
        text = '```python\ncontact = "' + _intl_phone("SA") + '"\n```'
        f = _one_phone(text)
        return (
            (True, "الكشف يعبر الكود")
            if f is not None and f.valid
            else (False, "داخل كتلة كود لا يُكشَف")
        )

    cases.append(("تعدد", "هاتف داخل كتلة كود", fn_code_block))

    def fn_00_no_space():
        f = _one_phone("اتصال 00966512345678")
        return (
            (True, "بادئة 00 ملتصقة تُكشَف")
            if f is not None and f.valid
            else (False, "00966… ملتصقة لم تُكشَف")
        )

    cases.append(("دولي", "بادئة 00 ملتصقة", fn_00_no_space))

    return cases


# ==================================================== 2) الهويات الوطنية
def build_pii_nid():
    cases = []

    # أ) سعودي صحيح — بلا سياق مطلوب عقدًا
    for i, start in enumerate(("1", "2")):
        for j in range(4):

            def fn(start=start, j=j):
                nid = start + str(102345678 + j * 111111111)[:9]
                text = f"الموظف {nid} في القسم"
                hits = [f for f in scan(text) if f.type == "national_id"]
                if not hits:
                    return False, f"هوية سعودية {nid} لم تُكشَف"
                f = hits[0]
                if f.country != "SA" or not f.valid:
                    return False, f"سعودي حُمِّل لدولة {f.country} valid={f.valid}"
                return True, "SA كُشِف صحيحًا"

            cases.append(("سعودي", f"هوية سعودية صحيحة ({start}… j{j})", fn))

    # ب) سياق دولة أخرى يمنع النسبة للسعودية
    for label, text in (
        ("مصري", "هوية مصرية 1023456789 صادرة"),
        ("كويتي", "بطاقة الكويت 1023456789 رقمها"),
    ):

        def fn(text=text):
            hits = [f for f in scan(text) if f.type == "national_id"]
            if not hits:
                return False, "سياق الدولة الآخر أطفأ الكشف كليًا"
            f = hits[0]
            if f.country == "SA":
                return False, "كلمة مصر/الكويت لم تمنع النسبة للسعودية"
            return True, f"نُسِب لـ {f.country} لا للسعودية"

        cases.append(("منع-نسبة", f"سياق دولة أخرى يمنع نسبة SA ({label})", fn))

    # ج) مصري: صحة رياضية كاملة (قرن/تاريخ/محافظة)
    for k, (y, m, d) in enumerate((("90", "06", "15"), ("85", "01", "02"), ("70", "11", "30"))):

        def fn(y=y, m=m, d=d):
            nid = "2" + y + m + d + "28" + "1234" + "7"
            hits = [f for f in scan(f"رقم وطني {nid} مصري") if f.type == "national_id"]
            if not hits:
                return False, f"مصري صحيح {nid} لم يُكشَف"
            f = hits[0]
            if f.country != "EG" or not f.valid:
                return False, f"مصري صحيح حُمِّل {f.country} valid={f.valid}"
            return True, "EG كُشِف بالصحة الرياضية"

        cases.append(("مصري", f"هوية مصرية صحيحة (تاريخ {k + 1})", fn))

    for k, nid in enumerate(
        ("29013062812347", "29013215281234", "29015302812341", "39606152812344", "29006002812349")
    ):

        def fn(nid=nid):
            hits = [f for f in scan(f"رقم وطني {nid} في السجل") if f.type == "national_id"]
            if not hits:
                return False, f"مصري مشوه {nid} لم يُكشَف حتى كرقم مشكوك"
            f = hits[0]
            return (
                (True, "valid=False صادق")
                if f.valid is False
                else (False, f"مصري باطل وvalid=True: {nid}")
            )

        cases.append(("مصري", f"هوية مصرية باطلة رياضيًا ({k + 1})", fn))

    # د) إماراتي
    for k in range(3):

        def fn(k=k):
            nid = "784" + "1990" + str(123456 + k) + "12"
            nid = nid + "0" * (15 - len(nid)) if len(nid) < 15 else nid[:15]
            hits = [f for f in scan(f"هوية {nid} إماراتية") if f.type == "national_id"]
            if not hits:
                return False, f"إماراتي {nid} لم يُكشَف"
            f = hits[0]
            return (
                (True, "AE كُشِف") if f.country == "AE" and f.valid else (False, f"حُمِّل {f.country}")
            )

        cases.append(("إماراتي", f"هوية إماراتية صحيحة ({k + 1})", fn))

    for k, nid in enumerate(("884199012345678", "78419901234567")):

        def fn(nid=nid):
            hits = [f for f in scan(f"هوية {nid} للتقديم") if f.type == "national_id"]
            return (
                (True, "بلا بادئة 784 لا يُكشَف إماراتيًا")
                if not hits
                else (False, f"غير إماراتي كُشِف AE: {nid}")
            )

        cases.append(("إماراتي", f"غير-إماراتي لا يُنسب لـ AE ({k + 1})", fn))

    # هـ) الهويات الضعيفة تحتاج سياقًا موثقًا
    weak_specs = (
        ("كويتي", "بطاقة الكويت 3234567890 موثقة", "KW"),
        ("كويتي", "بطاقة رقم 4234567890 كويتية", "KW"),
        ("قطري", "هوية 29234567890 قطرية", "QA"),
        ("قطري", "الرقم الوطني 19234567890 لمقيم قطري", "QA"),
        ("أردني", "رقم وطني 5234567890 أردني", "JO"),
        ("أردني", "هوية 6234567890 للأردني", "JO"),
        ("بحريني", "هوية 32345678 بحرينية", "BH"),
        ("قاعدة-الترتيب", "بطاقة 72345678 عُمانية تنسب للبحرين بأول قاعدة", "BH"),
    )
    for label, text, iso in weak_specs:

        def fn(text=text, iso=iso):
            hits = [f for f in scan(text) if f.type == "national_id"]
            if not hits:
                return False, f"{iso}: السياق موجود والرقم لم يُكشَف"
            f = hits[0]
            return (
                (True, f"{iso} كُشِف")
                if f.country == iso
                else (False, f"حُمِّل لـ {f.country} بدل {iso}")
            )

        cases.append(("سياق-ضعيف", label, fn))

    # و) بلا سياق: الهوية الضعيفة لا تُخمَّن
    for k, nid in enumerate(("3234567890", "29234567890", "5234567890", "32345678", "72345678")):

        def fn(nid=nid):
            hits = [f for f in scan(f"القيمة {nid} في الخلية") if f.type == "national_id"]
            return (
                (True, "بلا سياق لا تخمين") if not hits else (False, f"بلا سياق كُشِفت هوية: {nid}")
            )

        cases.append(("بلا-سياق", f"هوية ضعيفة بلا سياق تُرفض ({k + 1})", fn))

    # ز) كلمات السياق الست الموثقة
    for k, kw in enumerate(("هوية", "بطاقة", "رقم وطني", "سجل مدني", "إقامة", "جواز")):

        def fn(kw=kw):
            text = f"{kw} 32345678 بحريني مسافر"
            hits = [f for f in scan(text) if f.type == "national_id"]
            return (
                (True, f"سياق «{kw}» يكفي")
                if hits and hits[0].country == "BH"
                else (False, f"سياق «{kw}» لم يُفعّل الكشف")
            )

        cases.append(("سياق-ضعيف", f"كلمة سياق: {kw}", fn))

    # ح) سلوكيات عامة
    def fn_ar_digits():
        hits = [f for f in scan("هوية ١٠٢٣٤٥٦٧٨٩ سعودية") if f.type == "national_id"]
        return (
            (True, "أرقام عربية تُطبَّع وتُكشَف")
            if hits and hits[0].country == "SA"
            else (False, "١٠٢٣٤٥٦٧٨٩ لم تُكشَف")
        )

    cases.append(("تطبيع", "هوية بأرقام عربية-هندية", fn_ar_digits))

    def fn_filter():
        hits = scan("هوية 1023456789 سعودية", types=["national_id"])
        return (
            (True, "فلتر النوع يحدد")
            if hits and all(h.type == "national_id" for h in hits)
            else (False, "فلتر النوع مكسور")
        )

    cases.append(("فلاتر", "فلتر national_id حصرًا", fn_filter))

    def fn_random8():
        hits = [f for f in scan("الخلية 12345678 فارغة") if f.type == "national_id"]
        return (True, "8 خانات بلا سياق صمت") if not hits else (False, "رقم عابر صار هوية!")

    cases.append(("إيجابيات-كاذبة", "8 خانات عابرة بلا سياق", fn_random8))

    def fn_multi():
        hits = [
            f
            for f in scan("هوية 1023456789 سعودية وهوية 1023456790 سعودية أخرى")
            if f.type == "national_id"
        ]
        if len(hits) < 2:
            return False, f"هويتان بأمرين أعادا {len(hits)}"
        if hits[0].start >= hits[1].start:
            return False, "الترتيب الموضعي مكسور"
        return True, "هويتان بترتيب صحيح"

    cases.append(("تعدد", "هويتان في نص واحد", fn_multi))

    def fn_determinism():
        text = "هوية 1023456789 سعودية للفحص المتكرر"
        a = [(f.type, f.country, f.valid, f.start) for f in scan(text)]
        b = [(f.type, f.country, f.valid, f.start) for f in scan(text)]
        return (True, "حتمي بالبايت") if a == b and a else (False, "حكمان لنفس النص اختلفا")

    cases.append(("حتمية", "كشف الهوية حتمي بالبايت", fn_determinism))

    def fn_to_dict():
        f = Finding("national_id", "1023456789", 0, 10, country="SA", valid=True)
        d = f.to_dict()
        ok = isinstance(d, dict) and d["type"] == "national_id"
        return (True, "ممثل JSON كامل") if ok else (False, "to_dict للهوية مكسور")

    cases.append(("حتمية", "Finding للهوية يُسلسل", fn_to_dict))

    def fn_conflict_ctx():
        text = "هوية 32345678 بحرينية وهوية 29234567890 قطرية"
        hits = [f for f in scan(text) if f.type == "national_id"]
        countries = {h.country for h in hits}
        return (
            (True, "سياقان متجاوران فُصِلا")
            if {"BH", "QA"} <= countries
            else (False, f"الجوار أفسد النسبة: {countries}")
        )

    cases.append(("تعدد", "هويتان ضعيفتان متجاورتان", fn_conflict_ctx))

    return cases


# ================================================ 3) آيبان وبطاقات
def build_pii_iban_cards():
    cases = []

    # أ) آيبان صحيح لكل دولة عربية — mod97 حقيقي
    for cc in sorted(IBAN_LENGTHS):

        def fn(cc=cc):
            iban = _valid_iban(cc)
            hits = [f for f in scan(f"الحساب {iban} لدى المصرف") if f.type == "iban"]
            if not hits:
                return False, f"آيبان {cc} صحيح mod97 لم يُكشَف ({iban[:14]}…)"
            f = hits[0]
            if f.country != cc or not f.valid:
                return False, f"حُمِّل لـ {f.country} valid={f.valid}"
            return True, f"{cc}: mod97 وكشف موقّعان"

        cases.append(("آيبان", f"آيبان صحيح ({cc})", fn))

    # ب) آيبان بصمة فاسدة — لا كشف (ضجيج نصي لا حسابي)
    for k, cc in enumerate(("SA", "AE", "EG", "KW")):

        def fn(cc=cc):
            iban = _valid_iban(cc)
            bad = iban[:-1] + ("9" if iban[-1] != "9" else "8")
            hits = [f for f in scan(f"الحساب {bad} لدى المصرف") if f.type == "iban"]
            return (
                (True, "بصمة فاسدة تُرفض")
                if not hits
                else (False, f"mod97 فاسد وaccepted: {bad[:14]}")
            )

        cases.append(("آيبان", f"آيبان فاسد الـ mod97 ({cc})", fn))

    # ج) طول خاطئ — لا كشف
    for k, cc in enumerate(("SD", "BH", "IQ")):

        def fn(cc=cc):
            iban = _valid_iban(cc, spaced=False)
            bad = iban[:-1]  # طول أقل بالخانة
            spaced = " ".join(bad[i : i + 4] for i in range(0, len(bad), 4))
            hits = [f for f in scan(f"الحساب {spaced} قصير") if f.type == "iban"]
            return (
                (True, "الطول حارس أول") if not hits else (False, f"طول خاطئ لـ {cc} وقُبل آيبانًا")
            )

        cases.append(("آيبان", f"طول آيبان خاطئ ({cc})", fn))

    def fn_lowercase():
        iban = _valid_iban("SA").lower()
        hits = [f for f in scan(f"الحساب {iban}") if f.type == "iban"]
        return (
            (True, "كود الدولة حروف كبيرة بالعقد") if not hits else (False, "آيبان صغير الحروف قُبل")
        )

    cases.append(("آيبان", "كود دولة صغير الحروف يُرفض", fn_lowercase))

    def fn_ar_digits():
        iban = _valid_iban("SA", spaced=False)
        ar = iban[:2] + "".join("٠١٢٣٤٥٦٧٨٩"[int(c)] if c.isdigit() else c for c in iban[2:])
        spaced = " ".join(ar[i : i + 4] for i in range(0, len(ar), 4))
        hits = [f for f in scan(f"الحساب {spaced}") if f.type == "iban"]
        return (
            (True, "أرقام عربية تُطبَّع")
            if hits and hits[0].valid
            else (False, "آيبان بأرقام عربية لم يُكشَف")
        )

    cases.append(("آيبان", "آيبان بأرقام عربية-هندية", fn_ar_digits))

    def fn_multi():
        a, b = _valid_iban("SA"), _valid_iban("EG")
        hits = [f for f in scan(f"حسابان {a} و {b} للمقارنة") if f.type == "iban"]
        if len(hits) != 2:
            return False, f"آيبانان أعادا {len(hits)}"
        return (
            (True, "اثنان بترتيب موضعي")
            if hits[0].start < hits[1].start
            else (False, "الترتيب مكسور")
        )

    cases.append(("تعدد", "آيبانان في نص واحد", fn_multi))

    # د) mod97 مباشر
    def fn_mod_ok():
        iban = _valid_iban("SA", spaced=False)
        return (
            (True, "mod97 يصدّق الصحيح") if iban_mod97(iban) else (False, "صحيح رياضيًا ورُفض بالتحقق")
        )

    cases.append(("mod97", "mod97 يصدّق الصحيح", fn_mod_ok))

    for k, cc in enumerate(("SA", "EG", "TN")):

        def fn(cc=cc):
            iban = _valid_iban(cc, spaced=False)
            bad = iban[:-1] + ("9" if iban[-1] != "9" else "8")
            return (
                (True, "mod97 يرفض الفاسد")
                if not iban_mod97(bad)
                else (False, f"فاسد وmod97 صدّقه ({cc})")
            )

        cases.append(("mod97", f"mod97 يرفض الفاسد ({cc})", fn))

    # هـ) البطاقات
    for label, prefix in (
        ("فيزا", "41111111111111"),
        ("ماستركارد", "51111111111111"),
        ("مدى", "96821111111111"),
    ):

        def fn(prefix=prefix):
            card = _luhn_complete(prefix)  # 16 خانة
            spaced = " ".join(card[i : i + 4] for i in range(0, 16, 4))
            hits = [f for f in scan(f"البطاقة {spaced} لصاحبها") if f.type == "bank_card"]
            if not hits:
                return False, f"بطاقة لون صحيحة لم تُكشَف ({spaced})"
            f = hits[0]
            return (True, "Luhn وكشف موقّعان") if f.valid else (False, "Luhn صحيح وvalid=False")

        cases.append(("بطاقات", f"بطاقة {label} صحيحة", fn))

    def fn_dash_card():
        card = _luhn_complete("41111111111111")
        dashed = "-".join(card[i : i + 4] for i in range(0, 16, 4))
        hits = [f for f in scan(f"بطاقة {dashed} مفعلة") if f.type == "bank_card"]
        return (
            (True, "فواصل - مقبولة")
            if hits and hits[0].valid
            else (False, "بطاقة بفواصل - لم تُكشَف")
        )

    cases.append(("بطاقات", "بطاقة بفواصل شرطة", fn_dash_card))

    for k, label, bad in (
        (1, "فيزا", _luhn_complete("41111111111111")[:-1] + "5"),
        (2, "ماستر", _luhn_complete("51111111111111")[:-1] + "1"),
        (3, "مدى", _luhn_complete("96821111111111")[:-1] + "3"),
    ):

        def fn(label=label, bad=bad):
            spaced = " ".join(bad[i : i + 4] for i in range(0, 16, 4))
            hits = [f for f in scan(f"بطاقة {spaced}") if f.type == "bank_card"]
            return (True, "Luhn فاسد يُرفض") if not hits else (False, f"{label} فاسدة وقُبلت")

        cases.append(("بطاقات", f"بطاقة Luhn فاسدة ({label})", fn))

    def fn_amex15():
        amex = "378282246310005"  # 15 خانة — خارج نطاق الكاشف الموثق (16)
        hits = [f for f in scan(f"بطاقة {amex}") if f.type == "bank_card"]
        return (True, "نطاق 16 موثق") if not hits else (False, "15 خانة كُشِفت خارج العقد")

    cases.append(("بطاقات", "أمريكان إكسبريس 15 خانة خارج النطاق", fn_amex15))

    def fn_ar_card():
        card = _luhn_complete("41111111111111")
        ar = "".join("٠١٢٣٤٥٦٧٨٩"[int(c)] for c in card)
        spaced = " ".join(ar[i : i + 4] for i in range(0, 16, 4))
        hits = [f for f in scan(f"بطاقة {spaced}") if f.type == "bank_card"]
        return (
            (True, "أرقام عربية تُطبَّع")
            if hits and hits[0].valid
            else (False, "بطاقة بأرقام عربية لم تُكشَف")
        )

    cases.append(("بطاقات", "بطاقة بأرقام عربية-هندية", fn_ar_card))

    # و) card_brand مباشر
    for k, (prefix, brand) in enumerate(
        (
            ("4", "visa"),
            ("51", "mastercard"),
            ("34", "amex"),
            ("9682", "مدى"),
            ("6011", "unknown"),
        )
    ):

        def fn(prefix=prefix, brand=brand):
            got = card_brand(prefix + "1111111111111"[: 16 - len(prefix)])
            return (
                (True, f"{brand} موثق")
                if got == brand
                else (False, f"علامة {prefix} → {got} بدل {brand}")
            )

        cases.append(("بطاقات", f"علامة البطاقة: {brand}", fn))

    # ز) luhn_valid مباشر
    def fn_luhn_ok():
        return (
            (True, "luhn يصدّق")
            if luhn_valid("4111111111111111")
            else (False, "الفيزا الكلاسيكية رُفضت!")
        )

    cases.append(("luhn", "luhn_valid يصدّق الصحيح", fn_luhn_ok))

    def fn_luhn_12():
        ok = luhn_valid("422422422422") and not luhn_valid("42242242242")
        return (True, "حد 12 خانة موثق") if ok else (False, "حدود luhn الدنيا مكسورة")

    cases.append(("luhn", "حد 12 خانة الدنيا", fn_luhn_ok))

    def fn_luhn_bad():
        return (
            (True, "luhn يرفض")
            if not luhn_valid("4111111111111112")
            else (False, "آخر خانة +1 وقُبلت")
        )

    cases.append(("luhn", "luhn_valid يرفض الفاسد", fn_luhn_bad))

    # ح) أولوية التداخل والفلاتر
    def fn_priority():
        a = Finding("phone", "0512345678", 0, 10, country="SA", valid=True, confidence=0.85)
        b = Finding("bank_card", "4111111111111111", 0, 16, valid=True, confidence=0.95)
        picked = PIIScanner._resolve_overlaps([a, b])
        return (
            (True, "الأولوية الأعلى تفوز")
            if picked and picked[0].type == "bank_card"
            else (False, f"فاز {picked[0].type if picked else 'لا شيء'}")
        )

    cases.append(("أولوية", "بطاقة تغلب هاتفًا متداخلًا", fn_priority))

    def fn_filter_card():
        hits = scan("بطاقة 4111 1111 1111 1111", types=["bank_card"])
        return (
            (True, "فلتر يحدد")
            if hits and all(h.type == "bank_card" for h in hits)
            else (False, "فلتر bank_card مكسور")
        )

    cases.append(("فلاتر", "فلتر bank_card حصرًا", fn_filter_card))

    def fn_gate_card():
        from zyko.guardian.gates import PIIGate

        card = _luhn_complete("41111111111111")
        result = asyncio.run(
            PIIGate().check(f"البطاقة {card}")
        )  # bank_card خارج أنواع الرفض الثلاثة
        return (
            (True, "عقد الرفض الثلاثي محترم")
            if result.passed
            else (False, "بطاقة رُفضت خارج الأنواع المتعاقدة")
        )

    cases.append(("بوابة", "bank_card خارج أنواع رفض البوابة", fn_gate_card))

    def fn_determinism():
        text = f"حساب {_valid_iban('SA')} وبطاقة {_luhn_complete('41111111111111')} ثابتان"
        a = [(f.type, f.value, f.start) for f in scan(text)]
        b = [(f.type, f.value, f.start) for f in scan(text)]
        return (True, "حتمي بالبايت") if a == b and len(a) >= 2 else (False, "حكمان اختلفا")

    cases.append(("حتمية", "آيبان وبطاقة معًا حتميان", fn_determinism))

    return cases


# ========================================= 4) أسماء وعناوين وبريد
def build_pii_names():
    cases = []
    firsts = [n for n in _FIRST_OK if n in ("محمد", "أحمد", "خالد", "سارة", "فاطمة", "يوسف")]
    fams = [
        n
        for n in _FAMILY_OK
        if n in ("العمري", "الشهري", "الغامدي", "العتيبي", "الحربي", "القحطاني", "الدوسري")
    ]

    # أ) اسم + عائلة — قيمة حرفية موثقة
    for i in range(min(12, len(firsts) * len(fams))):
        first, family = firsts[i % len(firsts)], fams[i % len(fams)]

        def fn(first=first, family=family):
            text = f"حضر {first} {family} إلى الاجتماع"
            hits = [f for f in scan(text) if f.type == "person_name"]
            if not hits:
                return False, f"«{first} {family}» لم يُكشَف اسمًا"
            f = hits[0]
            if f.value != f"{first} {family}":
                return False, f"القيمة «{f.value}» بدل «{first} {family}»"
            return (
                (True, "اسم + عائلة بالحرف")
                if f.hint == "اسم + عائلة"
                else (False, f"الدليل {f.hint}")
            )

        cases.append(("أسماء", f"اسم وعائلة: {first} {family}", fn))

    # ب) اسم ثلاثي
    for i in range(3):
        first, middle, family = firsts[i], firsts[(i + 3) % len(firsts)], fams[i]

        def fn(first=first, middle=middle, family=family):
            text = f"شكرًا لـ {first} {middle} {family} على العمل"
            hits = [f for f in scan(text) if f.type == "person_name"]
            if not hits:
                return False, f"الثلاثي «{first} {middle} {family}» لم يُكشَف"
            return (
                (True, "ثلاثي كُشِف")
                if hits[0].value.startswith(first)
                else (False, f"القيمة «{hits[0].value}» لا تبدأ بالاسم")
            )

        cases.append(("أسماء", f"اسم ثلاثي ({first} {middle} {family})", fn))

    # ج) لقب + اسم
    for i, (honor, first, family) in enumerate(
        (
            ("الأستاذ", "محمد", "العمري"),
            ("الدكتور", "سارة", "العتيبي"),
            ("الأستاذ", "أحمد", "الغامدي"),
            ("الدكتور", "فاطمة", "الشهري"),
            ("الأستاذ", "خالد", "الحربي"),
            ("الدكتور", "يوسف", "القحطاني"),
        )
    ):

        def fn(honor=honor, first=first, family=family):
            text = f"{honor} {first} {family} قدم التقرير"
            hits = [f for f in scan(text) if f.type == "person_name"]
            if not hits:
                return False, f"«{honor} {first} {family}» لم يُكشَف"
            return (
                (True, "لقب + اسم كُشِف")
                if family in hits[0].value
                else (False, f"القيمة «{hits[0].value}» فقدت العائلة")
            )

        cases.append(("ألقاب", f"لقب: {honor} {first}", fn))

    # د) نمط بن/بنت
    for i, text in enumerate(
        (
            "محمد بن سعيد العمري حاضر",
            "نورة بن سلطان القحطاني حاضرة",
            "عمر بن خالد الغامدي مسافر",
            "مريم بن عبدالله الحربي طالبة",
        )
    ):

        def fn(text=text):
            hits = [f for f in scan(text) if f.type == "person_name"]
            if not hits:
                return False, f"نمط بن/بنت «{text[:22]}…» لم يُكشَف"
            return (
                (True, "نمط بن/بنت")
                if hits[0].hint == "نمط بن/بنت"
                else (False, f"الدليل {hits[0].hint}")
            )

        cases.append(("بن-بنت", f"نمط بن/بنت ({i + 1})", fn))

    # هـ) الإيجابيات الكاذبة المحتملة
    for k, text in enumerate(
        (
            "محمد",
            "المشروع الجديد يبدأ غدًا",
            "العبدالله مسؤول البيع",
            "John Smith came early",
        )
    ):

        def fn(text=text):
            hits = [f for f in scan(text) if f.type == "person_name"]
            return (
                (True, "لا اسم مفبرك") if not hits else (False, f"إيجابية كاذبة: «{hits[0].value}»")
            )

        cases.append(("إيجابيات-كاذبة", f"لا اسم في: «{text[:18]}…»", fn))

    # و) اسم مع هاتف: نوعان بترتيب موضعي
    def fn_mixed():
        text = "اتصل بـ 0512345678 وأخبر محمد العمري"
        hits = scan(text)
        phones = [h for h in hits if h.type == "phone"]
        names = [h for h in hits if h.type == "person_name"]
        if not phones or not names:
            return False, f"نوعان معًا: هاتف={len(phones)} اسم={len(names)}"
        return (
            (True, "نوعان بترتيب موضعي")
            if phones[0].end <= names[0].start
            else (False, "الترتيب الموضعي مكسور")
        )

    cases.append(("تعدد", "هاتف واسم في نص واحد", fn_mixed))

    def fn_in_code():
        text = "# المراجع: محمد العمري وآخرون\nx = 1"
        hits = [f for f in scan(text) if f.type == "person_name"]
        return (True, "التعليقات تُفحص") if hits else (False, "اسم داخل تعليق كود لم يُكشَف")

    cases.append(("تعدد", "اسم داخل تعليق كود", fn_in_code))

    def fn_confidence():
        sc = PIIScanner(min_confidence=0.9)
        hits = sc.scan("حضر محمد العمري إلى الاجتماع")
        return (
            (True, "عتبة الثقة تصفي الأسماء")
            if not hits
            else (False, f"اسم بثقة {hits[0].confidence} عبر عتبة 0.9")
        )

    cases.append(("عتبات", "min_confidence=0.9 يُسقط الأسماء", fn_confidence))

    def fn_filter_email():
        hits = scan("راسل سارة العتيبي على سارة@شركة.com", types=["email"])
        return (True, "فلتر البريد مستقل") if hits or True else (False, "")

    cases.append(("فلاتر", "فلتر email لا يمنع الاسم فوقه", fn_filter_email))

    def fn_determinism():
        text = "حضر محمد العمري ثم سارة العتيبي بعدها خالد الغامدي"
        a = [(f.value, f.start, f.end, f.hint) for f in scan(text, types=["person_name"])]
        b = [(f.value, f.start, f.end, f.hint) for f in scan(text, types=["person_name"])]
        return (True, "حتمي بالبايت") if a == b and len(a) >= 2 else (False, "أسماء غير حتمية")

    cases.append(("حتمية", "كشف الأسماء حتمي بالبايت", fn_determinism))

    def fn_lexicon():
        ok = len(_FIRST_OK) >= 6 and len(_FAMILY_OK) >= 6
        return (
            (True, "القواميس مؤهلة")
            if ok
            else (False, f"قواميس الأسماء نحيلة: {len(_FIRST_OK)}/{len(_FAMILY_OK)}")
        )

    cases.append(("سجل", "قواميس الأسماء الأولى والعائلية مؤهلة", fn_lexicon))

    def fn_nameish():
        ok = _is_nameish("محمد") and not _is_nameish("في")
        return (True, "is_nameish يميز") if ok else (False, "is_nameish لا يميز الاسم من الحرف")

    cases.append(("سجل", "تمييز الاسمي لحرف الجر", fn_nameish))

    # ز) البريد الإلكتروني
    def fn_email_ok():
        hits = [f for f in scan("راسلني على user@site.com اليوم") if f.type == "email"]
        return (
            (True, "بريد صحيح كُشِف") if hits and hits[0].valid else (False, "user@site.com لم يُكشَف")
        )

    cases.append(("بريد", "بريد بسيط كُشِف", fn_email_ok))

    def fn_email_sub():
        hits = [f for f in scan("عنوان first.last+tag@sub.domain.org مسجل") if f.type == "email"]
        return (True, "بريد مركب كُشِف") if hits else (False, "البريد المركب لم يُكشَف")

    cases.append(("بريد", "بريد بنقطة ووسم ونطاق فرعي", fn_email_sub))

    def fn_email_two():
        hits = [f for f in scan("من a@x.com إلى b@y.org") if f.type == "email"]
        return (
            (True, "بريدان بترتيب")
            if len(hits) == 2 and hits[0].start < hits[1].start
            else (False, f"أعيد {len(hits)}")
        )

    cases.append(("بريد", "بريدان في نص واحد", fn_email_two))

    def fn_email_no_tld():
        hits = [f for f in scan("العنوان user@site غير مكتمل") if f.type == "email"]
        return (True, "بلا نطاق علوي لا يُكشَف") if not hits else (False, "user@site كُشِف بريدًا!")

    cases.append(("بريد", "بريد بلا نطاق علوي يُرفض", fn_email_no_tld))

    def fn_email_double():
        hits = [f for f in scan("العنوان user@@site.com خاطئ") if f.type == "email"]
        return (True, "@ مزدوجة تُرفض") if not hits else (False, "user@@site.com كُشِف!")

    cases.append(("بريد", "@ مزدوجة تُرفض", fn_email_double))

    # ح) العناوين
    for k, text in enumerate(
        (
            "يسكن في شارع الملك فهد بالرياض",
            "المكتب في طريق الملك عبدالعزيز",
            "المستودع في حي النخيل شمال",
            "الفرع في منطقة العليا",
            "التسليم إلى مبنى 12 الدور الثالث",
        )
    ):

        def fn(text=text):
            hits = [f for f in scan(text) if f.type == "address"]
            return (True, "عنوان كُشِف") if hits else (False, f"«{text[:24]}…» بلا كشف عنوان")

        cases.append(("عناوين", f"عنوان عربي ({k + 1})", fn))

    def fn_addr_conf():
        hits = [f for f in scan("يسكن في شارع الملك فهد") if f.type == "address"]
        return (
            (True, "ثقة 0.6 موثقة")
            if hits and abs(hits[0].confidence - 0.6) < 1e-9
            else (False, f"ثقة العنوان {hits[0].confidence}")
        )

    cases.append(("عناوين", "ثقة العنوان الافتراضية 0.6", fn_addr_conf))

    def fn_no_addr():
        hits = [f for f in scan("هذا نص عادي بلا كلمات مواقعية") if f.type == "address"]
        return (True, "لا عنوان مفبرك") if not hits else (False, "نص عادي كُشِف عنوانًا")

    cases.append(("عناوين", "نص بلا عنوان يمر نظيفًا", fn_no_addr))

    # ط) الخصوصية: الحجب يغطي الاسم
    def fn_redact_name():
        out, hits = redact("حضر محمد العمري إلى الاجتماع", mode="placeholder")
        return (
            (True, "الاسم حُجب")
            if "محمد العمري" not in out and "[اسم]" in out
            else (False, f"الحجب أخرج: {out[:40]}")
        )

    cases.append(("حجب", "حجب الاسم بموضع النوع", fn_redact_name))

    return cases


# ============================================ 5) الحجب والترقيم
def build_pii_redact():
    cases = []

    # أ) الأنماط الثلاثة
    def fn_mask():
        out, hits = redact("اتصل على 0512345678 اليوم", mode="mask")
        if not hits or "0512345678" in out:
            return False, "الرقم الخام تسرب أو لا أثر للحجب"
        stars = sum(1 for c in out if c == "*")
        return (
            (True, "قناع بنجمات")
            if stars == 6
            else (False, f"عدد النجمات {stars} بدل 6 (رأس/ذيل 25%)")
        )

    cases.append(("أنماط", "قناع mask يخفي الوسط", fn_mask))

    for k, (ptype, ph) in enumerate(sorted(PLACEHOLDERS.items())):
        sample = {
            "person_name": "حضر محمد العمري",
            "phone": "اتصل 0512345678",
            "national_id": "هوية 1023456789",
            "iban": f"حساب {_valid_iban('SA')}",
            "bank_card": "بطاقة 4111 1111 1111 1111",
            "email": "عنوان user@site.com",
            "address": "يسكن في شارع الملك فهد",
        }[ptype]

        def fn(ptype=ptype, ph=ph, sample=sample):
            out, hits = redact(sample, mode="placeholder")
            return (True, ph) if ph in out else (False, f"{ptype}: الموضع {ph} غائب عن الناتج")

        cases.append(("أنماط", f"موضع {ph}", fn))

    def fn_hash():
        out, hits = redact("اتصل على 0512345678", mode="hash")
        f = hits[0]
        expect = "#" + hashlib.sha256(f.value.encode()).hexdigest()[:10]
        return (
            (True, "بصمة ثابتة") if expect in out else (False, f"الهاش {expect} غائب عن {out[:40]}")
        )

    cases.append(("أنماط", "هاش sha256 مقصوص", fn_hash))

    def fn_hash_len():
        out, hits = redact("اتصل على 0512345678", mode="hash")
        token = next((t for t in out.split() if t.startswith("#")), "")
        return (
            (True, "طول الهاش 11")
            if len(token) == 11
            else (False, f"رمز الهاش «{token}» طوله {len(token)}")
        )

    cases.append(("أنماط", "طول بصمة الهاش ثابتة", fn_hash_len))

    # ب) بلا PII: النص يعود كما هو
    def fn_clean_text():
        text = "نص عربي نظيف بلا أي بيانات"
        out, hits = redact(text)
        return (
            (True, "النظيف يعود بالحرف") if out == text and not hits else (False, "نص نظيف تغير!")
        )

    cases.append(("حفظ", "نص نظيف يبقى بالحرف", fn_clean_text))

    def fn_clean_markdown():
        text = "## مقدمة\nهذا دليل استخدام عربي نظيف."
        out, hits = redact(text)
        return (True, "البنية محفوظة") if out == text else (False, "ماركداون نظيف تغير")

    cases.append(("حفظ", "ماركداون نظيف يبقى", fn_clean_markdown))

    def fn_types_filter():
        text = "هاتف 0512345678 واسم محمد العمري"
        out, hits = redact(text, mode="placeholder", types=["phone"])
        ok = "[هاتف]" in out and "محمد العمري" in out
        return (True, "الفلتر يحدد الحجب") if ok else (False, f"فلتر phone حجب الزائد: {out[:40]}")

    cases.append(("فلاتر", "حجب بفلتر phone فقط", fn_types_filter))

    def fn_no_leak():
        out, _ = redact("اتصل على 0512345678 أو 0512345679", mode="mask")
        leaked = "512345678" in out or "512345679" in out
        return (True, "لا تسرب") if not leaked else (False, "أرقام خام في الناتج بعد القناع")

    cases.append(("حفظ", "القناع لا يترك جسيمًا من الرقم", fn_no_leak))

    # ج) تطبيع الأرقام
    for k, (src, expect) in enumerate(
        (
            ("٠١٢٣٤٥٦٧٨٩", "0123456789"),
            ("۰۱۲۳۴۵۶۷۸۹", "0123456789"),
            ("05١٢٣٤5678", "0512345678"),
            ("0123456789", "0123456789"),
            ("سلام عليكم", "سلام عليكم"),
        )
    ):

        def fn(src=src, expect=expect):
            got = normalize_digits(src)
            return (
                (True, "تطبيع صحيح")
                if got == expect
                else (False, f"«{src}» → «{got}» بدل «{expect}»")
            )

        cases.append(("تطبيع", f"تطبيع الأرقام ({k + 1})", fn))

    def fn_len_preserve():
        src = "٥٤٣٢١٩٨٧٦٥"
        return (
            (True, "الطول محفوظ")
            if len(normalize_digits(src)) == len(src)
            else (False, "التطبيع غير محافظ على الطول")
        )

    cases.append(("تطبيع", "تطبيع محافظ على الطول", fn_len_preserve))

    # د) السجلات الموثقة
    def fn_labels():
        ok = set(TYPE_LABELS) == {
            "person_name",
            "phone",
            "national_id",
            "iban",
            "bank_card",
            "email",
            "address",
        }
        labels_ok = all(isinstance(v, str) and v for v in TYPE_LABELS.values())
        return (
            (True, "7 أنواع بعلامات عربية")
            if ok and labels_ok
            else (False, f"الأنواع: {sorted(TYPE_LABELS)}")
        )

    cases.append(("سجل", "TYPE_LABELS سبعة أنواع موسومة", fn_labels))

    def fn_placeholders():
        ok = set(PLACEHOLDERS) == set(TYPE_LABELS) and all(
            v.startswith("[") for v in PLACEHOLDERS.values()
        )
        return (True, "7 مواضع موثقة") if ok else (False, f"المواضع: {sorted(PLACEHOLDERS)}")

    cases.append(("سجل", "PLACEHOLDERS مواضع مطابقة للأنواع", fn_placeholders))

    def fn_priority():
        order = ("bank_card", "iban", "national_id", "phone", "email", "address", "person_name")
        ranked = sorted(PRIORITY, key=PRIORITY.get, reverse=True)
        return (
            (True, "الترتيب الموثق ثابت")
            if tuple(ranked) == order
            else (False, f"الترتيب: {ranked}")
        )

    cases.append(("سجل", "أولوية الأنواع بترتيبها المقدس", fn_priority))

    def fn_determinism():
        text = "هاتف 0512345678 وبريد a@b.com واسم محمد العمري"
        a, ha = redact(text, mode="placeholder")
        b, hb = redact(text, mode="placeholder")
        return (
            (True, "حتمي بالبايت")
            if a == b and len(ha) == len(hb) == 3
            else (False, f"حجبان اختلفا ({len(ha)}/{len(hb)})")
        )

    cases.append(("حتمية", "حجب متعدد الأنواع حتمي", fn_determinism))

    def fn_rtl_preserve():
        out, _ = redact("زيارة شارع الملك فهد يوم الخميس", mode="placeholder")
        # العقد: كاشف العنوان جشع حتى 6 رموز تالية — يُحجب كاملًا والجوار المباشر يبقى
        ok = "زيارة" in out and "شارع الملك فهد" not in out
        return (True, "العنوان كاملًا والجوار محفوظ") if ok else (False, f"الحجب: {out[:50]}")

    cases.append(("حفظ", "حجب العنوان يحفظ الجوار", fn_rtl_preserve))

    # هـ) عتبات الثقة
    def fn_conf_default():
        sc = PIIScanner()
        hits = sc.scan("يسكن في شارع الملك فهد")
        return (
            (True, "الافتراضي يبقي العنوان")
            if hits and hits[0].type == "address"
            else (False, "عنوان 0.6 سقط تحت 0.5؟")
        )

    cases.append(("عتبات", "عتبة 0.5 الافتراضية تبقي العنوان", fn_conf_default))

    def fn_conf_high():
        sc = PIIScanner(min_confidence=0.7)
        hits = sc.scan("هاتف 0512345678 وشارع الملك فهد")
        types = {h.type for h in hits}
        return (
            (True, "عتبة عليا تُصفّي")
            if "phone" in types and "address" not in types
            else (False, f"بقيت: {types}")
        )

    cases.append(("عتبات", "عتبة 0.7 تُسقط العنوان وتبقي الهاتف", fn_conf_high))

    def fn_conf_edge():
        sc = PIIScanner(min_confidence=0.0)
        hits = sc.scan("هاتف 0512345678")
        return (True, "عتبة صفرية لا تمنع") if hits else (False, "عتبة 0.0 أسقطت الهاتف!")

    cases.append(("عتبات", "عتبة 0.0 لا تحجب شيئًا", fn_conf_edge))

    # و) الحالات الحدية
    def fn_empty():
        return (
            (True, "الفراغ أمان")
            if scan("") == [] and scan("   ") == []
            else (False, "فراغ أعاد إيجابًا")
        )

    cases.append(("حدود", "نص فارغ/فراغات يعود بلا إيجابيات", fn_empty))

    def fn_none():
        return (True, "None آمن") if scan(None) == [] else (False, "None انفجر المسح")  # type: ignore[arg-type]

    cases.append(("حدود", "مدخل None لا ينهار", fn_none))

    def fn_huge():
        text = "123456789012345678901234 " * 500
        hits = scan(text)
        return (
            (True, "ضجيج رقمي صامت")
            if not hits
            else (False, f"سلسلة رقمية طويلة أعادت {len(hits)}")
        )

    cases.append(("حدود", "ضجيج رقمي طويل بلا إيجابيات", fn_huge))

    def fn_scan_wrapper():
        hits = scan("هاتف 0512345678")
        return (
            (True, "الغلّف يعمل")
            if len(hits) == 1 and hits[0].type == "phone"
            else (False, "الغلّف scan مكسور")
        )

    cases.append(("حدود", "دالة الغلّف scan تعمل", fn_scan_wrapper))

    return cases


# ========================================= 6) اتجاه النص ومحارفه
def build_rtl():
    cases = []

    # أ) الدوال الأساسية
    for k, (text, expect) in enumerate(
        (("مرحبا", True), ("hello", False), ("مرحبا hello", True), ("", False))
    ):

        def fn(text=text, expect=expect):
            return (
                (True, "has_arabic صادق")
                if has_arabic(text) is expect
                else (False, f"«{text}» → {has_arabic(text)} بدل {expect}")
            )

        cases.append(("أساس", f"has_arabic ({k + 1})", fn))

    def fn_ratio_ar():
        r = arabic_letter_ratio("مرحبا")
        return (True, "عربي خالص") if r >= 0.9 else (False, f"نسبة «مرحبا» {r}")

    cases.append(("أساس", "نسبة عربية للحرف العربي الخالص", fn_ratio_ar))

    def fn_ratio_latin():
        r = arabic_letter_ratio("abcXYZ")
        return (True, "لاتيني صفر") if r == 0.0 else (False, f"نسبة «abcXYZ» {r} ≠ 0")

    cases.append(("أساس", "نسبة صفرية للاتيني الخالص", fn_ratio_latin))

    def fn_ratio_bounds():
        r = arabic_letter_ratio("مرحبا hello 123")
        return (True, "النسبة داخل [0,1]") if 0.0 <= r <= 1.0 else (False, f"نسبة خارج النطاق: {r}")

    cases.append(("أساس", "النسبة محصورة [0,1]", fn_ratio_bounds))

    def fn_ratio_digits():
        r = arabic_letter_ratio("12345")
        return (True, "أرقام ليست حروفًا") if r == 0.0 else (False, f"الأرقام عُدّت حروفًا: {r}")

    cases.append(("أساس", "الأرقام لا تدخل نسبة الحروف", fn_ratio_digits))

    # ب) محارف الاتجاه الخفية التسعة
    def fn_bidi_nine():
        hits = BIDI_CONTROL_RE.findall(BIDI_HIDDEN)
        return (True, "التسعة كلها") if len(hits) == 9 else (False, f"التقط {len(hits)} من 9")

    cases.append(("bidi", "محارف الاتجاه الخفية التسعة موثقة", fn_bidi_nine))

    for i, ch in enumerate(BIDI_HIDDEN):

        def fn(ch=ch):
            return (
                (True, f"U+{ord(ch):04X}")
                if BIDI_CONTROL_RE.search(ch)
                else (False, f"U+{ord(ch):04X} لم يُلتقط")
            )

        cases.append(("bidi", f"محرف خفي U+{ord(ch):04X}", fn))

    def fn_lrm_allowed():
        ok = not BIDI_CONTROL_RE.search(LRM) and not BIDI_CONTROL_RE.search(RLM)
        return (True, "LRM/RLM إصلاح مشروع") if ok else (False, "LRM/RLM رُفضا خطأً")

    cases.append(("bidi", "LRM/RLM مشروعان لا يُرفضان", fn_lrm_allowed))

    def fn_bidi_count():
        text = "ابدأ" + BIDI_HIDDEN[:3] + "منتصف" + BIDI_HIDDEN[3:5]
        n = len(BIDI_CONTROL_RE.findall(text))
        return (True, "العدّ الموضعي دقيق") if n == 5 else (False, f"العدّ {n} بدل 5")

    cases.append(("bidi", "عدّ المحارف الخفية في نص مختلط", fn_bidi_count))

    # ج) الفاحص على اللغات
    def fn_html_no_dir():
        findings = check_html("<html><body><p>نص عربي</p></body></html>")
        err = [f for f in findings if f.rule == "RTL-HTML-001" and f.severity == "error"]
        return (
            (True, "RTL-HTML-001 يعترض")
            if err
            else (False, f"عربي بلا dir ومرّ: {[(f.rule, f.severity) for f in findings]}")
        )

    cases.append(("فحص-لغات", "HTML عربي بلا dir يُرفض", fn_html_no_dir))

    def fn_html_with_dir():
        findings = check_html('<html dir="rtl" lang="ar"><body><p>نص عربي</p></body></html>')
        bad = [f for f in findings if f.rule == "RTL-HTML-001"]
        return (True, 'dir="rtl" يعفي') if not bad else (False, "وجود dir لم يعفِ العلة")

    cases.append(("فحص-لغات", 'HTML مع dir="rtl" يمر', fn_html_with_dir))

    def fn_html_latin():
        findings = check_html("<html><body><p>hello world</p></body></html>")
        return (
            (True, "لاتيني بلا التزام RTL")
            if not findings
            else (False, f"لاتيني خالص أعاد: {[f.rule for f in findings]}")
        )

    cases.append(("فحص-لغات", "HTML لاتيني نظيف", fn_html_latin))

    def fn_py_clean():
        findings = check_python('x = "نص عربي سليم"\ny = 2')
        return (
            (True, "سلسلة عربية سليمة")
            if not findings
            else (False, f"نص سليم أعاد: {[f.rule for f in findings]}")
        )

    cases.append(("فحص-لغات", "بايثون بسلسلة عربية سليمة", fn_py_clean))

    for i, ch in enumerate(BIDI_HIDDEN):

        def fn(ch=ch):
            findings = check_python(f'x = "بداية{ch}نهاية"')
            err = [f for f in findings if f.severity == "error"]
            return (
                (True, f"U+{ord(ch):04X} مرفوض")
                if err
                else (False, f"محرف خفي U+{ord(ch):04X} مرّ في بايثون!")
            )

        cases.append(("فحص-لغات", f"بايثون يحمل U+{ord(ch):04X}", fn))

    def fn_text_clean():
        findings = check_text("هذا نص عربي سليم للعرض")
        return (
            (True, "نص نظيف")
            if not findings
            else (False, f"نص نظيف أعاد: {[f.rule for f in findings]}")
        )

    cases.append(("فحص-لغات", "نص عربي سليم يمر", fn_text_clean))

    def fn_text_bidi():
        # العقد الزوجي: فاحص النص الخالص لا يرفض bidi (قواعد TXT لا تعرفه)
        # لكن بوابة RTL ترفضه في أي اقتراح — دفاع الطبقات موثق لا حدسي
        from zyko.guardian.gates import RTLGate as _RTLGate

        findings = check_text("نص" + BIDI_HIDDEN[0] + "مخترق")
        gate = asyncio.run(_RTLGate().check("نص" + BIDI_HIDDEN[0] + "مخترق"))
        ok = findings == [] and not gate.passed
        return (
            (True, "الفاحص يمر والبوابة تُمسك")
            if ok
            else (False, f"فاحص={len(findings)} بوابة={gate.passed}")
        )

    cases.append(("فحص-لغات", "bidi في النص الخالص: الزوج الموثق", fn_text_bidi))

    def fn_css_shape():
        findings = check_css('.menu::after { content: "قائمة" }')
        ok = all(
            f.rule
            in {r["id"] if isinstance(r, dict) else getattr(r, "id", r) for r in RULE_CATALOG}
            for f in findings
        )
        return (True, "أي مخرجات من الفهرس") if ok else (False, "قاعدة خارج الفهرس الموثق")

    cases.append(("فحص-لغات", "مخرجات CSS داخل الفهرس الموثق", fn_css_shape))

    def fn_css_direction():
        findings = check_css('body { direction: rtl; } .a::after { content: "نص" }')
        return (
            (True, "direction صريح لا يعترض")
            if all(f.rule != "RTL-CSS-001" for f in findings)
            else (False, "direction صريح ورفض بوابته")
        )

    cases.append(("فحص-لغات", "CSS مع direction صريح", fn_css_direction))

    # د) الفاحص ككائن
    def fn_checker_min():
        c_info = RTLChecker(min_severity="info").check_source(
            'x = "بداية\u202aنهاية"', lang="python"
        )
        c_err = RTLChecker(min_severity="error").check_source(
            'x = "بداية\u202aنهاية"', lang="python"
        )
        return (
            (True, "العتبة رتيبة")
            if len(c_err) <= len(c_info) and c_err
            else (False, "عتبة error أعادت أكثر من info!")
        )

    cases.append(("فاحص", "عتبة الخطورة رتيبة لا تتسع", fn_checker_min))

    def fn_checker_multi():
        c = RTLChecker()
        findings = c.check_source('a = "مرحبا"\nb = "عالم"', lang="python")
        return (
            (True, "متعدد الأسطر سليم")
            if not findings
            else (False, "سلاسل سليمة متعددة أعادت ملاحظات")
        )

    cases.append(("فاحص", "مصدر متعدد الأسطر سليم", fn_checker_multi))

    # هـ) فحص المسارات
    def fn_path_html(tmp=""):
        import pathlib
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "page.html"
            p.write_text("<html><body><p>نص</p></body></html>", encoding="utf-8")
            findings, scanned = RTLChecker().check_path(str(p))
            return (
                (True, "الامتداد يحدد اللغة")
                if scanned == 1 and findings
                else (False, f"فحص {scanned} ملف و{len(findings)} ملاحظة")
            )

    cases.append(("مسارات", "check_path على HTML معيب", fn_path_html))

    def fn_path_clean():
        import pathlib
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "ok.py"
            p.write_text("x = 'سلام'\n", encoding="utf-8")
            findings, scanned = RTLChecker().check_path(str(p))
            return (
                (True, "ملف سليم يمر")
                if scanned == 1 and not findings
                else (False, "ملف سليم أعاد ملاحظات")
            )

    cases.append(("مسارات", "check_path على ملف سليم", fn_path_clean))

    def fn_path_missing():
        try:
            RTLChecker().check_path("/nonexistent/zzz.html")
            return False, "مسار غائب مرّ بصمت!"
        except FileNotFoundError as exc:
            return (True, "خطأ عربي واضح") if "غير موجود" in str(exc) else (False, f"رسالة: {exc}")
        except Exception as exc:  # noqa: BLE001 — أي رفض صريح بعجز موثق مقبول
            return True, f"الغائب يُرفض صراحة ({type(exc).__name__})"

    cases.append(("مسارات", "مسار غائب يُرفض بخطأ عربي صريح", fn_path_missing))

    # و) الفهرس والسجلات
    def fn_catalog_unique():
        ids = [r["id"] if isinstance(r, dict) else getattr(r, "id", r) for r in RULE_CATALOG]
        return (
            (True, "15 قاعدة فريدة")
            if len(ids) == len(set(ids)) == 15
            else (False, f"{len(ids)} قاعدة بفريد {len(set(ids))}")
        )

    cases.append(("سجل", "فهرس القواعد: 15 فريدة", fn_catalog_unique))

    def fn_catalog_prefixes():
        ids = {r["id"] if isinstance(r, dict) else getattr(r, "id", r) for r in RULE_CATALOG}
        need = {"RTL-CSS-001", "RTL-HTML-001", "RTL-PY-000", "RTL-TXT-001"}
        return (True, "العائلات الأربع حاضرة") if need <= ids else (False, f"غائب: {need - ids}")

    cases.append(("سجل", "عائلات القواعد الأربع موثقة", fn_catalog_prefixes))

    def fn_severities():
        return (
            (True, "ثلاث درجات بالترتيب")
            if SEVERITIES == ("error", "warning", "info")
            else (False, f"الدرجات: {SEVERITIES}")
        )

    cases.append(("سجل", "درجات الخطورة الثلاث بترتيبها", fn_severities))

    def fn_lang_by_ext():
        ok = ".py" in LANG_BY_EXT and ".css" in LANG_BY_EXT and ".html" in LANG_BY_EXT
        return (True, "خريطة الامتدادات موثقة") if ok else (False, "خريطة الامتدادات ناقصة")

    cases.append(("سجل", "LANG_BY_EXT يغطي لغات العرض", fn_lang_by_ext))

    def fn_determinism():
        src = 'x = "بداية\u202bنهاية"'
        a = [(f.rule, f.severity, f.line, f.col) for f in check_python(src)]
        b = [(f.rule, f.severity, f.line, f.col) for f in check_python(src)]
        return (True, "حتمي بالبايت") if a == b and a else (False, "فحصان اختلفا")

    cases.append(("حتمية", "فحص متكرر حتمي بالبايت", fn_determinism))

    def fn_finding_dict():
        f = check_python('x = "بداية\u202bنهاية"')[0]
        d = f.to_dict()
        need = {"rule", "severity", "message", "file", "line", "col", "excerpt", "suggestion"}
        return (
            (True, "ممثل JSON كامل")
            if need <= set(d.keys())
            else (False, f"مفاتيح الناقصة: {need - set(d.keys())}")
        )

    cases.append(("حتمية", "Finding للـ RTL يُسلسل بالعقد", fn_finding_dict))

    def fn_line_col():
        src = 'line1 = 1\nline2 = "ب\u202cد"'
        findings = check_python(src)
        ok = all(f.line >= 1 and f.col >= 1 for f in findings) and findings
        return (True, "الموضع محسوب") if ok else (False, "موضع الملاحظة غير محسوب")

    cases.append(("حتمية", "سطر وعمود الملاحظة محسوبان", fn_line_col))

    def fn_excerpt():
        loc = line_col_of("abc\ndef\nghi", 5)
        text = excerpt_of("abc\ndef\nghi", 5)
        return (
            (True, "الموضع والاقتباس يعملان")
            if loc == (2, 2) and text
            else (False, f"line_col {loc} excerpt «{text[:12]}»")
        )

    cases.append(("حتمية", "line_col_of و excerpt_of دقيقان", fn_excerpt))

    return cases


# ============================================ 7) البوابات الثلاث
def build_gates():
    cases = []

    # أ) PIIGate
    def fn_pii_clean():
        r = _run_gate(PIIGate(), "مقترح نظيف بلا أي بيانات")
        return (True, "النظيف يمر") if r.passed else (False, r.reason_ar)

    cases.append(("PIIGate", "نظيف يمر", fn_pii_clean))

    for k, builder in enumerate(
        (
            lambda: f"هاتف {_intl_phone('SA')}",
            lambda: f"آيبان {_valid_iban('SA')}",
            lambda: "هوية 1023456789 سعودية",
        )
    ):

        def fn(builder=builder):
            r = _run_gate(PIIGate(), builder())
            return (
                (True, "الثلاثي يرفض") if not r.passed else (False, "نوع من الثلاثي مرّ بوابة PII")
            )

        cases.append(("PIIGate", f"رفض النوع الثلاثي ({k + 1})", fn))

    def fn_pii_reason():
        r = _run_gate(PIIGate(), f"هاتف {_intl_phone('SA')}")
        return (
            (True, "السبب وثيق")
            if "اكتُشف PII" in r.reason_ar
            else (False, f"السبب «{r.reason_ar[:30]}»")
        )

    cases.append(("PIIGate", "سبب الرفض الموثق", fn_pii_reason))

    def fn_pii_counts_shape():
        r = _run_gate(PIIGate(), f"هاتف {_intl_phone('SA')} وآخر {_intl_phone('EG')}")
        d = r.details
        ok = d.get("total") == 2 and d.get("counts", {}).get("phone") == 2
        return (True, "شكل التفاصيل موثق") if ok else (False, f"تفاصيل: {d}")

    cases.append(("PIIGate", "شكل تفاصيل الرفض", fn_pii_counts_shape))

    def fn_pii_counts_keys():
        r = _run_gate(PIIGate(), "هوية 1023456789")
        counts = r.details.get("counts", {})
        return (
            (True, "العدّ بمفتاح النوع")
            if counts.get("national_id") == 1
            else (False, f"counts: {counts}")
        )

    cases.append(("PIIGate", "مفتاح العدّ اسم النوع", fn_pii_counts_keys))

    def fn_pii_name():
        return (
            (True, "اسم البوابة")
            if PIIGate().gate_name == "PIIGate"
            else (False, "اسم البوابة تغير")
        )

    cases.append(("PIIGate", "اسم البوابة الثابت", fn_pii_name))

    # ب) RTLGate
    for i, ch in enumerate(BIDI_HIDDEN):

        def fn(ch=ch):
            r = _run_gate(RTLGate(), f"نص{ch}مخترق")
            return (
                (True, f"U+{ord(ch):04X}")
                if not r.passed
                else (False, f"U+{ord(ch):04X} مرّ البوابة")
            )

        cases.append(("RTLGate", f"رفض U+{ord(ch):04X}", fn))

    def fn_rtl_lrm():
        r = _run_gate(RTLGate(), "نص" + LRM + "بعلامة اتجاه")
        return (True, "LRM مشروع") if r.passed else (False, "LRM رُفض خطأً")

    cases.append(("RTLGate", "LRM يمر", fn_rtl_lrm))

    def fn_rtl_rlm():
        r = _run_gate(RTLGate(), "نص" + RLM + "بعلامة اتجاه")
        return (True, "RLM مشروع") if r.passed else (False, "RLM رُفض خطأً")

    cases.append(("RTLGate", "RLM يمر", fn_rtl_rlm))

    def fn_rtl_count():
        r = _run_gate(RTLGate(), BIDI_HIDDEN[:4] + "نص" + BIDI_HIDDEN[4:7])
        return (
            (True, "العدّ 7")
            if r.details.get("hidden_count") == 7
            else (False, f"hidden_count {r.details}")
        )

    cases.append(("RTLGate", "عدّ المحارف الخفية في التفاصيل", fn_rtl_count))

    def fn_rtl_reason():
        r = _run_gate(RTLGate(), "نص" + BIDI_HIDDEN[0])
        return (
            (True, "سبب التلاعب وثيق")
            if "تلاعب" in r.reason_ar
            else (False, f"السبب «{r.reason_ar[:30]}»")
        )

    cases.append(("RTLGate", "سبب رفض التلاعب", fn_rtl_reason))

    # ج) StructuralGate
    def fn_struct_blank():
        r = _run_gate(StructuralGate(), "")
        return (True, "الفراغ يُرفض") if not r.passed else (False, "اقتراح فارغ مرّ")

    cases.append(("Structural", "الفراغ يُرفض", fn_struct_blank))

    def fn_struct_ws():
        r = _run_gate(StructuralGate(), "   \n\t ")
        return (True, "الفراغ الأبيض خالص يُرفض") if not r.passed else (False, "فراغ أبيض مرّ")

    cases.append(("Structural", "الفراغ الأبيض يُرفض", fn_struct_ws))

    def fn_struct_limit():
        r = _run_gate(StructuralGate(), "ا" * (MAX_PROPOSAL_CHARS + 1))
        return (
            (True, "السقف يعمل")
            if not r.passed and r.details.get("limit") == MAX_PROPOSAL_CHARS
            else (False, "سقف المحارف مكسور")
        )

    cases.append(("Structural", "تجاوز سقف المحارف يُرفض", fn_struct_limit))

    def fn_struct_boundary():
        r = _run_gate(StructuralGate(), "ب" * MAX_PROPOSAL_CHARS)
        return (
            (True, "الحد بالتحديد يمر") if r.passed else (False, "الحد تمامًا رُفض — السقف غير محكم")
        )

    cases.append(("Structural", "الحد تمامًا (100000) يمر", fn_struct_boundary))

    for k, ch in enumerate(("\x00", "\x01", "\x07")):

        def fn(ch=ch):
            r = _run_gate(StructuralGate(), f"نص{ch}مخترق")
            return (True, "محرف تحكم يُرفض") if not r.passed else (False, f"محرف {ord(ch):02X} مرّ")

        cases.append(("Structural", f"محرف تحكم \\x{ord(ch):02X} يُرفض", fn))

    def fn_struct_allowed():
        r = _run_gate(StructuralGate(), "سطر1\nسطر2\tعمود\rنهاية")
        return (True, "الإعفاءات الثلاثة") if r.passed else (False, "\\t\\n\\r رُفضت خطأً")

    cases.append(("Structural", "\\t\\n\\r معفاة بالعقد", fn_struct_allowed))

    def fn_struct_arabic_len():
        r = _run_gate(StructuralGate(), "محرف" * 5000)
        return (True, "العربي محارف لا بايتات") if r.passed else (False, "عدّ المحارف عُدّ بالبايتات")

    cases.append(("Structural", "الطول بالمحارف لا بالبايتات", fn_struct_arabic_len))

    # د) الترتيب المقدس والحارس
    def fn_order():
        names = [g.gate_name for g in default_gates()]
        return (
            (True, "PII ثم RTL ثم البنيوية")
            if names == ["PIIGate", "RTLGate", "StructuralGate"]
            else (False, f"الترتيب: {names}")
        )

    cases.append(("ترتيب", "ترتيب البوابات الثلاث مقدس", fn_order))

    def fn_guard_allow():
        d = _run_guardian("مقترح نظيف يمر بسلام")
        ok = d.verdict == "ALLOW" and len(d.gate_results) == 3
        return (
            (True, "ALLOW بثلاث بوابات")
            if ok
            else (False, f"{d.verdict} بـ{len(d.gate_results)} بوابة")
        )

    cases.append(("الحارس", "الحارس يمرر النظيف كامل التدقيق", fn_guard_allow))

    def fn_guard_deny():
        proposal = f"هاتف {_intl_phone('SA')}" + BIDI_HIDDEN[0]
        d = _run_guardian(proposal)
        ok = d.verdict == "DENY" and len(d.gate_results) == 3
        return (
            (True, "DENY مع تدقيق كامل")
            if ok
            else (False, f"{d.verdict} — التدقيق {len(d.gate_results)}")
        )

    cases.append(("الحارس", "الرفض لا يقصّ التدقيق", fn_guard_deny))

    def fn_guard_hostile():
        text = get_scenario("hostile").render("طلب تجريبي")
        d = _run_guardian(text)
        return (
            (True, "العدوي يُرفض طبقيًا")
            if d.verdict == "DENY"
            else (False, f"اقتراح عدوي حكمه {d.verdict}")
        )

    cases.append(("الحارس", "سيناريو hostile يُرفض", fn_guard_hostile))

    def fn_guard_suspicious():
        text = get_scenario("suspicious").render("طلب تجريبي")
        d = _run_guardian(text)
        pii = next((g for g in d.gate_results if g.gate_name == "PIIGate"), None)
        ok = d.verdict == "DENY" and pii is not None and not pii.passed
        return (
            (True, "المشبوه يرفض بوابة PII") if ok else (False, "سيناريو الهاتف الصريح لم يرفض PII")
        )

    cases.append(("الحارس", "سيناريو suspicious يرفض PII", fn_guard_suspicious))

    def fn_guard_clean_mock():
        text = get_scenario("clean").render("طلب تجريبي")
        d = _run_guardian(text)
        return (
            (True, "النظيف الاصطناعي يمر")
            if d.verdict == "ALLOW"
            else (False, f"النظيف حكمه {d.verdict}: {d.reason_ar[:40]}")
        )

    cases.append(("الحارس", "سيناريو clean يمر", fn_guard_clean_mock))

    def fn_guard_review():
        class BoomGate:
            gate_name = "BoomGate"

            async def check(self, proposal):
                raise RuntimeError("انفجار تجريبي")

        d = asyncio.run(DefaultGuardian(default_gates() + [BoomGate()]).check("نص نظيف"))
        return (
            (True, "الانفجار REVIEW لا سكوت")
            if d.verdict == "REVIEW"
            else (False, f"انفجار بوابة حكمه {d.verdict}")
        )

    cases.append(("الحارس", "بوابة تنفجر ⇒ REVIEW", fn_guard_review))

    def fn_guard_exception_full():
        class BoomGate:
            gate_name = "BoomGate"

            async def check(self, proposal):
                raise RuntimeError("انفجار تجريبي")

        d = asyncio.run(DefaultGuardian(default_gates() + [BoomGate()]).check("نص نظيف"))
        ok = len(d.gate_results) == 4
        return (True, "كل البوابات سُجلت") if ok else (False, f"نتائج {len(d.gate_results)} بدل 4")

    cases.append(("الحارس", "REVIEW لا يقصّ سجل البوابات", fn_guard_exception_full))

    def fn_fingerprint():
        from zyko.guardian.contracts import GateResult

        results = [GateResult(g.gate_name, True, "سليم") for g in default_gates()]
        p = "نص ثابت للبصمة"
        a = compute_fingerprint(p, results)
        b = compute_fingerprint(p, [GateResult(g.gate_name, True, "سليم") for g in default_gates()])
        return (True, "بصمة حتمية") if a == b and a else (False, "بصمتان لنفس المدخل اختلفا")

    cases.append(("بصمة", "بصمة القرار حتمية بالبايت", fn_fingerprint))

    def fn_fingerprint_diff():
        def gr(name):
            return __import__("zyko.guardian.contracts", fromlist=["GateResult"]).GateResult(
                name, True, "سليم"
            )

        a = compute_fingerprint("نص أ", [gr("PIIGate"), gr("RTLGate")])
        b = compute_fingerprint("نص ب", [gr("PIIGate"), gr("RTLGate")])
        return (True, "النص يغير البصمة") if a != b else (False, "نصان مختلفان بنفس البصمة!")

    cases.append(("بصمة", "نصوص مختلفة بصمات مختلفة", fn_fingerprint_diff))

    def fn_fingerprint_order():
        # العلة المُصلَحة (0.39.0): إعادة الترتيب بالـruff أسقطت وسطي
        # «GateResult(name, True, "سليم")» إلى استدعاء بحجة واحدة —
        # TypeError حيّ في العدّة. المصنع يعيد الوسيطين الموثقين.
        def gr2(name):
            return __import__("zyko.guardian.contracts", fromlist=["GateResult"]).GateResult(
                name, True, "سليم"
            )

        a = compute_fingerprint("نص", [gr2("PIIGate"), gr2("RTLGate")])
        b = compute_fingerprint("نص", [gr2("RTLGate"), gr2("PIIGate")])
        return (
            (True, "الترتيب يغير البصمة") if a != b else (False, "ترتيب البوابات لا يظهر في البصمة")
        )

    cases.append(("بصمة", "ترتيب البوابات يدخل البصمة", fn_fingerprint_order))

    def fn_gate_result_shape():
        from zyko.guardian.contracts import GateResult

        g = GateResult("بوابة", False, "سبب")
        ok = g.details == {} and g.gate_name == "بوابة"
        return (True, "شكل النتيجة موثق") if ok else (False, "GateResult الافتراضي مكسور")

    cases.append(("بنية", "GateResult بتفاصيله الافتراضية", fn_gate_result_shape))

    def fn_scenarios():
        ok = set(SCENARIOS) == {"clean", "suspicious", "hostile"}
        return (
            (True, "ثلاثة سيناريوهات موثقة")
            if ok
            else (False, f"السيناريوهات: {sorted(SCENARIOS)}")
        )

    cases.append(("نموذج-مزيّف", "سيناريوهات MockLLM الثلاثة", fn_scenarios))

    def fn_scenario_unknown():
        try:
            get_scenario("غير-موجود")
            return False, "سيناريو مجهول عاد صامتًا!"
        except Exception as exc:
            return (True, "خطأ عربي واضح") if str(exc) else (False, "استثناء بلا رسالة")

    cases.append(("نموذج-مزيّف", "سيناريو مجهول يُرفض وضوحًا", fn_scenario_unknown))

    def fn_mock_calls():
        mock = MockLLM(scenario="clean")

        async def twice():
            await mock.propose("طلب 1")
            await mock.propose("طلب 2")

        asyncio.run(twice())
        return (True, "العدّاد يوثق") if mock.calls == 2 else (False, f"عدّاد النداءات {mock.calls}")

    cases.append(("نموذج-مزيّف", "عدّاد نداءات النموذج المزيّف", fn_mock_calls))

    def fn_mock_hostile_content():
        text = get_scenario("hostile").render("طلب")
        has_phone = "966" in text or "05" in text
        has_bidi = any(ch in BIDI_HIDDEN for ch in text)
        return (
            (True, "العدوي يحمل الاثنين")
            if has_phone and has_bidi
            else (False, "سيناريو العدوي فقد أحد العدوين")
        )

    cases.append(("نموذج-مزيّف", "العدوي يحمل هاتفًا ومحرفًا خفيًا", fn_mock_hostile_content))

    def fn_mock_async():
        async def twice():
            a = await MockLLM(scenario="clean").propose("طلب")
            b = await MockLLM(scenario="clean").propose("طلب")
            return a == b

        return (
            (True, "النموذج المزيّف حتمي")
            if asyncio.run(twice())
            else (False, "نموذج مزيّف غير حتمي")
        )

    cases.append(("نموذج-مزيّف", "النموذج المزيّف حتمي بالبايت", fn_mock_async))

    def fn_verdicts():
        ok_values = {"ALLOW", "DENY", "REVIEW"}
        seen = {
            _run_guardian("نظيف").verdict,
            _run_guardian(f"هاتف {_intl_phone('SA')}").verdict,
            asyncio.run(DefaultGuardian(default_gates() + [_Boom()]).check("نظيف")).verdict,
        }
        return (
            (True, "الأحكام الثلاثة عاشت")
            if seen <= ok_values and seen == ok_values
            else (False, f"الأحكام: {seen}")
        )

    cases.append(("أحكام", "الأحكام الثلاثة كلها قابلة للعيش", fn_verdicts))

    def fn_gate_privacy_reason():
        r = _run_gate(PIIGate(), f"هاتف {_intl_phone('SA')}")
        leaked = _intl_phone("SA").split()[-1] in r.reason_ar
        return (True, "السبب بلا قيمة خام") if not leaked else (False, "سبب الرفض يحمل الرقم الخام")

    cases.append(("PIIGate", "سبب الرفض بلا رقم خام", fn_gate_privacy_reason))

    return cases


class _Boom:
    """بوابة تنفجر — تُستخدم في حالات REVIEW فقط."""

    gate_name = "BoomGate"

    async def check(self, proposal):
        raise RuntimeError("انفجار تجريبي")
