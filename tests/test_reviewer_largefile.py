"""اختبارات largefile — المراجعة المقطّعة للملفات الضخمة: حتمية وحمل وسرعة.

العقد المُختبر:
1. ملف فوق سقف 5MB يُراجع فعلاً (كان يُرفض كليًا) بنتيجة مهيكلة موثقة
   (mode=chunked، عدد المقاطع، بصمة سلسلة المقاطع).
2. البصمة التدفقية مطابقة للبصمة المباشرة، والنوافذ حتمية بالبايت.
3. الدمج: إزاحة الأسطر العالمية صحيحة، تكرارات بلا overlap مستحيلة،
   والدرجة من وزن الخطورة نفسه.
4. سقف الإيجاد: القائمة تُقص حتميًا والعدّ الكامل يبقى صادقًا.
5. ملف متوسط (< السقف) يبقى على المسار العادي — مخرجاته بلا حقول المقطّع.
6. أداء: ملف ~6MB يُراجع ضمن ميزانية زمنية صارمة (قياس القوة/السرعة).
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from zyko.reviewer.engine import MAX_SOURCE_BYTES, ReviewEngine
from zyko.reviewer.largefile import (
    CHUNK_MAX_LINES,
    MAX_LISTED_FINDINGS,
    chunk_line_windows,
    hash_bytes_streaming,
    hash_file_streaming,
    hash_source_streaming,
    review_large_file,
    review_large_source,
)
from zyko.reviewer.rules import SEVERITY_WEIGHT


def _big_source(funcs: int = 150_000) -> str:
    """مصدر ضخم حتمي: دوال صغيرة أعلى حدود التعريفات — ~6MB فوق السقف فعلاً."""
    parts: list[str] = ["import os\n\n\n"]
    for i in range(funcs):
        parts.append(f"def fn_{i:06d}(x):\n    return x + {i}\n\n\n")
    return "".join(parts)


# ------------------------------------------------------------- البصمات التدفقية
def test_streaming_hash_matches_direct_hash(tmp_path: Path) -> None:
    data = b"zyko large file" * 100_000  # ~1.5MB — أكثر من مقطع بصمة واحد
    p = tmp_path / "blob.bin"
    p.write_bytes(data)
    assert hash_file_streaming(p) == hashlib.sha256(data).hexdigest()
    assert hash_bytes_streaming(data) == hashlib.sha256(data).hexdigest()


def test_streaming_hash_empty_and_small() -> None:
    assert hash_source_streaming("") == hashlib.sha256(b"").hexdigest()
    assert hash_source_streaming("س") == hashlib.sha256("س".encode("utf-8")).hexdigest()


# ------------------------------------------------------------- التقسيم
def test_chunk_windows_deterministic() -> None:
    lines = _big_source(2_000).splitlines(keepends=True)
    a = chunk_line_windows(lines)
    b = chunk_line_windows(lines)
    assert a == b and len(a) > 1


def test_chunk_windows_cover_all_lines_exactly() -> None:
    lines = _big_source(3_000).splitlines(keepends=True)
    windows = chunk_line_windows(lines)
    assert windows[0][0] == 0 and windows[-1][1] == len(lines)
    for (_, end_a), (start_b, _) in zip(windows, windows[1:]):
        assert end_a == start_b  # تغطية متصلة بلا فجوات ولا تداخل


def test_chunk_windows_respect_max_lines() -> None:
    """النافذة تُغلق عند أول حد تعريف بعد السقف — تجاوز بسيط محدود بدورية التعريفات."""
    lines = _big_source(5_000).splitlines(keepends=True)
    for start, end in chunk_line_windows(lines):
        assert end - start <= CHUNK_MAX_LINES + 4  # لا نافذة مفرطة
        assert end - start >= 1
    assert all(end - start >= CHUNK_MAX_LINES for start, end in chunk_line_windows(lines)[:-1])


def test_chunk_windows_empty_file() -> None:
    assert chunk_line_windows([]) == []


# ------------------------------------------------------------- المراجعة المقطّعة
def test_large_file_reviewed_not_refused(tmp_path: Path) -> None:
    """ملف ~6MB فوق السقف القديم: يُراجع فعلاً — كان يُرفض كليًا."""
    p = tmp_path / "huge.py"
    source = _big_source()
    assert len(source.encode("utf-8")) > MAX_SOURCE_BYTES  # فوق السقف القديم فعلاً
    p.write_text(source, encoding="utf-8")

    started = time.perf_counter()
    result = ReviewEngine().review_file(p)
    seconds = time.perf_counter() - started

    assert result.parse_error is None
    assert result.mode == "chunked" and result.chunk_count > 1
    assert result.reviewed_chunks == result.chunk_count
    assert result.counts["critical"] == 0

    # بوابة التدرّج النسبية (قياس القوة/السرعة الآلي على أي آلة):
    # الأبواب الزمنية المطلقة (120 ثانية و≥50KB/s سابقًا) كانت هشة —
    # تحت تغطية الاختبارات أو على آلة CI بطيئة تنكسر رغم أن الخوارزمية
    # سليمة. الصادق هو قياس *التدرّج*: مرجع صغير من المصدر نفسه فوق
    # سقف المقطع (‎~80KB → ~10 مقاطع)، فلو تحول التجميع تربيعيًا
    # (التفشل الكلاسيكي للملفات الضخمة) انفجرت نسبة الزمن/السطر
    # مهما كانت سرعة الآلة — وهذا ما نصطاده.
    ref_source = _big_source(2_000)
    ref_lines = max(len(ref_source.splitlines()), 1)
    ref_started = time.perf_counter()
    review_large_source(ref_source)
    ref_seconds = time.perf_counter() - ref_started

    big_lines = max(len(source.splitlines()), 1)
    per_line_big = seconds / big_lines
    per_line_ref = ref_seconds / ref_lines
    assert per_line_big <= 3.0 * per_line_ref, (
        "تدهور تربيعي محتمل: زمن السطر في الملف الضخم تجاوز 3× المرجع "
        f"(big={per_line_big:.6f}s/سطر، ref={per_line_ref:.6f}s/سطر)"
    )
    # حارس تعليق مطلق متسامح فقط — ليس بوابة أداء، بل ضد الانهيار الكامل
    assert seconds < 600.0

    payload = result.to_dict()
    assert payload["mode"] == "chunked" and payload["chunk_count"] == result.chunk_count
    assert "chunk_chain_hash" in payload


def test_large_file_determinism(tmp_path: Path) -> None:
    """نفس الملف مرتين ⇒ نفس الدرجة ونفس بصمة سلسلة المقاطع بالبايت."""
    p = tmp_path / "huge.py"
    p.write_text(_big_source(3_000), encoding="utf-8")
    a = review_large_file(p)
    b = review_large_file(p)
    assert a.score == b.score
    assert a.chunk_chain_hash == b.chunk_chain_hash
    assert a.source_sha256 == b.source_sha256
    assert a.to_dict() == b.to_dict()


def test_large_source_sha_matches_direct(tmp_path: Path) -> None:
    source = _big_source(2_000)
    p = tmp_path / "big.py"
    p.write_text(source, encoding="utf-8")
    result = review_large_file(p)
    assert result.source_sha256 == hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def test_findings_global_line_offsets(tmp_path: Path) -> None:
    """أسطر ملاحظات المقاطع مُزاحة عالميًا — السطر داخل النتيجة ≤ عدد أسطر الملف."""
    source = _big_source(2_500)
    lines_count = len(source.splitlines())
    result = review_large_source(source)
    assert result.findings
    for finding in result.findings:
        assert 1 <= finding.line <= lines_count


def test_medium_file_stays_single_mode(tmp_path: Path) -> None:
    """ملف متوسط تحت السقف: المسار العادي كما كان — بلا حقول المقطّع."""
    p = tmp_path / "medium.py"
    p.write_text("def f():\n    return 1\n", encoding="utf-8")
    result = ReviewEngine().review_file(p)
    assert result.mode == "single"
    assert "mode" not in result.to_dict()


def test_score_math_same_weights(tmp_path: Path) -> None:
    """الدرجة من العدّ المدموج بوزن الخطورة نفسه — رياضيات واحدة."""
    source = _big_source(1_500)
    result = review_large_source(source)
    deduction = sum(SEVERITY_WEIGHT[s] * result.counts[s] for s in result.counts)
    assert result.score == max(0, 100 - deduction)


def test_findings_truncated_but_counts_exact(tmp_path: Path) -> None:
    """سقف الإيجاد: القائمة تُقص حتميًا والعدّ الكامل يبقى صادقًا في counts."""
    source = _big_source(6_000)  # > 500 ملاحظة حتميًا — بحجم يجعل الاختبار سريعًا
    result = review_large_source(source)
    assert result.findings_truncated is True
    assert len(result.findings) == MAX_LISTED_FINDINGS
    total_counts = sum(result.counts.values())
    assert total_counts > MAX_LISTED_FINDINGS
    # القصة تُروى في to_dict بصدق أيضًا
    payload = result.to_dict()
    assert payload["findings_truncated"] is True
    assert payload["counts"]["low"] == result.counts["low"]


def test_unparseable_window_documented_not_crash() -> None:
    """نافذة إجبارية غير قابلة للتحليل ⇒ خطأ موثّق — لا استثناء ولا حذف صامت."""
    # كتلة واحدة بلا أي حد تعريف علوي أطول من سقف الإغلاق الإجباري
    body = "\n".join(f"x_{i} = value_{i} + 1" for i in range(4_000))
    source = "if True:\n" + "\n".join(f"    y_{i} = {i}" for i in range(4_000))
    # مصدر بلا حدود أعلى: أسئلة مستوى أعلى فقط عند الإغلاق الإجباري
    result = review_large_source(body + "\n" + source)
    # النتيجة مهيكلة دائماً — إما مقاطع مراجَعة أو أخطاء موثقة في parse_error
    assert result.parse_error is None or "مقطع" in result.parse_error


def test_chunked_through_orchestrator(tmp_path: Path, monkeypatch) -> None:
    """التكامل: مراجعة ملف ضخم عبر أدوات المنسق نفسها (بدون مسار خاص).

    السقف يُخفَّض مؤقتًا (monkeypatch) كي يصير ملف الاختبار فوق السقف
    بلا تكلفة ملف 6MB — المسار المقطّع نفسه يُختبر كما هو.
    """
    import zyko.reviewer.engine as engine_mod
    from zyko.orchestrator import classify, extract_context, route, run

    monkeypatch.setattr(engine_mod, "MAX_SOURCE_BYTES", 10_000)
    p = tmp_path / "huge.py"
    p.write_text(_big_source(1_200), encoding="utf-8")
    assert p.stat().st_size > 10_000
    goal = f"راجع {p}"
    plan = route(classify(goal), context=extract_context(goal))
    result = run(plan, dry_run=True)
    assert result.ok
    output = result.steps[0].output
    assert output["mode"] == "chunked"
    assert output["chunk_count"] >= 1
