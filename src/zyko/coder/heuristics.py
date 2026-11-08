"""zyko.coder.heuristics — مسوّدة مخطط حتمية من وصف عربي.

The *model* planner fills ProjectPlan on-device (D15–16). This module
is the deterministic stand-in used by:

- the offline acceptance harness (D20–21 runs in CI with no model);
- ``zyko new --plan ... --heuristic`` to preview a plan without any
  API key;
- tests that need real Arabic descriptions turning into valid plans.

It is intentionally transparent: a keyword table maps Arabic intents to
(template, modules, deps, run commands). Same words in, same plan out —
never a model call.
"""

from __future__ import annotations

import re

from .plan import ProjectPlan

# (المعرف، القالب، الوحدات، الاعتماديات، أوامر التشغيل، الكلمات المفتاحية)
_INTENTS: tuple[dict[str, object], ...] = (
    {
        "id": "todo",
        "name": "todo-cli",
        "display": "قائمة المهام",
        "template": "python-cli",
        "modules": ("tasks",),
        "deps": (),
        "run": ("todo-cli tasks --help", "pytest -q"),
        "keywords": ("مهام", "المهام", "تودو", "مهمات", "قائمة مهام"),
    },
    {
        "id": "notes",
        "name": "notes-cli",
        "display": "دفتر الملاحظات",
        "template": "python-cli",
        "modules": ("notes", "archive"),
        "deps": (),
        "run": ("notes-cli notes --help", "pytest -q"),
        "keywords": ("ملاحظات", "دفتر", "توثيق يومي"),
    },
    {
        "id": "expenses",
        "name": "expenses-cli",
        "display": "متتبع المصاريف",
        "template": "python-cli",
        "modules": ("expenses", "reports"),
        "deps": (),
        "run": ("expenses-cli expenses --help", "pytest -q"),
        "keywords": ("مصاريف", "مصروفات", "ميزانية", "نفقات"),
    },
    {
        "id": "pomodoro",
        "name": "pomodoro-cli",
        "display": "مؤقت البومودورو",
        "template": "python-cli",
        "modules": ("sessions", "stats"),
        "deps": (),
        "run": ("pomodoro-cli sessions --help", "pytest -q"),
        "keywords": ("بومودورو", "مؤقت", "تركيز", "استراحات"),
    },
    {
        "id": "blog",
        "name": "blog-site",
        "display": "مدونة عربية",
        "template": "static-site",
        "modules": ("posts", "about"),
        "deps": (),
        "run": ("python -m http.server 8000", "pytest -q"),
        "keywords": ("مدونة", "مقالات", "تدوين", "مدونت"),
    },
    {
        "id": "restaurant",
        "name": "restaurant-site",
        "display": "موقع مطعم",
        "template": "static-site",
        "modules": ("menu", "contact"),
        "deps": (),
        "run": ("python -m http.server 8000", "pytest -q"),
        "keywords": ("مطعم", "قائمة طعام", "كافيه", "مقهى"),
    },
    {
        "id": "gallery",
        "name": "gallery-site",
        "display": "معرض أعمال",
        "template": "static-site",
        "modules": ("gallery", "about"),
        "deps": (),
        "run": ("python -m http.server 8000", "pytest -q"),
        "keywords": ("معرض", "صور", "بورتفوليو", "أعمال"),
    },
    {
        "id": "bookings",
        "name": "bookings-api",
        "display": "واجهة حجوزات",
        "template": "fastapi-api",
        "modules": ("bookings", "services"),
        "deps": ("fastapi>=0.110", "uvicorn>=0.29"),
        "run": ("uvicorn app.main:app --reload", "pytest -q"),
        "keywords": ("حجوزات", "حجز", "مواعيد", "موعد", "عيادة", "صالون"),
    },
    {
        "id": "store",
        "name": "store-api",
        "display": "واجهة متجر",
        "template": "fastapi-api",
        "modules": ("products", "orders"),
        "deps": ("fastapi>=0.110", "uvicorn>=0.29"),
        "run": ("uvicorn app.main:app --reload", "pytest -q"),
        "keywords": ("متجر", "منتجات", "طلبيات", "سلة", "مبيعات"),
    },
    {
        "id": "school",
        "name": "school-api",
        "display": "واجهة مدرسة",
        "template": "fastapi-api",
        "modules": ("students", "courses"),
        "deps": ("fastapi>=0.110", "uvicorn>=0.29"),
        "run": ("uvicorn app.main:app --reload", "pytest -q"),
        "keywords": ("مدرسة", "طلاب", "دروس", "منهج", "حضور"),
    },
)

# إضافات وحدات بالكلمة المفتاحية (تُدمج مع الوحدات الافتراضية للنية)
_EXTRA_MODULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("تقارير", "تقرير"), "reports"),
    (("مستخدمين", "مستخدمون", "حسابات", "دخول"), "users"),
    (("تنبيهات", "إشعارات", "تذكير"), "reminders"),
)


def _match_intent(description: str) -> dict[str, object]:
    text = re.sub(r"[\u0640\u064B-\u065F]", "", description)  # تشكيل وتطويل
    best: dict[str, object] | None = None
    best_hits = 0
    for intent in _INTENTS:
        hits = sum(1 for kw in intent["keywords"] if kw in text)  # type: ignore[union-attr]
        if hits > best_hits:
            best, best_hits = intent, hits
    if best is None:
        # نية افتراضية: CLI مهام — الأكثر عمومية وأمانًا
        best = _INTENTS[0]
    return best


def draft_plan(description: str) -> ProjectPlan:
    """مسوّدة مخطط صالحة بالكامل من وصف عربي — حتمية 100%.

    تُستخدم كبديل بلا نموذج وللاختبارات؛ على الجهاز يملأ المخطط
    النموذج (planner) ثم يمر عبر نفس التحقق الصارم.
    """
    intent = _match_intent(description)
    mods = list(intent["modules"])  # type: ignore[arg-type]
    text = description
    for keywords, extra in _EXTRA_MODULES:
        if any(kw in text for kw in keywords) and extra not in mods:
            mods.append(extra)
    return ProjectPlan(
        name=str(intent["name"]),
        template=str(intent["template"]),
        description=description.strip(),
        modules=tuple(mods[:12]),
        dependencies=tuple(intent["deps"]),  # type: ignore[arg-type]
        run_commands=tuple(intent["run"]),  # type: ignore[arg-type]
        display_name=str(intent["display"]),
        author="zyko-coder",
    )


def known_intents() -> list[str]:
    """معرفات النوايا المدعومة (للتوثيق والاختبار)."""
    return [str(i["id"]) for i in _INTENTS]


__all__ = ["draft_plan", "known_intents"]
