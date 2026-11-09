"""نموذج نظيف — إدارة مخزون صغيرة (بوابة المرحلة 2: G2).

يجب أن تبقى هذه الوحدة بدرجة 100 وصفر ملاحظات على كل القواعد الـ 27:
توثيق كامل، توصيف أنواع كامل، دوال قصيرة، استيراد مستخدم، ولا أي نمط
من الأنماط المعيبة في السجل.
"""

from __future__ import annotations

import json
from pathlib import Path


class Inventory:
    """مخزون منتجات بسيط فوق ملف JSON."""

    def __init__(self, path: Path) -> None:
        """يجهّز المخزون فوق مسار ملف معين."""
        self._path = path
        self._items: dict[str, int] = {}

    def load(self) -> None:
        """يقرأ العناصر من الملف إن وُجد."""
        if not self._path.is_file():
            return
        raw = self._path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
        self._items = {str(k): int(v) for k, v in data.items()}

    def add(self, name: str, count: int) -> None:
        """يضيف كمية لعنصر موجود أو ينشئ عنصرًا جديدًا."""
        current = self._items.get(name, 0)
        self._items[name] = current + max(0, count)

    def total_units(self) -> int:
        """يرجع مجموع الكميات في المخزون."""
        return sum(self._items.values())

    def save(self) -> None:
        """يكتب العناصر إلى الملف بصيغة JSON مرتبة."""
        ordered = dict(sorted(self._items.items()))
        self._path.write_text(
            json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def clamp(value: int, low: int, high: int) -> int:
    """يقيّد القيمة داخل مجال معين."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def describe_stock(inventory: Inventory) -> str:
    """يرجع وصفًا عربيًا موجزًا لحالة المخزون."""
    total = inventory.total_units()
    if total == 0:
        return "المخزون فارغ"
    if total < 10:
        return f"المخزون منخفض: {total} وحدات"
    return f"المخزون جيد: {total} وحدات"
