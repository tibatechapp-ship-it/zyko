"""استخراج السياق الحتمي من هدف المستخدم — استدعاء `zyko do` بلا أعلام.

يستخرج من النص: أول مسار ملف (يغذي review/fix/transpile/verify/baseline
حسب نوع المهمة عبر سلاسل البدائل في route)، ويضع النص كاملاً في
``description`` للتوليد. نقي حتمي: regex ثابت على النص — لا بيئة ولا زمن.
الأعلام الصريحة (`--path` إلخ) تتغلب على المستخرج دائماً.
"""

from __future__ import annotations

import re

# مسار ملف: إما يحتوي «/» أو ينتهي بامتداد معروف — أول تطابق يفوز.
_PATH_RE = re.compile(
    r"(?:[\w.\-]+/)+[\w.\-]+"
    r"|[\w.\-]+\.(?:py|daad|json|md|txt|yaml|yml|toml|csv|log|js|ts)\b"
)

_CODE_EXTENSIONS = (".daad",)


def extract_context(goal: str) -> dict[str, str]:
    """سياق حتمي من نص الهدف: path/file/receipt إن وُجد مسار، + description."""
    goal = "" if goal is None else str(goal)
    context: dict[str, str] = {}
    match = _PATH_RE.search(goal)
    if match:
        first = match.group(0)
        context["path"] = first
        if first.endswith(_CODE_EXTENSIONS):
            context["file"] = first
        if first.endswith(".json"):
            context["receipt"] = first
    context["description"] = goal.strip()
    return context
