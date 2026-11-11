"""zyko.mind.memory — وحدة الذاكرة: ثلاث طبقات حتمية بلا اعتمادية.

وحدة «الذاكرة» من ``docs/MIND.md`` §6.1-6 — الطبقات الثلاث كما وثّقت:

  1. **جلسة فانية** في ذاكرة العملية: قائمة ملاحظات تُهدى مع الجلسة.
  2. **مشروع دائم** في ``<out>/.zyko/mind/``: ``state.json`` بصيغة JSON
     مفرزة المفاتيح (حتمية بالبايت، بلا طوابع زمنية) — حالة المشروع
     تُقرأ في الجلسة القادمة.
  3. **معرفة مستخلصة** (دروس عامة): ``lessons.json`` إلحاقي مُزال
     التكرار ومفرز — يُحمَّل مع كل جلسة جديدة فتتعلم الحلقة من جولاتها
     السابقة، و``MEMORY.md`` نص عربي مقروء للمشروع والمستودع.

الحتمية شرط التصميم كما في بقية المصنع: الترتيب مفروز، لا ``datetime``
ولا ``random``، ونفس الجلسة تعطي نفس الملفات بالبايت في أي جهاز.
"""

from __future__ import annotations

import json
from pathlib import Path

from zyko.ai.receipt import hash_file

STATE_SCHEMA = "zyko.mind/state-v1"
LESSONS_SCHEMA = "zyko.mind/lessons-v1"


class MindMemory:
    """الذاكرة الطبقية لمشروع واحد — كل الطبقات فوق مجلد ``.zyko/mind/``."""

    def __init__(self, project_dir: str | Path) -> None:
        self.project_dir = Path(project_dir)
        self.session: list[str] = []  # الطبقة الفانية — تُهدى مع العملية

    # ------------------------------------------------------------ الطبقة الفانية
    def remember(self, note: str) -> None:
        """أضف ملاحظة للجلسة الفانية — تُحفظ في الإيصال لا على القرص."""
        text = str(note).strip()
        if text:
            self.session.append(text)

    # ------------------------------------------------------------ المسارات
    @property
    def mind_dir(self) -> Path:
        """مجلد الذاكرة الدائمة ``<out>/.zyko/mind/``."""
        return self.project_dir / ".zyko" / "mind"

    @property
    def state_path(self) -> Path:
        """مسار حالة المشروع الدائمة."""
        return self.mind_dir / "state.json"

    @property
    def lessons_path(self) -> Path:
        """مسار الدروس المستخلصة."""
        return self.mind_dir / "lessons.json"

    @property
    def memory_md_path(self) -> Path:
        """مسار الذاكرة المقروءة للإنسان."""
        return self.mind_dir / "MEMORY.md"

    # ------------------------------------------------------------ المشروع الدائم
    def persist(self, state: dict) -> dict[str, str]:
        """اكتب حالة المشروع الدائمة — مفرزة المفاتيح، حتمية بالبايت."""
        payload = {"schema": STATE_SCHEMA, **state}
        self.mind_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {str(self.state_path): hash_file(self.state_path)}

    def load_state(self) -> dict:
        """اقرأ حالة المشروع الدائمة — فارغ آمن إن لم تُكتب بعد."""
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------ الدروس
    def load_lessons(self) -> tuple[str, ...]:
        """اقرأ الدروس المستخلصة — تُحمَّل مع كل جلسة جديدة."""
        try:
            data = json.loads(self.lessons_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ()
        if not isinstance(data, dict) or data.get("schema") != LESSONS_SCHEMA:
            return ()
        lessons = data.get("lessons")
        if not isinstance(lessons, list):
            return ()
        return tuple(str(lesson) for lesson in lessons if str(lesson).strip())

    def learn(self, lessons) -> tuple[str, ...]:
        """علِّم دروسًا جديدة — إلحاق بإزالة تكرار وفرز حتمي، واكتب فورًا.

        يعود tuple الدروس الجديدة المُضافة فعلًا (بعد إزالة ما كان معروفًا
        مسبقًا) — فتوثّق الجلسة ما تعلمته هذا المرة لا ما حفظته دائمًا.
        """
        existing = set(self.load_lessons())
        fresh: set[str] = set()
        for lesson in lessons or ():
            text = str(lesson).strip()
            if text and text not in existing:
                fresh.add(text)
        if not fresh:
            return ()
        merged = sorted(existing | fresh)
        self.mind_dir.mkdir(parents=True, exist_ok=True)
        self.lessons_path.write_text(
            json.dumps(
                {"schema": LESSONS_SCHEMA, "lessons": merged},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        self.memory_md_path.write_text(self._md(merged), encoding="utf-8")
        return tuple(sorted(fresh))

    # ------------------------------------------------------------ داخلي
    def _md(self, lessons: tuple[str, ...]) -> str:
        """نص ``MEMORY.md`` العربي الحتمي — حالة + دروس."""
        lines = ["# ذاكرة العقل — ZYKO Mind", ""]
        state = self.load_state()
        goal = str(state.get("goal", "")).strip()
        lines.append(f"الهدف: {goal or 'لم يُسجل بعد'}")
        kind = str(state.get("kind", "")).strip()
        if kind:
            lines.append(f"النوع: {kind}")
        lines.append("")
        lines.append("## الدروس المستخلصة")
        if lessons:
            lines.extend(f"{index}. {lesson}" for index, lesson in enumerate(lessons, start=1))
        else:
            lines.append("لا دروس بعد.")
        return "\n".join(lines) + "\n"


__all__ = ["LESSONS_SCHEMA", "STATE_SCHEMA", "MindMemory", "hash_file"]
