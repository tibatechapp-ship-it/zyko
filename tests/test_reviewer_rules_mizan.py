"""اختبارات موجة ميزان — القواعد الأمنية الجديدة R-SEC-109…119 + taint.

لكل قاعدة جديدة حالتان على الأقل: إيجابية (تلتقط نمطها) وسلبية (لا تكذب
على الشيفرة السليمة المجاورة له). الحمايات السلبية هنا ليست اختراعات:
كل واحدة منها إصلاح إنذار كاذب قِيس ميدانيًا في حملة ميزان على 50
مستودعًا حقيقيًا (v0.14.0) — نقلناه كما نُقلت القاعدة نفسها.

يشمل أيضًا اختبارات محرك تدفق البيانات (taint.py) بوصفه وحدة قائمة
بذاتها: المصادر، الانتشار حتى الثبات، وحتمية النتيجة.
"""

from __future__ import annotations

import ast
import textwrap

from zyko.reviewer import RULES, RULES_BY_ID, ReviewEngine, taint
from zyko.reviewer.rules import RULES as _RULES

ENGINE = ReviewEngine()

# القواعد الجديدة في موجة ميزان — الهوية والخطورة كما نُقلت من ميزان.
MIZAN_WAVE_IDS = tuple(f"R-SEC-{n}" for n in range(109, 120))


def hits(source: str, rule_id: str) -> list:
    result = ENGINE.review_source(textwrap.dedent(source).lstrip("\n"))
    return [f for f in result.findings if f.rule_id == rule_id]


# ------------------------------------------------------------- اختبارات السجل
def test_mizan_wave_rules_registered():
    for rid in MIZAN_WAVE_IDS:
        assert rid in RULES_BY_ID, rid


def test_total_rules_is_38():
    assert len(_RULES) == 38


def test_mizan_wave_ids_sequential_no_gaps():
    nums = sorted(int(r.rule_id.split("-")[2]) for r in RULES if r.rule_id.startswith("R-SEC-1"))
    assert nums == list(range(101, 120))


def test_mizan_wave_all_security_category():
    for rid in MIZAN_WAVE_IDS:
        assert RULES_BY_ID[rid].category == "security", rid


def test_mizan_wave_severities_match_mizan():
    expected = {
        "R-SEC-109": "medium",
        "R-SEC-110": "high",
        "R-SEC-111": "low",
        "R-SEC-112": "high",
        "R-SEC-113": "high",
        "R-SEC-114": "high",
        "R-SEC-115": "medium",
        "R-SEC-116": "high",
        "R-SEC-117": "low",
        "R-SEC-118": "high",
        "R-SEC-119": "high",
    }
    for rid, sev in expected.items():
        assert RULES_BY_ID[rid].severity == sev, rid


# ------------------------------------------------- محرك تدفق البيانات (taint)
def test_taint_is_input_source_detects_input_and_argv():
    tree = ast.parse("x = input()\ny = sys.argv[1]\nz = 5\n")
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)]
    by_target = {t.targets[0].id: t.value for t in calls}
    assert taint.is_input_source(by_target["x"])
    assert taint.is_input_source(by_target["y"])
    assert not taint.is_input_source(by_target["z"])


def test_taint_is_request_source_shape():
    assert taint.is_request_source(ast.parse("request.args.get('q')").body[0].value)
    assert taint.is_request_source(ast.parse("request.form['k']").body[0].value)
    assert taint.is_request_source(ast.parse("request.headers['X']").body[0].value)
    # request.method ليس مصدر بيانات — ميزان: الخاصية يجب أن تكون من بيانات العميل
    assert not taint.is_request_source(ast.parse("request.method").body[0].value)
    assert not taint.is_request_source(ast.parse("form").body[0].value)


def test_taint_propagate_fixpoint_through_chain():
    tree = ast.parse("a = input()\nb = a.strip()\nc = f'{b}/x'\nd = 1\n")
    tainted = taint.propagate(tree, taint.is_input_source)
    assert tainted == {"a", "b", "c"}


def test_taint_propagate_is_deterministic():
    src = "a = input()\nb = a\nc = b.upper()\nd = str(c)\n"
    one = taint.propagate(ast.parse(src), taint.is_input_source)
    two = taint.propagate(ast.parse(src), taint.is_input_source)
    assert one == two


def test_taint_propagate_for_target_and_augassign():
    tree = ast.parse(
        "raw = sys.argv\nfor chunk in raw:\n    part = chunk\nacc = ''\nacc += a_placeholder\n"
    )
    tainted = taint.propagate(tree, taint.is_input_source)
    assert "raw" in tainted and "chunk" in tainted and "part" in tainted
    assert "acc" not in tainted


# -------------------------------------------------- R-SEC-109 اجتياز المسارات
def test_sec109_fires_on_input_to_open():
    found = hits(
        """
        def read():
            path = input("المسار: ")
            return open(path)
        """,
        "R-SEC-109",
    )
    assert len(found) == 1 and found[0].line == 3


def test_sec109_fires_on_argv_chain():
    found = hits(
        """
        import sys
        name = sys.argv[1]
        full = f"data/{name}"
        fh = open(full)
        """,
        "R-SEC-109",
    )
    assert len(found) == 1 and found[0].line == 4


def test_sec109_silent_on_constant_path():
    assert not hits("fh = open('config.json')\n", "R-SEC-109")


def test_sec109_silent_on_method_open():
    # open كدالة على كائن (Path.open) ليست المدمجة open — ميزان: مؤهلة فقط
    assert not hits("fh = p.open('r')\n", "R-SEC-109")


# ------------------------------------------------- R-SEC-110 سياق SSL غير موثوق
def test_sec110_fires_on_qualified_call():
    found = hits(
        """
        import ssl
        ctx = ssl._create_unverified_context()
        """,
        "R-SEC-110",
    )
    assert len(found) == 1 and found[0].line == 2


def test_sec110_fires_on_bare_imported_call():
    found = hits(
        """
        from ssl import _create_unverified_context
        ctx = _create_unverified_context()
        """,
        "R-SEC-110",
    )
    assert len(found) == 1 and found[0].line == 2


def test_sec110_silent_on_default_context():
    assert not hits(
        """
        import ssl
        ctx = ssl.create_default_context()
        """,
        "R-SEC-110",
    )


# ------------------------------------------------- R-SEC-111 طلب بلا مهلة
def test_sec111_fires_on_requests_get_without_timeout():
    found = hits(
        """
        import requests
        r = requests.get("https://example.com")
        """,
        "R-SEC-111",
    )
    assert len(found) == 1 and found[0].line == 2


def test_sec111_covers_all_verbs():
    src = """
        import requests
        requests.post(u, json=x)
        requests.put(u)
        requests.delete(u)
        requests.head(u)
        requests.options(u)
        """
    found = hits(src, "R-SEC-111")
    assert len(found) == 5


def test_sec111_silent_with_timeout_kw():
    assert not hits(
        """
        import requests
        r = requests.get("https://example.com", timeout=5)
        """,
        "R-SEC-111",
    )


def test_sec111_silent_on_sessions_and_other_clients():
    # انحراف موثق عن Bandit: مستقبلات الجلسات خارج النطاق (ميزان v0.13.0)
    src = """
        import requests
        import httpx
        s = make_session()
        s.get(u)
        httpx.get(u)
        """
    assert not hits(src, "R-SEC-111")


# ------------------------------------------------- R-SEC-112 torch.load
def test_sec112_fires_on_bare_torch_load():
    found = hits(
        """
        import torch
        model = torch.load("ckpt.pt")
        """,
        "R-SEC-112",
    )
    assert len(found) == 1 and found[0].line == 2


def test_sec112_silent_with_weights_only_true():
    assert not hits(
        """
        import torch
        model = torch.load("ckpt.pt", weights_only=True)
        """,
        "R-SEC-112",
    )


def test_sec112_silent_on_other_loaders():
    assert not hits(
        """
        import json
        data = json.load(fh)
        """,
        "R-SEC-112",
    )


# ------------------------------------------------- R-SEC-113 trust_remote_code
def test_sec113_fires_on_true():
    found = hits(
        """
        def load(name):
            return from_pretrained(name, trust_remote_code=True)
        """,
        "R-SEC-113",
    )
    assert len(found) == 1 and found[0].line == 2


def test_sec113_silent_on_false():
    assert not hits(
        """
        def load(name):
            return from_pretrained(name, trust_remote_code=False)
        """,
        "R-SEC-113",
    )


# ------------------------------------------------- R-SEC-114 autoescape=False
def test_sec114_fires_on_false():
    found = hits(
        """
        def make():
            import jinja2
            return jinja2.Environment(autoescape=False)
        """,
        "R-SEC-114",
    )
    assert len(found) == 1 and found[0].line == 3


def test_sec114_silent_on_true():
    assert not hits(
        """
        def make():
            import jinja2
            return jinja2.Environment(autoescape=True)
        """,
        "R-SEC-114",
    )


# ------------------------------------------------- R-SEC-115 mark_safe
def test_sec115_fires_on_bare_and_qualified():
    src = """
        from django.utils.safestring import mark_safe
        a = mark_safe(body)
        b = formats.mark_safe(body)
        """
    found = hits(src, "R-SEC-115")
    assert {f.line for f in found} == {2, 3}


def test_sec115_silent_on_escape():
    assert not hits(
        "from html import escape\nsafe = escape(body)\n",
        "R-SEC-115",
    )


# ------------------------------------------------- R-SEC-116 extractall
def test_sec116_fires_on_unguarded_tarfile():
    found = hits(
        """
        import tarfile
        def extract(path):
            with tarfile.open(path) as tar:
                tar.extractall()
        """,
        "R-SEC-116",
    )
    assert len(found) == 1 and found[0].line == 4


def test_sec116_silent_with_pep706_filter():
    assert not hits(
        """
        import tarfile
        with tarfile.open(p) as tar:
            tar.extractall(filter="data")
        """,
        "R-SEC-116",
    )


def test_sec116_zipfile_carve_out_with_binding():
    # ميزان: اجتياز symlink خاص بـ tar لا ينطبق على zip — قياس ميداني
    assert not hits(
        """
        import zipfile
        with zipfile.ZipFile(p) as zf:
            zf.extractall()
        """,
        "R-SEC-116",
    )


def test_sec116_zipfile_carve_out_direct_call_and_assign():
    src = """
        import zipfile
        z = zipfile.ZipFile(p)
        z.extractall()
        zipfile.ZipFile(q).extractall()
        """
    assert not hits(src, "R-SEC-116")


# ------------------------------------------------- R-SEC-117 مسار /tmp مصمت
def test_sec117_fires_on_call_arg_and_assign():
    src = """
        open("/tmp/scratch.txt", "w")
        p = "/var/tmp/cache.bin"
        """
    found = hits(src, "R-SEC-117")
    assert {f.line for f in found} == {1, 2}


def test_sec117_fires_inside_list_literal():
    found = hits(
        'dirs = ["/opt/app", "/tmp/stage"]\n',
        "R-SEC-117",
    )
    assert len(found) == 1 and found[0].line == 1


def test_sec117_silent_on_tempfile_and_docs():
    # انحراف دقة موثق: نصوص التوثيق ليست مواضع قيم — ميزان v0.13.0
    src = '''
        """يستخدم مجلد /tmp داخليًا."""
        import tempfile
        d = tempfile.mkdtemp()
        '''
    assert not hits(src, "R-SEC-117")


# ------------------------------------------------- R-SEC-118 إدخال إلى عملية
def test_sec118_fires_on_input_to_subprocess():
    found = hits(
        """
        import subprocess
        cmd = input()
        subprocess.run(cmd, check=False)
        """,
        "R-SEC-118",
    )
    assert len(found) == 1 and found[0].line == 3


def test_sec118_fires_on_argv_to_os_system():
    found = hits(
        """
        import os
        import sys
        target = sys.argv[1]
        os.system(f"ping {target}")
        """,
        "R-SEC-118",
    )
    assert len(found) == 1 and found[0].line == 4


def test_sec118_fires_on_bare_imported_system():
    found = hits(
        """
        from os import system
        host = input()
        system(host)
        """,
        "R-SEC-118",
    )
    assert len(found) == 1 and found[0].line == 3


def test_sec118_silent_on_constant_command():
    assert not hits(
        """
        import subprocess
        subprocess.run(["ls", "-la"], check=False)
        """,
        "R-SEC-118",
    )


# ------------------------------------------------- R-SEC-119 طلب إلى SQL
def test_sec119_fires_on_request_tainted_query():
    found = hits(
        """
        def handler(cursor, request):
            q = request.args.get("q")
            return cursor.execute(q)
        """,
        "R-SEC-119",
    )
    assert len(found) == 1 and found[0].line == 3


def test_sec119_silent_on_parameterized_query():
    # الحماية الميدانية: الاستعلام المعاملات بقيم مرتبة لا يُطلق — ميزان v0.14.0
    assert not hits(
        """
        def handler(cursor, request):
            oid = request.args.get("id")
            return cursor.execute("SELECT * FROM t WHERE id = ?", (oid,))
        """,
        "R-SEC-119",
    )


def test_sec119_no_duplicate_with_sec104_on_dml_fstring():
    # f-string يحوي DML كاملًا يغطيها R-SEC-104 بنيويًا — R-SEC-119 لا يكرر
    src = """
        def handler(cursor, request):
            q = request.args.get("q")
            return cursor.execute(f"SELECT * FROM users WHERE name = '{q}'")
        """
    res = ENGINE.review_source(textwrap.dedent(src).lstrip("\n"))
    ids = {f.rule_id for f in res.findings if f.line == 3}
    assert "R-SEC-104" in ids
    assert "R-SEC-119" not in ids


def test_sec119_covers_dml_free_fstring_that_sec104_misses():
    # f-string بلا DML في جزئه الحرفي لا يغطيه R-SEC-104 — R-SEC-119 يسد الفجوة
    src = """
        def handler(cursor, request):
            q = request.args.get("q")
            return cursor.execute(f"SELECT {q}")
        """
    res = ENGINE.review_source(textwrap.dedent(src).lstrip("\n"))
    ids = {f.rule_id for f in res.findings if f.line == 3}
    assert "R-SEC-119" in ids
    assert "R-SEC-104" not in ids


def test_sec119_silent_on_clean_constant_query():
    assert not hits(
        """
        def run(cursor):
            return cursor.execute("SELECT * FROM orders")
        """,
        "R-SEC-119",
    )


# --------------------------------------------- تعزيز R-SEC-102 بعائلات ميزان
def test_sec102_dill_marshal_shelve_fire():
    src = """
        import dill
        import marshal
        import shelve
        a = dill.loads(blob)
        b = marshal.load(fh)
        c = shelve.open("db")
        """
    found = hits(src, "R-SEC-102")
    assert {f.line for f in found} == {4, 5, 6}


def test_sec102_cpickle_still_fires():
    found = hits(
        """
        import cPickle
        obj = cPickle.load(fh)
        """,
        "R-SEC-102",
    )
    assert len(found) == 1


def test_sec102_silent_on_json():
    assert not hits(
        """
        import json
        data = json.load(fh)
        """,
        "R-SEC-102",
    )


# --------------------------------------------------- الحتمية والثبات الشامل
def test_mizan_wave_determinism_bytewise():
    src = """
        import os
        import requests
        import subprocess

        cmd = input()
        subprocess.run(cmd)
        r = requests.get("https://example.com")
        p = "/tmp/x"
        """
    first = ENGINE.review_source(textwrap.dedent(src))
    second = ENGINE.review_source(textwrap.dedent(src))
    assert [f.to_dict() for f in first.findings] == [f.to_dict() for f in second.findings]
    mizan_hits = {f.rule_id for f in first.findings}
    assert {"R-SEC-111", "R-SEC-117", "R-SEC-118"} <= mizan_hits


def test_mizan_wave_rules_never_crash_on_hostile_input():
    # روح G4: القواعد الجديدة لا تُسقط المحرك على مدخلات عدائية
    hostile = [
        "",
        "def broken(:\n",
        "x = input()\n" * 200,
        "import requests\nrequests.get(u)\n" * 50,
        "a = request.args\nb = a\nc = b\nd = c\nopen(d)\n",
    ]
    for src in hostile:
        result = ENGINE.review_source(src)
        assert result.parse_error is not None or result.score in range(0, 101)
