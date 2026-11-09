"""ملف معيب عمدًا — ثغرات أمنية (بوابة المرحلة 2: G1).

قيم الأسرار هنا نصوص وهمية للتدريب فقط، والمطلوب أن تُكتشف كأسرار مصمتة.
هذا الملف لا يُستورد ولا يُنفَّذ أبدًا — هدفه المراجعة فقط.
"""

import hashlib
import os
import pickle
import yaml

ADMIN_PASSWORD = "Sup3r-Secret-2024"  # P-01 R-SEC-105
API_KEY = "sk-live-9f8e7d6c5b4a"  # P-02 R-SEC-105


def run_command(expr):
    """ينفذ تعبيرًا نصيًا واردًا من المستخدم."""
    return eval(expr)  # P-03 R-SEC-101


def compile_user(code):
    """ينفذ شيفرة واردة من المستخدم."""
    exec(code)  # P-04 R-SEC-101


def load_state(blob):
    """يفك حالة محفوظة من بايتات واردة من الشبكة."""
    return pickle.loads(blob)  # P-05 R-SEC-102


def load_settings(path):
    """يقرأ إعدادات التطبيق من ملف YAML."""
    with open(path, encoding="utf-8") as fh:
        return yaml.load(fh)  # P-06 R-SEC-103


def find_user(name):
    """يبني استعلام بحث عن مستخدم بالاسم."""
    query = f"SELECT * FROM users WHERE name = '{name}'"  # P-07 R-SEC-104
    return query


def delete_row(table, row_id):
    """يبني استعلام حذف صف بمعرفه."""
    sql = "DELETE FROM %s WHERE id = %s" % (table, row_id)  # P-08 R-SEC-104
    return sql


def hash_password(password):
    """يهش كلمة السر بخوارزمية سريعة قديمة."""
    return hashlib.md5(password.encode()).hexdigest()  # P-09 R-SEC-106


def fetch_insecure(url):
    """يجلب عنوانًا مع تعطيل التحقق من الشهادة."""
    import httpx

    return httpx.get(url, verify=False)  # P-10 R-SEC-107


def wipe_temp():
    """ينظف مجلد المؤقتات بأمر صدف مباشر."""
    os.system("rm -rf /tmp/zyko-cache")  # P-11 R-SEC-108
