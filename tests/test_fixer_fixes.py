"""اختبارات مسارات الإصلاح الـ12 — لكل قاعدة إيجابٌ حاسم ورفضٌ آمن.

كل اختبار يثبت أحد ثلاثة أمور: (1) الإصلاح ينتج النص المتوقع حرفيًا،
(2) الملاحظة تختفي من إعادة المراجعة، أو (3) المسار يرفض الحالة الغامضة
بأمان ويتركها يدوية/مفتوحة — الرفض الآمن هنا ميزة تُختبر لا قصور.
"""

from __future__ import annotations

import textwrap

from zyko.fixer.engine import FixerEngine
from zyko.fixer.fixes import AUTO_FIXABLE, MANUAL_RULES

ENGINE = FixerEngine()


def fix(source: str, path: str = "<text>"):
    return ENGINE.fix_source(textwrap.dedent(source), path)


def status_of(result, rule_id: str) -> set[str]:
    return {o.status for o in result.outcomes if o.rule_id == rule_id}


# ============================================================ R-ERR-001
def test_bare_except_fixed():
    r = fix("try:\n    x = 1\nexcept:\n    pass\n")
    assert "except Exception:" in r.fixed_source
    assert status_of(r, "R-ERR-001") == {"fixed"}


def test_bare_except_keeps_trailing_comment():
    r = fix("try:\n    x = 1\nexcept:  # سبب\n    pass\n")
    assert "except Exception:  # سبب" in r.fixed_source


def test_bare_except_multiline_header_stays_manual():
    # except في سطر والنقطتان في سطر آخر — المسار يرفض الاحتياطي
    src = "try:\n    x = 1\nexcept \\\n:\n    pass\n"
    r = fix(src)
    assert status_of(r, "R-ERR-001") == {"open"}
    assert r.changed is False


# ============================================================ R-ERR-003
def test_raise_from_named_handler():
    r = fix(
        """
        def f(v):
            try:
                return int(v)
            except ValueError as exc:
                raise RuntimeError("سيء")
        """
    )
    assert 'raise RuntimeError("سيء") from exc' in r.fixed_source
    assert status_of(r, "R-ERR-003") == {"fixed"}


def test_raise_from_binds_new_name():
    r = fix(
        """
        def f(v):
            try:
                return int(v)
            except ValueError:
                raise RuntimeError("سيء")
        """
    )
    assert "except ValueError as _zk_exc:" in r.fixed_source
    assert "from _zk_exc" in r.fixed_source


def test_raise_from_unique_name_on_collision():
    import re

    src = (
        "_zk_exc = 1\n"
        "def f(v):\n"
        "    try:\n"
        "        return int(v)\n"
        "    except ValueError:\n"
        "        raise RuntimeError('سيء')\n"
    )
    r = fix(src)
    m = re.search(r"except ValueError as (_zk_exc\d+):", r.fixed_source)
    assert m, r.fixed_source
    assert f"from {m.group(1)}" in r.fixed_source


def test_raise_with_cause_already_untouched():
    r = fix(
        """
        def f(v):
            try:
                return int(v)
            except ValueError as exc:
                raise RuntimeError("سيء") from exc
        """
    )
    assert not any(o.rule_id == "R-ERR-003" for o in r.outcomes)
    assert "from exc" in r.fixed_source  # لم يُمس السبب القائم


def test_bare_raise_untouched():
    r = fix(
        """
        def f(v):
            try:
                int(v)
            except ValueError:
                raise
        """
    )
    assert not any(o.rule_id == "R-ERR-003" for o in r.outcomes)


# ============================================================ R-ERR-004
def test_open_wrapped_in_with():
    r = fix(
        """
        def f(p):
            fh = open(p)
            data = fh.read()
            return data
        """
    )
    assert "with open(p) as fh:" in r.fixed_source
    assert "        data = fh.read()" in r.fixed_source  # أُزاحت بادئة الجسم
    assert "    return data" in r.fixed_source  # ما بعد الاعتماد بقي خارجًا
    assert status_of(r, "R-ERR-004") == {"fixed"}


def test_open_indirect_call_stays_open():
    r = fix(
        """
        def f(p):
            blob = open(p).read()
            return blob
        """
    )
    assert status_of(r, "R-ERR-004") == {"open"}
    assert "open(p).read()" in r.fixed_source  # لم يُمس


def test_open_no_dependents_stays_open():
    r = fix(
        """
        def f(p):
            fh = open(p)
            return None
        """
    )
    assert status_of(r, "R-ERR-004") == {"open"}


def test_open_later_use_outside_wrapping_stays_open():
    r = fix(
        """
        def f(p):
            fh = open(p)
            fh.read()
            print("وسط")
            fh.close()
        """
    )
    # «print» يقطع الجري المتصل والاستخدام اللاحق خارج اللف ⇒ رفض آمن
    assert status_of(r, "R-ERR-004") == {"open"}


def test_open_inside_with_not_flagged():
    r = fix(
        """
        def f(p):
            with open(p) as fh:
                data = fh.read()
            return data
        """
    )
    assert not any(o.rule_id == "R-ERR-004" for o in r.outcomes)


def test_open_multiline_string_in_body_refused():
    r = fix(
        '''
        def f(p):
            fh = open(p)
            log = f"""
            {fh.read()}
            """
            return log
        '''
    )
    # نص f-string متعدد الأسطر داخل الجسم الملفوف ⇒ الإزاحة تفسده ⇒ رفض
    assert status_of(r, "R-ERR-004") == {"open"}
    assert "    fh = open(p)" in r.fixed_source  # لم يُمس


# ============================================================ R-ERR-005
def test_shell_true_removed_for_list_command():
    r = fix(
        """
        import subprocess
        def f(t):
            subprocess.run(["ls", t], shell=True, check=True)
        """
    )
    assert 'subprocess.run(["ls", t], check=True)' in r.fixed_source
    assert status_of(r, "R-ERR-005") == {"fixed"}


def test_shell_true_string_command_stays_open():
    r = fix(
        """
        import subprocess
        def f(s):
            subprocess.run("ls " + s, shell=True)
        """
    )
    assert status_of(r, "R-ERR-005") == {"open"}
    assert "shell=True" in r.fixed_source


def test_shell_true_first_kw_removed_cleanly():
    r = fix(
        """
        import subprocess
        def f(t):
            subprocess.run(shell=True, args=["ls"])
        """
    )
    # shell أول وسطاء الاستدعاء (فوق args) — يُحذف حتى بداية التالي
    assert "shell=True" not in r.fixed_source


# ============================================================ R-ERR-006
def test_mutable_default_guarded():
    r = fix(
        """
        def add(tag, items=[]):
            items.append(tag)
            return items
        """
    )
    assert "def add(tag, items=None):" in r.fixed_source
    assert "if items is None:" in r.fixed_source
    assert "        items = []" in r.fixed_source
    assert status_of(r, "R-ERR-006") == {"fixed"}


def test_mutable_default_call_forms():
    r = fix(
        """
        def a(x=list()):
            return x
        def b(y=dict()):
            return y
        def c(z=set()):
            return z
        """
    )
    assert "x=None" in r.fixed_source and "x = list()" in r.fixed_source
    assert "y=None" in r.fixed_source and "y = dict()" in r.fixed_source
    assert "z=None" in r.fixed_source and "z = set()" in r.fixed_source


def test_mutable_default_kwonly():
    r = fix(
        """
        def render(*, rows=[]):
            rows.append(1)
            return rows
        """
    )
    assert "rows=None" in r.fixed_source
    assert "if rows is None:" in r.fixed_source


def test_mutable_default_guard_after_docstring():
    r = fix(
        '''
        def add(tag, items=[]):
            """توثيق يبقى أولًا."""
            items.append(tag)
            return items
        '''
    )
    lines = r.fixed_source.splitlines()
    doc_idx = next(i for i, ln in enumerate(lines) if "توثيق يبقى" in ln)
    guard_idx = next(i for i, ln in enumerate(lines) if "if items is None" in ln)
    assert doc_idx < guard_idx


def test_mutable_default_single_line_def_fixed_via_chain():
    # سلسلة عبر الجولات: التوثيق أولاً يفرد الدالة لأسطر، ثم الحارس يُدرج
    r = fix("def add(tag, items=[]): return items.append(tag) or items\n")
    assert status_of(r, "R-ERR-006") == {"fixed"}
    assert "items=None" in r.fixed_source
    assert "if items is None:" in r.fixed_source


def test_mutable_default_existing_guard_not_duplicated():
    r = fix(
        """
        def add(tag, items=[]):
            if items is None:
                items = []
            items.append(tag)
            return items
        """
    )
    # الحراسة موجودة أصلًا؛ الافتراضي نفسه يُستبدل بلا حارس ثانٍ
    assert r.fixed_source.count("if items is None:") == 1


# ============================================================ R-SEC-103
def test_yaml_load_becomes_safe_load():
    r = fix(
        """
        import yaml
        def f(p):
            return yaml.load(p)
        """
    )
    assert "yaml.safe_load(p)" in r.fixed_source
    assert status_of(r, "R-SEC-103") == {"fixed"}


def test_yaml_full_load_becomes_safe_load():
    r = fix(
        """
        import yaml
        def f(p):
            return yaml.full_load(p)
        """
    )
    assert "yaml.safe_load(p)" in r.fixed_source


def test_yaml_full_load_all_becomes_safe_load_all():
    r = fix(
        """
        import yaml
        def f(p):
            return yaml.full_load_all(p)
        """
    )
    assert "yaml.safe_load_all(p)" in r.fixed_source


def test_yaml_load_with_unsafe_loader_kw():
    r = fix(
        """
        import yaml
        def f(p):
            return yaml.load(p, Loader=yaml.Loader)
        """
    )
    assert "yaml.safe_load(p)" in r.fixed_source
    assert "Loader" not in r.fixed_source.split("def f")[1]


def test_yaml_load_positional_loader_refused():
    r = fix(
        """
        import yaml
        def f(p):
            return yaml.load(p, yaml.Loader)
        """
    )
    assert status_of(r, "R-SEC-103") == {"open"}


def test_yaml_safe_load_not_flagged():
    r = fix(
        """
        import yaml
        def f(p):
            return yaml.safe_load(p)
        """
    )
    assert not any(o.rule_id == "R-SEC-103" for o in r.outcomes)


# ============================================================ R-SEC-106
def test_md5_becomes_sha256():
    r = fix(
        """
        import hashlib
        def f(t):
            return hashlib.md5(t.encode()).hexdigest()
        """
    )
    assert "hashlib.sha256(t.encode())" in r.fixed_source
    assert status_of(r, "R-SEC-106") == {"fixed"}


def test_sha1_becomes_sha256():
    r = fix(
        """
        import hashlib
        def f(t):
            return hashlib.sha1(t)
        """
    )
    assert "hashlib.sha256(t)" in r.fixed_source


# ============================================================ R-SEC-107
def test_verify_false_kw_removed():
    r = fix(
        """
        import httpx
        def f(url):
            return httpx.get(url, verify=False)
        """
    )
    assert "httpx.get(url)" in r.fixed_source
    assert status_of(r, "R-SEC-107") == {"fixed"}


def test_verify_false_kw_sole_argument():
    r = fix(
        """
        import httpx
        def f():
            return httpx.get(verify=False)
        """
    )
    assert "httpx.get()" in r.fixed_source


def test_verify_attribute_flipped_to_true():
    r = fix(
        """
        def f(session):
            session.verify = False
            return session
        """
    )
    assert "session.verify = True" in r.fixed_source


def test_check_hostname_flipped():
    r = fix(
        """
        def f(ctx):
            ctx.check_hostname = False
        """
    )
    assert "ctx.check_hostname = True" in r.fixed_source


# ============================================================ R-QLT-204
def test_docstring_inserted_function():
    r = fix(
        """
        def handle(v):
            return int(v)
        """
    )
    assert '"""دالة handle:' in r.fixed_source
    assert status_of(r, "R-QLT-204") == {"fixed"}


def test_docstring_inserted_class():
    r = fix(
        """
        class Report:
            def build(self, rows):
                return rows
        """
    )
    assert '"""الفئة Report:' in r.fixed_source
    assert '"""دالة build:' in r.fixed_source


def test_docstring_single_line_def():
    r = fix("def tiny(): return 1\n")
    lines = r.fixed_source.splitlines()
    assert lines[0] == "def tiny():"
    assert '"""دالة tiny:' in lines[1]
    assert lines[2].strip() == "return 1"


def test_docstring_private_skipped():
    r = fix(
        """
        def _private(v):
            return v
        """
    )
    assert not any(o.rule_id == "R-QLT-204" for o in r.outcomes)


def test_docstring_existing_untouched():
    r = fix(
        '''
        def documented(v):
            """موثقة أصلًا."""
            return v
        '''
    )
    assert not any(o.rule_id == "R-QLT-204" for o in r.outcomes)


def test_docstring_indented_nested_function():
    r = fix(
        """
        def outer(v):
            def inner(x):
                return x
            return inner(v)
        """
    )
    assert '    """دالة inner' in r.fixed_source
    assert '"""دالة outer' in r.fixed_source


# ============================================================ R-QLT-206
def test_eq_none_becomes_is():
    r = fix(
        """
        def f(v):
            return v == None
        """
    )
    assert "return v is None" in r.fixed_source
    assert status_of(r, "R-QLT-206") == {"fixed"}


def test_neq_none_becomes_is_not():
    r = fix(
        """
        def f(v):
            return v != None
        """
    )
    assert "return v is not None" in r.fixed_source


def test_none_on_left_becomes_is():
    r = fix(
        """
        def f(v):
            return None == v
        """
    )
    assert "return None is v" in r.fixed_source


def test_chain_comparisons_each_fixed():
    r = fix(
        """
        def f(a, b):
            return a == None or b != None
        """
    )
    assert "return a is None or b is not None" in r.fixed_source


def test_non_none_compare_untouched():
    r = fix(
        """
        def f(a, b):
            return a == b
        """
    )
    assert "return a == b" in r.fixed_source
    assert not any(o.rule_id == "R-QLT-206" for o in r.outcomes)


# ============================================================ R-QLT-207
def test_unused_single_import_deleted():
    r = fix(
        """
        import os
        import sys

        def f():
            return sys.platform
        """
    )
    assert "import os" not in r.fixed_source
    assert "import sys" in r.fixed_source
    assert status_of(r, "R-QLT-207") == {"fixed"}


def test_unused_alias_from_multiline_import():
    r = fix(
        """
        from typing import (
            Dict,
            List,
        )

        def f(x: List[int]) -> int:
            return len(x)
        """
    )
    assert "Dict" not in r.fixed_source
    assert "List" in r.fixed_source


def test_import_used_in_string_counts_as_used():
    r = fix(
        """
        import pickle

        TABLE = "pickle يُذكر في نص توثيقي"
        """
    )
    # الاسم داخل نص يُحسب استخدامًا (منطق المراجع نفسه) ⇒ بلا ملاحظة أصلًا
    assert not any(o.rule_id == "R-QLT-207" for o in r.outcomes)
    assert "import pickle" in r.fixed_source


def test_import_in_all_counts_as_used():
    r = fix(
        """
        from zyko.tools import scanner

        __all__ = ["scanner"]
        """
    )
    assert "import" in r.fixed_source  # لم يُحذف — مُصدَّر في __all__


def test_init_py_never_autoremoved():
    src = "import os\n"
    r = fix(src, path="pkg/__init__.py")
    assert status_of(r, "R-QLT-207") == {"open"}
    assert r.changed is False


def test_import_with_semicolon_refused():
    r = fix("import os; x = 1\n")
    # بيان آخر بعد «;» في نفس السطر ⇒ حذف السطر كله يفسده ⇒ رفض
    assert status_of(r, "R-QLT-207") == {"open"}


def test_future_import_never_touched():
    r = fix(
        """
        from __future__ import annotations

        def f() -> "int":
            return 1
        """
    )
    assert "from __future__" in r.fixed_source


# ============================================================ R-QLT-209
def test_lambda_becomes_def():
    r = fix(
        """
        greet = lambda name: "مرحبًا " + name
        """
    )
    assert "def greet(name):" in r.fixed_source
    assert 'return "مرحبًا " + name' in r.fixed_source
    assert "lambda" not in r.fixed_source
    assert status_of(r, "R-QLT-209") == {"fixed"}


def test_lambda_with_default_args():
    r = fix("clamp = lambda v, lo=0: v if v > lo else lo\n")
    assert "def clamp(v, lo=0):" in r.fixed_source
    assert "return v if v > lo else lo" in r.fixed_source


def test_lambda_multiline_body_parens_dropped():
    r = fix(
        """
        fmt = lambda n: (
            f"{n:04d}"
        )
        """
    )
    assert "def fmt(n):" in r.fixed_source
    assert 'return f"{n:04d}"' in r.fixed_source


def test_lambda_nested_indentation_preserved():
    r = fix(
        """
        def outer():
            make = lambda x: x * 2
            return make(3)
        """
    )
    assert "    def make(x):" in r.fixed_source
    assert "        return x * 2" in r.fixed_source


def test_annassign_lambda_becomes_def():
    r = fix(
        """
        from collections.abc import Callable
        op: Callable = lambda x: x + 1
        """
    )
    assert "def op(x):" in r.fixed_source


def test_lambda_in_dict_value_untouched():
    r = fix("ops = {'inc': lambda x: x + 1}\n")
    # ليس إسنادًا لاسم مفرد ⇒ بلا ملاحظة أصلًا
    assert not any(o.rule_id == "R-QLT-209" for o in r.outcomes)


# ================================================== السجل والأسباب اليدوية
def test_registry_sizes_match_reviewer():
    from zyko.reviewer.rules import RULES

    assert len(AUTO_FIXABLE) == 12
    assert len(MANUAL_RULES) == 26
    assert len(AUTO_FIXABLE) + len(MANUAL_RULES) == 38 == len(RULES)


def test_manual_reasons_cover_all_and_arabic():
    from zyko.fixer.fixes import manual_reason_ar

    for rid in MANUAL_RULES:
        reason = manual_reason_ar(rid)
        assert reason and any("\u0600" <= ch <= "\u06ff" for ch in reason), rid


def test_action_ar_covers_all_auto_rules():
    from zyko.fixer.fixes import ACTION_AR

    for rid in AUTO_FIXABLE:
        assert rid in ACTION_AR and ACTION_AR[rid]
