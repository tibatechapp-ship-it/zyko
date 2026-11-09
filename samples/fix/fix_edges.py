"""حالات حافة للإصلاح الآلي — عينة مرساة للمرحلة 3 (بوابتا G1 وG6).

كل حالة هنا تختبر حدود المسار الآمن: ما يُصلَح آليًا وما يُترك يدويًا
مع بقاء الإصلاح المقترح العربي ظاهرًا — لا صمت ولا انهيار.
هذا الملف لا يُنفَّذ أبدًا — هدفه الإصلاح والمراجعة فقط.
"""

import hashlib
import json
import os  # R-QLT-207: غير مستخدم — استيراد مفرد يُحذف آليًا
import subprocess
import sys
import yaml
from typing import (
    Dict,
    List,
)


def dump_payload(payload: dict) -> str:
    """يسلسل حمولة إلى نص JSON."""
    return json.dumps(payload, ensure_ascii=False)


def platform_tag() -> str:
    """يرجع وسم المنصة الحالية."""
    return sys.platform


def join_paths(parts: List[str]) -> str:
    """يجمع مسارات بقائمة النوع."""
    return "/".join(parts)


def run_safe(target):
    """ينفذ قائمة وسائط حرفية — shell=True يُحذف آليًا (R-ERR-005)."""
    subprocess.run(["ls", "-la", target], shell=True, check=True)


def render(*, rows=[]):
    """قيمة افتراضية متحورة بوسيط مسمى فقط (R-ERR-006)."""
    rows.append(1)
    return rows


def load_yaml(path):
    """يقرأ إعدادات بتحميل غير آمن مع Loader صريح (R-SEC-103)."""
    with open(path, encoding="utf-8") as fh:
        return yaml.load(fh, Loader=yaml.Loader)


def compare_pair(a, b):
    """سلسلة مقارنات مع None (R-QLT-206) — تُصلَح آليًا."""
    return a == None or b != None


def tiny(): return 1  # R-QLT-204: دالة بسطر واحد — التوثيق يُدرج آليًا


class NoDocs:  # R-QLT-204: فئة بلا توثيق
    def build(self, rows):
        return rows


fmt = lambda n: (
    f"{n:04d}"
)  # R-QLT-209: لامدا بجسم متعدد الأسطر — تعادل def آليًا


def open_indirect(path):
    """فتح بلا with قيمته عبر تابع — لا مسار آمن (R-ERR-004 تبقى مفتوحة)."""
    blob = open(path).read()
    return blob


def loud_fail(value):
    """raise داخل معالج مسمى — from يُضاف آليًا (R-ERR-003)."""
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError("قيمة غير صالحة")


def silent(payload):
    """except عامة بجسم صامت — الأولى تُصلح والثانية تبقى يدويًا (R-ERR-002)."""
    try:
        return int(payload)
    except:  # صمت مقصود؟
        pass


def make_session(session):
    """جلسة مع تعطيل التحقق عبر سمة — تُردّ آليًا (R-SEC-107)."""
    session.verify = False
    return session


def weak_hash_text(text):
    """تجميعة ضعيفة — تُستبدل آليًا (R-SEC-106)."""
    return hashlib.md5(text.encode()).hexdigest()
