"""اختبارات الذاكرة الطبقية — جلسة فانية ومشروع دائم ودروس مستخلصة."""

from __future__ import annotations

import json

from zyko.mind.memory import LESSONS_SCHEMA, STATE_SCHEMA, MindMemory


class TestSessionLayer:
    def test_remember_and_read(self):
        m = MindMemory(".")
        m.remember("ملاحظة أولى")
        m.remember("ملاحظة ثانية")
        assert m.session == ["ملاحظة أولى", "ملاحظة ثانية"]

    def test_empty_note_ignored(self):
        m = MindMemory(".")
        m.remember("   ")
        assert m.session == []


class TestProjectLayer:
    def test_persist_deterministic_bytes(self, tmp_path):
        state = {"goal": "انشئ مشروع", "kind": "GENERATE"}
        m1 = MindMemory(tmp_path)
        m1.persist(state)
        raw1 = m1.state_path.read_bytes()
        m2 = MindMemory(tmp_path)
        m2.persist(state)
        raw2 = m2.state_path.read_bytes()
        assert raw1 == raw2

    def test_persist_sorted_keys_and_schema(self, tmp_path):
        m = MindMemory(tmp_path)
        m.persist({"goal": "انشئ مشروع", "kind": "GENERATE"})
        data = json.loads(m.state_path.read_text(encoding="utf-8"))
        assert data["schema"] == STATE_SCHEMA
        assert data["goal"] == "انشئ مشروع"

    def test_load_state_missing_is_empty(self, tmp_path):
        assert MindMemory(tmp_path).load_state() == {}

    def test_load_state_corrupt_is_empty(self, tmp_path):
        m = MindMemory(tmp_path)
        m.mind_dir.mkdir(parents=True)
        m.state_path.write_text("ليس json", encoding="utf-8")
        assert m.load_state() == {}

    def test_paths_layout(self, tmp_path):
        m = MindMemory(tmp_path)
        assert m.mind_dir == tmp_path / ".zyko" / "mind"
        assert m.state_path.name == "state.json"
        assert m.lessons_path.name == "lessons.json"
        assert m.memory_md_path.name == "MEMORY.md"


class TestLessonsLayer:
    def test_learn_then_load(self, tmp_path):
        m = MindMemory(tmp_path)
        learned = m.learn(["درس أ", "درس ب"])
        assert learned == ("درس أ", "درس ب")
        assert m.load_lessons() == ("درس أ", "درس ب")

    def test_learn_sorted_deterministic(self, tmp_path):
        m = MindMemory(tmp_path)
        m.learn(["درس ب", "درس أ"])
        assert m.load_lessons() == ("درس أ", "درس ب")

    def test_learn_deduplicates(self, tmp_path):
        m = MindMemory(tmp_path)
        first = m.learn(["درس أ"])
        second = m.learn(["درس أ", "درس ب"])
        assert first == ("درس أ",)
        assert second == ("درس ب",)
        assert m.load_lessons() == ("درس أ", "درس ب")

    def test_learn_empty_returns_nothing_and_no_write(self, tmp_path):
        m = MindMemory(tmp_path)
        assert m.learn([]) == ()
        assert m.learn(None) == ()
        assert not m.lessons_path.exists()

    def test_load_missing_lessons_is_empty(self, tmp_path):
        assert MindMemory(tmp_path).load_lessons() == ()

    def test_load_corrupt_lessons_is_empty(self, tmp_path):
        m = MindMemory(tmp_path)
        m.mind_dir.mkdir(parents=True)
        m.lessons_path.write_text("{ مكسور", encoding="utf-8")
        assert m.load_lessons() == ()

    def test_wrong_schema_rejected(self, tmp_path):
        m = MindMemory(tmp_path)
        m.mind_dir.mkdir(parents=True)
        m.lessons_path.write_text(
            json.dumps({"schema": "بعض-مخطط-غريب", "lessons": ["درس"]}, ensure_ascii=False),
            encoding="utf-8",
        )
        assert m.load_lessons() == ()

    def test_schema_constant(self, tmp_path):
        m = MindMemory(tmp_path)
        m.learn(["درس"])
        data = json.loads(m.lessons_path.read_text(encoding="utf-8"))
        assert data["schema"] == LESSONS_SCHEMA


class TestMemoryMd:
    def test_md_readable_with_state_and_lessons(self, tmp_path):
        m = MindMemory(tmp_path)
        m.persist({"goal": "انشئ مشروع مهام", "kind": "GENERATE"})
        m.learn(["درس أول"])
        text = m.memory_md_path.read_text(encoding="utf-8")
        assert "انشئ مشروع مهام" in text
        assert "درس أول" in text

    def test_md_deterministic(self, tmp_path):
        m = MindMemory(tmp_path)
        m.persist({"goal": "هدف ثابت", "kind": "FIX"})
        m.learn(["درس"])
        a = m.memory_md_path.read_bytes()
        m2 = MindMemory(tmp_path)
        m2.persist({"goal": "هدف ثابت", "kind": "FIX"})
        m2.learn(["درس"])
        assert a == m2.memory_md_path.read_bytes()
