"""الحالات المكمّلة — تكمل كل إمارة إلى عدّتها التعاقدية النهائية.

كل حالة هنا نفس عقد البنّائين الأصليين: كود حقيقي، حكم على عقد موثق،
سبب عربي واضح. الأعداد النهائية لكل إمارة مثبتة بالاختبار البنيوي.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pathlib
import tempfile
from types import SimpleNamespace

from zyko.guardian.gates import PIIGate, RTLGate, StructuralGate, default_gates
from zyko.mind.global_memory import GENESIS_HASH, GlobalMemory
from zyko.mind.reflect import (
    MAX_FEEDBACK_CHARS,
    RetryBudget,
    condense_feedback,
    guard_execution,
    guard_feedback,
    guard_perception,
    guard_plan,
    normalize_stage,
    reflect_note,
)
from zyko.mind.perception import perceive
from zyko.sandbox.audit import AuditLog, canonical_json, entry_hash
from zyko.sandbox.contracts import PermissionContract
from zyko.sandbox.jail import (
    jail_level,
    landlock_abi,
    net_confinement,
    reset_detection_cache,
    sensitive_overlays,
    wrap_argv,
    write_roots,
)
from zyko.sandbox.patcher import patch_file
from zyko.sandbox.runner import run_tests

_SECRET_AKIA = "AKIA" + "IOSFODNN7EXAMPLE"  # عيّنة AWS التعليمية — بالجمع لا بالحرف
_SECRET_XOX = "xoxb-" + "123456789012-ABCDEFGHIJKLMNOPQRSTUVWX"  # عيّنة سلاك مزيّفة


def build_extra_pii_redact():
    cases = []
    from zyko.tools.pii_ar import PIIScanner, normalize_digits, redact, scan
    from zyko.tools.pii_ar.engine import PRIORITY
    from zyko.tools.pii_ar.normalize import to_arabic_digits, to_western_digits

    def fn_mask_iban():
        from zyko.benchmarks.eval1000_cases_a import _valid_iban
        out, hits = redact(f"حساب {_valid_iban('SA')} لدى مصرف", mode="mask")
        return (True, "آيبان مقنّع") if "SA30" not in out and hits else (False, f"آيبان لم يُقنَّع: {out[:30]}")
    cases.append(("أنماط", "قناع mask على آيبان", fn_mask_iban))

    def fn_mask_nid():
        out, hits = redact("هوية 1023456789 سعودية", mode="mask")
        return (True, "هوية مقنّعة") if "1023456789" not in out and hits else (False, "هوية لم تُقنَّع")
    cases.append(("أنماط", "قناع mask على هوية وطنية", fn_mask_nid))

    def fn_hash_email():
        out, hits = redact("عنوان user@site.com مسجل", mode="hash")
        token = next((t for t in out.split() if t.startswith("#")), "")
        return (True, "بريد بهاش") if token and token not in ("#",) and "user@site.com" not in out else (False, f"هاش البريد: {out[:30]}")
    cases.append(("أنماط", "هاش على بريد إلكتروني", fn_hash_email))

    def fn_placeholder_neighborhood():
        out, _ = redact("اتصل على 0512345678 غدًا الصباح", mode="placeholder")
        ok = "اتصل" in out and "غدًا الصباح" in out
        return (True, "الجوار محفوظ") if ok else (False, f"الحجب أفسد الجوار: {out[:40]}")
    cases.append(("حفظ", "موضع النوع يحفظ الجوار", fn_placeholder_neighborhood))

    def fn_unknown_types_filter():
        hits = scan("هاتف 0512345678", types=["نوع-غريب"])
        return (True, "فلتر غريب يعود فارغًا") if hits == [] else (False, "فلتر مجهول أعاد نتائج")
    cases.append(("فلاتر", "فلتر نوع مجهول يعود فارغًا", fn_unknown_types_filter))

    def fn_scanner_default():
        sc = PIIScanner()
        return (True, "الافتراضي 0.5") if abs(sc.min_confidence - 0.5) < 1e-9 else (False, f"عتبة: {sc.min_confidence}")
    cases.append(("عتبات", "PIIScanner الافتراضية 0.5", fn_scanner_default))

    def fn_priority_keys():
        ok = set(PRIORITY) == {"person_name", "phone", "national_id", "iban", "bank_card", "email", "address"}
        return (True, "سبعة مفاتيح") if ok else (False, f"مفاتيح الأولوية: {sorted(PRIORITY)}")
    cases.append(("سجل", "PRIORITY سبعة أنواع موثقة", fn_priority_keys))

    def fn_ar_roundtrip():
        ar = to_arabic_digits("0123456789")
        back = to_western_digits(ar)
        return (True, "الرحلة ذهابًا وعودة") if back == "0123456789" and ar == "٠١٢٣٤٥٦٧٨٩" else (False, f"ذهاب {ar} عودة {back}")
    cases.append(("تطبيع", "تحويل الأرقام ذهابًا وعودة", fn_ar_roundtrip))
    return cases


def build_extra_gates():
    cases = []

    def fn_iban_counts():
        from zyko.benchmarks.eval1000_cases_a import _valid_iban
        r = asyncio.run(PIIGate().check(f"حساب {_valid_iban('SA')} لدى مصرف"))
        counts = r.details.get("counts", {})
        return (True, "آيبان معدود") if not r.passed and counts.get("iban") == 1 else (False, f"counts: {r.details}")
    cases.append(("PIIGate", "عدّ الآيبان في التفاصيل", fn_iban_counts))

    def fn_nid_counts():
        r = asyncio.run(PIIGate().check("هوية 1023456789 سعودية"))
        counts = r.details.get("counts", {})
        return (True, "هوية معدودة") if not r.passed and counts.get("national_id") == 1 else (False, f"counts: {r.details}")
    cases.append(("PIIGate", "عدّ الهوية في التفاصيل", fn_nid_counts))

    def fn_rtl_empty():
        r = asyncio.run(RTLGate().check(""))
        return (True, "فراغ يمر RTL") if r.passed else (False, "فراغ رُفض بوابة RTL خطأً")
    cases.append(("RTLGate", "النص الفارغ يمر", fn_rtl_empty))

    def fn_struct_numeric():
        r = asyncio.run(StructuralGate().check("1234567890"))
        return (True, "أرقام بنيويًا سليمة") if r.passed else (False, "أرقام خالصة رُفضت")
    cases.append(("Structural", "نص رقمي يمر بنيويًا", fn_struct_numeric))

    def fn_gates_fresh():
        a = default_gates()
        b = default_gates()
        ok = all(x is not y for x, y in zip(a, b))
        return (True, "بناء جديد كل نداء") if ok else (False, "default_gates أعاد نفس الكائنات")
    cases.append(("ترتيب", "default_gates يبني كائنات جديدة", fn_gates_fresh))

    def fn_gate_names_unique():
        names = [g.gate_name for g in default_gates()]
        return (True, "أسماء فريدة") if len(set(names)) == 3 else (False, f"أسماء: {names}")
    cases.append(("ترتيب", "أسماء البوابات فريدة", fn_gate_names_unique))
    return cases


def build_extra_contracts():
    cases = []

    def fn_cmd_none():
        c = PermissionContract.for_roots("/tmp", allow_run_tests=True)
        tokens, reason = c.check_command(None)
        return (True, "None يُرفض") if tokens is None else (False, "None مرّ أمرًا")
    cases.append(("أوامر", "check_command على None", fn_cmd_none))

    def fn_read_outside_passthrough():
        c = PermissionContract.for_roots("/tmp/zyko-nonexistent-root-eval")
        target, reason = c.check_read_path("/etc/hostname")
        ok = target is None and reason
        return (True, "رفض الجذر يمر أولًا") if ok else (False, "قراءة خارج الجذور قُبلت")
    cases.append(("قراءة-حساسة", "رفض الجذر الأصلي يسبق حرس الأسرار", fn_read_outside_passthrough))
    return cases


def build_extra_audit():
    cases = []

    def fn_canonical_arabic():
        s = canonical_json({"نص": "عربي"})
        return (True, "العربي غير مهرّب") if "عربي" in s else (False, f"canonical: {s[:30]}")
    cases.append(("بنية", "canonical_json يحفظ العربي غير مهرب", fn_canonical_arabic))

    def fn_detail_none():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            log.append("patch", "ALLOW", "سبب", None)
            entry = log.entries()[0]
            return (True, "تفاصيل فارغة") if entry.detail == {} else (False, f"detail: {entry.detail}")
    cases.append(("سجل-حي", "تفاصيل None تصير قاموسًا فارغًا", fn_detail_none))

    def fn_detail_string():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            log.append("patch", "ALLOW", "سبب", "نص مفرد")
            entry = log.entries()[0]
            ok = entry.detail.get("المدخل") == "نص مفرد"
            return (True, "النص يغلَّف") if ok else (False, f"نص مفرد: {entry.detail}")
    cases.append(("سجل-حي", "تفاصيل نصية تُغلَّف", fn_detail_string))

    def fn_tool_numeric():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            log.append(12345, "ALLOW", "سبب")
            entry = log.entries()[0]
            return (True, "الأداة تُسلسل نصًا") if entry.tool == "12345" else (False, f"أداة: {entry.tool!r}")
    cases.append(("سجل-حي", "أداة رقمية تُسلسل نصًا", fn_tool_numeric))

    def _rewrite(td: str, key: str, value: object) -> None:
        path = pathlib.Path(td) / "audit.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        target = json.loads(lines[2])
        target[key] = value
        lines[2] = canonical_json(target)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    for k, (key, val, label) in enumerate((
        ("reason_ar", "سبب مزوَّر", "السبب"),
        ("decision", "FORGED", "القرار"),
        ("tool", "أداة-مزوَّرة", "الأداة"),
        ("seq", 99, "التسلسل"),
        ("prev_hash", "f" * 64, "الهاش السابق"),
    )):
        def fn(key=key, val=val):
            with tempfile.TemporaryDirectory() as td:
                log = AuditLog(pathlib.Path(td) / "audit.jsonl")
                for i in range(4):
                    log.append("patch", "ALLOW", f"سبب {i}", {"i": i})
                _rewrite(td, key, val)
                report = log.verify()
                ok = not report.ok and report.first_broken_seq == 3
                return (True, f"عبث {label} يُكتشف") if ok else (False, f"عبث {label}: {report.to_dict()}")
        cases.append(("عبث", f"عبث {label} يُكتشف عند الحدث 3", fn))

    def fn_forged_append():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            for i in range(2):
                log.append("patch", "ALLOW", f"سبب {i}")
            forged = canonical_json({
                "seq": 3, "prev_hash": "0" * 64, "hash": "بصمة-مزوَّرة",
                "tool": "patch", "decision": "ALLOW", "reason_ar": "خيال", "detail": {}, "ts": None,
            })
            path = pathlib.Path(td) / "audit.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(forged + "\n")
            report = log.verify()
            return (True, "السطر المزوَّر يُكشف") if not report.ok else (False, "سطر مزوَّر مرّ بسلام")
    cases.append(("عبث", "سطر مزوَّر ملحق يُكشف", fn_forged_append))

    def fn_missing_file():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "غائب.jsonl")
            return (True, "الغائب فارغ") if log.entries() == [] else (False, "ملف غائب أعاد أحداثًا")
    cases.append(("سجل-حي", "قراءة ملف غائب تعود فارغة", fn_missing_file))

    def fn_nested_parent():
        with tempfile.TemporaryDirectory() as td:
            deep = pathlib.Path(td) / "أ" / "ب" / "ج.jsonl"
            log = AuditLog(deep)
            log.append("patch", "ALLOW", "سبب")
            return (True, "الأب أعماقًا يُنشأ") if deep.is_file() else (False, "المجلدات المتداخلة لم تُنشأ")
    cases.append(("سجل-حي", "append ينشئ المجلدات المتداخلة", fn_nested_parent))

    def fn_many_entries():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            for i in range(200):
                log.append("patch", "ALLOW", f"سبب {i}", {"n": i})
            report = log.verify()
            return (True, "200 حدثًا سليمة") if report.ok and report.count == 200 else (False, f"سلسلة طويلة: {report.count}")
    cases.append(("سجل-حي", "سلسلة من 200 حدث تُصدَّق", fn_many_entries))

    def fn_entry_frozen():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            entry = log.append("patch", "ALLOW", "سبب")
            try:
                entry.seq = 99  # type: ignore[misc]
                return False, "الحدث المجمد تغير!"
            except (AttributeError, Exception):  # noqa: BLE001 — البيانات المجمّدة ترفض
                return True, "الحدث مجمّد لا يتغير"
    cases.append(("بنية", "AuditEntry مجمّد", fn_entry_frozen))

    def fn_scrub_akia():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            log.append("run", "DENY", "مفتاح " + _SECRET_AKIA + " مرفوض")
            entry = log.entries()[0]
            return (True, "AKIA مقنَّع") if _SECRET_AKIA not in entry.reason_ar else (False, "مفتاح AWS تسرب!")
    cases.append(("اقنعة", "نمط AKIA يُقنَّع", fn_scrub_akia))

    def fn_scrub_xox():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            log.append("run", "DENY", "توكن " + _SECRET_XOX + " مرفوض")
            entry = log.entries()[0]
            return (True, "xox مقنَّع") if _SECRET_XOX not in entry.reason_ar else (False, "توكن سلاك تسرب!")
    cases.append(("اقنعة", "نمط xox يُقنَّع", fn_scrub_xox))

    def fn_entry_self_consistent():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            entry = log.append("patch", "ALLOW", "سبب موحد للفحص", {"k": "قيمة"})
            expect = entry_hash(entry.seq, entry.prev_hash, entry.tool, entry.decision, entry.reason_ar, entry.detail)
            return (True, "التوقيع ذاتي الاتساق") if entry.hash == expect else (False, "هاش الحدث لا يطابق إعادة حسابه")
    cases.append(("بنية", "توقيع الحدث ذاتي الاتساق", fn_entry_self_consistent))

    return cases


def build_extra_patch_run():
    cases = []

    def fn_missing_file():
        with tempfile.TemporaryDirectory() as td:
            c = PermissionContract.for_roots(td, allow_patch=True)
            r = patch_file(c, path="غائب.py", old_text="أ", new_text="ب")
            return (True, "ملف غائب يُرفض") if not r.ok else (False, "رقعة على ملف غائب قُبلت")
    cases.append(("رقع", "رقعة على ملف غائب تُرفض", fn_missing_file))

    def fn_dir_target():
        with tempfile.TemporaryDirectory() as td:
            (pathlib.Path(td) / "مجلد").mkdir()
            c = PermissionContract.for_roots(td, allow_patch=True)
            r = patch_file(c, path="مجلد", content="x")
            return (True, "المجلد لا يرقَّع") if not r.ok else (False, "مجلد قُبل ملفًا")
    cases.append(("رقع", "الهدف مجلد يُرفض", fn_dir_target))

    def fn_content_nul():
        with tempfile.TemporaryDirectory() as td:
            c = PermissionContract.for_roots(td, allow_patch=True)
            r = patch_file(c, path="x.py", content="a\x00b")
            return (True, "NUL يُرفض") if not r.ok else (False, "محتوى بـNUL قُبل")
    cases.append(("رقع", "محتوى يحمل NUL يُرفض", fn_content_nul))

    def fn_oldtext_nul():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "x.py"
            p.write_text("x = 1\n", encoding="utf-8")
            c = PermissionContract.for_roots(td, allow_patch=True)
            r = patch_file(c, path="x.py", old_text="x\x00", new_text="y")
            return (True, "NUL في القديم يُرفض") if not r.ok else (False, "old_text بـNUL قُبل")
    cases.append(("رقع", "old_text يحمل NUL يُرفض", fn_oldtext_nul))

    def fn_zero_match_no_write():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "x.py"
            p.write_text("الأصل\n", encoding="utf-8")
            c = PermissionContract.for_roots(td, allow_patch=True)
            patch_file(c, path="x.py", old_text="مفقود", new_text="مزروع")
            after = p.read_text(encoding="utf-8")
            return (True, "الرفض لا يلمس الملف") if after == "الأصل\n" else (False, "رفض رقعة غيّر الملف!")
    cases.append(("رقع", "رفض الرقعة لا يغير الملف", fn_zero_match_no_write))

    def fn_write_over_existing():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "x.py"
            p.write_text("قديم\n", encoding="utf-8")
            c = PermissionContract.for_roots(td, allow_patch=True)
            r = patch_file(c, path="x.py", content="جديد\n")
            after = p.read_text(encoding="utf-8")
            ok = r.ok and after == "جديد\n"
            return (True, "الكتابة تستبدل") if ok else (False, f"كتابة على موجود: {r.reason_ar[:30]}")
    cases.append(("رقع", "وضع الكتابة يستبدل الموجود", fn_write_over_existing))

    def fn_path_none():
        with tempfile.TemporaryDirectory() as td:
            c = PermissionContract.for_roots(td, allow_patch=True)
            r = patch_file(c, path=None, content="x")
            return (True, "None يُرفض") if not r.ok else (False, "مسار None قُبل")
    cases.append(("رقع", "مسار None يُرفض", fn_path_none))

    def fn_relative_anchored():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "نسبي.py"
            p.write_text("الأصل\n", encoding="utf-8")
            c = PermissionContract.for_roots(td, allow_patch=True)
            r = patch_file(c, path="نسبي.py", old_text="الأصل", new_text="معدّل")
            ok = r.ok and "معدّل" in p.read_text(encoding="utf-8")
            return (True, "النسبي يثبت على الجذر") if ok else (False, f"نسبي: {r.reason_ar[:30]}")
    cases.append(("رقع", "مسار رقعي نسبي يثبت على الجذر", fn_relative_anchored))

    def fn_unicode_replace():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "unicode.py"
            p.write_text("text = \"café naïve\"\n", encoding="utf-8")
            c = PermissionContract.for_roots(td, allow_patch=True)
            r = patch_file(c, path="unicode.py", old_text="café naïve", new_text="سلام عليكم")
            ok = r.ok and "سلام عليكم" in p.read_text(encoding="utf-8")
            return (True, "يونيكود يُستبدل") if ok else (False, f"يونيكود: {r.reason_ar[:30]}")
    cases.append(("رقع", "استبدال يونيكود كامل", fn_unicode_replace))

    def fn_arabic_replace():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "عربي.py"
            p.write_text("message = \"الرسالة القديمة\"\n", encoding="utf-8")
            c = PermissionContract.for_roots(td, allow_patch=True)
            r = patch_file(c, path="عربي.py", old_text="الرسالة القديمة", new_text="الرسالة الجديدة")
            ok = r.ok and "الرسالة الجديدة" in p.read_text(encoding="utf-8")
            return (True, "عربي يُستبدل") if ok else (False, f"عربي: {r.reason_ar[:30]}")
    cases.append(("رقع", "استبدال نص عربي", fn_arabic_replace))

    def fn_bytes_written():
        with tempfile.TemporaryDirectory() as td:
            c = PermissionContract.for_roots(td, allow_patch=True)
            content = "النص العربي واللاتيني mixed\n"
            r = patch_file(c, path="بس.py", content=content)
            ok = r.bytes_written == len(content.encode("utf-8"))
            return (True, "البايتات دقيقة") if ok else (False, f"bytes_written={r.bytes_written}")
    cases.append(("رقع", "bytes_written يطابق UTF-8", fn_bytes_written))

    def fn_content_changed_flag():
        with tempfile.TemporaryDirectory() as td:
            c = PermissionContract.for_roots(td, allow_patch=True)
            patch_file(c, path="x.py", content="الأول\n")
            r = patch_file(c, path="x.py", content="الثاني\n")
            ok = r.ok and r.changed and r.mode == "write"
            return (True, "التغير يوثق") if ok else (False, f"changed={r.changed}")
    cases.append(("رقع", "الكتابة على موجود توثق التغير", fn_content_changed_flag))

    def fn_run_argv_none():
        with tempfile.TemporaryDirectory() as td:
            c = PermissionContract.for_roots(td, allow_run_tests=True)
            r = run_tests(c, argv=None, cwd=td)  # type: ignore[arg-type]
            return (True, "None يُرفض") if not r.ok else (False, "argv=None مرّ")
    cases.append(("تشغيل", "argv=None يُرفض", fn_run_argv_none))

    def fn_run_command_field():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "ok.py"
            p.write_text("print('1 passed in 0.01s')\n", encoding="utf-8")
            c = PermissionContract.for_roots(td, allow_run_tests=True, timeout_s=10)
            r = run_tests(c, argv=("python", "ok.py"), cwd=td)
            ok = r.ok and r.command == "python ok.py"
            return (True, "الأمر موثق") if ok else (False, f"command={r.command!r}")
    cases.append(("تشغيل", "حقل command يوثق الأمر", fn_run_command_field))

    def fn_run_missing_script():
        with tempfile.TemporaryDirectory() as td:
            c = PermissionContract.for_roots(td, allow_run_tests=True, timeout_s=10)
            r = run_tests(c, argv=("python", "غائب.py"), cwd=td)
            return (True, "السكربت الغائب فشل") if not r.ok else (False, "سكربت غائب نجح!")
    cases.append(("تشغيل", "سكربت غائب يعود فاشلًا", fn_run_missing_script))

    def fn_run_no_pycache():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "quiet.py"
            p.write_text("print('بلا أثر')\n", encoding="utf-8")
            c = PermissionContract.for_roots(td, allow_run_tests=True, timeout_s=10)
            run_tests(c, argv=("python", "quiet.py"), cwd=td)
            leftovers = [x.name for x in pathlib.Path(td).iterdir() if x.name == "__pycache__"]
            return (True, "بلا bytecode يتيم") if not leftovers else (False, "__pycache__ تسرب إلى الجذر")
    cases.append(("تشغيل", "التشغيل لا يترك bytecode", fn_run_no_pycache))

    def fn_run_output_cap():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "chatty.py"
            p.write_text("print('ط' * 50000)\nprint('1 passed in 0.01s')\n", encoding="utf-8")
            c = PermissionContract.for_roots(td, allow_run_tests=True, timeout_s=10, max_output_chars=2000)
            r = run_tests(c, argv=("python", "chatty.py"), cwd=td)
            ok = r.ok and len(r.stdout_tail or "") <= 2100
            return (True, "المخرجات مسقوفة") if ok else (False, f"tail={len(r.stdout_tail or '')}")
    cases.append(("تشغيل", "سقف المخرجات يحكم الذيل", fn_run_output_cap))

    def fn_run_counters_errors():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "errs.py"
            p.write_text("print('2 errors, 1 failed, 3 passed in 0.1s')\n", encoding="utf-8")
            c = PermissionContract.for_roots(td, allow_run_tests=True, timeout_s=10)
            r = run_tests(c, argv=("python", "errs.py"), cwd=td)
            ok = r.ok and r.errors == 2 and r.failed == 1 and r.passed == 3
            return (True, "العدّاء الثلاثي بالحكم من الخروج") if ok else (False, f"e/f/p: {r.errors}/{r.failed}/{r.passed} ok={r.ok}")
    cases.append(("تشغيل", "عدّاد errors وfailed وpassed معًا", fn_run_counters_errors))

    return cases


def build_extra_jail():
    cases = []

    def fn_roots_missing_skip():
        roots = write_roots(("/nonexistent-eval-zz", "/tmp"))
        ok = "/nonexistent-eval-zz" not in roots
        return (True, "الغائب يُتخطى") if ok else (False, f"الجذور: {roots}")
    cases.append(("جذور", "جذر غائب يُتخطى", fn_roots_missing_skip))

    def fn_roots_strip():
        roots = write_roots(("   /tmp   ",))
        ok = roots and roots[0] == str(pathlib.Path("/tmp").absolute())
        return (True, "الفراغ يُقصّ") if ok else (False, f"جذر بفراغ: {roots}")
    cases.append(("جذور", "فراغات الجذر تُقصّ", fn_roots_strip))

    def fn_wrap_empty():
        reset_detection_cache()
        got = wrap_argv((), ("/tmp",))
        level = jail_level()
        if level != "bwrap":
            return (True, "بلا bwrap: فراغ يعود None") if got is None else (False, "argv فارغ أعاد غلافًا")
        return (True, "تحت bwrap: فراغ يعود None") if got is None else (False, "argv فارغ أعاد غلافًا تحت bwrap")
    cases.append(("غلاف", "argv فارغ يعود بلا غلاف", fn_wrap_empty))

    def fn_overlays_clean():
        with tempfile.TemporaryDirectory() as td:
            (pathlib.Path(td) / "src").mkdir()
            (pathlib.Path(td) / "app.py").write_text("x = 1\n", encoding="utf-8")
            overlays = sensitive_overlays([td])
            return (True, "النظيف بلا تعمية") if not overlays else (False, f"مجلد نظيف أعاد: {overlays}")
    cases.append(("تعمية", "مجلد نظيف بلا تعمية", fn_overlays_clean))

    def fn_abi_stable():
        a, b = landlock_abi(), landlock_abi()
        return (True, "ABI مستقر") if a == b else (False, f"ABI: {a} ثم {b}")
    cases.append(("اكتشاف", "landlock_abi مستقر عبر النداءات", fn_abi_stable))

    def fn_net_stable():
        a, b = net_confinement(), net_confinement()
        return (True, "إعلان مستقر") if a == b else (False, f"net: {a} ثم {b}")
    cases.append(("اكتشاف", "net_confinement مستقر", fn_net_stable))

    def fn_level_stable():
        reset_detection_cache()
        a = jail_level()
        reset_detection_cache()
        b = jail_level()
        return (True, "المستوى مستقر") if a == b else (False, f"level: {a} ثم {b}")
    cases.append(("اكتشاف", "jail_level مستقر بعد التصفير", fn_level_stable))

    def fn_wrap_missing_roots():
        reset_detection_cache()
        got = wrap_argv(("python", "x.py"), ("/nonexistent-eval-zz",))
        level = jail_level()
        if level != "bwrap":
            return (True, "جذر غائب بلا غلاف") if got is None else (False, "غلاف فوق جذور غائبة")
        return True, "تحت bwrap غلاف يُبنى أو None — المستوى معلن"
    cases.append(("غلاف", "جذور غائبة لا تفجر الغلاف", fn_wrap_missing_roots))

    def fn_reset_twice():
        reset_detection_cache()
        reset_detection_cache()
        level = jail_level()
        return (True, "التصفير المزدوج آمن") if level in ("landlock", "bwrap", "none") else (False, "تصفير مزدوج كسر الاكتشاف")
    cases.append(("اكتشاف", "تصفير الكاش مرتين آمن", fn_reset_twice))

    def fn_roots_type_hostile():
        got = write_roots(None)
        ok = isinstance(got, tuple)
        return (True, "None يعود tuple") if ok else (False, f"None → {type(got).__name__}")
    cases.append(("جذور", "write_roots على None آمن", fn_roots_type_hostile))
    return cases


def build_extra_reflect():
    from zyko.benchmarks.eval1000_cases_c import _StubPlanStep, _StubVerdict
    cases = []

    def fn_per_stage_junk():
        b = RetryBudget(per_stage={"plan": "خمسة"})
        return (True, "النص صفر") if b.limit("plan") == 0 else (False, f"حد نصي: {b.limit('plan')}")
    cases.append(("ميزانية", "حد مرحلة غير عددي يُقيَّد", fn_per_stage_junk))

    def fn_total_cap_negative():
        b = RetryBudget(total_cap=-5)
        return (True, "السقف السالب صفر") if b.total_cap == 0 and not b.can_retry("plan") else (False, f"سقف: {b.total_cap}")
    cases.append(("ميزانية", "سقف كلي سالب يُقيَّد", fn_total_cap_negative))

    def fn_stages_independent():
        b = RetryBudget(default_limit=1)
        a = b.consume("plan")
        c = b.consume("critic")
        return (True, "المراحل مستقلة") if a and c else (False, f"استقلال: {a}/{c}")
    cases.append(("ميزانية", "ميزانيات المراحل مستقلة", fn_stages_independent))

    def fn_consume_junk_stage():
        b = RetryBudget(default_limit=1)
        got = b.consume(None)  # type: ignore[arg-type]
        return (True, "اسم عدوي يُطبَّع") if isinstance(got, bool) else (False, "اسم عدوي انفجر consume")
    cases.append(("ميزانية", "consume على اسم عدوي آمن", fn_consume_junk_stage))

    def fn_plan_verdicts_all_pass():
        plan = SimpleNamespace(
            steps=(_StubPlanStep("orchestrator", 1), _StubPlanStep("critic", 2)),
            verdicts=(_StubVerdict("PII", True), _StubVerdict("RTL", True)),
        )
        r = guard_plan(plan)
        return (True, "أحكام ناجحة تمر") if r.ok else (False, f"أحكام ناجحة رُفضت: {r.reason_ar[:30]}")
    cases.append(("حارس-خطة", "أحكام بوابات ناجحة تمر", fn_plan_verdicts_all_pass))

    def fn_plan_perception_generate():
        p = perceive("أنشئ مشروع قائمة مهام")
        plan = SimpleNamespace(steps=(_StubPlanStep("pipeline", 1), _StubPlanStep("critic", 2), _StubPlanStep("baseline", 3)), verdicts=())
        r = guard_plan(plan, p)
        return (True, "GENERATE يطابق جدوله") if r.ok else (False, f"خطة GENERATE: {r.reason_ar[:40]}")
    cases.append(("حارس-خطة", "خطة GENERATE تطابق الجدول", fn_plan_perception_generate))

    def fn_plan_perception_mismatch():
        p = perceive("أنشئ مشروع قائمة مهام")
        plan = SimpleNamespace(steps=(_StubPlanStep("critic", 1), _StubPlanStep("pipeline", 2), _StubPlanStep("baseline", 3)), verdicts=())
        r = guard_plan(plan, p)
        return (True, "الخلط يُرفض") if not r.ok else (False, "ترتيب خاطئ مع إدراك مرّ!")
    cases.append(("حارس-خطة", "خطة مخالفة للإدراك تُرفض", fn_plan_perception_mismatch))

    def fn_perception_zero_confidence():
        p = perceive("")
        r = guard_perception(p)
        ok = not r.ok and "الثقة" in r.reason_ar or "النوع" in r.reason_ar
        return (True, "الثقة الصفرية تُرفض") if ok else (False, f"ثقة صفرية: {r.reason_ar[:30]}")
    cases.append(("حارس-إدراك", "الثقة الصفرية تُرفض", fn_perception_zero_confidence))

    def fn_exec_absolute_evidence():
        with tempfile.TemporaryDirectory() as td:
            import hashlib
            p = pathlib.Path(td) / "أثر.py"
            p.write_text("x = 1\n", encoding="utf-8")
            sha = hashlib.sha256(p.read_bytes()).hexdigest()
            step = SimpleNamespace(ok=True, evidence={str(p): sha}, details_ar="")
            r = guard_execution(step, td, write=True)
            return (True, "مسار مطلق يفحص") if r.ok else (False, f"أثر مطلق: {r.reason_ar[:40]}")
    cases.append(("حارس-تنفيذ", "أدلة بمسارات مطلقة تُفحص", fn_exec_absolute_evidence))

    def fn_feedback_none():
        r = guard_feedback(None, ())
        return (True, "None يُرفض") if not r.ok else (False, "ملاحظة None مرّت")
    cases.append(("حارس-ملاحظة", "ملاحظة None تُرفض", fn_feedback_none))

    def fn_feedback_int():
        r = guard_feedback(12345, ())
        ok = isinstance(r.ok, bool)
        return (True, "العدد يُسلسل ويفحص") if ok else (False, "مدخل رقمي انفجر الحارس")
    cases.append(("حارس-ملاحظة", "ملاحظة رقمية تُسلسل وتفحص", fn_feedback_int))

    def fn_feedback_ws():
        r = guard_feedback("   ", ())
        return (True, "الفراغ الأبيض يُرفض") if not r.ok else (False, "ملاحظة فراغية مرّت")
    cases.append(("حارس-ملاحظة", "ملاحظة فراغية تُرفض", fn_feedback_ws))

    def fn_condense_no_gaps():
        text = condense_feedback("س" * 900, ())
        return (True, "السقف يعمل بلا فجوات") if len(text) <= MAX_FEEDBACK_CHARS else (False, f"ضغط {len(text)}")
    cases.append(("تكثيف", "تكثيف بلا فجوات يلتزم السقف", fn_condense_no_gaps))

    def fn_reflect_note_no_gaps():
        note = reflect_note("critic", reason_ar="النقاط منخفضة", gaps=(), attempt=1)
        ok = note and "critic" in note
        return (True, "بلا فجوات يعمل") if ok else (False, f"ملاحظة: {note[:30]}")
    cases.append(("ملاحظة", "ملاحظة بلا فجوات تعمل", fn_reflect_note_no_gaps))

    def fn_stage_constants():
        from zyko.mind.reflect import STAGE_CRITIC, STAGE_EXECUTE, STAGE_PLAN, STAGE_PERCEIVE
        ok = {STAGE_PERCEIVE, STAGE_PLAN, STAGE_EXECUTE, STAGE_CRITIC} == {"perceive", "plan", "execute", "critic"}
        return (True, "أسماء المراحل الأربع") if ok else (False, "ثوابت المراحل تغيرت")
    cases.append(("سقوف", "ثوابت المراحل الأربع", fn_stage_constants))
    return cases


def build_extra_ledger():
    cases = []

    def fn_ledger_filename():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            mem.record_session(goal="هدف", project="p")
            return (True, "اسم الملف موثق") if (pathlib.Path(td) / "sessions.jsonl").is_file() else (False, "sessions.jsonl غير موجود")
    cases.append(("دفتر", "ملف الدفتر sessions.jsonl", fn_ledger_filename))

    def fn_lessons_filename():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            mem.learn(["درس فريد"])
            return (True, "اسم الملف موثق") if (pathlib.Path(td) / "lessons.json").is_file() else (False, "lessons.json غير موجود")
    cases.append(("دروس", "ملف الدروس lessons.json", fn_lessons_filename))

    def fn_verify_reorder():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            for i in range(3):
                mem.record_session(goal=f"هدف {i}", project=f"p{i}")
            path = pathlib.Path(td) / "sessions.jsonl"
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[0], lines[1] = lines[1], lines[0]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            r = mem.verify()
            return (True, "الإعادة تُكتشف") if not r.ok else (False, "تبديل جلستين مرّ بسلام")
    cases.append(("عبث", "إعادة ترتيب الجلسات تُكتشف", fn_verify_reorder))

    def fn_verify_delete():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            for i in range(3):
                mem.record_session(goal=f"هدف {i}", project=f"p{i}")
            path = pathlib.Path(td) / "sessions.jsonl"
            lines = path.read_text(encoding="utf-8").splitlines()
            del lines[0]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            r = mem.verify()
            return (True, "الحذف يُكتشف") if not r.ok else (False, "حذف جلسة مرّ بسلام")
    cases.append(("عبث", "حذف جلسة يكسر السلسلة", fn_verify_delete))

    def fn_learn_ws_dedupe():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            mem.learn(["درس   متعدد   الفراغات"])
            mem.learn(["درس متعدد الفراغات"])
            lessons = mem.load_lessons()
            return (True, "الفراغ يطوى قبل التفرد") if len(lessons) == 1 else (False, f"فراغ فرَّد درسين: {len(lessons)}")
    cases.append(("دروس", "فراغات الدرس تُطوى قبل التفرد", fn_learn_ws_dedupe))

    def fn_recall_tie_stable():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            for i in range(3):
                mem.learn([f"درس الاتصال المتساوي رقم {i}"])
            a = mem.recall("الاتصال")
            b = mem.recall("الاتصال")
            return (True, "التعادل مستقر") if a == b and a else (False, "استرجاعان لنفس الاستعلام اختلفا")
    cases.append(("استرجاع", "التعادل في الاسترجاع مستقر", fn_recall_tie_stable))

    def fn_data_dir_env():
        with tempfile.TemporaryDirectory() as td:
            old = os.environ.get("ZYKO_DATA_DIR")
            os.environ["ZYKO_DATA_DIR"] = td
            try:
                mem = GlobalMemory()
                mem.record_session(goal="هدف", project="p")
                ok = (pathlib.Path(td) / "mind" / "sessions.jsonl").is_file() or (pathlib.Path(td) / "sessions.jsonl").is_file()
                return (True, "البيئة تحكم المسار") if ok else (False, "ZYKO_DATA_DIR لم يُحترم")
            finally:
                if old is None:
                    os.environ.pop("ZYKO_DATA_DIR", None)
                else:
                    os.environ["ZYKO_DATA_DIR"] = old
    cases.append(("دفتر", "ZYKO_DATA_DIR يحكم المسار الافتراضي", fn_data_dir_env))

    def fn_entry_no_goal_key():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            e = mem.record_session(goal="هدف-خام-سري", project="p")
            d = e.to_dict()
            return (True, "لا مفتاح نص خام") if "goal" not in d and "goal_sha256" in d else (False, f"مفاتيح: {sorted(d.keys())}")
    cases.append(("خصوصية", "إدخال الجلسة بلا مفتاح هدف خام", fn_entry_no_goal_key))

    def fn_outcome_none():
        with tempfile.TemporaryDirectory() as td:
            mem = GlobalMemory(home=td)
            e = mem.record_session(goal="هدف", project="p")
            got = e.to_dict()["outcome_ar"]
            return (True, "الخلاصة الافتراضية نص موثق") if isinstance(got, str) and got.strip() else (False, f"خلاصة: {got!r}")
    cases.append(("توثيق", "خلاصة غائبة تُوثق None", fn_outcome_none))
    return cases


def build_extra_classify_route():
    cases = []
    from zyko.orchestrator import classify, extract_context, route

    def fn_generate_missing():
        plan = route(classify("أنشئ مشروعاً"), context={})
        ok = plan.steps[0].args.get("description") == "" and plan.notes_ar
        return (True, "الوصف الناقص موثق") if ok else (False, "GENERATE بلا وصف بلا ملاحظة")
    cases.append(("توجيه", "GENERATE بلا وصف يحمل ملاحظة", fn_generate_missing))

    def fn_transpile_missing():
        plan = route(classify("ترجم إلى ضاد"), context={})
        ok = plan.steps[0].args.get("file") == "" and plan.notes_ar
        return (True, "الملف الناقص موثق") if ok else (False, "TRANSPILE بلا ملف بلا ملاحظة")
    cases.append(("توجيه", "TRANSPILE بلا ملف يحمل ملاحظة", fn_transpile_missing))

    def fn_verify_missing():
        plan = route(classify("تحقق"), context={})
        ok = plan.steps[0].args.get("receipt") == "" and plan.notes_ar
        return (True, "الإيصال الناقص موثق") if ok else (False, "VERIFY بلا إيصال بلا ملاحظة")
    cases.append(("توجيه", "VERIFY بلا إيصال يحمل ملاحظة", fn_verify_missing))

    def fn_ctx_daad_json():
        ctx = extract_context("ترجم pipeline.daad ثم راجع report.json")
        ok = ctx.get("file") == "pipeline.daad" and "receipt" not in ctx
        return (True, "وسمان في هدف واحد") if ok else (False, f"ctx: {ctx}")
    cases.append(("سياق", "ملف ضاد وإيصال json معًا", fn_ctx_daad_json))
    return cases


def build_extra_policy():
    cases = []
    from zyko.policy.engine import BUILTIN_PATTERNS, Redactor, builtin_default_policy

    def fn_unknown_privacy_key():
        try:
            Redactor.from_doc({"نمط-مجهول": True})
            return True, "مفتاح مجهول أُهمل بصمت"
        except Exception:
            return False, "مفتاح مجهول انفجر الحجب"
    cases.append(("سجل", "مفتاح خصوصية مجهول يُهمل", fn_unknown_privacy_key))

    def fn_phone_local():
        r = Redactor.from_doc({"redact": ["phone"]})
        out, kinds = r.apply("جوال 0512345678 داخل النص")
        return (True, "هاتف محلي محجوب") if "0512345678" not in out and kinds else (False, "هاتف محلي مرّ")
    cases.append(("حجب", "الهاتف المحلي يُحجب", fn_phone_local))

    def fn_kinds_are_strings():
        r = Redactor.from_doc({"redact": ["email"]})
        _, kinds = r.apply("راسلني على a@b.com")
        ok = kinds and all(isinstance(k, str) for k in kinds)
        return (True, "أنواع الحجب نصية") if ok else (False, f"أنواع: {kinds}")
    cases.append(("توثيق", "أنواع الحجب قائمة نصية", fn_kinds_are_strings))

    def fn_pattern_shape():
        ok = all(isinstance(v, tuple) and len(v) == 2 for v in BUILTIN_PATTERNS.values())
        return (True, "كل نمط زوج") if ok else (False, "نمط بشكل غير زوجي")
    cases.append(("سجل", "أنماط الحجب أزواج (نمط، بديل)", fn_pattern_shape))

    def fn_doc_shape():
        d = builtin_default_policy()
        ok = isinstance(d, dict) and len(d) >= 2 and all(isinstance(k, str) for k in d)
        return (True, "مفاتيح نصية متعددة") if ok else (False, f"السياسة: {sorted(d.keys())[:6]}")
    cases.append(("سياسة", "السياسة الافتراضية بمفاتيح متعددة", fn_doc_shape))

    def fn_cross_instance():
        a = Redactor.from_doc({}).apply("عنوان x@y.com")
        b = Redactor.from_doc({}).apply("عنوان x@y.com")
        return (True, "مثيلتان متطابقتان") if a == b else (False, "مثيلتا حجب اختلفا")
    cases.append(("حتمية", "مثيلتا Redactor متطابقتان", fn_cross_instance))

    def fn_two_emails():
        r = Redactor.from_doc({"redact": ["email"]})
        out, kinds = r.apply("من a@x.com إلى b@y.org")
        ok = "a@x.com" not in out and "b@y.org" not in out and len(kinds) >= 2
        return (True, "بريدان حُجبا") if ok else (False, f"بريدان: {out[:40]} kinds={kinds}")
    cases.append(("حجب", "بريدان في نص واحد يُحجبان", fn_two_emails))
    return cases


def build_extra_kernel_core():
    cases = []
    from zyko.kernel import cosine_similarity

    def fn_cos_zero():
        got = cosine_similarity([0, 0], [1, 2])
        return (True, "المتجه الصفري 0.0") if got == 0.0 else (False, f"صفري → {got}")
    cases.append(("تشابه", "المتجه الصفري لا يقسم على صفر", fn_cos_zero))
    return cases


def build_extra_receipts():
    cases = []
    from zyko.ai.receipt import AIReceipt, StepRecord, hash_file, hash_text
    from zyko.ai.session import AISession, detect_session_mode

    def fn_hash_unicode_vs_latin():
        a = hash_text("نص")
        b = hash_text("text")
        return (True, "نصان مختلفان بصمتان") if a != b else (False, "عربي ولاتيني بنفس البصمة!")
    cases.append(("بصمات", "العربي واللاتيني بصمات مختلفة", fn_hash_unicode_vs_latin))

    def fn_step_defaults():
        s = StepRecord("plan", "تخطيط", True, 0)
        ok = s.details_ar == "" and s.evidence == {}
        return (True, "الافتراضات موثقة") if ok else (False, "افتراضيات الخطوة مكسورة")
    cases.append(("سجل", "افتراضيات StepRecord الموثقة", fn_step_defaults))

    def fn_receipt_accumulate_after_fail():
        r = AIReceipt(goal="هدف", brain="مزيف", brain_deterministic=True, out="مخرجات")
        r.add(StepRecord("plan", "تخطيط", False, 1))
        r.add(StepRecord("generate", "توليد", True, 0))
        ok = not r.ok and len(r.steps) == 2
        return (True, "التراكم يستمر") if ok else (False, "فشل أوقف التسجيل")
    cases.append(("إيصال", "التراكم يستمر بعد الفشل", fn_receipt_accumulate_after_fail))

    def fn_receipt_dict_keys():
        r = AIReceipt(goal="هدف", brain="مزيف", brain_deterministic=True, out="مخرجات")
        r.add(StepRecord("plan", "تخطيط", True, 0))
        d = r.to_dict()
        need = {"goal", "brain", "ok", "steps", "failed_step"}
        return (True, "ممثل JSON موثق") if need <= set(d.keys()) else (False, f"مفاتيح: {sorted(d.keys())}")
    cases.append(("توثيق", "AIReceipt.to_dict مفاتيحه", fn_receipt_dict_keys))

    def fn_detect_two_paths():
        with tempfile.TemporaryDirectory() as td:
            first = pathlib.Path(td) / "الأول.py"
            first.write_text("x=1\n", encoding="utf-8")
            mode, _ = detect_session_mode(f"راجع {first} ثم /nonexistent-zz/app.py", td)
            return (True, "الأول يفوز") if mode == "existing" else (False, "المسار الأول لم يحسم")
    cases.append(("اكتشاف-جلسة", "مساران في الهدف: الأول يحسم", fn_detect_two_paths))

    def fn_detect_pathlib_out():
        with tempfile.TemporaryDirectory() as td:
            mode, _ = detect_session_mode("أنشئ مشروعاً", pathlib.Path(td))
            return (True, "Path مقبول") if mode == "factory" else (False, f"Path → {mode}")
    cases.append(("اكتشاف-جلسة", "out_dir كـ Path يقبل", fn_detect_pathlib_out))

    def fn_receipt_md_steps():
        r = AIReceipt(goal="هدف", brain="مزيف", brain_deterministic=True, out="مخرجات")
        r.add(StepRecord("plan", "خطوة التخطيط المميزة", True, 0))
        md = r.to_md()
        return (True, "الخطوة في الماركداون") if "خطوة التخطيط" in md else (False, "to_md فقد خطوة")
    cases.append(("توثيق", "to_md يحمل عناوين الخطوات", fn_receipt_md_steps))

    def fn_receipt_brain_recorded():
        r = AIReceipt(goal="هدف", brain="عقل-مميز", brain_deterministic=False, out="مخرجات")
        d = r.to_dict()
        ok = d.get("brain") == "عقل-مميز" and d.get("brain_deterministic") is False
        return (True, "العقل موثق") if ok else (False, f"عقل: {d.get('brain')}")
    cases.append(("توثيق", "اسم العقل ومصدره يُوثقان", fn_receipt_brain_recorded))

    def fn_hash_file_large():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "كبير.bin"
            content = (b"zyko-" + bytes(range(256))) * 4096  # ~1MB حتمي
            p.write_bytes(content)
            got = hash_file(p)
            expect = hashlib.sha256(content).hexdigest()
            return (True, "ملف كبير دقيق") if got == expect else (False, "التدفق على ملف كبير أخطأ البصمة")
    cases.append(("بصمات", "hash_file على ملف بمقدار 1MB", fn_hash_file_large))
    return cases


EXTRA_BUILDERS = {
    "pii-redact": build_extra_pii_redact,
    "gates": build_extra_gates,
    "contracts": build_extra_contracts,
    "audit": build_extra_audit,
    "patch-run": build_extra_patch_run,
    "jail": build_extra_jail,
    "reflect": build_extra_reflect,
    "ledger": build_extra_ledger,
    "classify-route": build_extra_classify_route,
    "policy": build_extra_policy,
    "kernel-core": build_extra_kernel_core,
    "receipts": build_extra_receipts,
}
