"""النواة المشتركة — أنواع النتائج، كشف اللغة، والماسح الرئيسي.

zyko_rtl — كاشف مشاكل الاتجاه RTL (حتمي 100%، بدون نماذج).
كل قاعدة تُخرج Finding بموقع دقيق (ملف/سطر/عمود) وخطورة واقتراح إصلاح عربي.
لا اعتماديات خارجية إطلاقًا — تعمل على Termux كما هي.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

# ---------------------------------------------------------------- أنواع أساسية

SEVERITIES = ("error", "warning", "info")
SEVERITY_AR = {"error": "خطأ", "warning": "تحذير", "info": "معلومة"}
SEVERITY_RANK = {"info": 1, "warning": 2, "error": 3}

# نطاقات المحارف العربية (حروف + أرقام + إعراب + عروض)
ARABIC_RE = re.compile("[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]")
# حروف عربية فقط (بلا أرقام عربية-هندية ولا محارف تحكم)
ARABIC_LETTER_RE = re.compile("[\u0621-\u063a\u0641-\u064a\u066e-\u06d5\u08a1-\u08ff]")
ARABIC_INDIC_DIGITS_RE = re.compile("[\u0660-\u0669\u06f0-\u06f9]")
LATIN_LETTER_RE = re.compile("[A-Za-z]")
ASCII_DIGITS_RE = re.compile("[0-9]")
# محارف التحكم بالاتجاه — ثغرة Trojan Source (CVE-2021-42574 / CVE-2021-42694)
BIDI_CONTROL_RE = re.compile("[\u202a-\u202e\u2066-\u2069]")
# علامات الاتجاه المشروعة (LRM/RLM) — هي الإصلاح الموصى به للسلاسل المختلطة
BIDI_MARKS_RE = re.compile("[\u200e\u200f]")

MAX_FILE_BYTES = 2 * 1024 * 1024  # نتجاهل الملفات الأضخم من 2MB (محمية)

LANG_BY_EXT = {
    ".css": "css",
    ".html": "html",
    ".htm": "html",
    ".py": "python",
    ".md": "text",
    ".txt": "text",
}

SKIP_DIR_NAMES = {
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".idea",
    ".vscode",
}

SKIP_DIR_SUFFIXES = (".egg-info", ".dist-info")


def has_arabic(text: str) -> bool:
    """هل يحتوي النص أي محرف عربي (حرفًا أو رقمًا)."""
    return bool(ARABIC_RE.search(text))


def arabic_letter_ratio(text: str) -> float:
    """نسبة الحروف العربية من مجموع الحروف في النص (0.0 إن لا حروف)."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    arabic = sum(1 for c in letters if ARABIC_LETTER_RE.match(c))
    return arabic / len(letters)


# ---------------------------------------------------------------- Finding


@dataclass
class Finding:
    """ملاحظة واحدة بموقع دقيق وخطورة واقتراح."""

    rule: str  # معرّف القاعدة مثل RTL-CSS-001
    severity: str  # error | warning | info
    message: str  # شرح المشكلة بالعربية
    file: str  # مسار الملف أو <inline>
    line: int  # سطر (يبدأ من 1)
    col: int  # عمود (يبدأ من 1)
    excerpt: str  # السطر المخالف (مقصوص عند 120 محرفًا)
    suggestion: str  # اقتراح الإصلاح بالعربية

    def to_dict(self) -> dict:
        return asdict(self)


def line_col_of(source: str, offset: int) -> tuple[int, int]:
    """يحوّل إزاحة نصية إلى (سطر، عمود) يبدآن من 1."""
    line = source.count("\n", 0, offset) + 1
    col = offset - (source.rfind("\n", 0, offset) + 1) + 1
    return line, col


def excerpt_of(source: str, offset: int, width: int = 120) -> str:
    """يستخرج السطر الكامل الذي يقع فيه الموقع (مقصوصًا ونظيفًا)."""
    start = source.rfind("\n", 0, offset) + 1
    end = source.find("\n", offset)
    if end == -1:
        end = len(source)
    return source[start:end].strip()[:width]


# ---------------------------------------------------------------- فهرس القواعد

RULE_CATALOG: dict[str, tuple[str, str]] = {
    # CSS
    "RTL-CSS-001": ("error", "text-align: left داخل سياق RTL"),
    "RTL-CSS-002": ("warning", "قيم فيزيائية left/right لمحاذاة النص"),
    "RTL-CSS-003": ("warning", "هوامش وحشوات وحدود فيزيائية left/right"),
    "RTL-CSS-004": ("warning", "float بقيم فيزيائية left/right"),
    "RTL-CSS-005": ("info", "إزاحات تموضع فيزيائية left/right"),
    # HTML
    "RTL-HTML-001": ("error", "مستند عربي بلا dir على <html>"),
    "RTL-HTML-002": ("warning", "dir=rtl بلا lang على <html>"),
    "RTL-HTML-003": ("warning", "عنصر بنص عربي بلا dir في مستند LTR"),
    "RTL-HTML-004": ("error", "محاذاة يسار داخلية داخل عنصر RTL"),
    # Python
    "RTL-PY-000": ("error", "ملف بايثون غير صالح التركيب"),
    "RTL-PY-001": ("error", "مقارنة سلسلة عربية بسلسلة لاتينية (أو أرقام عربية-هندية بغربية)"),
    "RTL-PY-002": ("info", "سلسلة رسائل مختلطة عربي/لاتيني بلا محارف اتجاه"),
    "RTL-PY-003": ("error", "محارف تحكم اتجاه مخفية — Trojan Source"),
    "RTL-PY-004": ("warning", "معرّفات بأرقام عربية-هندية أو خليط عربي/لاتيني"),
    # نصوص عامة
    "RTL-TXT-001": ("info", "سطر مختلط الاتجاه قد يُعرض مبعثرًا"),
}


# ---------------------------------------------------------------- الماسح


class RTLChecker:
    """الماسح الرئيسي — يوزّع الملفات على القواعد حسب امتدادها."""

    def __init__(self, min_severity: str = "info") -> None:
        if min_severity not in SEVERITY_RANK:
            raise ValueError(f"خطورة غير معروفة: {min_severity}")
        self.min_severity = min_severity

    # ------------------------------------------------------------- داخلية

    def _keep(self, findings: list[Finding]) -> list[Finding]:
        floor = SEVERITY_RANK[self.min_severity]
        return [f for f in findings if SEVERITY_RANK[f.severity] >= floor]

    # ------------------------------------------------------------- مصدر خام

    def check_source(self, source: str, lang: str, filename: str = "<inline>") -> list[Finding]:
        """يفحص نصًا خامًا بلسان معروف: css | html | python | text."""
        if lang == "css":
            from .css_rules import check_css

            findings = check_css(source, filename)
        elif lang == "html":
            from .html_rules import check_html

            findings = check_html(source, filename)
        elif lang == "python":
            from .py_rules import check_python

            findings = check_python(source, filename)
        elif lang == "text":
            from .text_rules import check_text

            findings = check_text(source, filename)
        else:
            raise ValueError(f"لسان غير مدعوم: {lang}")
        return self._keep(findings)

    # ------------------------------------------------------------- مسار

    def check_path(self, path: str | Path) -> tuple[list[Finding], int]:
        """يفحص ملفًا واحدًا أو شجرة مجلدات كاملة.

        يرجع (النتائج مرتبة، عدد الملفات المفحوصة فعليًا).
        يرفع ValueError لامتداد غير معروف عند تمرير ملف مفرد،
        وFileNotFoundError لمسار غير موجود.
        """
        p = Path(path)
        if p.is_file():
            lang = LANG_BY_EXT.get(p.suffix.lower())
            if lang is None:
                raise ValueError(
                    f"لا أفحص صيغة «{p.suffix}» — الأنواع المدعومة: "
                    + " ".join(sorted(LANG_BY_EXT))
                )
            findings = self.check_source(_read_text(p), lang, str(p))
            return self._sort(findings), 1

        if not p.is_dir():
            raise FileNotFoundError(f"المسار غير موجود: {p}")

        findings: list[Finding] = []
        scanned = 0
        for f in sorted(p.rglob("*")):
            if not f.is_file():
                continue
            if any(_skip_part(part) for part in f.parts):
                continue
            lang = LANG_BY_EXT.get(f.suffix.lower())
            if lang is None:
                continue
            try:
                if f.stat().st_size > MAX_FILE_BYTES:
                    continue
                raw = f.read_bytes()
            except OSError:
                continue
            if b"\x00" in raw[:1024]:  # ملف ثنائي
                continue
            try:
                source = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            findings.extend(self.check_source(source, lang, str(f)))
            scanned += 1
        return self._sort(findings), scanned

    @staticmethod
    def _sort(findings: list[Finding]) -> list[Finding]:
        return sorted(findings, key=lambda f: (f.file, f.line, f.col, f.rule))


def _skip_part(part: str) -> bool:
    return part in SKIP_DIR_NAMES or part.endswith(SKIP_DIR_SUFFIXES)


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"الملف ليس UTF-8: {path}") from exc
