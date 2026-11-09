"""اختبارات سجل القواعد — لكل قاعدة اختبار إيجابي (تلتقط) وسلبي (لا تكذب).

هذه هي الحصينة الأولى ضد «مراجع يخترع المشكلات»: كل قاعدة يجب أن تثبت
أنها تلتقط نمطها بدقة، وأنها صامتة أمام الشيفرة السليمة المجاورة له.
"""

from __future__ import annotations

import re
import textwrap

from zyko.reviewer import CATEGORIES, RULES, RULES_BY_ID, SEVERITIES, ReviewEngine
from zyko.reviewer.rules import (
    CATEGORY_AR,
    SEVERITY_AR,
    SEVERITY_WEIGHT,
    RuleConfig,
)

ENGINE = ReviewEngine()


def hits(source: str, rule_id: str) -> list:
    result = ENGINE.review_source(textwrap.dedent(source))
    return [f for f in result.findings if f.rule_id == rule_id]


# ------------------------------------------------------------- اختبارات السجل
def test_registry_ids_unique():
    ids = [r.rule_id for r in RULES]
    assert len(ids) == len(set(ids))


def test_registry_ids_follow_pattern():
    for r in RULES:
        assert re.fullmatch(r"R-(ERR|SEC|QLT)-\d{3}", r.rule_id), r.rule_id


def test_registry_groups_in_order():
    prefixes = [r.rule_id.split("-")[1] for r in RULES]
    assert prefixes == sorted(prefixes, key=["ERR", "SEC", "QLT"].index)


def test_registry_severities_valid():
    for r in RULES:
        assert r.severity in SEVERITIES


def test_registry_categories_valid():
    for r in RULES:
        assert r.category in CATEGORIES
        assert r.category in CATEGORY_AR


def test_registry_messages_and_suggestions_arabic():
    for r in RULES:
        assert len(r.message_ar) >= 15, r.rule_id
        assert len(r.suggestion_ar) >= 10, r.rule_id
        assert any("\u0600" <= ch <= "\u06ff" for ch in r.message_ar), r.rule_id


def test_severity_tables_cover_all():
    assert set(SEVERITY_AR) == set(SEVERITIES)
    assert set(SEVERITY_WEIGHT) == set(SEVERITIES)
    assert SEVERITY_WEIGHT["info"] == 0
    assert SEVERITY_WEIGHT["critical"] > SEVERITY_WEIGHT["high"] > SEVERITY_WEIGHT["medium"]


def test_rule_config_defaults():
    cfg = RuleConfig()
    assert (cfg.max_func_lines, cfg.max_depth, cfg.max_args) == (50, 4, 6)


# ------------------------------------------------- معالجة الأخطاء (R-ERR-001..010)
def test_err001_bare_except_positive():
    src = """
    try:
        x = 1
    except:
        pass
    """
    assert len(hits(src, "R-ERR-001")) == 1


def test_err001_bare_except_negative():
    src = """
    try:
        x = 1
    except ValueError:
        pass
    """
    assert hits(src, "R-ERR-001") == []


def test_err002_swallowed_positive():
    src = """
    try:
        x = 1
    except ValueError:
        pass
    """
    assert len(hits(src, "R-ERR-002")) == 1


def test_err002_swallowed_negative_logs():
    src = """
    try:
        x = 1
    except ValueError as exc:
        print("فشل", exc)
    """
    assert hits(src, "R-ERR-002") == []


def test_err003_raise_without_from_positive():
    src = """
    try:
        x = 1
    except ValueError:
        raise RuntimeError("فشل")
    """
    found = hits(src, "R-ERR-003")
    assert len(found) == 1
    assert found[0].detail_ar == "RuntimeError"


def test_err003_raise_with_from_negative():
    src = """
    try:
        x = 1
    except ValueError as exc:
        raise RuntimeError("فشل") from exc
    """
    assert hits(src, "R-ERR-003") == []


def test_err003_nested_function_inside_handler_ignored():
    src = """
    def outer():
        try:
            x = 1
        except ValueError:
            def helper():
                raise RuntimeError("داخلي")
            return helper
    """
    assert hits(src, "R-ERR-003") == []


def test_err004_open_outside_with_positive():
    assert len(hits("data = open('x.txt').read()", "R-ERR-004")) == 1


def test_err004_open_inside_with_negative():
    src = """
    with open('a.txt') as fh:
        other = open('b.txt')
    """
    assert hits(src, "R-ERR-004") == []


def test_err005_shell_true_positive():
    src = """
    import subprocess
    subprocess.run("ls -la", shell=True)
    """
    found = hits(src, "R-ERR-005")
    assert len(found) == 1
    assert found[0].severity == "critical"


def test_err005_shell_false_negative():
    src = """
    import subprocess
    subprocess.run(["ls", "-la"], shell=False)
    """
    assert hits(src, "R-ERR-005") == []


def test_err006_mutable_default_positive():
    for src in ("def f(a=[]): pass", "def f(a={}): pass", "def f(a=set()): pass"):
        assert len(hits(src, "R-ERR-006")) == 1, src


def test_err006_immutable_default_negative():
    assert hits("def f(a=None, b=0, c='x'): pass", "R-ERR-006") == []


def test_err007_assert_positive():
    assert len(hits("def check(v):\n    assert v > 0\n    return v", "R-ERR-007")) == 1


def test_err007_explicit_raise_negative():
    assert (
        hits(
            "def check(v):\n    if v <= 0:\n        raise ValueError(v)\n    return v", "R-ERR-007"
        )
        == []
    )


def test_err008_return_in_finally_positive():
    src = """
    def f(items):
        try:
            return items[0]
        finally:
            return None
    """
    assert len(hits(src, "R-ERR-008")) == 1


def test_err008_cleanup_only_finally_negative():
    src = """
    def f(items, log):
        try:
            return items[0]
        finally:
            log("انتهى")
    """
    assert hits(src, "R-ERR-008") == []


def test_err009_broad_exception_positive():
    src = """
    def f(payload):
        try:
            return int(payload)
        except Exception:
            return 0
    """
    assert len(hits(src, "R-ERR-009")) == 1


def test_err009_specific_negative():
    src = """
    def f(payload):
        try:
            return int(payload)
        except ValueError:
            return 0
    """
    assert hits(src, "R-ERR-009") == []


def test_err010_base_exception_positive():
    found = hits("try:\n    x = 1\nexcept BaseException:\n    raise", "R-ERR-010")
    assert len(found) == 1
    assert found[0].severity == "high"


# ------------------------------------------------------- الأمن (R-SEC-101..108)
def test_sec101_eval_positive():
    found = hits("def f(expr):\n    return eval(expr)", "R-SEC-101")
    assert len(found) == 1
    assert found[0].detail_ar == "eval"
    assert found[0].severity == "critical"


def test_sec101_exec_positive():
    assert len(hits("def f(code):\n    exec(code)", "R-SEC-101")) == 1


def test_sec101_literal_eval_negative():
    assert hits("from ast import literal_eval\nliteral_eval('[1]')", "R-SEC-101") == []


def test_sec102_pickle_positive():
    assert len(hits("import pickle\npickle.loads(blob)", "R-SEC-102")) == 1


def test_sec102_pickle_direct_import_positive():
    src = """
    from pickle import loads
    data = loads(blob)
    """
    assert len(hits(src, "R-SEC-102")) == 1


def test_sec102_json_negative():
    src = """
    import json
    data = json.loads(blob)
    """
    assert hits(src, "R-SEC-102") == []


def test_sec103_yaml_load_unsafe_positive():
    assert len(hits("import yaml\nyaml.load(fh)", "R-SEC-103")) == 1


def test_sec103_yaml_full_load_positive():
    assert len(hits("import yaml\nyaml.full_load(fh)", "R-SEC-103")) == 1


def test_sec103_yaml_safe_loader_negative():
    src = """
    import yaml
    data = yaml.load(fh, Loader=yaml.SafeLoader)
    """
    assert hits(src, "R-SEC-103") == []


def test_sec103_yaml_safe_load_negative():
    assert hits("import yaml\ndata = yaml.safe_load(fh)", "R-SEC-103") == []


def test_sec104_sql_fstring_positive():
    src = "def q(name):\n    return f\"SELECT * FROM users WHERE name = '{name}'\""
    assert len(hits(src, "R-SEC-104")) == 1


def test_sec104_sql_percent_positive():
    src = 'def q(t):\n    return "DELETE FROM %s" % (t,)'
    assert len(hits(src, "R-SEC-104")) == 1


def test_sec104_static_query_negative():
    assert hits('QUERY = "SELECT id FROM users WHERE active = 1"', "R-SEC-104") == []


def test_sec104_non_sql_fstring_negative():
    assert hits('def g(name):\n    return f"مرحبًا {name}"', "R-SEC-104") == []


def test_sec105_hardcoded_password_positive():
    src = "ADMIN_PASSWORD = 'hunter2hunter2'"
    found = hits(src, "R-SEC-105")
    assert len(found) == 1
    assert found[0].detail_ar == "ADMIN_PASSWORD"


def test_sec105_hardcoded_api_key_keyword_positive():
    src = "def connect():\n    return client(api_key='kj29dj38dj38dj')"
    assert len(hits(src, "R-SEC-105")) == 1


def test_sec105_env_read_negative():

    src = "import os\nPASSWORD = os.environ['APP_PASSWORD']"
    assert hits(src, "R-SEC-105") == []


def test_sec105_short_value_negative():
    assert hits("TOKEN = 'abc'", "R-SEC-105") == []


def test_sec106_weak_hash_positive():
    found = hits("import hashlib\nhashlib.md5(b'x')", "R-SEC-106")
    assert len(found) == 1
    assert found[0].severity == "medium"


def test_sec106_sha256_negative():
    src = """
    import hashlib
    digest = hashlib.sha256(b'x')
    """
    assert hits(src, "R-SEC-106") == []


def test_sec107_verify_false_positive():
    assert len(hits("import requests\nrequests.get(url, verify=False)", "R-SEC-107")) == 1


def test_sec107_assignment_form_positive():
    src = """
    session = make_session()
    session.verify = False
    """
    assert len(hits(src, "R-SEC-107")) == 1


def test_sec107_verify_true_negative():
    assert hits("import requests\nrequests.get(url, verify=True)", "R-SEC-107") == []


def test_sec108_os_system_positive():
    found = hits("import os\nos.system('ls')", "R-SEC-108")
    assert len(found) == 1
    assert found[0].severity == "critical"


def test_sec108_subprocess_negative():
    src = """
    import subprocess
    subprocess.run(['ls'])
    """
    assert hits(src, "R-SEC-108") == []


# ----------------------------------------------------- الجودة (R-QLT-201..209)
def _long_body(n: int) -> str:
    lines = ["def long_func():", '    """دالة طويلة."""', "    acc = 0"]
    lines += [f"    acc += {i}" for i in range(1, n + 1)]
    lines.append("    return acc")
    return "\n".join(lines)


def test_qlt201_long_function_positive():
    assert len(hits(_long_body(52), "R-QLT-201")) == 1


def test_qlt201_short_function_negative():
    assert hits(_long_body(30), "R-QLT-201") == []


def test_qlt201_config_override():
    engine = ReviewEngine(RuleConfig(max_func_lines=10))
    result = engine.review_source(_long_body(12))
    assert any(f.rule_id == "R-QLT-201" for f in result.findings)


def test_qlt202_deep_nesting_positive():
    src = """
    def decide(x):
        if x > 0:
            if x > 1:
                if x > 2:
                    if x > 3:
                        if x > 4:
                            return x
        return 0
    """
    assert len(hits(src, "R-QLT-202")) == 1


def test_qlt202_acceptable_depth_negative():
    src = """
    def decide(x):
        if x > 0:
            if x > 1:
                if x > 2:
                    if x > 3:
                        return x
        return 0
    """
    assert hits(src, "R-QLT-202") == []


def test_qlt203_too_many_args_positive():
    src = "def f(a, b, c, d, e, g, h, i):\n    return a"
    assert len(hits(src, "R-QLT-203")) == 1


def test_qlt203_six_args_negative():
    assert hits("def f(a, b, c, d, e, g):\n    return a", "R-QLT-203") == []


def test_qlt203_self_excluded():
    src = """
    class A:
        def m(self, a, b, c, d, e, g):
            return a
    """
    assert hits(src, "R-QLT-203") == []


def test_qlt204_missing_docstring_function_positive():
    assert len(hits("def public_api():\n    return 1", "R-QLT-204")) == 1


def test_qlt204_missing_docstring_class_positive():
    found = hits("class Widget:\n    def make(self):\n        return 1", "R-QLT-204")
    assert len(found) == 2  # الصنف والمنهية كلاهما بلا docstring
    assert any(f.line == 1 for f in found)  # والصنف مُرسّى عند سطره


def test_qlt204_documented_negative():
    src = """
    def public_api():
        \"\"\"واجهة موثقة.\"\"\"
        return 1
    """
    assert hits(src, "R-QLT-204") == []


def test_qlt204_private_skipped():
    assert hits("def _internal():\n    return 1", "R-QLT-204") == []


def test_qlt205_no_type_hints_positive():
    src = """
    def clean(text):
        \"\"\"ينظف النص.\"\"\"
        return text.strip()
    """
    found = hits(src, "R-QLT-205")
    assert len(found) == 1
    assert found[0].severity == "info"


def test_qlt205_annotated_negative():
    src = """
    def clean(text: str) -> str:
        \"\"\"ينظف النص.\"\"\"
        return text.strip()
    """
    assert hits(src, "R-QLT-205") == []


def test_qlt206_none_compare_positive():
    assert len(hits("def f(x):\n    return x == None", "R-QLT-206")) == 1


def test_qlt206_is_none_negative():
    assert hits("def f(x):\n    return x is None", "R-QLT-206") == []


def test_qlt207_unused_import_positive():
    assert len(hits("import os\nVALUE = 1", "R-QLT-207")) == 1


def test_qlt207_used_import_negative():
    assert hits("import os\nPLATFORM = os.sep", "R-QLT-207") == []


def test_qlt207_future_import_negative():
    assert hits("from __future__ import annotations\nX = 1", "R-QLT-207") == []


def test_qlt207_reexport_via_all_negative():
    src = """
    from json import loads
    __all__ = ['loads']
    """
    assert hits(src, "R-QLT-207") == []


def test_qlt208_builtin_shadow_assignment_positive():
    found = hits("list = [1, 2]", "R-QLT-208")
    assert len(found) == 1
    assert found[0].detail_ar == "list"


def test_qlt208_builtin_shadow_parameter_positive():
    assert len(hits("def f(dict):\n    return dict", "R-QLT-208")) == 1


def test_qlt208_normal_names_negative():
    assert hits("items = [1]\nindex = 0", "R-QLT-208") == []


def test_qlt209_lambda_assign_positive():
    assert len(hits("square = lambda x: x * x", "R-QLT-209")) == 1


def test_qlt209_def_negative():
    src = """
    def square(x):
        return x * x
    """
    assert hits(src, "R-QLT-209") == []


# ------------------------------------------------------- عقود هيكلية إضافية
def test_finding_col_is_one_based():
    result = ENGINE.review_source("value = eval('1')")
    assert result.findings[0].col == 8  # الحقل الخام صفري الارتكاز («e» في eval)
    assert result.findings[0].to_dict()["col"] == 9  # والمخرجات للبشر تبدأ من 1


def test_every_rule_in_registry_has_id_prefix_mapping():
    for r in RULES:
        category_from_id = {"ERR": "error_handling", "SEC": "security", "QLT": "quality"}
        assert r.category == category_from_id[r.rule_id.split("-")[1]]
    assert len(RULES) == len(RULES_BY_ID)
