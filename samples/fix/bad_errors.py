"""ملف معيب عمدًا — أخطاء معالجة الاستثناءات (بوابة المرحلة 2: G1).

كل عيب مزروع موسوم بتعليق «P-xx R-…» يلتقطه مولّد manifest.json.
هذا الملف لا يُستورد ولا يُنفَّذ أبدًا — هدفه المراجعة فقط.
"""

import subprocess


def load_config(path):
    """يقرأ نص الإعدادات من ملف."""
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except:  # P-01 R-ERR-001
        pass  # P-02 R-ERR-002


def save_report(path, data):
    """يحفظ تقريرًا نصيًا ويرفع خطأ عام عند الفشل."""
    try:
        fh = open(path, "w", encoding="utf-8")  # P-03 R-ERR-004
        fh.write(data)
        return True
    except OSError:
        raise RuntimeError("فشل الحفظ")  # P-04 R-ERR-003


def run_backup(source):
    """ينسخ المصدر إلى النسخة الاحتياطية عبر الصدفة."""
    subprocess.call("cp " + source + " /tmp/backup", shell=True)  # P-05 R-ERR-005


def add_tag(tag, tags=[]):
    """يضيف وسمًا إلى قائمة الوسوم."""
    tags.append(tag)
    return tags


def parse_amount(text):
    """يحوّل النص إلى عدد عشري."""
    assert text is not None, "النص مطلوب"  # P-06 R-ERR-007
    return float(text)


def fetch_status(items):
    """يرجع أول عنصر مع تنظيف في النهاية."""
    try:
        return items[0]
    finally:
        return None  # P-07 R-ERR-008


def handle(payload):
    """يحوّل الحمولة إلى عدد مع قيمة افتراضية."""
    try:
        return int(payload)
    except Exception:  # P-08 R-ERR-009
        return 0


def hard_exit(payload):
    """يحوّل الحمولة إلى عدد مع قيمة سالبة عند الفشل."""
    try:
        return int(payload)
    except BaseException:  # P-09 R-ERR-010
        return -1
