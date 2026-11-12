"""استخراج السياق الحتمي من هدف المستخدم — استدعاء `zyko do` بلا أعلام.

يستخرج من النص: أول مسار ملف (يغذي review/fix/transpile/verify/baseline
حسب نوع المهمة عبر سلاسل البدائل في route)، ويضع النص كاملاً في
``description`` للتوليد. نقي حتمي: regex ثابت على النص — لا بيئة ولا زمن.
الأعلام الصريحة (`--path` إلخ) تتغلب على المستخرج دائماً.
"""

from __future__ import annotations

import re

# مسار ملف: أول تطابق يفوز — بالترتيب:
#   1. مطلق: بادئة محرك اختيارية (C:) ثم مكوّنات بفواصل / أو \ —
#      يغطي /posix وC:\win و\\unc — كانت تُقتطع بدايتها سابقاً فتفشل الأدوات.
#      ويشمل «~» لأسماء ويندوز القصيرة (RUNNER~1 في CI) — التقطيع عند
#      التلدة كان يقطع المسار إلى «C:\Users» فيفقد الملف كله.
#   2. نسبي بمكوّنات مجلدات (src/app.py).
#   3. ملف بامتداد معروف (widget.py).
_PATH_RE = re.compile(
    r"(?:[A-Za-z]:)?(?:[/\\]+[\w.\-~]+)+"
    r"|(?:[\w.\-~]+[/\\])+[\w.\-~]+"
    r"|[\w.\-~]+\.(?:py|daad|json|md|txt|yaml|yml|toml|csv|log|js|ts)\b"
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
