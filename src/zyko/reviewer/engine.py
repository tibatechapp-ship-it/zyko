"""zyko.reviewer.engine — محرك المراجعة: مصدر نصي ⇒ نتيجة حتمية موقّعة.

سلوك المحرك أمام المدخلات العدائية مضمون تعاقديًا:
  - ملف بترميز غير مدعوم ⇒ نتيجة مهيكلة (parse_error) لا استثناء
  - ملف بترميز صيغة خاطئة (SyntaxError/RecursionError/…) ⇒ نتيجة مهيكلة
  - ملف فارغ ⇒ درجة 100 (لا شيء ليُخالف)
  - ملف أكبر من الحد ⇒ نتيجة مهيكلة تشرح السبب عربيًا
المحرك لا يلمس الشبكة أبدًا ولا يستورد أي شيء خارج المكتبة القياسية.
"""

from __future__ import annotations

import ast
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zyko.reviewer.rules import (
    CATEGORY_AR,
    RULES,
    SEVERITIES,
    SEVERITY_AR,
    SEVERITY_WEIGHT,
    Finding,
    RuleConfig,
)

# مخطط الحمولة JSON — يتغير فقط بمراجعة مقصودة مع توثيق في CHANGELOG.
SCHEMA = "zyko.review/1"

# سقف حجم الملف الواحد (5MB) — ما فوقه نتيجة مهيكلة بلا قراءة كاملة.
MAX_SOURCE_BYTES = 5_000_000

# مجلدات تُتخطى عند المسح الشجري (حتمية وموثقة).
SKIP_PARTS = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "build",
        "dist",
    }
)

VERDICT_ACCEPT = "مقبول"
VERDICT_IMPROVE = "يحتاج تحسينًا"
VERDICT_FIX = "يحتاج إصلاحًا"
VERDICT_REJECT = "مرفوض"
VERDICT_UNPARSEABLE = "غير قابل للتحليل"


def verdict_for_score(score: int) -> str:
    """خريطة الدرجة ⇒ حكم عربي حتمي (حدود مضبوطة بالاختبار)."""
    if score >= 90:
        return VERDICT_ACCEPT
    if score >= 75:
        return VERDICT_IMPROVE
    if score >= 50:
        return VERDICT_FIX
    return VERDICT_REJECT


@dataclass
class ReviewResult:
    """نتيجة مراجعة ملف واحد: ملاحظات + درجة + حكم — كلها قابلة للتسلسل."""

    path: str
    score: int
    verdict_ar: str
    findings: list[Finding] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    parse_error: str | None = None
    source_sha256: str = ""
    seconds: float = 0.0

    def to_dict(self, *, include_timing: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "path": self.path,
            "score": self.score,
            "verdict_ar": self.verdict_ar,
            "counts": {s: self.counts.get(s, 0) for s in SEVERITIES},
            "findings": [f.to_dict() for f in self.findings],
            "source_sha256": self.source_sha256,
        }
        if self.parse_error is not None:
            payload["parse_error_ar"] = self.parse_error
        if include_timing:
            payload["seconds"] = round(self.seconds, 4)
        return payload


class ReviewEngine:
    """محرك المراجعة الحتمي: 27 قاعدة AST، بلا نموذج وبلا شبكة."""

    def __init__(self, cfg: RuleConfig | None = None, *, rules: tuple | None = None) -> None:
        self.cfg = cfg or RuleConfig()
        self.rules = rules if rules is not None else RULES

    # ------------------------------------------------------------- المصدر
    def review_source(self, source: str, filename: str = "<text>") -> ReviewResult:
        """مراجعة نص مصدر واحد — نقطة الدخول الحتمية الأساسية."""
        started = time.perf_counter()
        sha = hashlib.sha256(source.encode("utf-8", errors="replace")).hexdigest()[:16]
        try:
            tree = ast.parse(source, filename=filename)
        except (SyntaxError, ValueError, MemoryError, RecursionError) as exc:
            return ReviewResult(
                path=filename,
                score=0,
                verdict_ar=VERDICT_UNPARSEABLE,
                findings=[],
                counts={s: 0 for s in SEVERITIES},
                parse_error=_friendly_parse_error(exc),
                source_sha256=sha,
                seconds=time.perf_counter() - started,
            )
        findings: list[Finding] = []
        for rule in self.rules:
            findings.extend(rule.run(tree, self.cfg))
        findings.sort(key=lambda f: (f.line, f.col, f.rule_id))
        counts = {s: 0 for s in SEVERITIES}
        deduction = 0
        for f in findings:
            counts[f.severity] += 1
            deduction += SEVERITY_WEIGHT[f.severity]
        score = max(0, 100 - deduction)
        return ReviewResult(
            path=filename,
            score=score,
            verdict_ar=verdict_for_score(score),
            findings=findings,
            counts=counts,
            parse_error=None,
            source_sha256=sha,
            seconds=time.perf_counter() - started,
        )

    # --------------------------------------------------------------- الملف
    def review_file(self, path: str | Path) -> ReviewResult:
        """مراجعة ملف واحد من القرص مع رسائل عربية لأي عائق قراءة."""
        p = Path(path)
        if not p.is_file():
            return _error_result(str(p), f"الملف غير موجود: {p}")
        try:
            raw = p.read_bytes()
        except OSError as exc:
            return _error_result(str(p), f"تعذرت قراءة الملف: {exc}")
        if len(raw) > MAX_SOURCE_BYTES:
            return _error_result(
                str(p), f"حجم الملف يتجاوز الحد ({len(raw)} بايت > {MAX_SOURCE_BYTES})"
            )
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError:
            return _error_result(str(p), "ترميز الملف ليس UTF-8 — مراجعة نصية غير ممكنة")
        return self.review_source(source, str(p))

    # -------------------------------------------------------------- الشجرة
    def review_path(self, path: str | Path) -> list[ReviewResult]:
        """مراجعة ملف أو شجرة مجلدات — ترتيب حتمي (فرز المسارات)."""
        p = Path(path)
        if p.is_file():
            return [self.review_file(p)]
        if not p.is_dir():
            return [_error_result(str(p), f"المسار غير موجود: {p}")]
        py_files = sorted(
            f
            for f in p.rglob("*.py")
            if not any(part in SKIP_PARTS or part.endswith(".egg-info") for part in f.parts)
        )
        return [self.review_file(f) for f in py_files]


def _error_result(path: str, message_ar: str) -> ReviewResult:
    return ReviewResult(
        path=path,
        score=0,
        verdict_ar=VERDICT_UNPARSEABLE,
        findings=[],
        counts={s: 0 for s in SEVERITIES},
        parse_error=message_ar,
        source_sha256="",
    )


def _friendly_parse_error(exc: Exception) -> str:
    if isinstance(exc, SyntaxError):
        line = f" عند السطر {exc.lineno}" if exc.lineno else ""
        return f"خطأ صياغة بايثون{line}: {exc.msg}"
    if isinstance(exc, RecursionError):
        return "عمق التركيب يتجاوز حدود المحلل — الملف مرفوض عمليًا"
    if isinstance(exc, MemoryError):
        return "استهلاك ذاكرة مفرط أثناء التحليل — الملف مرفوض عمليًا"
    return f"تعذر تحليل المصدر: {exc}"


def summarize(results: list[ReviewResult]) -> dict[str, Any]:
    """ملخص دفعة نتائج: ملفات، ملاحظات بالخطورة، أسوأ الملفات."""
    counts = {s: 0 for s in SEVERITIES}
    for r in results:
        for s in SEVERITIES:
            counts[s] += r.counts.get(s, 0)
    scored = [r for r in results if r.parse_error is None]
    worst = sorted(scored, key=lambda r: (r.score, r.path))[:5]
    return {
        "schema": SCHEMA,
        "files": len(results),
        "counts": counts,
        "total_findings": sum(counts.values()),
        "min_score": min((r.score for r in scored), default=0),
        "worst_files": [
            {"path": r.path, "score": r.score, "verdict_ar": r.verdict_ar} for r in worst
        ],
        "category_ar": CATEGORY_AR,
        "severity_ar": SEVERITY_AR,
    }


__all__ = [
    "MAX_SOURCE_BYTES",
    "SCHEMA",
    "SKIP_PARTS",
    "ReviewEngine",
    "ReviewResult",
    "VERDICT_ACCEPT",
    "VERDICT_FIX",
    "VERDICT_IMPROVE",
    "VERDICT_REJECT",
    "VERDICT_UNPARSEABLE",
    "summarize",
    "verdict_for_score",
]
