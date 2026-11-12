"""zyko.benchmarks.repair — معمل الإصلاح المحلي: كود أجنبي معطوب يُكشف ويُصلَح ويُقاس.

الـ Gauntlet يقيس **التوليد** (ما يبنيه المصنع من قوالبنا)، وهذه الوحدة
تقيس **الصيانة**: وحدات بايثون أجنبية واقعية — ليست من قوالب المصنع —
بُذرت فيها أعطال موثقة بتصنيف القواعد الـ38 نفسه، ثم يُقاس مستوى zyko
في البرمجة على ثلاث فئات صادقة:

1. **فئة السلوك (behavioral)** — عطل يغيّر سلوك الكود فعلاً (تسريب حالة،
   ابتلاع استثناء أساسي، كسر سلسلة الأسباب، مقارنة None الخاطئة، حمولة
   YAML غير آمنة). الاختبارات الخفية مكتوبة لـ*النية*: تفشل على الكود
   المعطوب وتمر بعد الإصلاح — هذا هو مقياس SWE-bench المحلي الحرفي.
2. **فئة الجودة (quality)** — عيب لا يغيّر السلوك (مورد يتسرب، استيراد
   ميت، lambda على اسم، هاش ضعيف، docstrings مفقودة). الاختبارات تمر
   قبل وبعد؛ القياس: هل يُكشف العيب ويُصلَح آليًا دون كسر السلوك؟
3. **الفئة اليدوية (manual)** — أعطال تستحق إصلاحًا بشرًا (eval، حقن
   SQL، سر مصمت، return في finally). القياس الصادق هنا **الكشف** لا
   الإصلاح: المحرك يعترف بحدوده ويعيد الإصلاح المقترح العربي.

القواعد الصارمة كما في المستودع كله:
- **حتمية بالبايت (P6)** — نفس الكوربوس ⇒ نفس الإيصال بالبايت؛ الأزمنة
  خارج الإيصال إلا بطلب صريح.
- **اختبارات حقيقية معزولة** — كل حالة تُبنى على القرص وتُشغَّل باختباراتها
  عبر ``zyko.sandbox.runner.run_tests``: argv قائمة، بيئة بيضاء بلا أسرار،
  مهلة مسقوفة، وحصر كتابة نواتي (Landlock) حيث تتيح النواة — ومستوى
  العزل الفعلي يُعلن في الإيصال لا يُفترض.
- **فشل صادق** — أي حالة لا تطابق توقع فئتها تعود صفًا فاشلاً بمشكلة
  عربية صريحة؛ لا يُخفى ولا يُعتذر عنه.

حدا الصدق الموثقان:
- الكوربوس كود أجنبي *بُذرت فيه* أعطال من تصنيفنا — ليست SWE-bench
  العامة؛ الدليل القياسي العام مسار آخر موثق في EVAL.
- الإصلاح السلوكي خارج القواعد الـ12 الآلية يحتاج نموذجاً لغوياً —
  فئة اليدوية هنا تقيس الكشف، وعقل السلوك الكامل (جولة 8 المخططة)
  هو الذي سيرفع هذه الفئة لاحقاً.

    from zyko.benchmarks.repair import run_repair_lab

    report = run_repair_lab()
    assert report.behavior_preserved and report.detection_rate >= 0.9
    print(report.table_ar())

على سطر الأوامر: ``zyko repair-lab`` (لاحقًا) أو عبر الوحدة مباشرة.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zyko.fixer.engine import FixerEngine
from zyko.reviewer.engine import ReviewEngine
from zyko.sandbox.contracts import PermissionContract
from zyko.sandbox.jail import jail_level
from zyko.sandbox.runner import TestRunResult, run_tests

__all__ = [
    "CATEGORIES",
    "CORPUS",
    "RepairCase",
    "RepairReport",
    "RepairRow",
    "run_case",
    "run_repair_lab",
]

# --------------------------------------------------------------- الفئات الثلاث
CATEGORY_BEHAVIORAL = "behavioral"
CATEGORY_QUALITY = "quality"
CATEGORY_MANUAL = "manual"

CATEGORIES: tuple[str, ...] = (CATEGORY_BEHAVIORAL, CATEGORY_QUALITY, CATEGORY_MANUAL)

CATEGORY_AR: dict[str, str] = {
    CATEGORY_BEHAVIORAL: "سلوكي — يُصلَح آلياً والاختبارات تنعكس",
    CATEGORY_QUALITY: "جودة — يُصلَح آلياً دون كسر السلوك",
    CATEGORY_MANUAL: "يدوي — يُكشف ويُقترح، الإصلاح بشر",
}

_TEST_TIMEOUT_S = 30.0


# --------------------------------------------------------------- الكوربوس
@dataclass(frozen=True)
class RepairCase:
    """حالة إصلاح واحدة: وحدة أجنبية معطوبة + اختبارات نية + حقائق مرجعية.

    ``seeded``: أزواج (معرّف القاعدة، عدد البذور المتوقعة) — الحقيقة
    المرجعية المرتبة التي يقاس عليها الكشف والإصلاح.
    """

    name: str
    category: str
    module_name: str
    source: str
    tests: str
    seeded: tuple[tuple[str, int], ...]
    note_ar: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "module_name": self.module_name,
            "seeded": [list(pair) for pair in self.seeded],
            "note_ar": self.note_ar,
        }


# ---- فئة أ: أعطال سلوكية تُصلَح آلياً (الاختبارات تفشل قبل وتمر بعد)
_A1_QUEUE = '''"""tasks_queue — قائمة مهام صغيرة (كود أجنبي، علة بُذرت موثقة)."""

def add_task(task, tasks=[]):
    tasks.append(task)
    return tasks


def describe(tasks):
    """وصف موجز لعدد المهام."""
    return f"{len(tasks)} مهمة"
'''

_A1_TESTS = '''from tasks_queue import add_task, describe


def test_single_call():
    assert add_task("مراجعة") == ["مراجعة"]


def test_no_leak_between_calls():
    add_task("أول")
    second = add_task("ثانٍ")
    assert second == ["ثانٍ"]


def test_describe():
    assert describe(["a", "b"]) == "2 مهمة"
'''

_A2_PARSE = '''"""batch_parse — تحويل دفعات بعنصر آمن يبتلع الأعطال العادية."""

class AbortJob(BaseException):
    """إجهاض معالجة الدفعة — لا يُبتلع كخطأ عادي."""


def parse_batch(entries, parser):
    """حوّل كل عنصر، والعناصر الفاسدة تصير None."""
    out = []
    for entry in entries:
        try:
            out.append(parser(entry))
        except:
            out.append(None)
    return out
'''

_A2_TESTS = '''import pytest

from batch_parse import AbortJob, parse_batch


def _parser(value):
    if value == "STOP":
        raise AbortJob()
    if value == "boom":
        raise ValueError("قيمة سيئة")
    return value.upper()


def test_abort_propagates():
    with pytest.raises(AbortJob):
        parse_batch(["A", "STOP"], _parser)


def test_regular_error_swallowed():
    assert parse_batch(["A", "boom"], _parser) == ["A", None]


def test_clean_pass():
    assert parse_batch(["A", "B"], _parser) == ["A", "B"]
'''

_A3_PAYLOAD = '''"""payload_parse — فك حمولة JSON مع رفض موثق للحمولة الفاسدة."""

import json


def parse_payload(text):
    """فك الحمولة أو رفضها باستثناء واضح."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("حمولة غير صالحة")
'''

_A3_TESTS = '''import json

import pytest

from payload_parse import parse_payload


def test_valid_payload():
    assert parse_payload('{"a": 1}') == {"a": 1}


def test_error_chain_preserved():
    with pytest.raises(ValueError) as err:
        parse_payload("{oops")
    assert isinstance(err.value.__cause__, json.JSONDecodeError)
'''

_A4_SCAN = '''"""none_scan — إيجاد أول فراغ None دون مسّ القيم التي ترفض المقارنة."""

class Uncomparable:
    """قيمة ترفض المقارنة أصلاً — __eq__ عندها فخ لا أداة."""

    def __eq__(self, other):
        raise ValueError("هذه القيمة ترفض المقارنة")

    def __ne__(self, other):
        raise ValueError("هذه القيمة ترفض المقارنة")

    def __hash__(self):
        return 1


def find_missing(values):
    """أول فهرس بقيمة None، أو -1."""
    for index, value in enumerate(values):
        if value == None:
            return index
    return -1


def has_gap(values):
    """هل فيها فراغ؟"""
    return find_missing(values) >= 0
'''

_A4_TESTS = '''from none_scan import Uncomparable, find_missing, has_gap


def test_finds_none():
    assert find_missing([1, None, 3]) == 1


def test_no_none():
    assert find_missing([1, 2]) == -1


def test_uncomparable_not_compared():
    assert find_missing([1, Uncomparable(), 2]) == -1


def test_has_gap():
    assert has_gap([1, None]) is True
    assert has_gap([1]) is False
'''

_A5_SETTINGS = '''"""settings_loader — تحميل إعدادات YAML من نص موثوق المصدر."""

import yaml


def load_settings(text):
    """فك نص الإعدادات إلى قاموس."""
    return yaml.load(text)
'''

_A5_TESTS = '''from settings_loader import load_settings


def test_parses_map():
    assert load_settings("timeout: 30\\nretries: 5") == {"timeout": 30, "retries": 5}


def test_parses_nested():
    data = load_settings("db:\\n  host: localhost\\n  port: 5432")
    assert data["db"]["port"] == 5432
'''

# ---- فئة ب: عيوب جودة تُصلَح آلياً دون كسر السلوك (الاختبارات تمر قبل وبعد)
_B1_READER = '''"""config_reader — قراءة ملف إعدادات نصي."""

def read_config(path):
    """قراءة المحتوى مقصوص الأطراف."""
    f = open(path, "r", encoding="utf-8")
    data = f.read()
    return data.strip()
'''

_B1_TESTS = '''from config_reader import read_config


def test_reads_content(tmp_path):
    target = tmp_path / "app.cfg"
    target.write_text("mode=fast\\n", encoding="utf-8")
    assert read_config(str(target)) == "mode=fast"


def test_second_read(tmp_path):
    target = tmp_path / "app.cfg"
    target.write_text("x=1\\n", encoding="utf-8")
    assert read_config(str(target)) == "x=1"
    assert read_config(str(target)) == "x=1"
'''

_B2_EXPORT = '''"""export_util — تصدير سجلات JSON بترتيب ثابت."""

import os
import json


def dump_record(record):
    """سجل واحد كسطر JSON مفاتيحه مرتبة."""
    return json.dumps(record, sort_keys=True)
'''

_B2_TESTS = '''from export_util import dump_record


def test_sorted_keys():
    assert dump_record({"b": 2, "a": 1}) == '{"a": 1, "b": 2}'


def test_nested():
    assert dump_record({"k": [1, 2]}) == '{"k": [1, 2]}'
'''

_B3_CONVERT = '''"""temp_convert — تحويلات حرارة بسيطة."""

to_celsius = lambda fahrenheit: (fahrenheit - 32) * 5 / 9


def boiling_point():
    """درجة غليان الماء بالمئوية."""
    return to_celsius(212)
'''

_B3_TESTS = '''import pytest

from temp_convert import boiling_point, to_celsius


def test_value():
    assert to_celsius(212) == pytest.approx(100.0)


def test_boiling():
    assert boiling_point() == pytest.approx(100.0)
'''

_B4_DIGEST = '''"""digest_util — بصمات نصية للاستخدام غير الأمني."""

import hashlib


def fingerprint(text):
    """بصمة سداسية عشرية ثابتة للنص."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()
'''

_B4_TESTS = '''import re

from digest_util import fingerprint


def test_hex_digest():
    assert re.fullmatch(r"[0-9a-f]+", fingerprint("hello"))


def test_distinguishes():
    assert fingerprint("hello") != fingerprint("hellp")
'''

_B5_MATH = '''"""math_notes — عمليات حسابية صغيرة بلا توثيق (عيب بُذر عمداً)."""

def add(a, b):
    return a + b


def mul(a, b):
    return a * b


def clamp(value, low, high):
    return max(low, min(high, value))
'''

_B5_TESTS = '''from math_notes import add, clamp, mul


def test_add():
    assert add(2, 3) == 5


def test_mul():
    assert mul(2, 3) == 6


def test_clamp():
    assert clamp(5, 0, 3) == 3
    assert clamp(-1, 0, 3) == 0
'''

# ---- فئة ج: أعطال تستحق إصلاحاً بشراً — القياس الصادق هنا الكشف لا الإصلاح
_C1_EVAL = '''"""calc_eval — حاسبة تعبيرات داخل نطاق متحكم به."""

def evaluate(expr, variables=None):
    """تقييم تعبير حسابي على متغيرات معطاة."""
    env = dict(variables or {})
    return eval(expr, {"__builtins__": {}}, env)
'''

_C1_TESTS = '''from calc_eval import evaluate


def test_arithmetic():
    assert evaluate("a + b", {"a": 2, "b": 3}) == 5


def test_literal():
    assert evaluate("2 * 4") == 8
'''

_C2_SQL = '''"""sql_builder — بناء استعلام مستخدم واحد (نصي لا تنفيذي)."""

def user_query(username):
    """استعلام جلب مستخدم بالاسم."""
    return "SELECT * FROM users WHERE name = '" + username + "'"
'''

_C2_TESTS = '''from sql_builder import user_query


def test_query_shape():
    assert user_query("ali") == "SELECT * FROM users WHERE name = 'ali'"
'''

_C3_TOKEN = (  # nosec B105 — عينة بذر للعابث لا اعتمادية حقيقية
    '''"""auth_token — ترويسة تخويل بمفتاح افتراضي (سر بُذر للفحص)."""

API_KEY = "sk-live-9f2c1a7b4d8e6f0a1b2c3d4e5f6a7b8c"


def auth_header(key=None):
    """ترويسة Bearer بمفتاح صريح أو الافتراضي."""
    return {"Authorization": "Bearer " + (key or API_KEY)}
'''
)

_C3_TESTS = '''from auth_token import API_KEY, auth_header


def test_explicit_key():
    assert auth_header("abc") == {"Authorization": "Bearer abc"}


def test_default_key():
    assert auth_header() == {"Authorization": "Bearer " + API_KEY}
'''

_C4_FINALLY = '''"""finally_guard — قسمة آمنة تُنظف أثرها دائماً."""

def safe_div(a, b):
    """قسمة تعيد None عند الخطأ بدل الانهيار."""
    result = None
    try:
        result = a / b
        return result
    finally:
        return result
'''

_C4_TESTS = '''from finally_guard import safe_div


def test_normal_path():
    assert safe_div(6, 3) == 2.0


def test_fraction():
    assert safe_div(1, 4) == 0.25
'''

CORPUS: tuple[RepairCase, ...] = (
    RepairCase(
        name="mutable_default_queue",
        category=CATEGORY_BEHAVIORAL,
        module_name="tasks_queue.py",
        source=_A1_QUEUE,
        tests=_A1_TESTS,
        seeded=(("R-ERR-006", 1),),
        note_ar="الوسيط الافتراضي [] يتسرب بين النداءات — النداء الثاني يرى مهام الأول",
    ),
    RepairCase(
        name="bare_except_swallows_abort",
        category=CATEGORY_BEHAVIORAL,
        module_name="batch_parse.py",
        source=_A2_PARSE,
        tests=_A2_TESTS,
        seeded=(("R-ERR-001", 1),),
        note_ar="except عارٍ يبتلع AbortJob المشتق من BaseException — الإجهاض يختفي صامتاً",
    ),
    RepairCase(
        name="raise_without_from",
        category=CATEGORY_BEHAVIORAL,
        module_name="payload_parse.py",
        source=_A3_PAYLOAD,
        tests=_A3_TESTS,
        seeded=(("R-ERR-003", 1),),
        note_ar="رفع ValueError دون from يقطع سلسلة الأسباب — أثر JSONDecodeError يضيع",
    ),
    RepairCase(
        name="eq_none_trap",
        category=CATEGORY_BEHAVIORAL,
        module_name="none_scan.py",
        source=_A4_SCAN,
        tests=_A4_TESTS,
        seeded=(("R-QLT-206", 1),),
        note_ar="v == None يستدعي __eq__ على قيمة ترفض المقارنة — انهيار في مسار سليم",
    ),
    RepairCase(
        name="yaml_unsafe_load",
        category=CATEGORY_BEHAVIORAL,
        module_name="settings_loader.py",
        source=_A5_SETTINGS,
        tests=_A5_TESTS,
        seeded=(("R-SEC-103", 1),),
        note_ar="yaml.load بلا Loader آمن — على PyYAML الحديث انهيار، وعلى القديم تنفيذ كائنات",
    ),
    RepairCase(
        name="open_without_with",
        category=CATEGORY_QUALITY,
        module_name="config_reader.py",
        source=_B1_READER,
        tests=_B1_TESTS,
        seeded=(("R-ERR-004", 1),),
        note_ar="ملف يُفتح خارج with — يتسرب عند وقوع خطأ بين الفتح والإغلاق",
    ),
    RepairCase(
        name="unused_import",
        category=CATEGORY_QUALITY,
        module_name="export_util.py",
        source=_B2_EXPORT,
        tests=_B2_TESTS,
        seeded=(("R-QLT-207", 1),),
        note_ar="استيراد os ميت يخفي الاعتماديات الحقيقية",
    ),
    RepairCase(
        name="lambda_assigned_name",
        category=CATEGORY_QUALITY,
        module_name="temp_convert.py",
        source=_B3_CONVERT,
        tests=_B3_TESTS,
        seeded=(("R-QLT-209", 1),),
        note_ar="lambda مسندة لاسم تخالف PEP 8 وتفقد أثر التتبع",
    ),
    RepairCase(
        name="weak_md5_digest",
        category=CATEGORY_QUALITY,
        module_name="digest_util.py",
        source=_B4_DIGEST,
        tests=_B4_TESTS,
        seeded=(("R-SEC-106", 1),),
        note_ar="md5 غير آمن للتوقيع — البصمات هنا تحويل تستحقه خوارزمية أقوى",
    ),
    RepairCase(
        name="missing_docstrings",
        category=CATEGORY_QUALITY,
        module_name="math_notes.py",
        source=_B5_MATH,
        tests=_B5_TESTS,
        seeded=(("R-QLT-204", 3),),
        note_ar="ثلاث دوال عامة بلا docstring — النية مخفية عن القارئ",
    ),
    RepairCase(
        name="eval_on_input",
        category=CATEGORY_MANUAL,
        module_name="calc_eval.py",
        source=_C1_EVAL,
        tests=_C1_TESTS,
        seeded=(("R-SEC-101", 1),),
        note_ar="eval ببنى مضبوطة — الكشف والتوصيل البشري، لا إصلاح آلي مغرٍ للمعنى",
    ),
    RepairCase(
        name="sql_string_concat",
        category=CATEGORY_MANUAL,
        module_name="sql_builder.py",
        source=_C2_SQL,
        tests=_C2_TESTS,
        seeded=(("R-SEC-104", 1),),
        note_ar="دمج نصوص في SQL — الإصلاح الصحيح (مُعامِلات مرتبطة) قرار معمارٍ لا قطعة نص",
    ),
    RepairCase(
        name="hardcoded_secret",
        category=CATEGORY_MANUAL,
        module_name="auth_token.py",
        source=_C3_TOKEN,
        tests=_C3_TESTS,
        seeded=(("R-SEC-105", 1),),
        note_ar="سر مصمت في الشيفرة — إزالته تتطلب تدوير المفتاح وتخزيناً خارجياً",
    ),
    RepairCase(
        name="return_in_finally",
        category=CATEGORY_MANUAL,
        module_name="finally_guard.py",
        source=_C4_FINALLY,
        tests=_C4_TESTS,
        seeded=(("R-ERR-008", 1),),
        note_ar="return في finally يبتلع الاستثناءات الجارية — المسار الطبيعي يمر والأعطال تختفي",
    ),
)


# --------------------------------------------------------------- صف النتيجة
@dataclass(frozen=True)
class RepairRow:
    """نتيجة حالة واحدة — كل حقائقها موثقة، والحكم من فئتها لا من التمني."""

    name: str
    category: str
    note_ar: str
    seeded: tuple[tuple[str, int], ...]
    detected: tuple[str, ...]  # قواعد البذور التي رصدها المراجع
    resolved_rules: tuple[str, ...]  # قواعد البذور التي اختفت بعد الإصلاح
    tests_before_ok: bool
    tests_after_ok: bool
    tests_before_counts: tuple[int, int, int]  # (ناجح، فاشل، أخطاء) — -1 مجهول
    tests_after_counts: tuple[int, int, int]
    score_before: int
    score_after: int
    changed: bool
    idempotent: bool
    resolved: bool
    problems: tuple[str, ...] = field(default=())
    source_sha256: str = ""
    fixed_sha256: str = ""

    @property
    def category_ar(self) -> str:
        return CATEGORY_AR[self.category]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "note_ar": self.note_ar,
            "seeded": [list(pair) for pair in self.seeded],
            "detected": list(self.detected),
            "resolved_rules": list(self.resolved_rules),
            "tests_before_ok": self.tests_before_ok,
            "tests_after_ok": self.tests_after_ok,
            "tests_before_counts": list(self.tests_before_counts),
            "tests_after_counts": list(self.tests_after_counts),
            "score_before": self.score_before,
            "score_after": self.score_after,
            "changed": self.changed,
            "idempotent": self.idempotent,
            "resolved": self.resolved,
            "problems": list(self.problems),
            "source_sha256": self.source_sha256,
            "fixed_sha256": self.fixed_sha256,
        }


def _counts_of(result: TestRunResult) -> tuple[int, int, int]:
    """(ناجح، فاشل، أخطاء) من نتيجة run_tests — المجهول -1 بصدق."""
    return (
        result.passed if result.passed is not None else -1,
        result.failed if result.failed is not None else -1,
        result.errors if result.errors is not None else -1,
    )


def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


# --------------------------------------------------------------- تشغيل حالة
def run_case(case: RepairCase, *, root: Path, timeout_s: float = _TEST_TIMEOUT_S) -> RepairRow:
    """نفّذ حالة واحدة كاملة: فحص ← إصلاح ← اختبارات قبل/بعد ← حكم فئتها.

    كل تشغيل اختبارات يمر عبر ``run_tests`` بعقد صلاحيات محصور بجذر
    الحالة — argv قائمة وبيئة بيضاء وحصر كتابة نواتي حيث تتيح النواة.
    """
    problems: list[str] = []
    case_dir = root / case.name
    case_dir.mkdir(parents=True, exist_ok=True)
    module_path = case_dir / case.module_name
    test_path = case_dir / f"test_{case.module_name}"
    test_file = test_path.name

    module_path.write_text(case.source, encoding="utf-8")
    test_path.write_text(case.tests, encoding="utf-8")

    contract = PermissionContract.for_roots(
        case_dir, allow_run_tests=True, timeout_s=timeout_s
    )
    argv = ["python", "-m", "pytest", "-q", test_file]

    # ---- 1) الاختبارات قبل الإصلاح — الحقيقة المرجعية السلوكية
    before = run_tests(contract, argv=argv, cwd=case_dir)
    tests_before_ok = bool(before.ok)
    counts_before = _counts_of(before)

    # ---- 2) الكشف ثم الإصلاح الحتمي
    reviewer = ReviewEngine()
    fixer = FixerEngine()
    base = reviewer.review_source(case.source, case.module_name)
    if base.parse_error is not None:
        problems.append(f"الكوربوس نفسه لا يُحلَّل: {base.parse_error}")
    fix = fixer.fix_source(case.source, case.module_name)
    fixed_source = fix.fixed_source

    # ---- 3) الاختبارات بعد الإصلاح على الكود المُصلَح فعلاً
    module_path.write_text(fixed_source, encoding="utf-8")
    after = run_tests(contract, argv=argv, cwd=case_dir)
    tests_after_ok = bool(after.ok)
    counts_after = _counts_of(after)

    after_review = reviewer.review_source(fixed_source, case.module_name)

    detected = tuple(rid for rid, _n in case.seeded if any(f.rule_id == rid for f in base.findings))
    resolved_rules = tuple(
        rid for rid, _n in case.seeded if not any(f.rule_id == rid for f in after_review.findings)
    )

    # ---- 4) الاعتدال: تشغيل المصلح على ناتجه ⇒ صفر تغيير
    idempotent = True
    if fix.changed:
        second = fixer.fix_source(fixed_source, case.module_name)
        idempotent = not second.changed

    # ---- 5) حكم الفئة — كل فئة عقد مختلف، لا مقياس واحد جامد
    if case.category == CATEGORY_BEHAVIORAL:
        if tests_before_ok:
            problems.append("الاختبارات نجحت قبل الإصلاح — العلة السلوكية ليست علة؛ الكوربوس فاسد")
        if not tests_after_ok:
            problems.append("الاختبارات لم تمر بعد الإصلاح — العلة باقية أو الإصلاح كسر السلوك")
        if set(resolved_rules) != {rid for rid, _n in case.seeded}:
            problems.append("قاعدة بذر لم تُصلَح آلياً رغم كونها ضمن القواعد الـ12")
        resolved = tests_after_ok and not tests_before_ok and len(resolved_rules) == len(case.seeded)
    elif case.category == CATEGORY_QUALITY:
        if not tests_before_ok:
            problems.append("الاختبارات فشلت قبل الإصلاح — عيب الجودة لا يبرر كسر السلوك؛ الكوربوس فاسد")
        if not tests_after_ok:
            problems.append("الاختبارات لم تمر بعد الإصلاح — الإصلاح كسر السلوك")
        if len(resolved_rules) != len(case.seeded):
            problems.append("قاعدة بذر جودة لم تُصلَح آلياً كاملة")
        if not idempotent:
            problems.append("الإصلاح غير معتدل — تشغيل ثانٍ غيّر النص")
        resolved = (
            tests_before_ok
            and tests_after_ok
            and len(resolved_rules) == len(case.seeded)
            and idempotent
        )
    else:  # CATEGORY_MANUAL — العقد: كشف كامل، اعتراف بالحد، لا مساس بالسلوك
        if set(detected) != {rid for rid, _n in case.seeded}:
            problems.append("قاعدة بذر يدوية لم تُكشف — ثغرة في شبكة الكشف")
        if not tests_before_ok or not tests_after_ok:
            problems.append("الاختبارات فشلت على كود الفئة اليدوية — الكوربوس فاسد")
        resolved = (
            len(detected) == len(case.seeded)
            and tests_before_ok
            and tests_after_ok
        )

    return RepairRow(
        name=case.name,
        category=case.category,
        note_ar=case.note_ar,
        seeded=case.seeded,
        detected=detected,
        resolved_rules=resolved_rules,
        tests_before_ok=tests_before_ok,
        tests_after_ok=tests_after_ok,
        tests_before_counts=counts_before,
        tests_after_counts=counts_after,
        score_before=base.score,
        score_after=after_review.score,
        changed=fix.changed,
        idempotent=idempotent,
        resolved=resolved,
        problems=tuple(problems),
        source_sha256=_sha16(case.source),
        fixed_sha256=_sha16(fixed_source),
    )


# --------------------------------------------------------------- التقرير
@dataclass(frozen=True)
class RepairReport:
    """تقرير معمل الإصلاح — إيصال حتمي بالبايت لكل مستوى الصيانة."""

    rows: tuple[RepairRow, ...]
    isolation_level: str

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def resolved_total(self) -> int:
        return sum(1 for r in self.rows if r.resolved)

    @property
    def total_seeds(self) -> int:
        return sum(n for r in self.rows for _rid, n in r.seeded)

    @property
    def detected_seeds(self) -> int:
        return sum(
            n for r in self.rows for rid, n in r.seeded if rid in r.detected
        )

    @property
    def detection_rate(self) -> float:
        return self.detected_seeds / self.total_seeds if self.total_seeds else 0.0

    def _category_rows(self, category: str) -> tuple[RepairRow, ...]:
        return tuple(r for r in self.rows if r.category == category)

    @property
    def behavior_repair_rate(self) -> float:
        rows = self._category_rows(CATEGORY_BEHAVIORAL)
        return sum(1 for r in rows if r.resolved) / len(rows) if rows else 0.0

    @property
    def quality_repair_rate(self) -> float:
        rows = self._category_rows(CATEGORY_QUALITY)
        return sum(1 for r in rows if r.resolved) / len(rows) if rows else 0.0

    @property
    def manual_detection_rate(self) -> float:
        rows = self._category_rows(CATEGORY_MANUAL)
        return sum(1 for r in rows if r.resolved) / len(rows) if rows else 0.0

    @property
    def behavior_preserved(self) -> bool:
        return all(r.tests_after_ok for r in self.rows)

    @property
    def ok(self) -> bool:
        """القبول: كل الحلول خضراء على فئاتها + لا مشاكل + سلوك محفوظ كلياً."""
        return (
            self.total > 0
            and self.resolved_total == self.total
            and self.behavior_preserved
            and not any(r.problems for r in self.rows)
        )

    @property
    def chain_hash(self) -> str:
        """بصمة السلسلة: sha256 فوق صفوف مرتبة بالاسم — حتمية بالبايت."""
        digest = hashlib.sha256()
        for row in sorted(self.rows, key=lambda r: r.name):
            payload = json.dumps(row.to_dict(), ensure_ascii=False, sort_keys=True)
            digest.update(payload.encode("utf-8"))
            digest.update(b"\x00")
        return digest.hexdigest()

    def to_dict(self, *, include_timing: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": "repair_lab",
            "isolation_level": self.isolation_level,
            "total": self.total,
            "resolved": self.resolved_total,
            "total_seeds": self.total_seeds,
            "detected_seeds": self.detected_seeds,
            "detection_rate": round(self.detection_rate, 4),
            "behavior_repair_rate": round(self.behavior_repair_rate, 4),
            "quality_repair_rate": round(self.quality_repair_rate, 4),
            "manual_detection_rate": round(self.manual_detection_rate, 4),
            "behavior_preserved": self.behavior_preserved,
            "ok": self.ok,
            "chain_hash": self.chain_hash,
            "rows": [r.to_dict() for r in self.rows],
        }
        return payload

    def to_json(self, *, include_timing: bool = False) -> str:
        return json.dumps(
            self.to_dict(include_timing=include_timing),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )

    def table_ar(self) -> str:
        """الجدول العربي — الفئة × الحالة × الكشف × الإصلاح × السلوك."""
        lines = [
            "معمل الإصلاح المحلي — كود أجنبي معطوب يُكشف ويُصلَح ويُقاس",
            f"مستوى العزل الفعلي: {self.isolation_level}",
            "=" * 78,
            f"{'الحالة':24} {'الفئة':11} {'الكشف':>7} {'درجة قبل':>9} {'درجة بعد':>9} {'الحكم':>9}",
            "-" * 78,
        ]
        for row in self.rows:
            cat = {CATEGORY_BEHAVIORAL: "سلوكي", CATEGORY_QUALITY: "جودة", CATEGORY_MANUAL: "يدوي"}[
                row.category
            ]
            detected = f"{len(row.detected)}/{len(row.seeded)}"
            verdict = "✅" if row.resolved else "❌"
            lines.append(
                f"{row.name:24} {cat:11} {detected:>7} {row.score_before:>9} {row.score_after:>9} {verdict:>9}"
            )
        lines.append("-" * 78)
        lines.append(
            f"الإجمالي: {self.resolved_total}/{self.total} حالة ناجحة — "
            f"كشف البذور {self.detected_seeds}/{self.total_seeds} ({self.detection_rate:.0%})"
        )
        lines.append(
            "الفئات: سلوكي "
            f"{self.behavior_repair_rate:.0%} · جودة {self.quality_repair_rate:.0%} · "
            f"يدوي(كشف) {self.manual_detection_rate:.0%}"
        )
        lines.append(f"بصمة السلسلة: {self.chain_hash[:16]}…")
        verdict = (
            "الناتج النهائي: ✅ كل الفئات على عقدها والسلوك محفوظ في كل الحالات"
            if self.ok
            else "الناتج النهائي: ❌ فشل صادق في الأعلى — الأرقام كما هي لا كما نتمنى"
        )
        lines.append(verdict)
        return "\n".join(lines)


# --------------------------------------------------------------- المشغّل
def run_repair_lab(
    *,
    cases: tuple[RepairCase, ...] | None = None,
    timeout_s: float = _TEST_TIMEOUT_S,
    root: Path | None = None,
) -> RepairReport:
    """شغّل معمل الإصلاح كاملاً (أو على عينات) — إيصال حتمي بالبايت.

    ``cases``: افتراضيًا الكوربوس الكامل (14 حالة)؛ للاختبارات والتجارب
    السريعة مرّر عينة حتمية. ``root``: مجلد عمل بديل (افتراضيًا مجلد حرارة).
    """
    selected = cases if cases is not None else CORPUS
    if not selected:
        raise ValueError("الكوربوس فارغ — لا معمل بلا حالات")
    levels: set[str] = set()
    rows: list[RepairRow] = []
    tmp_ctx = tempfile.TemporaryDirectory(prefix="zyko-repair-") if root is None else None
    base_root = Path(tmp_ctx.name) if tmp_ctx is not None else Path(root)  # type: ignore[arg-type]
    try:
        for case in selected:
            rows.append(run_case(case, root=base_root, timeout_s=timeout_s))
            levels.add(jail_level())
        isolation = "+".join(sorted(levels)) if levels else jail_level()
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()
    return RepairReport(rows=tuple(rows), isolation_level=isolation)
