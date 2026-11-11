"""اختبارات سجل التدقيق — سلسلة لا تُخترق، زمن خارج السلسلة، سر لا يُدوَّن."""

from __future__ import annotations

import json

from zyko.sandbox.audit import (
    AUDIT_SCHEMA,
    AuditLog,
    AuditVerifyReport,
    canonical_json,
    entry_hash,
)


# ---------------------------------------------------------------- الكتابة
def test_append_writes_signed_entry(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    entry = log.append("patch_file", "ALLOW", "رقعة مقبولة", {"path": "a.py"})
    assert entry.seq == 1
    assert entry.prev_hash == "0" * 64
    assert len(entry.hash) == 64
    assert log.verify().ok


def test_append_chains_to_previous(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    first = log.append("patch_file", "ALLOW", "أول حدث", {})
    second = log.append("run_tests", "DENY", "أمر خارج القائمة", {})
    assert second.seq == 2
    assert second.prev_hash == first.hash
    assert second.hash != first.hash


def test_append_creates_parent_dirs(tmp_path):
    log = AuditLog(tmp_path / "deep" / "nested" / "audit.jsonl")
    log.append("run_tests", "ALLOW", "ok", {})
    assert (tmp_path / "deep" / "nested" / "audit.jsonl").is_file()


def test_seq_increments_across_reopens(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append("a", "ALLOW", "1", {})
    log.append("a", "ALLOW", "2", {})
    # جلسة جديدة على نفس الملف — الترقيم يواصل لا يعيد
    reopened = AuditLog(tmp_path / "audit.jsonl")
    entry = reopened.append("a", "DENY", "3", {})
    assert entry.seq == 3
    assert reopened.verify().count == 3


def test_empty_log_verifies_ok(tmp_path):
    log = AuditLog(tmp_path / "لا-يوجد.jsonl")
    report = log.verify()
    assert report.ok and report.count == 0


# ---------------------------------------------------------------- التطبيع
def test_hostile_inputs_normalized_not_raised(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    entry = log.append(None, None, None, {"x": None})
    assert entry.tool and entry.decision and entry.reason_ar
    assert entry.tool == "أداة-غير-مسماة"


def test_detail_values_truncated_deterministically(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    huge = "ن" * 10_000
    e1 = log.append("t", "ALLOW", "سبب", {"blob": huge})
    e2 = log.append("t", "ALLOW", "سبب", {"blob": huge})
    assert len(e1.detail["blob"]) <= 240 + len("…[مقتطع]")
    assert e1.detail["blob"] == e2.detail["blob"]
    # الحتمية: نفس الحدث في نفس الموقع يعطي نفس الهاش (السلسلة تتقدم عبر seq)
    assert entry_hash(1, "0" * 64, "t", "ALLOW", "سبب", {"blob": e1.detail["blob"]}) == entry_hash(
        1, "0" * 64, "t", "ALLOW", "سبب", {"blob": e2.detail["blob"]}
    )


def test_reason_capped_at_600(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    entry = log.append("t", "DENY", "س" * 5_000, {})
    assert len(entry.reason_ar) <= 600


def test_secrets_masked_in_entry(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    entry = log.append(
        "patch_file",
        "DENY",
        "فشل مع gh p؟ gh p لا — ghp_YgW03Abcdefghijklmnop قُنّع",
        {"note": "token=ghp_Irk3AAbcdefghijklmnop و sk-SecretValueAbcdefgh1234"},
    )
    blob = json.dumps(entry.to_dict(), ensure_ascii=False)
    assert "ghp_YgW03" not in blob
    assert "ghp_Irk3" not in blob
    assert "sk-SecretValue" not in blob
    assert "[سر-مقنّع]" in blob


# ---------------------------------------------------------------- الزمن
def test_ts_stored_but_outside_hash(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    a = log.append("t", "ALLOW", "سبب", {}, ts=111.0)
    b = log.append("t", "ALLOW", "سبب", {}, ts=999.0)
    assert a.ts == 111.0 and b.ts == 999.0
    assert a.hash != b.hash  # السلسلة تتقدم
    # لكن الهاش لا يتغير بتغير الزمن وحده — إعادة توقيع نفس المحتوى
    h1 = entry_hash(1, "0" * 64, "t", "ALLOW", "سبب", {})
    h2 = entry_hash(1, "0" * 64, "t", "ALLOW", "سبب", {})
    assert h1 == h2


def test_same_events_same_chain_bytes(tmp_path):
    """حتمية كاملة: نفس الأحداث ⇒ نفس السجل بالبايت (عدا الزمن)."""
    log_a, log_b = AuditLog(tmp_path / "a.jsonl"), AuditLog(tmp_path / "b.jsonl")
    for log in (log_a, log_b):
        log.append("patch_file", "DENY", "مرفوض", {"path": "x.py"})
        log.append("run_tests", "ALLOW", "نجح", {"exit_code": 0})
    entries_a, entries_b = log_a.entries(), log_b.entries()
    assert len(entries_a) == len(entries_b) == 2
    for x, y in zip(entries_a, entries_b):
        assert x.hash == y.hash
        assert x.seq == y.seq


# ---------------------------------------------------------------- العبث
def _tamper(path, transform):
    lines = path.read_text(encoding="utf-8").splitlines()
    lines = transform(lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_tamper_modified_value_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append("t", "ALLOW", "سبب صادق", {"v": "1"})
    log.append("t", "ALLOW", "سبب ثان", {"v": "2"})
    _tamper(path, lambda lines: [lines[0].replace("سبب صادق", "سبب مزوّر"), lines[1]])
    report = log.verify()
    assert not report.ok and report.first_broken_seq == 1


def test_tamper_deleted_line_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(3):
        log.append("t", "ALLOW", f"حدث {i}", {})
    _tamper(path, lambda lines: [lines[0], lines[2]])
    report = log.verify()
    assert not report.ok


def test_tamper_reordered_lines_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(3):
        log.append("t", "ALLOW", f"حدث {i}", {})
    _tamper(path, lambda lines: [lines[1], lines[0], lines[2]])
    assert not log.verify().ok


def test_tamper_appended_foreign_line_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append("t", "ALLOW", "قانوني", {})
    with path.open("a", encoding="utf-8") as fh:
        forged = {"seq": 2, "prev_hash": "0" * 64, "hash": "z" * 64,
                  "tool": "t", "decision": "ALLOW", "reason_ar": "مزوّر", "detail": {}}
        fh.write(canonical_json(forged) + "\n")
    report = log.verify()
    assert not report.ok and report.first_broken_seq == 2


def test_corrupt_line_is_broken_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append("t", "ALLOW", "سليم", {})
    with path.open("a", encoding="utf-8") as fh:
        fh.write("هذا ليس JSON إطلاقًا\n")
    report = log.verify()
    assert not report.ok and "تالف" in report.reason_ar


def test_entries_skips_corrupt_but_verify_flags(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append("t", "ALLOW", "سليم", {})
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{broken\n")
    assert len(log.entries()) == 1  # القراءة تتخطى
    assert not log.verify().ok  # والتحقق يدين


# ---------------------------------------------------------------- التوثيق
def test_entry_to_dict_deterministic(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    entry = log.append("t", "ALLOW", "سبب", {"a": 1})
    once = json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True)
    twice = json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True)
    assert once == twice


def test_verify_report_to_dict(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    report = log.verify()
    assert isinstance(report, AuditVerifyReport)
    assert report.to_dict()["ok"] is True


def test_chain_summary(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append("t", "ALLOW", "أول", {})
    log.append("t", "ALLOW", "ثانٍ", {})
    summary = log.chain_summary()
    assert summary["count"] == 2
    assert len(summary["last_hash"]) == 64
    assert summary["path"] == "audit.jsonl"


def test_audit_schema_is_versioned():
    assert AUDIT_SCHEMA == "zyko.audit.v1"
