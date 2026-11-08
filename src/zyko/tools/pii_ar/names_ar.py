"""معجم الأسماء العربية + كاشف الأسماء الحتمي.

Dictionary-based Arabic name detection (no capitalization signal exists in
Arabic, so we use a curated lexicon + structural patterns).

Normalization notes:
- Strip tatweel (ـ) and harakat before matching.
- Join the split form "عبد الله" -> "عبدالله" (and similar عبد + X).
- Family names may appear with or without the definite article ("العنزي"/"عنزي").
"""

from __future__ import annotations

import re

HONORIFICS: tuple[str, ...] = (
    "الأستاذ",
    "الاستاذ",
    "أستاذ",
    "الاستاذة",
    "الأستاذة",
    "الدكتور",
    "دكتور",
    "الدكتورة",
    "دكتورة",
    "الطبيب",
    "الطبيبة",
    "المهندس",
    "المهندسة",
    "السيد",
    "سيدي",
    "السيدة",
    "السيدة",
    "سعادة",
    "الشيخ",
    "الحاج",
    "الحاجة",
    "الأمير",
    "الوزير",
)

FIRST_NAMES: frozenset[str] = frozenset(
    """
محمد أحمد عبدالله عبدالرحمن فهد سلطان خالد سعود ناصر بندر تركي فيصل سعد ماجد
طلال سامي عمر علي حسن حسين يوسف إبراهيم مصطفى ياسر رامي طارق زياد مروان وسيم
باسل أدهم كريم كمال عادل جمال هيثم أيمن إياد مؤيد محمود حمزة أنس بلال ثامر
جواد حاتم داوود رضوان زهير سليم شادي صالح ضياء عزام عصام عماد عادل عمران
عامر بدر جاسم حارب حمد خالد دلال زايد سلطان شخبوط سهيل عبدالعزيز عبدالإله
عبدالمحسن عطا غسان فارس فايز مراد منصور نبيل نديم هاني وائل
وليد يامن يزن عبدالحميد عبدالوهاب عوني غالب فادي مازن مهند نائل وسام يمنى
فاطمة عائشة مريم سارة نورة هند لطيفة الجوهرة منال ريم دانة شهد رزان سلمى ليان
جواهر حصة موضي غادة نادين رنا حنان خديجة زينب أمينة نادية شيماء منى لمى
هيا حور أروى بشرى تهاني ثراء جمانة حنين خولة دعاء رهف سارة سما سرى عفاف
فرح قمر لينا ملاك نهى وفاء ياسمين أسماء بثينة بيداء تغريد جلنار حبيبة
""".split()
)

FAMILY_NAMES: frozenset[str] = frozenset(
    """
العمري الشمري القحطاني الحربي المطيري العتيبي الدوسري الغامدي الزهراني السبيعي
البقمي العنزي الرشيدي الشهري البلوي الجهني الحارثي السالمي الخالدي المالكي
الأنصاري الهاشمي القرني الزهراني الصاعدي الشريف الحسني العمري البكري التميمي
الطائي السامرائي الخفاجي العبيدي الجبوري الدليمي الحديدي المصري الشاذلي حسني
الظاهري المكتوم النعيمي السويدي الرومي العلي الصفار الفردان العوضي الثقفي
الرشيد الفارس الكعبي المنصوري المري حمدان الفهد العامري السالم الشامسي النومان
المدني الدوسري العباسي الحاج عيسى كمال سعيد شاهين نصر عبدالملك البنا حجازي
الأسعد الأسدي الطيب الزين عبدالهادي عطار سلامة درويش حسان شاهين شمعون حداد
الخوري النجار الأحمد الصالح الحسين الغريب مسعود بن عمار الطرابلسي البلوشي
البرواني البلوشي الحبسي المعمري الرواحي البلوشي الكندي العامري
""".split()
)

_NAME_TOKEN = r"[\u0621-\u064A]{2,}"  # nosec B105

# كلمات "عبد + X" المركبة: تُدمج بعد إزالة الفراغ أثناء التطبيع
_JOIN_ABD_WORDS = "الله|الرحمن|العزيز|الحميد|الإله|الوهاب|المحسن|الملك|اللطيف|الكريم|الرحيم"

# tatweel + harakat to strip
_STRIP_RE = re.compile(r"[\u0640\u064B-\u065F\u0670]")
_JOIN_ABD_RE = re.compile(r"\bعبد\s+(" + _JOIN_ABD_WORDS + r")\b")
_HONORIFIC_RE = re.compile("(" + "|".join(HONORIFICS) + r")\s+((?:" + _NAME_TOKEN + r"\s+){1,3})")
_IBN_RE = re.compile(
    "(" + _NAME_TOKEN + r")\s+(?:بن|بنت)\s+(" + _NAME_TOKEN + r")(?:\s+(" + _NAME_TOKEN + r"))?"
)
_FULL_RE = re.compile(
    "(" + _NAME_TOKEN + r")(?:\s+(" + _NAME_TOKEN + r"))?\s+(" + _NAME_TOKEN + r")"
)


def _clean_tokens(text: str) -> str:
    """Strip diacritics/tatweel and join عبد الله-style splits."""
    t = _STRIP_RE.sub("", text)
    t = _JOIN_ABD_RE.sub(lambda m: "عبد" + m.group(1), t)
    return t


def _strip_article(tok: str) -> str:
    return tok[2:] if tok.startswith("ال") and len(tok) > 4 else tok


def _in_first(tok: str) -> bool:
    return tok in FIRST_NAMES or _strip_article(tok) in FIRST_NAMES


def _in_family(tok: str) -> bool:
    tok_n = tok
    return (
        tok_n in FAMILY_NAMES
        or _strip_article(tok_n) in FAMILY_NAMES
        or ("ال" + tok_n) in FAMILY_NAMES
    )


def _is_nameish(tok: str) -> bool:
    return _in_first(tok) or _in_family(tok)
