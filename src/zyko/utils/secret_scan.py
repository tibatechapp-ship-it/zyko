"""secret_scan — بوابة الأسرار الحتمية (الموجة 26: درس 19 توكن صار عقداً).

الزبدة المُستقادة بهندسة عكسية معلنة: قواعد كشف الأسرار في بوابات الدفع
(Push Rules / Secret Detection) تمنع التسريب قبل وقوعه لا بعده. أسلوبنا:
أنماط مسمّاة عددها معلن، فحص بالسطر، **الإثبات ببصمة sha256 لا بطباعة
القيمة** (الدليل يتحقق ولا يسرَّب)، وثغرة إعفاء صريحة قابلة للبحث
(``zyko:secret-ok`` في السطر) للاختبارات والتوثيق — لا استثناء صامت.

الطبقة: utils (الأدنى) — مدقّق الرقع في benchmarks يورث نمط القيمة من
هنا فتبقى حقيقة السر واحدة في المستودع كلها.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass

__all__ = [
    "EXEMPT_MARKER",
    "SECRET_PATTERNS",
    "SecretHit",
    "TOKEN_VALUE_RE",
    "scan_text",
    "scan_tree",
    "scan_to_json",
]

# علامة الإعفاء الصريحة: سطر يحويها لا يُفحص — تُبحث بـ grep ولا تُختبأ
EXEMPT_MARKER = "zyko:secret-ok"

# نمط قيمة السر (الواحد في المستودع) — تورّثه قواعد الفرق أيضاً
TOKEN_VALUE_RE = re.compile(
    "(ghp_|gho_|ghu_|ghs_)[A-Za-z0-9]{20,}"
    "|github_pat_[A-Za-z0-9_]{20,}"
    "|AKIA[0-9A-Z]{16}"
    "|xox[baprs]-[A-Za-z0-9-]{10,}"
    "|sk-ant-[A-Za-z0-9-]{20,}"
    "|sk-[A-Za-z0-9]{20,}"
    "|-----BEGIN[A-Z ]*PRIVATE KEY-----"
)

_CRED_ASSIGN_RE = re.compile(
    r"(?i)\b(password|secret|api_key|access_token)\s*[=:]\s*[\"'][^\"']{8,}[\"']"
)


@dataclass(frozen=True)
class SecretHit:
    """إصابة واحدة: النمط + السطر + بصمة القيمة (لا القيمة)."""

    name: str
    severity: str
    line_no: int
    evidence_sha16: str
    message_ar: str

    def to_dict(self) -> dict:
        return {
            "line_no": self.line_no,
            "message_ar": self.message_ar,
            "name": self.name,
            "severity": self.severity,
            "value_sha16": self.evidence_sha16,
        }


@dataclass(frozen=True)
class _Pattern:
    name: str
    severity: str
    regex: re.Pattern[str]
    message_ar: str


SECRET_PATTERNS: tuple[_Pattern, ...] = (
    _Pattern("github-token", "critical", TOKEN_VALUE_RE, "قيمة توكن مضمّنة في السطر"),
    _Pattern("cred-assignment", "medium", _CRED_ASSIGN_RE, "إسناد بيانات اعتماد نصياً في السطر"),
)


def scan_text(text: str) -> tuple[SecretHit, ...]:
    """فحص نص بالسطر — الأسطر الحاملة علامة الإعفاء تُتخطى معلناً."""
    hits: list[SecretHit] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if EXEMPT_MARKER in line:
            continue
        for pat in SECRET_PATTERNS:
            for m in pat.regex.finditer(line):
                value = m.group(0)
                hits.append(
                    SecretHit(
                        name=pat.name,
                        severity=pat.severity,
                        line_no=line_no,
                        evidence_sha16=hashlib.sha256(value.encode()).hexdigest()[:16],
                        message_ar=pat.message_ar,
                    )
                )
    return tuple(hits)


_SKIP_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        ".mypy_cache",
        ".pytest_cache",
    }
)


def scan_tree(root, *, max_bytes: int = 2_000_000) -> dict:
    """فحص شجرة كاملة: ملفات نصية تحت السقف — المجلدات المهملة معلنة."""
    root = __import__("pathlib").Path(root)
    files_scanned = 0
    hits: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for fn in sorted(filenames):
            path = __import__("pathlib").Path(dirpath) / fn
            try:
                if path.stat().st_size > max_bytes:
                    continue
                rel = str(path.relative_to(root)).replace(os.sep, "/")
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            files_scanned += 1
            for hit in scan_text(text):
                d = hit.to_dict()
                d["file"] = rel
                hits.append(d)
    return {
        "schema": "zyko.secret_scan/1",
        "files_scanned": files_scanned,
        "hit_count": len(hits),
        "hits": hits,
    }


def scan_to_json(payload: dict) -> str:
    """تسلسل حتمي بالبايت — نفس الفحص ⇒ نفس البايتات."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1)
