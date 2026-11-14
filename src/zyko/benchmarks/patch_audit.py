"""patch_audit — مدقّق الرقع الحتمي على مستوى الفرق (الموجة 26).

الزبدة المُستقادة بهندسة عكسية معلنة: الطبقة الأولى في منظومات مراجعة
الكود الهجينة — قواعد ثابتة سريعة تفحص **الأسطر المضافة فقط** قبل أي
فهم سياقي أعمق. أسلوبنا: ثماني قواعد مسماة عددها معلن، كل إصابة
بمعرّف قاعدة + ملف + رقم سطر في الملف الهدف + الشاهد النصي المقتطع،
حتمية بالبايت، بلا شبكة وبلا نموذج.

الحدود الموثقة قبل التوسيع (روح taint: نطاق مقصود مضغوط):
  * يفحص الأسطر المضافة في رقعة موحّدة (unified diff) فقط؛ الأسطر
    المحذوفة والسياق لا تُفحص أبداً (حذف السر ليس جريمة).
  * قواعد نصية بالسطر (AST يعمل في المراجع الكامل على الملف كله
    بعد تطبيق الرقعة — الطبقتان متكاملتان لا مكررتان).
  * رقعة بلا ترويسات موحّدة تُعاد بصفر إصابات معلن (لا تخمين).

الدرجات (أسوأ إصابة تفوز):
  critical ⇒ «مرفوض» · high ⇒ «مراجعة» · medium ⇒ «تنبيه» ·
  low ⇒ «ملاحظة» · لا شيء ⇒ «نظيف»
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from zyko.utils.secret_scan import TOKEN_VALUE_RE  # مصدر حقيقة السر الواحد في المستودع

__all__ = [
    "DIFF_RULES",
    "DiffFinding",
    "PatchAudit",
    "audit_patch_text",
    "patch_audit_to_json",
]

HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
NEW_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$")


@dataclass(frozen=True)
class DiffRule:
    """قاعدة فرق واحدة: معرف + خطورة + نمط + رسالة عربية حتمية."""

    rule_id: str
    severity: str
    pattern: re.Pattern[str]
    message_ar: str


@dataclass(frozen=True)
class DiffFinding:
    """إصابة موثقة: قاعدة + موقع مطلق + شاهد مقتطع."""

    rule_id: str
    severity: str
    file: str
    line_in_file: int
    evidence: str
    message_ar: str

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "file": self.file,
            "line_in_file": self.line_in_file,
            "evidence": self.evidence[:80],
            "message_ar": self.message_ar,
        }


_SHELL_RE = re.compile(r"os\.system\(|shell\s*=\s*True")
_SQLI_RE = re.compile(r"execute\s*\(\s*(f[\"']|[\"']\s*(?:SELECT|INSERT|UPDATE|DELETE))", re.I)
_SILENT_RE = re.compile(r"except[^\n:]*:\s*$|except\s*Exception\s*:\s*pass\b")

# القواعد الثماني المعلنة — العدد عقد يفحصه الاختبار
DIFF_RULES: tuple[DiffRule, ...] = (
    DiffRule(
        "SEC-SECRET-001",
        "critical",
        TOKEN_VALUE_RE,
        "سر مضمّن في سطر مضاف — التوكنات لا تُكتب في الكود",
    ),
    DiffRule(
        "SEC-EVAL-001",
        "high",
        re.compile(r"\beval\s*\("),
        "نداء eval على سطر مضاف — تنفيذ حر للتعبيرات",
    ),
    DiffRule(
        "SEC-EXEC-001",
        "high",
        re.compile(r"\bexec\s*\("),
        "نداء exec على سطر مضاف — تنفيذ حر للكود",
    ),
    DiffRule(
        "SEC-SHELL-001", "high", _SHELL_RE, "صدفة نظام أو shell=True على سطر مضاف — حقن أوامر ممكن"
    ),
    DiffRule(
        "SEC-SQLI-001", "high", _SQLI_RE, "استعلام SQL بسلسلة مبنية على سطر مضاف — حقن SQL ممكن"
    ),
    DiffRule(
        "ERR-BAREEXC-001",
        "medium",
        re.compile(r"^\s*except\s*:\s*$"),
        "except عارٍ يبتلع كل الأخطاء",
    ),
    DiffRule("ERR-SILENT-001", "medium", _SILENT_RE, "ابتلاع صامت للاستثناء بلا تسجيل"),
    DiffRule(
        "QUA-TODO-001", "low", re.compile(r"\b(TODO|FIXME|XXX)\b"), "واسم عمل معلّق في سطر مضاف"
    ),
)

_GRADE_AR = {"critical": "مرفوض", "high": "مراجعة", "medium": "تنبيه", "low": "ملاحظة"}
_SEVERITY_ORDER = ("critical", "high", "medium", "low")


@dataclass
class PatchAudit:
    """نتيجة تدقيق رقعة: ملفات + إصابات + درجة — كلها قابلة للتسلسل."""

    added_count: int = 0
    file_count: int = 0
    findings: list[DiffFinding] = field(default_factory=list)
    files: tuple[str, ...] = ()

    @property
    def grade_ar(self) -> str:
        for sev in _SEVERITY_ORDER:
            if any(f.severity == sev for f in self.findings):
                return _GRADE_AR[sev]
        return "نظيف"

    def to_dict(self) -> dict:
        return {
            "schema": "zyko.patch_audit/1",
            "added_count": self.added_count,
            "file_count": self.file_count,
            "files": list(self.files),
            "finding_count": len(self.findings),
            "grade_ar": self.grade_ar,
            "findings": [f.to_dict() for f in self.findings],
        }


def _added_lines(diff: str) -> tuple[tuple[str, int, str], ...]:
    """(ملف، سطر في الملف الهدف، نص السطر المضاف) — بترتيب الرقعة."""
    out: list[tuple[str, int, str]] = []
    current_file: str | None = None
    new_line = 0
    for raw in diff.splitlines():
        m = NEW_FILE_RE.match(raw)
        if m:
            current_file = m.group(1).strip()
            continue
        if raw.startswith(("--- ", "diff --git ", "index ", "new file mode", "deleted file mode")):
            continue
        hm = HUNK_RE.match(raw)
        if hm:
            new_line = int(hm.group(1))
            continue
        if current_file is None:
            continue
        if raw.startswith("+"):
            out.append((current_file, new_line, raw[1:]))
            new_line += 1
        elif raw.startswith("-") or raw.startswith("\\ No newline"):
            continue
        else:  # سطر سياق (أو فارغ بلا بادئة في الرقع اليدوية)
            new_line += 1
    return tuple(out)


def added_lines(diff: str) -> tuple[tuple[str, int, str], ...]:
    """الواجهة العامة لأسطر المضاف — بوابة الأسرار في scripts تورثها."""
    return _added_lines(diff)


def audit_patch_text(diff: str) -> PatchAudit:
    """تدقيق حتمي: الأسطر المضافة تُقاس بالقواعد الثماني بالترتيب."""
    added = _added_lines(diff)
    files = tuple(sorted({f for f, _, _ in added}))
    findings: list[DiffFinding] = []
    for fpath, lineno, text in added:
        for rule in DIFF_RULES:
            m = rule.pattern.search(text)
            if m:
                findings.append(
                    DiffFinding(
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        file=fpath,
                        line_in_file=lineno,
                        evidence=text.strip()[:80],
                        message_ar=rule.message_ar,
                    )
                )
    return PatchAudit(
        added_count=len(added),
        file_count=len(files),
        findings=findings,
        files=files,
    )


def patch_audit_to_json(audit: PatchAudit) -> str:
    """تسلسل حتمي بالبايت — نفس الرقعة ⇒ نفس البايتات."""
    return json.dumps(audit.to_dict(), ensure_ascii=False, sort_keys=True, indent=1)


if __name__ == "__main__":  # واجهة قياس مباشرة: python -m zyko.benchmarks.patch_audit
    import argparse
    import sys
    from pathlib import Path

    ap = argparse.ArgumentParser(description="مدقّق الرقع الحتمي — ثماني قواعد على الأسطر المضافة")
    ap.add_argument("--patch", required=True, help="ملف الرقعة الموحّدة")
    args = ap.parse_args()
    text = Path(args.patch).read_text(encoding="utf-8", errors="replace")
    print(patch_audit_to_json(audit_patch_text(text)))
    sys.exit(0 if audit_patch_text(text).grade_ar in ("نظيف", "ملاحظة") else 1)
