"""نموذج نظيف لمعالجة الأخطاء — الصنف الذي نريد أن يقلده الجميع.

استثناءات محددة، سياق محفوظ بـ from، أقفال سياق for files، تسجيل واضح،
ولا أي ابتلاع صامت — ويبقى بدرجة 100 بصفر ملاحظات.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """خطأ إعدادات خاص يُرفع عند غياب الملف أو فساد محتواه."""


def read_config(path: str) -> dict[str, str]:
    """يقرأ الإعدادات من ملف JSON مع رسائل خطأ عربية واضحة."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        logger.warning("ملف الإعدادات غير موجود: %s", path)
        raise ConfigError(f"الملف غير موجود: {path}") from exc
    except json.JSONDecodeError as exc:
        logger.error("ملف إعدادات فاسد: %s", path)
        raise ConfigError(f"محتوى غير صالح في {path}") from exc
    if not isinstance(data, dict):
        raise ConfigError("جذر الإعدادات يجب أن يكون قاموسًا")
    return {str(k): str(v) for k, v in data.items()}


def safe_divide(left: float, right: float, default: float = 0.0) -> float:
    """قسمة آمنة تعيد قيمة افتراضية معلنة عند القسمة على صفر."""
    if right == 0.0:
        logger.info("قسمة على صفر — إعادة القيمة الافتراضية")
        return default
    return left / right


def retry_read(path: str, attempts: int = 3) -> str:
    """يحاول قراءة ملف عدة مرات ثم يرفع خطأ سياقيًا محفوظ الأثر."""
    last_error: OSError | None = None
    for attempt in range(1, attempts + 1):
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            last_error = exc
            logger.warning("المحاولة %d فشلت: %s", attempt, exc)
    raise ConfigError(f"فشلت كل المحاولات لقراءة {path}") from last_error
