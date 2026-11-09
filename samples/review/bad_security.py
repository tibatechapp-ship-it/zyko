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


# ---------------- موجة ميزان (v0.15.0): عيوب القواعد R-SEC-109…R-SEC-119


def read_report():
    """يقرأ تقريرًا من مسار أدخله المستخدم مباشرة."""
    path = input("المسار: ")
    return open(path, encoding="utf-8").read()  # P-12 R-SEC-109


def build_context():
    """يبني سياق SSL بلا تحقق من الشهادات."""
    import ssl

    return ssl._create_unverified_context()  # P-13 R-SEC-110


def fetch_url(url):
    """يجلب عنوانًا بلا مهلة زمنية."""
    import requests

    return requests.get(url)  # P-14 R-SEC-111


def load_checkpoint(path):
    """يحمل نقطة تفتيش نموذج بلا قيد الأوزان."""
    import torch

    return torch.load(path)  # P-15 R-SEC-112


def load_model(name):
    """يحمل نموذجًا يسمح بتنفيذ شيفرة بعيدة."""
    return from_pretrained(name, trust_remote_code=True)  # P-16 R-SEC-113


def build_template_engine():
    """يبني محرك قوالب بلا تهريب HTML."""
    import jinja2

    return jinja2.Environment(autoescape=False)  # P-17 R-SEC-114


def render_greeting(body):
    """يعلن نصًا آمنًا لـ HTML دون تهريب."""
    from django.utils.safestring import mark_safe

    return mark_safe(body)  # P-18 R-SEC-115


def extract_archive(path):
    """يستخرج أرشيفًا بلا فلتر آمن."""
    import tarfile

    with tarfile.open(path) as tar:
        tar.extractall()  # P-19 R-SEC-116


def stage_file():
    """يكتب ملفًا في مجلد مؤقت مصمت."""
    return open("/tmp/zyko-stage.txt", "w", encoding="utf-8")  # P-20 R-SEC-117


def ping_host():
    """يستدعي مضيفًا أدخله المستخدم كسلسلة أمر خام."""
    import subprocess

    host = input("المضيف: ")
    return subprocess.run(host, check=False)  # P-21 R-SEC-118


def query_orders(cursor, request):
    """ينفذ استعلامًا واردًا نصه من بيانات الطلب."""
    q = request.args.get("q")
    return cursor.execute(q)  # P-22 R-SEC-119
