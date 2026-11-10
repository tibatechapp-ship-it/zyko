"""zyko.reviewer.largefile — المراجعة المقطّعة للملفات الضخمة (حتمية بالبايت).

الفجوة التي يغلقها هذا المورد: ``ReviewEngine`` كان يرفض أي ملف يتجاوز
5MB بنتيجة مهيكلة — أي أن الكود الحقيقي الضخم (ملفات مولدة، مخرجات
أدوات، ملفات عهدة قديمة) كان خارج الرقعة كليًا. هنا المراجعة تتجاوزه:

1. **بصمة تدفقية** — sha256 تزايدية بمقاطع ثابتة، تعمل على أي حجم بلا
   قراءة كاملة للذاكرة، ومطابقة للبصمة المباشرة على أي ملف صغير.
2. **تقسيم حتمي** — نوافذ من ``CHUNK_MAX_LINES`` سطرًا تُغلق عند حدود
   التعريفات العليا (``def``/``class``/decorator في العمود صفر) كي يبقى
   كل مقطع بايثون قابلًا للتحليل؛ وإن طال كتلة بلا حدود ترقى إلى
   ``HARD_WINDOW_LINES`` يُغلق إجباريًا (مقطع غير قابل للتحليل ⇒ خطأ
   موثّق بصدق لا انهيار ولا حذف صامت).
3. **دمج موثّق** — ملاحظات كل مقطع تُزاح إلى أسطرها العالمية، تُفرز،
   وتُزال التكرارات بمفتاح (rule_id، سطر عالمي، عمود)؛ الدرجات تُحسب
   من العدّ النهائي بوزن الخطورة نفسه (``SEVERITY_WEIGHT``) فتبقى
   الرياضيات واحدة مع المراجعة العادية.
4. **سقف إيجاد** — الفرضيات الحقيقية قد تولّد عشرات آلاف الملاحظات؛
   قائمة ``findings`` في الناتج تُقص عند ``MAX_LISTED_FINDINGS`` بعد
   الفرز الحتمي مع ``findings_truncated=True`` وعدّ دقيق كامل — الإيصال
   يبقى محمولاً والعدّ يبقى صادقًا.

الحتمية (R2): نفس الملف ⇒ نفس التقسيم ⇒ نفس الملاحظات ⇒ نفس الدرجة
ونفس ``chunk_chain_hash`` — بلا أزمنة ولا عشوائية في أي خطوة.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from pathlib import Path
from typing import Any

from zyko.reviewer.engine import ReviewEngine, ReviewResult, verdict_for_score
from zyko.reviewer.rules import SEVERITIES, SEVERITY_WEIGHT

__all__ = [
    "CHUNK_MAX_LINES",
    "HARD_WINDOW_LINES",
    "HASH_CHUNK_BYTES",
    "MAX_LARGE_BYTES",
    "MAX_LISTED_FINDINGS",
    "chunk_line_windows",
    "hash_file_streaming",
    "hash_source_streaming",
    "review_large_file",
    "review_large_source",
]

# نوافذ المراجعة: 800 سطرًا — قابلة للتحليل بسرعة وبذاكرة محدودة.
CHUNK_MAX_LINES = 800
# سقف الإغلاق الإجباري: كتلة بلا حدود تعريفات تُغلق هنا (قد تكون غير قابلة للتحليل — موثّق).
HARD_WINDOW_LINES = 3200
# مقاس مقطع البصمة التدفقية (1MB).
HASH_CHUNK_BYTES = 1_048_576
# السقف الأعلى لوضع الملفات الضخمة — فوقه نتيجة مهيكلة رافضة (حماية ذاكرة).
MAX_LARGE_BYTES = 100_000_000
# أقصى عدد ملاحظات يُدرج في الناتج (العدّ الكامل يبقى في counts دائمًا).
MAX_LISTED_FINDINGS = 500

# حدود التعريفات العليا — العمود صفر فقط، حتمية بحتة.
_TOP_LEVEL_RE = re.compile(r"^(def |async def |class |@)")


def hash_source_streaming(source: str, *, chunk_bytes: int = HASH_CHUNK_BYTES) -> str:
    """بصمة sha256 لنص بمقاطع ثابتة — نفس نتيجة sha256 المباشر بالبايت."""
    data = source.encode("utf-8", errors="replace")
    return hash_bytes_streaming(data, chunk_bytes=chunk_bytes)


def hash_bytes_streaming(data: bytes, *, chunk_bytes: int = HASH_CHUNK_BYTES) -> str:
    """بصمة sha256 تزايدية على بايتات — الحتمية نفسها بذاكرة أقل."""
    digest = hashlib.sha256()
    for start in range(0, len(data), chunk_bytes):
        digest.update(data[start : start + chunk_bytes])
    return digest.hexdigest()


def hash_file_streaming(path: str | Path, *, chunk_bytes: int = HASH_CHUNK_BYTES) -> str:
    """بصمة sha256 تدفقية لملف على القرص — تعمل على أي حجم بلا قراءة كاملة."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk_bytes)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def chunk_line_windows(lines: list[str]) -> list[tuple[int, int]]:
    """نوافذ التقسيم (بداية، نهاية حصرية) — حتمية بالبايت لنفس الأسطر.

    النافذة تُغلق عند أول حد تعريف علوي يتجاوز ``CHUNK_MAX_LINES`` من
    بدايتها؛ وإن تجاوزت الكتلة ``HARD_WINDOW_LINES`` بلا أي حد تُغلق
    إجباريًا عند هذا السقف. الملفات الصغيرة تعيد نافذة واحدة تغطي الكل.
    """
    total = len(lines)
    if total == 0:
        return []
    windows: list[tuple[int, int]] = []
    start = 0
    for index in range(total):
        span = index - start
        if span >= HARD_WINDOW_LINES or (
            span >= CHUNK_MAX_LINES and _TOP_LEVEL_RE.match(lines[index])
        ):
            windows.append((start, index))
            start = index
    windows.append((start, total))
    return windows


def _chunk_result_name(filename: str, index: int) -> str:
    return f"{filename}#[مقطع {index}]"


def review_large_source(source: str, filename: str = "<large>") -> ReviewResult:
    """راجع نصًا ضخمًا بتقسيم حتمي ودمج موثّق — نقطة الدخول الحتمية."""
    engine = ReviewEngine()
    lines = source.splitlines(keepends=True)
    windows = chunk_line_windows(lines)
    chunk_shas: list[str] = []
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    counts = {s: 0 for s in SEVERITIES}
    parse_errors: list[str] = []
    reviewed_chunks = 0

    for order, (start, end) in enumerate(windows, start=1):
        chunk_text = "".join(lines[start:end])
        chunk_shas.append(hashlib.sha256(chunk_text.encode("utf-8", errors="replace")).hexdigest())
        result = engine.review_source(chunk_text, _chunk_result_name(filename, order))
        if result.parse_error is not None:
            parse_errors.append(f"مقطع {order} (سطر {start + 1}): {result.parse_error}")
            continue
        reviewed_chunks += 1
        for finding in result.findings:
            global_line = finding.line + start
            key = (finding.rule_id, global_line, finding.col)
            if key in seen:
                continue
            seen.add(key)
            counts[finding.severity] += 1
            merged.append(dataclasses.replace(finding, line=global_line))

    merged.sort(key=lambda f: (f.line, f.col, f.rule_id))
    deduction = sum(SEVERITY_WEIGHT[s] * counts[s] for s in SEVERITIES)
    score = max(0, 100 - deduction)
    result = ReviewResult(
        path=filename,
        score=score,
        verdict_ar=verdict_for_score(score),
        findings=merged[:MAX_LISTED_FINDINGS],
        counts=counts,
        parse_error="؛ ".join(parse_errors) if parse_errors else None,
        source_sha256=hash_source_streaming(source)[:16],
    )
    result.mode = "chunked"
    result.chunk_count = len(windows)
    result.chunk_chain_hash = hashlib.sha256("|".join(chunk_shas).encode("utf-8")).hexdigest()
    result.findings_truncated = len(merged) > MAX_LISTED_FINDINGS
    result.reviewed_chunks = reviewed_chunks
    return result


def review_large_file(path: str | Path) -> ReviewResult:
    """راجع ملفًا ضخمًا من القرص — رسائل عربية مهيكلة لأي عائق."""
    p = Path(path)
    try:
        size = p.stat().st_size
    except OSError as exc:
        return _refusal(str(p), f"تعذّر فحص حجم الملف: {exc}")
    if size > MAX_LARGE_BYTES:
        return _refusal(str(p), f"الملف يتجاوز سقف المراجعة المقطّعة ({size} بايت > {MAX_LARGE_BYTES})")
    try:
        source = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return _refusal(str(p), "ترميز الملف ليس UTF-8 — مراجعة نصية غير ممكنة")
    except OSError as exc:
        return _refusal(str(p), f"تعذرت قراءة الملف: {exc}")
    return review_large_source(source, str(p))


def _refusal(path: str, message_ar: str) -> ReviewResult:
    result = ReviewResult(
        path=path,
        score=0,
        verdict_ar="غير قابل للتحليل",
        findings=[],
        counts={s: 0 for s in SEVERITIES},
        parse_error=message_ar,
        source_sha256="",
    )
    result.mode = "chunked"
    result.chunk_count = 0
    return result
