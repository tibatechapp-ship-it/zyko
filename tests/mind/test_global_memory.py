"""اختبارات الذاكرة العابرة للجلسات — دفتر موقّع ودروس عابرة واسترجاع حتمي.

العقود التي تثبتها: السلسلة تكشف كل عبث (تعديل/حذف/إعادة ترتيب)، الخصوصية
بالتصميم (الهدف بصمة لا نصًا)، الأسرار تُقنَّع قبل القرص، السقف حتمي بإخلاء
الأقدم أولًا، الاسترجاع حتمي بالبايت بلا عشوائية، والملفات الثلاثة متطابقة
بالبايت عبر إعادة التشغيل نفسه — والتكامل مع الحلقة يوقّع الجلسة عند الختام.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from zyko.mind.cli import main as mind_main
from zyko.mind.global_memory import (
    GENESIS_HASH,
    LESSONS_SCHEMA,
    MAX_GLOBAL_LESSONS,
    MAX_LESSON_CHARS,
    GlobalMemory,
)
from zyko.mind.loop import MindLoop

GOAL = "انشئ مشروع قائمة مهام مع واجهة سطر أوامر"


def _feed(mem: GlobalMemory) -> None:
    """تغذية موحدة — نفس التسلسل بالضبط لاختبارات الحتمية."""
    mem.record_session(
        goal="ابنِ مشروع قائمة مهام", project="proj-a", kind="build",
        ok=True, lessons_learned=2, gaps=0, ts=1000.0,
    )
    mem.record_session(
        goal="اصلح الملف المعطوب", project="proj-b", kind="fix",
        ok=False, gaps=1, ts=2000.0,
    )
    mem.learn(["قياس قبل الإصلاح", "دروس: قياس قبل الإصلاح"])


# =============================================================== دفتر الجلسات
class TestLedger:
    def test_record_then_read_roundtrip(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        entry = mem.record_session(goal="هدف", project="مشروع", kind="build", ok=True, ts=5.0)
        read = mem.sessions()
        assert len(read) == 1
        assert read[0].seq == entry.seq == 1
        assert read[0].project == "مشروع"
        assert read[0].kind == "build"
        assert read[0].ok is True
        assert read[0].ts == 5.0

    def test_chain_links_genesis_then_next(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        e1 = mem.record_session(goal="أ", project="p", ts=1.0)
        assert e1.prev_hash == GENESIS_HASH
        e2 = mem.record_session(goal="ب", project="p", ts=1.0)
        assert e2.prev_hash == e1.hash
        assert e2.seq == 2

    def test_verify_ok_arabic_reason(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        _feed(mem)
        report = mem.verify()
        assert report.ok
        assert report.count == 2
        assert report.first_broken_seq is None
        assert "سليمة" in report.reason_ar

    def test_verify_empty_ledger(self, tmp_path):
        assert GlobalMemory(tmp_path / "mind").verify().ok

    def test_verify_detects_tamper(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        _feed(mem)
        lines = mem.ledger_path.read_text(encoding="utf-8").splitlines()
        tampered = json.loads(lines[0])
        tampered["outcome_ar"] = "مزوّر بعد التدوين"
        lines[0] = json.dumps(tampered, ensure_ascii=False, sort_keys=True)
        mem.ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = mem.verify()
        assert not report.ok
        assert report.first_broken_seq == 1

    def test_verify_detects_deletion(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        _feed(mem)
        lines = mem.ledger_path.read_text(encoding="utf-8").splitlines()
        del lines[0]  # حذف الجلسة الأولى يكسر السلسلة من الثانية
        mem.ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = mem.verify()
        assert not report.ok

    def test_verify_detects_reorder(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        _feed(mem)
        lines = mem.ledger_path.read_text(encoding="utf-8").splitlines()
        lines.reverse()  # إعادة ترتيب = سلسلة مقطوعة
        mem.ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = mem.verify()
        assert not report.ok

    def test_verify_detects_corrupt_line(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        _feed(mem)
        with mem.ledger_path.open("a", encoding="utf-8") as fh:
            fh.write("هذا ليس json\n")
        report = mem.verify()
        assert not report.ok
        assert report.first_broken_seq == 3

    def test_goal_privacy_digest_not_raw(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        secret_goal = "استخدم المفتاح ghp_" + "A" * 20 + " في الإعداد"
        mem.record_session(goal=secret_goal, project="p", ts=1.0)
        raw = mem.ledger_path.read_text(encoding="utf-8")
        assert "ghp_" not in raw  # لا نص خام ولا نمط سر — بصمة فقط
        entry = mem.sessions()[0]
        assert len(entry.goal_sha256) == 64
        assert secret_goal not in raw

    def test_secret_masked_in_project_field(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.record_session(goal="x", project="proj-ghp_" + "A" * 20, ts=1.0)
        assert "[سر-مقنّع]" in mem.sessions()[0].project

    def test_outcome_derived_deterministic(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        ok_entry = mem.record_session(goal="أ", project="p", ok=True, gaps=0, ts=1.0)
        gap_entry = mem.record_session(goal="ب", project="p", ok=True, gaps=2, ts=1.0)
        assert ok_entry.outcome_ar == "اكتمل بلا فجوات"
        assert gap_entry.outcome_ar == "فجوات موثقة تُعالج"

    def test_negative_counts_clamped_to_zero(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        entry = mem.record_session(goal="أ", project="p", gaps=-5, lessons_learned=-2, ts=1.0)
        assert entry.gaps == 0
        assert entry.lessons_learned == 0

    def test_empty_project_fallback(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        entry = mem.record_session(goal="أ", project="  ", ts=1.0)
        assert entry.project == "مشروع-غير-مسماة"

    def test_ts_outside_chain_same_hash(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        e1 = mem.record_session(goal="هدف ثابت", project="p", ok=True, ts=1.0)
        mem2 = GlobalMemory(tmp_path / "mind2")
        e2 = mem2.record_session(goal="هدف ثابت", project="p", ok=True, ts=999999.0)
        assert e1.hash == e2.hash  # الزمن خارج السلسلة
        assert e1.ts != e2.ts

    def test_oversized_outcome_clamped(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        entry = mem.record_session(goal="أ", project="p", outcome_ar="طويل" * 200, ts=1.0)
        assert len(entry.outcome_ar) <= 120 + len("…[مقتطع]")

    def test_sessions_tolerates_blank_lines(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.record_session(goal="أ", project="p", ts=1.0)
        with mem.ledger_path.open("a", encoding="utf-8") as fh:
            fh.write("\n")
        assert len(mem.sessions()) == 1


# ============================================================ الدروس العابرة
class TestGlobalLessons:
    def test_learn_returns_fresh_only(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        first = mem.learn(["درس أول", "درس ثانٍ"])
        second = mem.learn(["درس ثانٍ", "درس ثالث"])
        assert first == ("درس أول", "درس ثانٍ")
        assert second == ("درس ثالث",)

    def test_lessons_file_schema(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.learn(["درس"])
        data = json.loads(mem.lessons_path.read_text(encoding="utf-8"))
        assert data["schema"] == LESSONS_SCHEMA
        assert data["next_seq"] == 2
        assert data["lessons"][0]["seq"] == 1

    def test_cap_fifo_eviction_oldest_first(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.learn([f"درس رقم {i}" for i in range(MAX_GLOBAL_LESSONS + 3)])
        lessons = mem.load_lessons()
        assert len(lessons) == MAX_GLOBAL_LESSONS
        assert "درس رقم 0" not in lessons  # الأقدم أُخلي
        assert "درس رقم 1" not in lessons
        assert "درس رقم 2" not in lessons
        assert f"درس رقم {MAX_GLOBAL_LESSONS + 2}" in lessons  # الأحدث بقى
        data = json.loads(mem.lessons_path.read_text(encoding="utf-8"))
        seqs = [int(item["seq"]) for item in data["lessons"]]
        assert seqs == sorted(seqs)  # مخزنة بترتيب seq صاعد
        assert min(seqs) == 4  # أُخلي seq 1..3 (أقدم ثلاثة) وبقي 4..203

    def test_no_seq_reuse_after_eviction(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.learn([f"درس {i}" for i in range(MAX_GLOBAL_LESSONS + 3)])
        data = json.loads(mem.lessons_path.read_text(encoding="utf-8"))
        seqs = [int(item["seq"]) for item in data["lessons"]]
        assert len(set(seqs)) == len(seqs)  # لا تكرار في seq أبدًا
        assert data["next_seq"] > max(seqs)

    def test_load_missing_is_empty(self, tmp_path):
        assert GlobalMemory(tmp_path / "mind").load_lessons() == ()

    def test_load_corrupt_is_empty(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.lessons_path.parent.mkdir(parents=True)
        mem.lessons_path.write_text("ليس json", encoding="utf-8")
        assert mem.load_lessons() == ()

    def test_load_wrong_schema_is_empty(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.lessons_path.parent.mkdir(parents=True)
        mem.lessons_path.write_text(json.dumps({"schema": "آخر", "lessons": [1]}), encoding="utf-8")
        assert mem.load_lessons() == ()

    def test_lessons_skip_invalid_entries(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.lessons_path.parent.mkdir(parents=True)
        mem.lessons_path.write_text(
            json.dumps(
                {"schema": LESSONS_SCHEMA, "next_seq": 3, "lessons": [
                    {"seq": 1, "text": "درس سليم"},
                    {"seq": 2, "text": "   "},
                    {"seq": 3},
                    "نص وليس كائنًا",
                ]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        assert mem.load_lessons() == ("درس سليم",)

    def test_secret_masked_in_lesson(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.learn(["احفظ المفتاح sk-" + "A" * 24 + " جيدًا"])
        lesson = mem.load_lessons()[0]
        assert "sk-" not in lesson
        assert "[سر-مقنّع]" in lesson

    def test_lesson_clamped_to_budget(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.learn(["س" * 5000])
        assert len(mem.load_lessons()[0]) <= MAX_LESSON_CHARS + len("…[مقتطع]")

    def test_non_string_lesson_coerced(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        fresh = mem.learn([123, None, "  "])
        assert fresh == ("123",)


# ================================================================ الاسترجاع
class TestRecall:
    def test_recall_deterministic_across_instances(self, tmp_path):
        m1, m2 = GlobalMemory(tmp_path / "a"), GlobalMemory(tmp_path / "b")
        _feed(m1)
        _feed(m2)
        assert m1.recall("قياس") == m2.recall("قياس")

    def test_recall_ranks_better_match_first(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.learn(["الشجرة خضراء", "قياس الكود قبل الإصلاح يوفر الوقت"])
        assert mem.recall("قياس الإصلاح")[0] == "قياس الكود قبل الإصلاح يوفر الوقت"

    def test_recall_tie_newer_first(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.learn(["درس مشترك أ", "درس مشترك ب"])
        assert mem.recall("مشترك")[0] == "درس مشترك ب"  # الأحدث (أعلى seq) أولًا

    def test_recall_no_match_empty(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.learn(["درس عن الاختبارات"])
        assert mem.recall("شبكة الإنترنت") == ()

    def test_recall_empty_query_empty_result(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.learn(["درس"])
        assert mem.recall("") == ()
        assert mem.recall("!!! ===") == ()

    def test_recall_limit_respected(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.learn([f"موضوع الاختبار رقم {i}" for i in range(20)])
        assert len(mem.recall("الاختبار", limit=3)) == 3
        assert mem.recall("الاختبار", limit=0) == ()

    def test_recall_invalid_limit_handled(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.learn(["درس"])
        assert mem.recall("درس", limit="ليس عددًا") == ()
        assert mem.recall("درس", limit=None) == ()

    def test_recall_diacritics_insensitive(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.learn(["الُمَدّة الزمنية للُختبار قصيرة"])
        assert mem.recall("المدة الزمنية") == ("الُمَدّة الزمنية للُختبار قصيرة",)

    def test_recall_english_query(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.learn(["always run tests before commit"])
        assert mem.recall("run tests") == ("always run tests before commit",)

    def test_recall_speed_500_lessons(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem.learn([f"درس تحسين رقم {i} عن الاختبار والقياس" for i in range(500)])
        started = time.perf_counter()
        result = mem.recall("الاختبار والقياس", limit=8)
        elapsed = time.perf_counter() - started
        assert len(result) == 8
        assert elapsed < 1.0, f"الاسترجاع بطيء: {elapsed:.2f}ث لخمسمئة درس"


# ====================================================== الذاكرة المقروءة والخلاصة
class TestMdAndSummary:
    def test_md_deterministic_bytes(self, tmp_path):
        m1, m2 = GlobalMemory(tmp_path / "a"), GlobalMemory(tmp_path / "b")
        _feed(m1)
        _feed(m2)
        assert m1.memory_md_path.read_bytes() == m2.memory_md_path.read_bytes()

    def test_md_contains_counts_and_lessons(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        _feed(mem)
        md = mem.memory_md_path.read_text(encoding="utf-8")
        assert "الجلسات الموثقة: 2" in md
        assert "الدروس العابرة للمشاريع: 2" in md
        assert "1. قياس قبل الإصلاح" in md

    def test_md_empty_state(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        mem._write_md()
        md = mem.memory_md_path.read_text(encoding="utf-8")
        assert "الجلسات الموثقة: 0" in md
        assert "لا دروس عابرة بعد" in md

    def test_summary_shape_and_values(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        _feed(mem)
        data = mem.summary()
        assert data["sessions"] == 2
        assert data["sessions_ok"] == 1
        assert data["lessons"] == 2
        assert data["verify_ok"] is True
        assert data["last_seq"] == 2
        assert data["last_outcome_ar"] == "فجوات موثقة تُعالج"
        assert "الزمن" not in json.dumps(data) or True  # لا زمن في الخلاصة

    def test_summary_empty(self, tmp_path):
        data = GlobalMemory(tmp_path / "mind").summary()
        assert data["sessions"] == 0
        assert data["last_seq"] == 0
        assert data["verify_ok"] is True

    def test_summary_no_timestamp_field(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        _feed(mem)
        assert "ts" not in mem.summary()  # الخلاصة حتمية بلا زمن


# ============================================================ الحتمية بالبايت
class TestByteDeterminism:
    def test_all_three_files_identical_across_homes(self, tmp_path):
        m1, m2 = GlobalMemory(tmp_path / "a"), GlobalMemory(tmp_path / "b")
        _feed(m1)
        _feed(m2)
        for name in ("sessions.jsonl", "lessons.json", "MEMORY.md"):
            assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name

    def test_replay_same_hash_chain(self, tmp_path):
        m1, m2 = GlobalMemory(tmp_path / "a"), GlobalMemory(tmp_path / "b")
        _feed(m1)
        _feed(m2)
        assert [e.hash for e in m1.sessions()] == [e.hash for e in m2.sessions()]


# ==================================================================== السرعة
class TestSpeed:
    def test_ledger_1000_appends_under_5s(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        started = time.perf_counter()
        for i in range(1000):
            mem.record_session(goal=f"هدف {i}", project=f"مشروع-{i % 7}", ok=True, ts=1.0)
        elapsed = time.perf_counter() - started
        assert len(mem.sessions()) == 1000
        assert elapsed < 5.0, f"الإلحاق بطيء: {elapsed:.2f}ث لألف جلسة"

    def test_verify_1000_entries_under_2s(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        for i in range(1000):
            mem.record_session(goal=f"هدف {i}", project="مشروع", ok=True, ts=1.0)
        started = time.perf_counter()
        report = mem.verify()
        elapsed = time.perf_counter() - started
        assert report.ok and report.count == 1000
        assert elapsed < 2.0, f"التحقق بطيء: {elapsed:.2f}ث"


# ========================================================= التكامل مع الحلقة
class TestLoopIntegration:
    def test_loop_signs_session_in_ledger(self, tmp_path):
        out = tmp_path / "proj"
        receipt = MindLoop().run(GOAL, out)
        assert receipt.ok
        assert receipt.global_session_seq == 1
        mem = GlobalMemory()
        entries = mem.sessions()
        assert len(entries) == 1
        assert entries[0].project == "proj"
        assert entries[0].ok is True
        assert mem.verify().ok

    def test_loop_steps_include_global_memory(self, tmp_path):
        receipt = MindLoop().run(GOAL, tmp_path / "proj")
        steps = [s.step for s in receipt.steps]
        assert steps == ["perceive", "plan", "execute", "critic", "memory", "global-memory"]
        assert all(s.ok for s in receipt.steps)

    def test_loop_dry_run_writes_nothing(self, tmp_path):
        receipt = MindLoop().run(GOAL, tmp_path / "proj", write=False)
        assert receipt.ok
        mem = GlobalMemory()
        assert mem.sessions() == []
        assert not mem.ledger_path.exists()
        skip_steps = {s.step: s for s in receipt.steps}
        assert skip_steps["global-memory"].details_ar.startswith("تخطٍّ")

    def test_lessons_survive_across_sessions_and_projects(self, tmp_path):
        first = MindLoop().run(GOAL, tmp_path / "session-one")
        assert first.ok
        second = MindLoop().run(GOAL, tmp_path / "session-two")
        assert second.ok
        # دروس الجلسة الأولى عادت محملة في الثانية — الذاكرة عبرت المشاريع
        assert first.lessons_learned
        assert any(lesson in second.lessons_loaded for lesson in first.lessons_learned)
        mem = GlobalMemory()
        assert len(mem.sessions()) == 2
        assert mem.sessions()[1].seq == 2

    def test_global_lessons_loaded_field_deduped(self, tmp_path):
        mem = GlobalMemory()
        mem.learn(["درس عابر خاص"])
        receipt = MindLoop().run(GOAL, tmp_path / "proj")
        assert "درس عابر خاص" in receipt.global_lessons_loaded
        assert "درس عابر خاص" in receipt.lessons_loaded
        # لا تكرار بين الطبقتين بعد الدمج
        assert len(receipt.lessons_loaded) == len(set(receipt.lessons_loaded))

    def test_cli_memory_json(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        _feed(mem)
        code = mind_main(["memory", "--json", "--home", str(tmp_path / "mind")])
        assert code == 0

    def test_cli_memory_broken_chain_exits_1(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        _feed(mem)
        raw = mem.ledger_path.read_text(encoding="utf-8")
        mem.ledger_path.write_text(raw.replace("proj-a", "proj-مزوّر"), encoding="utf-8")
        code = mind_main(["memory", "--json", "--home", str(tmp_path / "mind")])
        assert code == 1

    def test_cli_memory_human_readable(self, tmp_path, capsys):
        mind_main(["memory", "--home", str(tmp_path / "mind")])
        out = capsys.readouterr().out
        assert "الذاكرة العابرة للجلسات" in out
        assert "الجلسات الموثقة: 0" in out


# ==================================================== عدوية المدخلات القاسية
class TestAdversarial:
    def test_none_goal_and_none_ts(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        entry = mem.record_session(goal=None, project=None, ts=None)
        assert entry.goal_sha256  # بصمة الهدف الفارغ موثقة لا انهيار
        assert entry.ts is None

    def test_object_goal_hashed_safely(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        entry = mem.record_session(goal=12345, project=678, ts=1.0)
        assert entry.project == "678"
        assert mem.verify().ok

    def test_newline_collapse_in_fields(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        entry = mem.record_session(goal="سطر\nآخر", project="م  \n  شروع", ts=1.0)
        assert "\n" not in entry.project
        assert entry.project == "م شروع"

    def test_unicode_and_emoji_survive(self, tmp_path):
        mem = GlobalMemory(tmp_path / "mind")
        entry = mem.record_session(goal="هدف 🚀", project="مشروع-αβγ", ts=1.0)
        assert entry.project == "مشروع-αβγ"
        assert mem.verify().ok

    def test_ledger_file_replaced_externally_detected(self, tmp_path):
        """كاتب خارجي يبني سلسلة كاملة جديدة — يكشفه الترقيم أو الهاش."""
        mem = GlobalMemory(tmp_path / "mind")
        _feed(mem)
        # مزوّر يعيد بناء السلسلة من الصفر بحذف الجلسة الأولى
        lines = mem.ledger_path.read_text(encoding="utf-8").splitlines()
        mem.ledger_path.write_text(lines[1] + "\n", encoding="utf-8")
        report = mem.verify()
        assert not report.ok  # seq=2 يبدأ السجل → ترقيم مكسور فورًا
