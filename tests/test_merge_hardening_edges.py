"""تحصين ما بعد الدمج — عقود الوحدات المساندة عبر الطبقات.

بعد دمج جولة 17، هذا الملف يضغط العقود الحتمية الموثقة في الوحدات
التي يحتكم إليها المحرك الجديد: سجل التدقيق (سلسلة sha256 ضد العبث)،
استخراج JSON من نص النماذج، أدوات RTL والـPII العربية، بصمة المحرّس،
تقطيع الملفات الكبيرة، وفحص الأشجار قبل التسليم. كل تأكيد هنا قِيس
على السلوك الفعلي للوحدة قبل كتابته — لا اختبار على تخمين.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from zyko.coder.precheck import check_directory
from zyko.guardian.contracts import GateResult, compute_fingerprint
from zyko.reviewer.largefile import chunk_line_windows, hash_file_streaming, hash_source_streaming
from zyko.sandbox.audit import AUDIT_SCHEMA, AuditLog, canonical_json, entry_hash
from zyko.structured.extract import extract_json
from zyko.tools.pii_ar.engine import scan as pii_scan
from zyko.tools.rtl.core import arabic_letter_ratio, excerpt_of, has_arabic, line_col_of


# ------------------------------------------------------------------ سجل التدقيق
def test_canonical_json_is_deterministic_and_sorted() -> None:
    """JSON حتمي بالبايت: المفاتيح مفرزة والفاصل مقتصد — إدخالان متطابقان."""
    a = canonical_json({"ب": 1, "أ": 2})
    b = canonical_json({"أ": 2, "ب": 1})
    assert a == b == '{"أ":2,"ب":1}'


def test_entry_hash_changes_when_content_changes() -> None:
    """النفس يعطي النفس، وأي انحراف يغيّر البصمة — سلسلة لا تُغش."""
    base = entry_hash(1, "0" * 64, "patch_file", "ALLOW", "سبب", {"path": "a.py"})
    assert entry_hash(1, "0" * 64, "patch_file", "ALLOW", "سبب", {"path": "a.py"}) == base
    changed_seq = entry_hash(2, "0" * 64, "patch_file", "ALLOW", "سبب", {"path": "a.py"})
    changed_reason = entry_hash(1, "0" * 64, "patch_file", "ALLOW", "سبب آخر", {"path": "a.py"})
    assert base != changed_seq and base != changed_reason


def test_audit_log_chain_of_three_verifies_clean(tmp_path: Path) -> None:
    """ثلاثة أحداث موقعة تُتحقق سلسلتها من الرأس — السليم يُحكم سليمًا."""
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(3):
        log.append("patch_file", "ALLOW", f"محاولة {i}", {"path": f"f{i}.py"})
    report = log.verify()
    assert report.ok and report.count == 3 and report.first_broken_seq is None


def test_audit_log_detects_tampering_at_exact_entry(tmp_path: Path) -> None:
    """تعديل تفصيل حدث وسط السلسلة يكشفه إعادة الحساب عند رقمه بالضبط."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append("tool_a", "ALLOW", "أول", {})
    log.append("tool_b", "DENY", "ثانٍ", {"path": "سر.py"})
    log.append("tool_c", "ALLOW", "ثالث", {})
    lines = log.path.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[1])
    row["detail"]["path"] = "معدّل-تسليلاً.py"
    lines[1] = canonical_json(row)
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = log.verify()
    assert not report.ok
    assert report.first_broken_seq == 2
    assert "لا يطابق المحتوى" in report.reason_ar


def test_audit_log_masks_secret_shaped_text_before_disk(tmp_path: Path) -> None:
    """كل نص يشبه سرًا يُقنَّع قبل التدوين — دفاع عمق موثق لا وعد."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(
        "tool",
        "ALLOW",
        "مفتاح ghp_Abcdef12345678901234 داخل السبب",
        {"token": "sk-abc123456789012345678"},
    )
    entry = log.entries()[0]
    assert "ghp_" not in entry.reason_ar
    assert "sk-abc" not in json.dumps(entry.detail, ensure_ascii=False)
    assert "[سر-مقنّع]" in entry.reason_ar


def test_audit_log_clamps_long_values_deterministically(tmp_path: Path) -> None:
    """القيمة الطويلة تُقص بعلامة موثقة — نفس المدخل يعطي نفس المقتطع بالبايت."""
    log = AuditLog(tmp_path / "audit.jsonl")
    long = "ث" * 500
    log.append("tool", "ALLOW", "سبب", {"value": long})
    clamped = log.entries()[0].detail["value"]
    assert len(clamped) <= 240 and clamped.endswith("…[مقتطع]")
    log2 = AuditLog(tmp_path / "audit2.jsonl")
    log2.append("tool", "ALLOW", "سبب", {"value": long})
    assert log2.entries()[0].detail["value"] == clamped


def test_audit_entries_skip_corrupt_line_but_summary_counts_clean(tmp_path: Path) -> None:
    """سجل فارغ يُحكم سليمًا بعدد صفر، وسطر تالف يُتخطى في القراءة لا يُنهيها."""
    assert AuditLog(tmp_path / "فارغ.jsonl").verify().ok
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append("tool_a", "ALLOW", "سليم", {})
    with log.path.open("a", encoding="utf-8") as fh:
        fh.write("سطر-تالف-ليس-json\n")
    log.append("tool_b", "DENY", "سليم ثانٍ", {})
    entries = log.entries()
    assert [e.seq for e in entries] == [1, 2]
    assert log.chain_summary()["count"] == 2


# ------------------------------------------------------------------ استخراج JSON
@pytest.mark.parametrize("empty", [None], ids=["none"])
def test_extract_json_returns_none_for_no_text(empty: str | None) -> None:
    """لا نص = لا JSON — None صريح لا استثناء."""
    assert extract_json(empty) is None


def test_extract_json_parses_plain_object() -> None:
    """‏JSON صريح يُقبل كما هو — الحد الأدنى الموثق."""
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_digs_json_out_of_arabic_prose() -> None:
    """نموذج يلف JSON بنثر عربي — المسح المتوازن يخرّج القيمة الأولى."""
    text = 'هذه هي النتيجة التي طلبتها: {"الاسم": "خالد", "العمر": 30} وشكرًا'
    assert extract_json(text) == {"الاسم": "خالد", "العمر": 30}


def test_extract_json_prefers_markdown_fenced_block() -> None:
    """كتلة ```json داخل النثر تُفضَّل — والقيم على أسطر متعددة تُقبل."""
    text = 'شرح أول\n```json\n{\n  "ok": true\n}\n```\nشرح آخر'
    assert extract_json(text) == {"ok": True}


def test_extract_json_strips_reasoning_blocks_first() -> None:
    """كتل التفكير تُسقط قبل المسح — صمت التفكير لا يخدع المستخرج."""
    text = '<think>سأعيد {"خاطئ": 1}</think>{"صحيح": 2}'
    assert extract_json(text) == {"صحيح": 2}


def test_extract_json_handles_top_level_list() -> None:
    """القائمة بالنطاق الأعلى قيمة JSON مشروعة — لا حصر بالكائنات."""
    assert extract_json("عناصر: [1, 2, 3]") == [1, 2, 3]


def test_extract_json_braces_inside_strings_do_not_confuse_balance() -> None:
    """أقواس داخل سلاسل لا تخل بالتوازن، والنثر الأعمى بلا JSON يعطي None صادقًا."""
    text = '{"code": "if (x) { return \\"}\\" }", "n": 1}'
    assert extract_json(text) == {"code": 'if (x) { return "}" }', "n": 1}
    assert extract_json("لا شيء هنا إطلاقاً") is None


# ------------------------------------------------------------------ أدوات RTL
def test_has_arabic_distinguishes_scripts_and_ratio_measures_letters() -> None:
    """كشف العربية: عربي نعم، لاتيني لا — والنسبة تقيس الحروف لا الفراغات."""
    assert has_arabic("مرحبا بالعالم") is True
    assert has_arabic("hello world") is False
    assert arabic_letter_ratio("مرحبا hello") == 0.5
    assert arabic_letter_ratio("hello") == 0.0


def test_line_col_and_excerpt_map_offset_to_human_position() -> None:
    """الإزاحة تُحوَّل إلى (سطر، عمود) من 1 ومقتطع حولها — للتشخيص البشري."""
    source = "سطر أول\nسطر ثانٍ"
    assert line_col_of(source, 0) == (1, 1)
    assert line_col_of(source, 3) == (1, 4)  # داخل السطر الأول
    assert line_col_of(source, 8) == (2, 1)  # أول محرف بعد السطر الجديد
    assert excerpt_of("abcdef", 2, 4) == "abcd"


# ------------------------------------------------------------------ فاحص PII العربي
def test_pii_scan_finds_saudi_phone_with_country_and_validity() -> None:
    """هاتف سعودي محلي يُعثر عليه بنوعه وبلده وصلاحيته — قياس لا ادعاء."""
    findings = pii_scan("تواصل معي على 0501234567 لأي استفسار")
    assert len(findings) == 1
    f = findings[0]
    assert f.type == "phone" and f.value == "0501234567"
    assert f.country == "966" and f.valid is True


def test_pii_scan_type_filter_limits_findings() -> None:
    """مرشّح الأنواع يقيّد الفحص: هاتف يُعثر عليه، وهوية لا شيء، ونص نظيف صفر."""
    text = "تواصل معي على 0501234567"
    assert len(pii_scan(text, types=["phone"])) == 1
    assert pii_scan(text, types=["national_id"]) == []
    assert pii_scan("هذا نص عربي نظيف بلا أي بيانات شخصية إطلاقا") == []


# ------------------------------------------------------------------ بصمة المحرّس
def test_guardian_fingerprint_is_deterministic_per_exact_input() -> None:
    """بصمة القرار: نفس الاقتراح والبوابات = نفس sha256 دائمًا."""
    gates = [GateResult("secrets", True, "نظيف"), GateResult("syntax", False, "مكسور")]
    fp1 = compute_fingerprint("اقتراح", gates)
    fp2 = compute_fingerprint(
        "اقتراح",
        [GateResult("secrets", True, "نظيف"), GateResult("syntax", False, "مكسور")],
    )
    assert fp1 == fp2 and len(fp1) == 64
    assert AUDIT_SCHEMA  # المخططان معلنان ثابتين في المستودع


def test_guardian_fingerprint_changes_when_gate_verdict_flips() -> None:
    """انقلاب الحكم أو تغيّر السبب يغيّر البصمة — الحكم والسبب معًا في العقد."""
    allow = [GateResult("secrets", True, "نظيف")]
    deny = [GateResult("secrets", False, "سرب")]
    softened = [GateResult("secrets", True, "نظيف بعد الإصلاح")]
    assert compute_fingerprint("نص", allow) != compute_fingerprint("نص", deny)
    assert compute_fingerprint("نص", allow) != compute_fingerprint("نص", softened)


# ------------------------------------------------------------------ تقطيع الملفات الكبيرة
def test_streaming_hash_equals_direct_sha256() -> None:
    """الهاش المتدفق يطابق sha256 المباشر — التقطيع لا يغيّر البصمة."""
    source = "سطر = 1\n" * 5000
    assert hash_source_streaming(source) == hashlib.sha256(source.encode("utf-8")).hexdigest()


def test_streaming_file_hash_matches_source_hash(tmp_path: Path) -> None:
    """هاش الملف من القرص يطابق هاش نصه — القراءة المتدفقة صادقة."""
    source = "x = 2\n" * 3000
    path = tmp_path / "big.py"
    path.write_text(source, encoding="utf-8")
    assert hash_file_streaming(path) == hash_source_streaming(source)


def test_chunk_windows_tile_the_whole_file_without_overlap() -> None:
    """نوافذ التقسيم تبلاط الأسطر كلها بلا فجوة ولا تراكب، والصغير نافذة واحدة."""
    lines = [f"val_{i} = {i}\n" for i in range(1000)]
    windows = chunk_line_windows(lines)
    assert windows[0][0] == 0 and windows[-1][1] == len(lines)
    for (_s1, e1), (s2, _e2) in zip(windows, windows[1:]):
        assert e1 == s2  # متتالية حصرية النهاية
    assert sum(e - s for s, e in windows) == len(lines)
    assert chunk_line_windows(["x = 1\n", "y = 2\n"]) == [(0, 2)]
    assert chunk_line_windows([]) == []


# ------------------------------------------------------------------ فحص الأشجار قبل التسليم
def test_check_directory_empty_tree_is_clean_with_zero_counts(tmp_path: Path) -> None:
    """مجلد فارغ: نظيف بعدد صفر — لا خطأ على لا شيء."""
    report = check_directory(tmp_path)
    assert report.ok and report.py_files == 0 and report.other_files == 0


def test_check_directory_counts_python_and_other_files(tmp_path: Path) -> None:
    """العدّ يفرز البايثوني عن الامتدادات غير المصنفة — والمكسور يرفض الشجرة."""
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "config.toml").write_text("[a]\n", encoding="utf-8")
    (tmp_path / "بيانات.json").write_text("{}", encoding="utf-8")
    (tmp_path / "مكسور.py").write_text("def :( \n", encoding="utf-8")
    report = check_directory(tmp_path)
    assert report.py_files == 2 and report.other_files == 2
    assert not report.ok  # المكسور يرفض الشجرة كاملة
