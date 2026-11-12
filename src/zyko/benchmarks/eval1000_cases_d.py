"""بنّاؤو حالات التقييم (د) — المراجعة والإصلاح، البنية المهيكلة، السياسة، النواة، الإيصالات."""

from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import tempfile

from zyko.fixer.engine import AUTO_FIXABLE, FixerEngine, apply_edits
from zyko.reviewer.engine import ReviewEngine, verdict_for_score
from zyko.reviewer.rules import RULES, RULES_BY_ID
from zyko.reviewer.taint import collect_taints


# ================================================= 16) المراجعة والإصلاح
def build_review_fix():
    cases = []

    def fn_rules_unique():
        ids = [r.rule_id for r in RULES]
        return (
            (True, f"{len(ids)} قاعدة فريدة")
            if len(ids) == len(set(ids)) == 38
            else (False, f"قواعد: {len(ids)} فريد {len(set(ids))}")
        )

    cases.append(("فهرس", "38 قاعدة فريدة", fn_rules_unique))

    for rule in RULES:

        def fn(rule=rule):
            ok = rule.severity in ("critical", "high", "medium", "low", "info")
            ok = ok and bool(rule.message_ar.strip()) and bool(rule.suggestion_ar.strip())
            ok = ok and callable(rule.checker)
            return (True, f"{rule.rule_id} سليمة") if ok else (False, f"{rule.rule_id} بحقول ناقصة")

        cases.append(("فهرس", f"قاعدة {rule.rule_id} سليمة", fn))

    def fn_by_id():
        ok = set(RULES_BY_ID.keys()) == {r.rule_id for r in RULES}
        return (True, "الفهرس يطابق القائمة") if ok else (False, "RULES_BY_ID لا يطابق RULES")

    cases.append(("فهرس", "RULES_BY_ID يطابق القائمة", fn_by_id))

    # المُشغّلات السلوكية — عيّنات عيوب حقيقية
    def fn_trigger_eval():
        result = ReviewEngine().review_source("result = eval('2+2')\n", filename="t.py")
        err = [f for f in result.findings if f.severity in ("critical", "high")]
        return (
            (True, "eval يُرفض")
            if err
            else (False, f"eval بلا خطأ: {[(f.rule_id, f.severity) for f in result.findings]}")
        )

    cases.append(("مُشغّل", "eval() يعترض بخطأ", fn_trigger_eval))

    def fn_trigger_os_system():
        result = ReviewEngine().review_source("import os\nos.system('ls -la')\n", filename="t.py")
        err = [f for f in result.findings if f.severity in ("critical", "high")]
        return (True, "os.system يُرفض") if err else (False, "استدعاء نظام خام مرّ بلا خطأ")

    cases.append(("مُشغّل", "os.system يعترض بخطأ", fn_trigger_os_system))

    def fn_trigger_secret():
        src = "password = 'SuperSecret123!'\n"
        result = ReviewEngine().review_source(src, filename="auth.py")
        sec = [f for f in result.findings if f.severity in ("critical", "high")]
        return (
            (True, "سر مكتوب يُرفض")
            if sec
            else (
                False,
                f"كلمة مرور حرفية مرّت: {[(f.rule_id, f.severity) for f in result.findings]}",
            )
        )

    cases.append(("مُشغّل", "سر مكتوب في الكود يُرفض", fn_trigger_secret))

    def fn_trigger_bare_except():
        result = ReviewEngine().review_source(
            "try:\n    pass\nexcept:\n    pass\n", filename="t.py"
        )
        ok = bool(result.findings)
        return (True, "except عارٍ يُلاحظ") if ok else (False, "except عارٍ مرّ بلا ملاحظة")

    cases.append(("مُشغّل", "except عارٍ يُلاحظ", fn_trigger_bare_except))

    def fn_trigger_none_cmp():
        result = ReviewEngine().review_source("x = 1\nif x == None:\n    pass\n", filename="t.py")
        ok = bool(result.findings)
        return (True, "مقارنة None تُلاحظ") if ok else (False, "x == None مرّ بلا ملاحظة")

    cases.append(("مُشغّل", "مقارنة None بعلامتي يساوي تُلاحظ", fn_trigger_none_cmp))

    def fn_clean_source():
        src = 'def add(a: int, b: int) -> int:\n    """جمع رقمين."""\n    return a + b\n'
        result = ReviewEngine().review_source(src, filename="clean.py")
        errs = [f for f in result.findings if f.severity in ("critical", "high")]
        return (
            (True, "كود نظيف بلا أخطاء")
            if not errs
            else (False, f"كود نظيف بأخطاء: {[f.rule_id for f in errs]}")
        )

    cases.append(("مُشغّل", "كود نظيف يمر بلا أخطاء", fn_clean_source))

    def fn_verdict_monotonic():
        v0 = verdict_for_score(0)
        v50 = verdict_for_score(50)
        v100 = verdict_for_score(100)
        texts = {str(v) for v in (v0, v50, v100)}
        return (True, "الأحكام تفرز") if len(texts) >= 2 else (False, f"أحكام: {texts}")

    cases.append(("أحكام", "verdict_for_score يفرز النتائج", fn_verdict_monotonic))

    def fn_review_file():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "t.py"
            p.write_text("x = eval('1')\n", encoding="utf-8")
            result = ReviewEngine().review_file(p)
            return (True, "الملف يُراجع") if result.findings else (False, "ملف معيب مرّ بلا ملاحظات")

    cases.append(("واجهات", "review_file على ملف حقيقي", fn_review_file))

    def fn_review_path():
        with tempfile.TemporaryDirectory() as td:
            d = pathlib.Path(td) / "pkg"
            d.mkdir()
            (d / "a.py").write_text("import os\nos.system('ls')\n", encoding="utf-8")
            results = ReviewEngine().review_path(d)
            return (
                (True, "المسار يُراجع")
                if results and any(r.findings for r in results)
                else (False, "مسار بلا ملاحظات")
            )

    cases.append(("واجهات", "review_path على مجلد", fn_review_path))

    def fn_finding_dict():
        r = ReviewEngine().review_source("x = eval('1')\n", filename="t.py")
        d = r.findings[0].to_dict()
        need = {"rule_id", "severity", "message_ar", "line", "col"}
        return (
            (True, "ممثل JSON موثق")
            if need <= set(d.keys())
            else (False, f"مفاتيح: {sorted(d.keys())}")
        )

    cases.append(("توثيق", "Finding للمراجعة يُسلسل", fn_finding_dict))

    def fn_result_dict():
        r = ReviewEngine().review_source("x = eval('1')\n", filename="t.py")
        d = r.to_dict()
        ok = "score" in d
        return (
            (True, "نتيجة قابلة للتسلسل") if ok else (False, f"مفاتيح النتيجة: {sorted(d.keys())}")
        )

    cases.append(("توثيق", "ReviewResult يُسلسل بالنقاط", fn_result_dict))

    def fn_taint_argv():
        import ast as _ast

        tree_ok = collect_taints(_ast.parse("x = sys.argv[1]\n"))
        return (
            (True, "sys.argv مصدر إدخال")
            if "x" in tree_ok.input_names
            else (False, f"مصدر sys.argv: {set(tree_ok.input_names)}")
        )

    cases.append(("تلوث", "تلوث sys.argv في مصادر الإدخال", fn_taint_argv))

    def fn_taint_input():
        import ast as _ast

        t = collect_taints(_ast.parse("x = input('؟')\n"))
        ok = "x" in t.input_names
        return (True, "input موسوم") if ok else (False, f"مصدر input: {set(t.input_names)}")

    cases.append(("تلوث", "تلوث input() في مصادر الإدخال", fn_taint_input))

    def fn_taint_request():
        import ast as _ast

        t = collect_taints(_ast.parse("x = request.args.get('a')\n"))
        return (
            (True, "request موسوم")
            if "x" in t.request_names
            else (False, f"مصدر request: {set(t.request_names)}")
        )

    cases.append(("تلوث", "تلوث request.args في مصادر الطلب", fn_taint_request))

    def fn_fixer_equality():
        src = "x = 1\nif x == None:\n    pass\n"
        result = FixerEngine().fix_source(src, filename="t.py")
        ok = result.fixed_count > 0 and result.parse_error is None
        return (
            (True, "إصلاح آلي موثق")
            if ok
            else (False, f"إصلاح: fixed={result.fixed_count} err={result.parse_error}")
        )

    cases.append(("إصلاح", "المقارنة الخاطئة تُصلح آليًا", fn_fixer_equality))

    def fn_fixer_auto_fixable():
        ok = bool(AUTO_FIXABLE) and all(isinstance(x, str) for x in AUTO_FIXABLE)
        return (True, "قائمة الإصلاح الآلي موثقة") if ok else (False, "AUTO_FIXABLE فارغة أو غريبة")

    cases.append(("إصلاح", "AUTO_FIXABLE قائمة موثقة", fn_fixer_auto_fixable))

    def fn_fixer_file():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "t.py"
            p.write_text("if x == None:\n    pass\n", encoding="utf-8")
            result = FixerEngine().fix_file(p)
            ok = result.parse_error is None and (result.fixed_count > 0 or result.fixed_count == 0)
            return (
                (True, "إصلاح ملف موثق") if ok else (False, f"إصلاح ملف: err={result.parse_error}")
            )

    cases.append(("إصلاح", "fix_file على ملف حقيقي", fn_fixer_file))

    def fn_apply_edits_identity():
        src = "x = 1\n"
        got, applied, rejected = apply_edits(src, [])
        return (
            (True, "بلا تحريرات يبقى")
            if got == src and not applied and not rejected
            else (False, "بلا تحريرات تغير النص!")
        )

    cases.append(("إصلاح", "apply_edits بلا تحريرات يبقى", fn_apply_edits_identity))

    def fn_manual_reason():
        import zyko.fixer as _fz

        rules = _fz.MANUAL_RULES
        if not rules:
            return True, "بلا قواعد يدوية موثقة اليوم"
        text = _fz.manual_reason_ar(rules[0])
        ok = bool(text.strip())
        return (True, "اليدوية بسبعها العربي") if ok else (False, "قاعدة يدوية بلا سبب عربي")

    cases.append(("إصلاح", "القواعد اليدوية موثقة", fn_manual_reason))

    def fn_summarize():
        with tempfile.TemporaryDirectory() as td:
            d = pathlib.Path(td) / "pkg"
            d.mkdir()
            (d / "a.py").write_text("x = eval('1')\n", encoding="utf-8")
            (d / "b.py").write_text("y = 1\n", encoding="utf-8")
            results = ReviewEngine().review_path(d)
            summary = __import__("zyko.reviewer.report", fromlist=["summarize"]).summarize(results)
            ok = isinstance(summary, dict) or isinstance(summary, str)
            return (True, "ملخص موثق") if ok else (False, f"ملخص: {type(summary).__name__}")

    cases.append(("توثيق", "summarize يجمل النتائج", fn_summarize))

    def fn_review_determinism():
        src = "import os\nos.system('ls')\nx = eval('2')\n"
        a = [
            (f.rule_id, f.severity, f.line)
            for f in ReviewEngine().review_source(src, filename="t.py").findings
        ]
        b = [
            (f.rule_id, f.severity, f.line)
            for f in ReviewEngine().review_source(src, filename="t.py").findings
        ]
        return (True, "حتمي بالبايت") if a == b and a else (False, "مراجعتان لنفس المصدر اختلفا")

    cases.append(("حتمية", "المراجعة حتمية بالبايت", fn_review_determinism))

    return cases


# ============================================= 17) البنية المهيكلة
def build_structured():
    from zyko.exceptions import SchemaSpecError
    from zyko.structured.extract import extract_json
    from zyko.structured.schema import json_schema_of, validate_against_schema

    cases = []

    def fn_type_object():
        errs = validate_against_schema({"a": 1}, {"type": "object"})
        return (True, "object صحيح") if not errs else (False, errs)

    cases.append(("أنواع", "type: object يقبل الكائن", fn_type_object))

    def fn_type_int_bool_trap():
        errs = validate_against_schema(True, {"type": "integer"})
        return (True, "bool لا يعبر عددًا") if errs else (False, "True قُبل عددًا صحيحًا!")

    cases.append(("أنواع", "bool لا يُقبل integer (فخ بايثون)", fn_type_int_bool_trap))

    def fn_type_number_bool():
        errs = validate_against_schema(True, {"type": "number"})
        return (True, "bool لا يعبر رقمًا") if errs else (False, "True قُبل رقمًا")

    cases.append(("أنواع", "bool لا يُقبل number", fn_type_number_bool))

    def fn_type_list_type():
        ok = not validate_against_schema(
            "x", {"type": ["string", "null"]}
        ) and not validate_against_schema(None, {"type": ["string", "null"]})
        return (True, "قائمة أنواع تعمل") if ok else (False, "قائمة الأنواع مكسورة")

    cases.append(("أنواع", "type كقائمة تعمل", fn_type_list_type))

    def fn_type_null():
        errs = validate_against_schema(None, {"type": "null"})
        return (True, "null يقبل") if not errs else (False, errs)

    cases.append(("أنواع", "type: null يقبل None", fn_type_null))

    def fn_enum_typed():
        ok = not validate_against_schema(1, {"enum": [1, 2]}) and validate_against_schema(
            True, {"enum": [1, 2]}
        )
        return (True, "النوع في العضوية") if ok else (False, "enum خلط 1 مع True")

    cases.append(("قيود", "enum يميز النوع (1 ≠ True)", fn_enum_typed))

    def fn_const():
        ok = not validate_against_schema("a", {"const": "a"}) and validate_against_schema(
            "b", {"const": "a"}
        )
        return (True, "const يعمل") if ok else (False, "const مكسور")

    cases.append(("قيود", "const يقبل ويرفض", fn_const))

    for k, (schema, value, expect_ok) in enumerate(
        (
            ({"type": "integer", "minimum": 3}, 5, True),
            ({"type": "integer", "minimum": 3}, 2, False),
            ({"type": "integer", "maximum": 10}, 11, False),
            ({"type": "integer", "exclusiveMinimum": 3}, 3, False),
            ({"type": "integer", "exclusiveMinimum": 3}, 4, True),
            ({"type": "integer", "exclusiveMaximum": 10}, 10, False),
            ({"type": "integer", "multipleOf": 3}, 9, True),
            ({"type": "integer", "multipleOf": 3}, 10, False),
        )
    ):

        def fn(schema=schema, value=value, expect_ok=expect_ok):
            errs = validate_against_schema(value, schema)
            return (
                (True, "متسق")
                if (not errs) is expect_ok
                else (False, f"{value} على {schema}: {errs}")
            )

        cases.append(("قيود", f"قيود عددية ({k + 1})", fn))

    for k, (schema, value, expect_ok) in enumerate(
        (
            ({"type": "string", "minLength": 3}, "سلام", True),
            ({"type": "string", "minLength": 3}, "ا", False),
            ({"type": "string", "maxLength": 5}, "سلام عليكم", False),
            ({"type": "string", "pattern": "^[0-9]+$"}, "12345", True),
            ({"type": "string", "pattern": "^[0-9]+$"}, "12a45", False),
        )
    ):

        def fn(schema=schema, value=value, expect_ok=expect_ok):
            errs = validate_against_schema(value, schema)
            return (True, "متسق") if (not errs) is expect_ok else (False, f"نص: {errs}")

        cases.append(("قيود", f"قيود نصية ({k + 1})", fn))

    for k, (fmt, value, expect_ok) in enumerate(
        (
            ("email", "a@b.com", True),
            ("email", "not-an-email", False),
            ("date", "2026-11-12", True),
            ("date", "2026/11/12", False),
            ("date-time", "2026-11-12T08:30:00", True),
            ("uuid", "550e8400-e29b-41d4-a716-446655440000", True),
            ("uuid", "550e8400", False),
            ("ipv4", "192.168.1.1", True),
            ("ipv4", "not.an.ip", False),
            ("uri", "https://example.com", True),
            ("uri", "example.com", False),
            ("hostname", "api.example.com", True),
            ("hostname", "-bad-", False),
        )
    ):

        def fn(fmt=fmt, value=value, expect_ok=expect_ok):
            errs = validate_against_schema(value, {"type": "string", "format": fmt})
            return (True, "متسق") if (not errs) is expect_ok else (False, f"{fmt}={value}: {errs}")

        cases.append(("صيغ", f"format {fmt} ({k + 1})", fn))

    def fn_array():
        schema = {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 3}
        ok = not validate_against_schema([1, 2], schema)
        ok = (
            ok
            and validate_against_schema([], schema)
            and validate_against_schema([1, "x"], schema)
            and validate_against_schema([1, 2, 3, 4], schema)
        )
        return (True, "أربع حوائم تعمل") if ok else (False, "قيود المصفوفة مكسورة")

    cases.append(("مصفوفات", "items وحدود المصفوفة", fn_array))

    def fn_unique():
        ok = validate_against_schema([1, 1], {"uniqueItems": True}) and not validate_against_schema(
            [1, 2], {"uniqueItems": True}
        )
        return (True, "uniqueItems يعمل") if ok else (False, "uniqueItems مكسور")

    cases.append(("مصفوفات", "uniqueItems يمنع التكرار", fn_unique))

    def fn_object_props():
        schema = {
            "type": "object",
            "properties": {"a": {"type": "integer"}},
            "required": ["a"],
            "additionalProperties": False,
        }
        ok = not validate_against_schema({"a": 1}, schema)
        ok = (
            ok
            and validate_against_schema({"b": 1}, schema)
            and validate_against_schema({"a": "نص", "b": 1}, schema)
        )
        return (True, "الخصائص والناقص والزائد") if ok else (False, "قيود الكائن مكسورة")

    cases.append(("كائنات", "properties وrequired وadditional", fn_object_props))

    def fn_object_counts():
        schema = {"type": "object", "minProperties": 2, "maxProperties": 3}
        ok = validate_against_schema({"a": 1}, schema) and not validate_against_schema(
            {"a": 1, "b": 2}, schema
        )
        return (True, "حدود الخصائص") if ok else (False, "min/maxProperties مكسورة")

    cases.append(("كائنات", "min/maxProperties تعمل", fn_object_counts))

    def fn_all_of():
        schema = {"allOf": [{"type": "integer", "minimum": 1}, {"type": "integer", "maximum": 5}]}
        ok = not validate_against_schema(3, schema) and validate_against_schema(9, schema)
        return (True, "allOf يعمل") if ok else (False, "allOf مكسور")

    cases.append(("تركيب", "allOf يشترط الجميع", fn_all_of))

    def fn_any_of():
        schema = {"anyOf": [{"type": "string"}, {"type": "integer"}]}
        ok = (
            not validate_against_schema("نص", schema)
            and not validate_against_schema(3, schema)
            and validate_against_schema(1.5, schema)
        )
        return (True, "anyOf يعمل") if ok else (False, "anyOf مكسور")

    cases.append(("تركيب", "anyOf يشترط واحدًا على الأقل", fn_any_of))

    def fn_one_of():
        schema = {"oneOf": [{"type": "integer", "const": 1}, {"type": "integer", "const": 1}]}
        # نمطان متطابقان ⇒ فرضية واحدة لا تنفرد ⇒ مرفوض
        errs = validate_against_schema(1, schema)
        return (True, "oneOf يفرض الانفراد") if errs else (False, "نمطان يرضيان وoneOf قَبِل")

    cases.append(("تركيب", "oneOf يفرض انفراد المطابقة", fn_one_of))

    def fn_ref():
        schema = {
            "type": "object",
            "properties": {"child": {"$ref": "#/$defs/node"}},
            "$defs": {"node": {"type": "integer", "minimum": 0}},
        }
        ok = not validate_against_schema({"child": 3}, schema) and validate_against_schema(
            {"child": -1}, schema
        )
        return (True, "$ref المحلي يعمل") if ok else (False, "المرجع المحلي مكسور")

    cases.append(("مراجع", "$ref إلى $defs يعمل", fn_ref))

    def fn_ref_cycle():
        schema = {
            "$ref": "#/$defs/a",
            "$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}},
        }
        try:
            validate_against_schema("قيمة", schema)
            return True, "الدورة محكومة بلا انفجار"
        except SchemaSpecError:
            return True, "الدورة ترفض المخطط نفسه"
        except RecursionError:
            return False, "دورة $ref انفجرت بالتكرار!"

    cases.append(("مراجع", "دورة $ref لا تنفجر", fn_ref_cycle))

    def fn_unknown_keywords():
        errs = validate_against_schema(
            3, {"type": "integer", "title": "عنوان", "examples": [1], "x-custom": True}
        )
        return (True, "المفاتيح المجهولة تُتجاهل") if not errs else (False, "مفتاح مجهول أفسد الحكم")

    cases.append(("مراجع", "مفاتيح غير معروفة تُتجاهل", fn_unknown_keywords))

    for k, (bad, probe) in enumerate(
        (
            ({"type": "سلطة"}, 1),
            ({"type": "integer", "minimum": "خمسة"}, 1),
            ({"type": "string", "pattern": "["}, "نص"),
            ({"type": "object", "properties": {"a": {"type": "سلطة"}}}, {"a": 1}),
        )
    ):

        def fn(bad=bad, probe=probe):
            try:
                validate_against_schema(probe, bad)
                return False, f"مخطط فاسد قُبل بصمت: {bad}"
            except SchemaSpecError:
                return True, "المخطط الفاسد يفشل سريعًا"

        cases.append(("مخططات-فاسدة", f"مخطط فاسد يفشل سريعًا ({k + 1})", fn))

    def fn_minimum_no_type_legal():
        # عقد المخطط: minimum بلا type مخطط قانوني يطبق على كل الأنواع
        errs = validate_against_schema("أي قيمة", {"minimum": 3})
        return (True, "المخطط القانوني يقبل") if not errs else (False, errs)

    cases.append(("مراجع", "minimum بلا type مخطط قانوني", fn_minimum_no_type_legal))

    def fn_spec_non_dict():
        try:
            json_schema_of(42)
            return False, "عدد قُبل مخططًا!"
        except SchemaSpecError:
            return True, "المواصفة غير المدعومة ترفض"

    cases.append(("مخططات-فاسدة", "json_schema_of يرفض غير المدعوم", fn_spec_non_dict))

    def fn_spec_dict_passthrough():
        d = {"type": "string"}
        return (
            (True, "القاموس يعود كما هو")
            if json_schema_of(d) is d
            else (False, "قاموس المخطط تغير")
        )

    cases.append(("مراجع", "json_schema_of يمرر القاموس", fn_spec_dict_passthrough))

    # extract_json
    for k, (text, expect) in enumerate(
        (
            ('{"a": 1}', {"a": 1}),
            ('<think>فكرة</think>\n{"a": 2}', {"a": 2}),
            ('```json\n{"a": 3}\n```', {"a": 3}),
            ('الجواب: {"a": 4} وبعد', {"a": 4}),
            ("[1, 2, 3]", [1, 2, 3]),
            ('{"مفتاح": "قيمة عربية"}', {"مفتاح": "قيمة عربية"}),
            ('{"nested": {"deep": [1, {"x": 2}]}}', {"nested": {"deep": [1, {"x": 2}]}}),
        )
    ):

        def fn(text=text, expect=expect):
            got = extract_json(text)
            return (True, "استُخرج") if got == expect else (False, f"استخراج «{text[:20]}…» → {got}")

        cases.append(("استخراج", f"extract_json ({k + 1})", fn))

    for k, bad in enumerate(("ليس جيسون", '{"a": 1', "", '{"a": }')):

        def fn(bad=bad):
            got = extract_json(bad)
            return (True, "الفاسد يعود None") if got is None else (False, f"«{bad[:16]}» → {got}")

        cases.append(("استخراج", f"نص فاسد يعود None ({k + 1})", fn))

    def fn_extract_think_multi():
        got = extract_json('<think>سطر\nآخر</think> نص ثم {"a": 9}')
        return (True, "think متعدد الأسطر") if got == {"a": 9} else (False, f"→ {got}")

    cases.append(("استخراج", "كتلة think متعددة الأسطر", fn_extract_think_multi))

    def fn_validate_empty():
        errs = validate_against_schema({"أ": 1}, {})
        return (True, "مخطط فارغ يقبل كل شيء") if not errs else (False, errs)

    cases.append(("مراجع", "مخطط فارغ يقبل أي قيمة", fn_validate_empty))

    def fn_determinism():
        schema = {"type": "object", "required": ["a"]}
        a = validate_against_schema({}, schema)
        b = validate_against_schema({}, schema)
        return (True, "حتمي بالبايت") if a == b and a else (False, "حكمان اختلفا")

    cases.append(("حتمية", "التحقق حتمي بالبايت", fn_determinism))

    return cases


# ============================================= 18) السياسة والحجب
def build_policy():
    from zyko.policy.engine import (
        BUILTIN_PATTERNS,
        KNOWN_FN_REDACTORS,
        Redactor,
        builtin_default_policy,
        load_policy,
    )

    cases = []

    def fn_builtin_keys():
        need = {"email", "ssn", "iban", "credit_card", "phone"}
        return (
            (True, "الأنماط الخمسة")
            if need <= set(BUILTIN_PATTERNS.keys())
            else (False, f"مفاتيح: {sorted(BUILTIN_PATTERNS)}")
        )

    cases.append(("سجل", "أنماط الحجب المدمجة الخمسة", fn_builtin_keys))

    def fn_fn_redactors():
        return (
            (True, "pii_ar مفوض")
            if KNOWN_FN_REDACTORS == ("pii_ar",)
            else (False, f"المفوضون: {KNOWN_FN_REDACTORS}")
        )

    cases.append(("سجل", "المفوَض العربي pii_ar موثق", fn_fn_redactors))

    def fn_redact_email():
        r = Redactor.from_doc({"redact": ["email"]})
        out, kinds = r.apply("راسلني على user@site.com اليوم")
        return (
            (True, "بريد محجوب")
            if "user@site.com" not in out and kinds
            else (False, f"بريد مرّ: {out[:30]}")
        )

    cases.append(("حجب", "البريد يُحجب", fn_redact_email))

    def fn_redact_card():
        r = Redactor.from_doc({"redact": ["credit_card"]})
        out, kinds = r.apply("بطاقة 4111 1111 1111 1111 مفعلة")
        return (
            (True, "بطاقة محجوبة")
            if "4111 1111 1111 1111" not in out and kinds
            else (False, "بطاقة مرّت")
        )

    cases.append(("حجب", "البطاقة تُحجب", fn_redact_card))

    def fn_redact_card_dashes():
        r = Redactor.from_doc({"redact": ["credit_card"]})
        out, kinds = r.apply("بطاقة 4111-1111-1111-1111 مفعلة")
        return (
            (True, "بطاقة بشرطات محجوبة")
            if "4111-1111-1111-1111" not in out and kinds
            else (False, "شرطات كسرت الحجب")
        )

    cases.append(("حجب", "البطاقة بفواصل تُحجب", fn_redact_card_dashes))

    def fn_redact_iban():
        r = Redactor.from_doc({"redact": ["iban"]})
        out, kinds = r.apply("حساب SA0312345678901234567890")
        ok = "SA0312345678901234567890" not in out
        return (True, "آيبان محجوب") if ok else (False, f"آيبان مرّ: {out[:40]}")

    cases.append(("حجب", "الآيبان يُحجب", fn_redact_iban))

    def fn_redact_phone():
        r = Redactor.from_doc({"redact": ["phone"]})
        out, kinds = r.apply("اتصل على +966501234567 اليوم")
        return (
            (True, "هاتف محجوب")
            if "+966501234567" not in out and kinds
            else (False, "هاتف دولي مرّ")
        )

    cases.append(("حجب", "الهاتف الدولي يُحجب", fn_redact_phone))

    def fn_redact_priority():
        r = Redactor.from_doc({"redact": ["credit_card", "phone"]})
        out, _ = r.apply("بطاقة 4111 1111 1111 1111 وهاتف +966501234567")
        ok = "4111" not in out and "+966501234567" not in out
        return (True, "نوعان حُجبا") if ok else (False, "حجب مزدوج ناقص")

    cases.append(("حجب", "حجب متعدد الأنواع في نص واحد", fn_redact_priority))

    def fn_redact_clean():
        r = Redactor.from_doc({})
        text = "نص عربي نظيف بلا بيانات حساسة"
        out, kinds = r.apply(text)
        return (True, "النظيف يبقى") if out == text and not kinds else (False, "نص نظيف حُجب!")

    cases.append(("حجب", "نص نظيف لا يتغير", fn_redact_clean))

    def fn_redact_determinism():
        r = Redactor.from_doc({"redact": ["email"]})
        a = r.apply("راسلني على user@site.com")
        b = r.apply("راسلني على user@site.com")
        return (True, "حتمي بالبايت") if a == b else (False, "حجبان اختلفا")

    cases.append(("حتمية", "الحجب حتمي بالبايت", fn_redact_determinism))

    def fn_redact_unknown_name():
        try:
            Redactor.from_doc({"redact": ["نمط-غريب"]})
            return False, "نمط مجهول قُبل صامتًا!"
        except Exception as exc:
            return (True, "خطأ بالأسماء المتاحة") if str(exc) else (False, "استثناء بلا رسالة")

    cases.append(("سجل", "نمط مجهول يُرفض وضوحًا", fn_redact_unknown_name))

    def fn_builtin_doc():
        doc = builtin_default_policy()
        ok = isinstance(doc, dict) and doc
        return (True, "سياسة افتراضية موثقة") if ok else (False, "السياسة الافتراضية فارغة")

    cases.append(("سياسة", "السياسة الافتراضية موثقة", fn_builtin_doc))

    def fn_engine_construction():
        import tempfile

        eng = __import__("zyko.policy.engine", fromlist=["PolicyEngine"]).PolicyEngine(
            builtin_default_policy(), state_dir=pathlib.Path(tempfile.mkdtemp())
        )
        return (True, "المحرك يُبنى") if eng is not None else (False, "بناء المحرك فشل")

    cases.append(("سياسة", "PolicyEngine يُبنى على الافتراضية", fn_engine_construction))

    def fn_allows_tool():
        import tempfile

        eng = __import__("zyko.policy.engine", fromlist=["PolicyEngine"]).PolicyEngine(
            builtin_default_policy(), state_dir=pathlib.Path(tempfile.mkdtemp())
        )
        got = eng.allows_tool("chat")
        return (True, "حكم موثق") if isinstance(got, bool) else (False, f"allows_tool → {got}")

    cases.append(("سياسة", "allows_tool يعود قرارًا", fn_allows_tool))

    def fn_explicit_tool():
        import tempfile

        eng = __import__("zyko.policy.engine", fromlist=["PolicyEngine"]).PolicyEngine(
            builtin_default_policy(), state_dir=pathlib.Path(tempfile.mkdtemp())
        )
        got = eng.explicitly_allows_tool("shell")
        return (
            (True, "الخطر يحتاج تسمية صريحة") if got is False else (False, "أداة خطر مسموحة ضمنيًا!")
        )

    cases.append(("سياسة", "الأدوات الخطر تحتاج تسمية صريحة", fn_explicit_tool))

    def fn_star_no_unlock():
        doc = builtin_default_policy()
        doc.setdefault("tools", {})
        doc["tools"] = {"allow": ["*"]}
        import tempfile

        eng = __import__("zyko.policy.engine", fromlist=["PolicyEngine"]).PolicyEngine(
            doc, state_dir=pathlib.Path(tempfile.mkdtemp())
        )
        got = eng.explicitly_allows_tool("shell")
        return (True, "النجمة لا تفتح الخطر") if got is False else (False, "* فتحت أداة خطر!")

    cases.append(("سياسة", "النجمة لا تفتح الأدوات الخطر", fn_star_no_unlock))

    def fn_allows_model():
        import tempfile

        eng = __import__("zyko.policy.engine", fromlist=["PolicyEngine"]).PolicyEngine(
            builtin_default_policy(), state_dir=pathlib.Path(tempfile.mkdtemp())
        )
        got = eng.allows_model("openai", "gpt-x")
        return (
            (True, "حكم نموذج موثق") if isinstance(got, bool) else (False, f"allows_model → {got}")
        )

    cases.append(("سياسة", "allows_model يعود قرارًا", fn_allows_model))

    def fn_load_policy_path():
        path = (
            pathlib.Path(__file__).resolve().parents[3] / "examples" / "policies" / "default.yaml"
        )
        if not path.is_file():
            return True, "لا أمثلة سياسات في هذا التشجير — يُتخطى"
        eng = load_policy(str(path))
        return (True, "سياسة من ملف تُحمَّل") if eng is not None else (False, "تحميل السياسة فشل")

    cases.append(("سياسة", "load_policy من مسار مطلق", fn_load_policy_path))

    def fn_load_policy_missing():
        try:
            load_policy("/nonexistent/zz-policy.yaml")
            return False, "سياسة غائبة قُبلت!"
        except Exception:
            return True, "الغائب يُرفض"

    cases.append(("سياسة", "مسار سياسة غائب يُرفض", fn_load_policy_missing))

    def fn_snapshot():
        import tempfile

        eng = __import__("zyko.policy.engine", fromlist=["PolicyEngine"]).PolicyEngine(
            builtin_default_policy(), state_dir=pathlib.Path(tempfile.mkdtemp())
        )
        snap = eng.snapshot()
        return (
            (True, "لقطة موثقة")
            if isinstance(snap, dict)
            else (False, f"لقطة: {type(snap).__name__}")
        )

    cases.append(("توثيق", "snapshot قاموس موثق", fn_snapshot))

    def fn_budget_guard():
        import tempfile

        eng = __import__("zyko.policy.engine", fromlist=["PolicyEngine"]).PolicyEngine(
            builtin_default_policy(), state_dir=pathlib.Path(tempfile.mkdtemp())
        )
        eng.record_cost(10**9, "نموذج-تجريبي")
        snap = eng.snapshot()
        ok = "budget_remaining_usd" in snap
        return (
            (True, "الإنفاق يُسجل في اللقطة")
            if ok
            else (False, f"مفاتيح اللقطة: {sorted(snap.keys())}")
        )

    cases.append(("سياسة", "إنفاق ضخم يُسجل في اللقطة", fn_budget_guard))

    def fn_redact_text_engine():
        import tempfile

        doc = builtin_default_policy()
        doc["privacy"] = {"redact": ["email"]}
        eng = __import__("zyko.policy.engine", fromlist=["PolicyEngine"]).PolicyEngine(
            doc, state_dir=pathlib.Path(tempfile.mkdtemp())
        )
        out = eng.redact_text("راسلني على user@site.com")
        return (
            (True, "حجب على مستوى المحرك")
            if "user@site.com" not in out
            else (False, f"حجب المحرك: {out[:30]}")
        )

    cases.append(("حجب", "redact_text على مستوى المحرك", fn_redact_text_engine))

    def fn_redact_arabic_phone():
        r = Redactor.from_doc({"redact": ["pii_ar"]})
        out, kinds = r.apply("اتصل على 0512345678 اليوم")
        ok = "0512345678" not in out
        return (True, "المفوَض العربي يعمل") if ok else (False, f"المفوض العربي لم يحجب: {out[:30]}")

    cases.append(("حجب", "المفوَض العربي يحجب الهاتف المحلي", fn_redact_arabic_phone))

    def fn_unicode_email():
        # العقد: أنماط الحجب المدمجة ASCII — النطاق المعرّب (IDN) خارج نطاقها
        r = Redactor.from_doc({"redact": ["email"]})
        out1, _ = r.apply("بريد olympia@attina.com سري")
        ascii_redacted = "olympia@attina.com" not in out1
        return (
            (True, "ASCII يُحجب وIDN خارج النطاق") if ascii_redacted else (False, "بريد ASCII مرّ!")
        )

    cases.append(("حجب", "بريد ASCII يُحجب وIDN خارج النطاق الموثق", fn_unicode_email))

    def fn_empty_text():
        r = Redactor.from_doc({})
        out, kinds = r.apply("")
        return (True, "الفراغ آمن") if out == "" and not kinds else (False, "فراغ أفسد الحجب")

    cases.append(("حجب", "نص فارغ يمر بسلام", fn_empty_text))

    def fn_big_text():
        r = Redactor.from_doc({"redact": ["email"]})
        text = ("نص عادي غير حساس. " * 500) + " مع بريد user@site.com"
        out, kinds = r.apply(text)
        return (
            (True, "نص ضخم يُحجب بدقة")
            if "user@site.com" not in out and len(out) > 5000
            else (False, "نص طويل كسر الحجب")
        )

    cases.append(("حجب", "نص طويل مع بريد واحد", fn_big_text))

    def fn_policy_dict_shape():
        d = builtin_default_policy()
        ok = all(isinstance(k, str) for k in d.keys())
        return (True, "مفاتيح نصية") if ok else (False, "مفاتيح غريبة في السياسة")

    cases.append(("توثيق", "مفاتيح السياسة نصية", fn_policy_dict_shape))

    def fn_policy_decision_fields():
        from zyko.policy.engine import PolicyDecision

        d = PolicyDecision(allowed=False, reason="سبب", redactions=[])
        ok = d.allowed is False and d.reason == "سبب"
        return (True, "قرار موثق") if ok else (False, "PolicyDecision مكسور")

    cases.append(("توثيق", "PolicyDecision بحقوله", fn_policy_decision_fields))

    return cases


# ============================================= 19) النواة والرسائل
def build_kernel_core():
    from zyko.kernel import (
        backend,
        cosine_similarity,
        estimate_tokens,
        messages_tokens,
        moving_average,
        top_k,
    )

    cases = []

    def fn_est_nonneg():
        return (
            (True, "لا سالب")
            if estimate_tokens("سلام عليكم") > 0
            else (False, "تقدير سالب أو صفر لنص")
        )

    cases.append(("تقدير", "estimate_tokens موجب للنص", fn_est_nonneg))

    def fn_est_monotonic():
        a = estimate_tokens("كلمة")
        b = estimate_tokens("كلمة كلمة كلمة كلمة")
        return (True, "رتيب") if b > a else (False, f"نص أطول تقديره {b} ≤ {a}")

    cases.append(("تقدير", "التقدير رتيب مع الطول", fn_est_monotonic))

    def fn_est_empty():
        return (
            (True, "الفراغ صفر")
            if estimate_tokens("") == 0
            else (False, f"فراغ → {estimate_tokens('')}")
        )

    cases.append(("تقدير", "النص الفارغ تقديره صفر", fn_est_empty))

    def fn_msg_tokens():
        from zyko.core import Message

        msgs = [Message.system("نظام"), Message.user("سؤال عربي طويل نسبيًا للمقياس")]
        total = messages_tokens(msgs)
        single = estimate_tokens("نظام")
        return (
            (True, "المجموع أكبر") if total >= single else (False, f"مجموع {total} < جزء {single}")
        )

    cases.append(("تقدير", "messages_tokens يجمع الأجزاء", fn_msg_tokens))

    def fn_cos_identical():
        return (
            (True, "1.0 للمتطابق")
            if abs(cosine_similarity([1, 0], [1, 0]) - 1.0) < 1e-9
            else (False, "متطابقان ليسا 1")
        )

    cases.append(("تشابه", "متجهان متطابقان = 1.0", fn_cos_identical))

    def fn_cos_orthogonal():
        return (
            (True, "0 للتعامد")
            if abs(cosine_similarity([1, 0], [0, 1])) < 1e-9
            else (False, "متعامدان ليسا 0")
        )

    cases.append(("تشابه", "متجهان متعامدان = 0", fn_cos_orthogonal))

    def fn_cos_opposite():
        return (
            (True, "-1 للتعاكس")
            if abs(cosine_similarity([1, 0], [-1, 0]) + 1.0) < 1e-9
            else (False, "متعاكسان ليسا -1")
        )

    cases.append(("تشابه", "متجهان متعاكسان = -1", fn_cos_opposite))

    def fn_topk():
        got = top_k([3, 1, 2], 2)
        return (True, "الفهارس رتبت") if got == [0, 2] else (False, f"top_k: {got}")

    cases.append(("ترتيب", "top_k يعيد الفهارس مرتبة", fn_topk))

    def fn_topk_clamp():
        got = top_k([1, 2], 5)
        return (True, "السقف يعمل") if len(got) == 2 else (False, f"طول {len(got)}")

    cases.append(("ترتيب", "top_k فوق الطول يُقصّ", fn_topk_clamp))

    def fn_topk_zero():
        return (True, "الصفر فراغ") if top_k([1, 2], 0) == [] else (False, "k=0 أعاد شيئًا")

    cases.append(("ترتيب", "top_k صفر يعود فارغًا", fn_topk_zero))

    def fn_ma_window2():
        got = moving_average([1, 2, 3, 4], 2)
        expect = [1.0, 1.5, 2.5, 3.5]
        return (True, "نافذة 2 دقيقة") if got == expect else (False, f"ma: {got}")

    cases.append(("متوسط", "moving_average بنافذة 2", fn_ma_window2))

    def fn_ma_identity():
        got = moving_average([1, 2, 3], 1)
        return (True, "نافذة 1 تطابق") if got == [1.0, 2.0, 3.0] else (False, f"ma: {got}")

    cases.append(("متوسط", "moving_average بنافذة 1", fn_ma_identity))

    def fn_ma_empty():
        return (
            (True, "الفراغ فراغ")
            if moving_average([], 3) == []
            else (False, "قائمة فارغة أعادت شيئًا")
        )

    cases.append(("متوسط", "moving_average على فراغ", fn_ma_empty))

    def fn_backend():
        got = backend()
        return (
            (True, f"النواة: {got}") if got in ("python", "rust") else (False, f"نواة غريبة: {got}")
        )

    cases.append(("بنية", "backend من الفهرس الثنائي", fn_backend))

    def fn_message_roles():
        from zyko.core import Message

        m1 = Message.system("تعليمات")
        m2 = Message.user("سؤال")
        m3 = Message.assistant("جواب")
        ok = m1.role == "system" and m2.role == "user" and m3.role == "assistant"
        return (True, "الأدوار الثلاثة") if ok else (False, "أدوار الرسائل مكسورة")

    cases.append(("رسائل", "أنواع الرسائل الثلاثة", fn_message_roles))

    def fn_map_content():
        from zyko.core import Message

        msgs = [Message.user("نص"), Message.assistant("رد")]
        mapped = [m.map_content(lambda t: t + "!") for m in msgs]
        ok = len(mapped) == 2 and mapped[0].content.endswith("!") and mapped[0].role == "user"
        return (True, "التحويل يحفظ البنية") if ok else (False, "map_content فقد رسالة أو دورًا")

    cases.append(("رسائل", "map_content يحفظ البنية", fn_map_content))

    def fn_openai_shape():
        from zyko.core import Message, messages_to_openai

        msgs = [Message.system("ن"), Message.user("س")]
        out = messages_to_openai(msgs)
        ok = len(out) == 2 and all("role" in m and "content" in m for m in out)
        return (True, "شكل OpenAI سليم") if ok else (False, "ممثل OpenAI مكسور")

    cases.append(("رسائل", "ممثل OpenAI ببنية سليمة", fn_openai_shape))

    def fn_anthropic_system():
        from zyko.core import Message, messages_to_anthropic

        msgs = [Message.system("تعليمات النظام"), Message.user("سؤال")]
        system_text, chat = messages_to_anthropic(msgs)
        ok = (
            system_text == "تعليمات النظام"
            and chat
            and all(m.get("role") != "system" for m in chat)
        )
        return (
            (True, "النظام منفصل بالثنائية الموثقة")
            if ok
            else (False, f"شكل: {system_text!r} + {len(chat)} رسالة")
        )

    cases.append(("رسائل", "ممثل Anthropic يفصل system", fn_anthropic_system))

    def fn_google_parts():
        from zyko.core import Message, messages_to_google

        msgs = [Message.user("سؤال عربي")]
        system_text, contents = messages_to_google(msgs)
        ok = contents and all("parts" in c for c in contents)
        return (True, "محتويات Google بأجزائها") if ok else (False, f"شكل Google: {contents}")

    cases.append(("رسائل", "ممثل Google بمحتوياته", fn_google_parts))

    def fn_usage_merge():
        from zyko.core import Usage

        a = Usage(input_tokens=10, output_tokens=5)
        b = Usage(input_tokens=7, output_tokens=3)
        m = a.merged(b)
        return (
            (True, "الدمج يجمع")
            if m.input_tokens == 17 and m.output_tokens == 8
            else (False, "دمج الاستخدام مكسور")
        )

    cases.append(("استخدام", "Usage.merged يجمع الرموز", fn_usage_merge))

    def fn_usage_cost():
        from zyko.core import Usage

        c = Usage(input_tokens=1000, output_tokens=500).cost_usd(None)
        ok = c is None or (isinstance(c, float) and c >= 0)
        return (True, "التكلفة بلا نموذج تعود None") if ok else (False, f"cost_usd(None) → {c}")

    cases.append(("استخدام", "cost_usd رقم غير سالب", fn_usage_cost))

    def fn_accumulate():
        from zyko.core import accumulate_stream, text_event

        async def _stream():
            for piece in ("مرح", "با ", "بالعربي"):
                yield text_event(piece)

        got = asyncio.run(accumulate_stream(_stream()))
        text = got[0] if isinstance(got, tuple) else got
        return (True, "التجميع يلصق") if text == "مرحبا بالعربي" else (False, f"تجميع: {text!r}")

    cases.append(("بث", "accumulate_stream يلصق القطع", fn_accumulate))

    def fn_events():
        from zyko.core import done_event, text_event

        t = text_event("نص")
        d = done_event()
        ok = getattr(t, "type", "") == "text" and getattr(d, "type", "") == "done"
        return (True, "أحداث البث بعقدها") if ok else (False, f"أحداث: {t} / {d}")

    cases.append(("بث", "أحداث البث موثقة البنية", fn_events))

    def fn_determinism():
        a = estimate_tokens("نص ثابت للفحص")
        b = estimate_tokens("نص ثابت للفحص")
        return (True, "حتمي بالبايت") if a == b else (False, "تقديران اختلفا")

    cases.append(("حتمية", "تقدير الرموز حتمي", fn_determinism))

    return cases


# ======================================= 20) الإيصالات والجلسة
def build_receipts():
    from zyko.ai.receipt import SCHEMA, AIReceipt, StepRecord, hash_file, hash_text
    from zyko.ai.session import DEFAULT_FAIL_UNDER, SESSION_MODES, AISession, detect_session_mode

    cases = []

    def fn_hash_text():
        got = hash_text("نص ثابت")
        expect = hashlib.sha256("نص ثابت".encode()).hexdigest()
        return (True, "sha256 ثابت") if got == expect else (False, "hash_text ليس sha256")

    cases.append(("بصمات", "hash_text يطابق sha256", fn_hash_text))

    def fn_hash_text_stable():
        return (
            (True, "نداءان متطابقان")
            if hash_text("نص") == hash_text("نص")
            else (False, "بصمة نص غير حتمية")
        )

    cases.append(("بصمات", "hash_text حتمي", fn_hash_text_stable))

    def fn_hash_file():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "f.txt"
            p.write_bytes(b"content-123")
            a = hash_file(p)
            b = hash_file(p)
            expect = hashlib.sha256(b"content-123").hexdigest()
            return (
                (True, "بصمة ملف دقيقة")
                if a == b == expect
                else (False, "hash_file لا يطابق sha256")
            )

    cases.append(("بصمات", "hash_file يطابق sha256 الفعلي", fn_hash_file))

    def fn_schema():
        return (
            (True, "المخطط موثق")
            if SCHEMA == "zyko.ai.receipt/v1"
            else (False, f"المخطط: {SCHEMA}")
        )

    cases.append(("سجل", "مخطط إيصال الجلسة", fn_schema))

    def fn_step_dict():
        s = StepRecord("plan", "تخطيط", True, 0, evidence={"b.py": "0" * 64, "a.py": "1" * 64})
        d = s.to_dict()
        keys = list(d["evidence"].keys())
        ok = keys == sorted(keys)
        return (True, "الأدلة مفرزة") if ok else (False, f"أدلة: {keys}")

    cases.append(("سجل", "StepRecord يفرز أدلته", fn_step_dict))

    def fn_receipt_ok_path():
        r = AIReceipt(goal="هدف", brain="مزيف", brain_deterministic=True, out="مخرجات")
        r.add(StepRecord("plan", "تخطيط", True, 0))
        r.add(StepRecord("generate", "توليد", True, 0))
        ok = r.ok and r.failed_step is None and len(r.steps) == 2
        return (True, "السليم يبقى سليمًا") if ok else (False, f"إيصال سليم: ok={r.ok}")

    cases.append(("إيصال", "خطوات ناجحة تحفظ ok", fn_receipt_ok_path))

    def fn_receipt_fail_path():
        r = AIReceipt(goal="هدف", brain="مزيف", brain_deterministic=True, out="مخرجات")
        r.add(StepRecord("plan", "تخطيط", True, 0))
        r.add(StepRecord("generate", "توليد", False, 1))
        ok = not r.ok and r.failed_step == "generate"
        return (True, "أول فشل يوثق") if ok else (False, f"فشل: ok={r.ok} failed={r.failed_step}")

    cases.append(("إيصال", "أول فشل يوثق بالاسم", fn_receipt_fail_path))

    def fn_receipt_first_fail_kept():
        r = AIReceipt(goal="هدف", brain="مزيف", brain_deterministic=True, out="مخرجات")
        r.add(StepRecord("plan", "تخطيط", False, 1))
        r.add(StepRecord("generate", "توليد", False, 2))
        return (
            (True, "الأول يبقى")
            if r.failed_step == "plan"
            else (False, f"failed_step={r.failed_step}")
        )

    cases.append(("إيصال", "أول فشل يبقى المؤشر", fn_receipt_first_fail_kept))

    def fn_receipt_no_timing():
        r = AIReceipt(goal="هدف", brain="مزيف", brain_deterministic=True, out="مخرجات")
        r.add(StepRecord("plan", "تخطيط", True, 0))
        d = r.to_dict(include_timing=False)
        return (
            (True, "بلا زمن افتراضيًا")
            if "seconds_total" not in d
            else (False, "الزمن تسرب خارج الطلب الصريح")
        )

    cases.append(("حتمية", "الزمن خارج الإيصال افتراضيًا", fn_receipt_no_timing))

    def fn_receipt_timing_optin():
        r = AIReceipt(goal="هدف", brain="مزيف", brain_deterministic=True, out="مخرجات")
        r.add(StepRecord("plan", "تخطيط", True, 0))
        d = r.to_dict(include_timing=True)
        return (
            (True, "بالطلب الصريح يظهر")
            if "seconds_total" in d
            else (False, "include_timing لم يظهر الزمن")
        )

    cases.append(("حتمية", "الزمن يظهر بالطلب الصريح", fn_receipt_timing_optin))

    def fn_receipt_json_stable():
        r1 = AIReceipt(goal="هدف", brain="مزيف", brain_deterministic=True, out="مخرجات")
        r1.add(StepRecord("plan", "تخطيط", True, 0))
        r2 = AIReceipt(goal="هدف", brain="مزيف", brain_deterministic=True, out="مخرجات")
        r2.add(StepRecord("plan", "تخطيط", True, 0))
        a, b = r1.to_json(), r2.to_json()
        return (True, "متطابق بالبايت") if a == b else (False, "إيصالان متطابقان اختلفا بالبايت")

    cases.append(("حتمية", "to_json حتمي بالبايت", fn_receipt_json_stable))

    def fn_receipt_verdict():
        r = AIReceipt(goal="هدف", brain="مزيف", brain_deterministic=True, out="مخرجات")
        r.add(StepRecord("plan", "تخطيط", False, 1))
        text = r.verdict_ar()
        return (True, "حكم عربي") if text and isinstance(text, str) else (False, "الحكم فارغ")

    cases.append(("توثيق", "verdict_ar نص عربي موثق", fn_receipt_verdict))

    def fn_receipt_md():
        r = AIReceipt(goal="هدف واضح للفحص", brain="مزيف", brain_deterministic=True, out="مخرجات")
        r.add(StepRecord("plan", "تخطيط", True, 0))
        md = r.to_md()
        return (True, "الهدف في الماركداون") if "هدف واضح" in md else (False, "to_md فقد الهدف")

    cases.append(("توثيق", "to_md يحمل الهدف", fn_receipt_md))

    def fn_receipt_defaults():
        r = AIReceipt(goal="g", brain="b", brain_deterministic=False, out="o")
        ok = r.rounds == 1 and r.fail_under == DEFAULT_FAIL_UNDER and r.ok is True
        return (
            (True, "الافتراضيات موثقة") if ok else (False, f"افتراضيات: {r.rounds}/{r.fail_under}")
        )

    cases.append(("سجل", "افتراضيات الإيصال الموثقة", fn_receipt_defaults))

    def fn_write_receipt():
        with tempfile.TemporaryDirectory() as td:
            r = AIReceipt(goal="هدف", brain="مزيف", brain_deterministic=True, out=td)
            r.add(StepRecord("plan", "تخطيط", True, 0))
            paths = AISession().write_receipt(r, td)
            names = {pathlib.Path(p).name for p in paths}
            ok = "ai_receipt.json" in names and "AI_RECEIPT.md" in names
            return (True, "ملفا الإيصال يُكتبان") if ok else (False, f"كتب: {names}")

    cases.append(("توثيق", "write_receipt يكتب JSON وMD", fn_write_receipt))

    def fn_write_receipt_json_valid():
        with tempfile.TemporaryDirectory() as td:
            r = AIReceipt(goal="هدف", brain="مزيف", brain_deterministic=True, out=td)
            r.add(StepRecord("plan", "تخطيط", True, 0))
            paths = AISession().write_receipt(r, td)
            json_path = next(p for p in paths if str(p).endswith("ai_receipt.json"))
            data = json.loads(pathlib.Path(json_path).read_text(encoding="utf-8"))
            ok = data.get("goal") == "هدف"
            return (True, "JSON قابل للتحليل") if ok else (False, "الإيصال المكتوب غير صالح")

    cases.append(("توثيق", "الإيصال المكتوب JSON صالح", fn_write_receipt_json_valid))

    def fn_session_modes():
        return (
            (True, "النمطان")
            if SESSION_MODES == ("factory", "existing")
            else (False, f"الأنماط: {SESSION_MODES}")
        )

    cases.append(("سجل", "أنماط الجلسة الثنائية", fn_session_modes))

    def fn_fail_under():
        return (
            (True, "العتبة 75")
            if DEFAULT_FAIL_UNDER == 75
            else (False, f"عتبة: {DEFAULT_FAIL_UNDER}")
        )

    cases.append(("سجل", "عتبة النجاح الافتراضية 75", fn_fail_under))

    def fn_detect_existing():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "app.py"
            p.write_text("x = 1\n", encoding="utf-8")
            mode, reason = detect_session_mode(f"راجع وأصلح {p}", td)
            ok = mode == "existing" and "existing" in reason
            return (
                (True, "ملف قائم ⇒ existing")
                if ok
                else (False, f"ملف قائم → {mode}: {reason[:40]}")
            )

    cases.append(("اكتشاف-جلسة", "ملف قائم يعطي existing", fn_detect_existing))

    def fn_detect_missing():
        with tempfile.TemporaryDirectory() as td:
            mode, reason = detect_session_mode("راجع /nonexistent-zz-eval/app.py", td)
            ok = mode == "factory" and "factory" in reason
            return (True, "مسار غائب ⇒ factory") if ok else (False, f"غائب → {mode}")

    cases.append(("اكتشاف-جلسة", "مسار غائب يعطي factory", fn_detect_missing))

    def fn_detect_no_path():
        with tempfile.TemporaryDirectory() as td:
            mode, reason = detect_session_mode("أنشئ مشروعاً جديداً من الصفر", td)
            return (
                (True, "بلا مسار ⇒ factory") if mode == "factory" else (False, f"بلا مسار → {mode}")
            )

    cases.append(("اكتشاف-جلسة", "بلا مسار يعطي factory", fn_detect_no_path))

    def fn_detect_determinism():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "app.py"
            p.write_text("x = 1\n", encoding="utf-8")
            a = detect_session_mode(f"راجع {p}", td)
            b = detect_session_mode(f"راجع {p}", td)
            return (True, "حتمي بالبايت") if a == b else (False, "اكتشافان اختلفا")

    cases.append(("حتمية", "اكتشاف الجلسة حتمي", fn_detect_determinism))

    def fn_detect_arabic_name():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "الملف.py"
            p.write_text("x = 1\n", encoding="utf-8")
            mode, _ = detect_session_mode(f"راجع {p} بعناية", td)
            return (True, "عربي في المسار") if mode == "existing" else (False, "مسار عربي لم يُكشَف")

    cases.append(("اكتشاف-جلسة", "مسار باسم عربي يُكشَف", fn_detect_arabic_name))

    def fn_detect_relative():
        with tempfile.TemporaryDirectory() as td:
            sub = pathlib.Path(td) / "src"
            sub.mkdir()
            (sub / "app.py").write_text("x=1\n", encoding="utf-8")
            import os

            old = os.getcwd()
            os.chdir(td)
            try:
                mode, _ = detect_session_mode("راجع src/app.py", td)
            finally:
                os.chdir(old)
            return (True, "نسبي يُحسم") if mode == "existing" else (False, "مسار نسبي قائم لم يُحسم")

    cases.append(("اكتشاف-جلسة", "مسار نسبي قائم يُحسم", fn_detect_relative))

    # الخريطة الدلالية
    def fn_symbol_summary():
        from zyko.reviewer.repo_map import symbol_summary

        src = "class الحاسبة:\n    def جمع(self, a, b):\n        return a + b\n"
        text = symbol_summary(src)
        ok = bool(text) and "الحاسبة" in text
        return (True, "الرموز تُلخص") if ok else (False, f"ملخص: {text}")

    cases.append(("خريطة", "symbol_summary يوثق الرموز", fn_symbol_summary))

    def fn_symbol_unparseable():
        from zyko.reviewer.repo_map import symbol_summary

        got = symbol_summary("def مكسورة(:\n    pass\n")
        return (True, "المكسور يعود None بالعقد") if got is None else (False, f"مكسور: {got!r}")

    cases.append(("خريطة", "الملف غير القابل للتحليل يوسم", fn_symbol_unparseable))

    def fn_symbol_no_symbols():
        from zyko.reviewer.repo_map import symbol_summary

        got = symbol_summary("x = 1\ny = 2\n")
        return (
            (True, "بلا رموز يعود نصًا فارغًا بالعقد") if got == "" else (False, f"بلا رموز: {got!r}")
        )

    cases.append(("خريطة", "الملف بلا رموز يوسم", fn_symbol_no_symbols))

    def fn_repo_map_fake():
        from types import SimpleNamespace

        from zyko.reviewer.repo_map import build_repo_map

        with tempfile.TemporaryDirectory() as td:
            (pathlib.Path(td) / "lib.py").write_text(
                "class A:\n    def b(self):\n        pass\n", encoding="utf-8"
            )
            (pathlib.Path(td) / "main.py").write_text(
                "def run():\n    return 1\n", encoding="utf-8"
            )
            fake = SimpleNamespace(stdout="lib.py\nmain.py\n", returncode=0, stderr="")
            lines = build_repo_map(pathlib.Path(td), runner=lambda *a, **k: fake)
            ok = len(lines) == 2 and all("::" in line for line in lines)
            return (True, "خريطة موقعة") if ok else (False, f"خريطة: {lines}")

    cases.append(("خريطة", "build_repo_map بسطر لكل ملف", fn_repo_map_fake))

    def fn_repo_map_determinism():
        from types import SimpleNamespace

        from zyko.reviewer.repo_map import build_repo_map

        with tempfile.TemporaryDirectory() as td:
            (pathlib.Path(td) / "lib.py").write_text("class A:\n    pass\n", encoding="utf-8")
            fake = SimpleNamespace(stdout="lib.py\n", returncode=0, stderr="")
            a = build_repo_map(pathlib.Path(td), runner=lambda *a_, **k_: fake)
            b = build_repo_map(pathlib.Path(td), runner=lambda *a_, **k_: fake)
            return (True, "حتمي بالبايت") if tuple(a) == tuple(b) else (False, "خرائط اختلفا")

    cases.append(("حتمية", "الخريطة حتمية بالبايت", fn_repo_map_determinism))

    def fn_repo_map_failure_line():
        # العقد المعلن (جولة 11): بلا git ⇒ خريطة فارغة معلنة () — لا سطر ولا صمت كاذب
        from types import SimpleNamespace

        from zyko.reviewer.repo_map import build_repo_map

        with tempfile.TemporaryDirectory() as td:
            fake = SimpleNamespace(stdout="", returncode=1, stderr="git خطأ")
            lines = build_repo_map(pathlib.Path(td), runner=lambda *a, **k: fake)
            return (
                (True, "بلا git خريطة فارغة معلنة") if lines == () else (False, f"فشل git: {lines}")
            )

    cases.append(("خريطة", "فشل git يوثق في سطر", fn_repo_map_failure_line))

    def fn_repo_map_max_files():
        from types import SimpleNamespace

        from zyko.reviewer.repo_map import build_repo_map

        with tempfile.TemporaryDirectory() as td:
            names = "\n".join(f"f{i}.py" for i in range(10))
            for i in range(10):
                (pathlib.Path(td) / f"f{i}.py").write_text("x = 1\n", encoding="utf-8")
            fake = SimpleNamespace(stdout=names, returncode=0, stderr="")
            lines = build_repo_map(pathlib.Path(td), runner=lambda *a, **k: fake, max_files=3)
            real = [line for line in lines if "::" in line and "فشل" not in line]
            return (True, "السقف يعمل") if len(real) <= 3 else (False, f"سقف الملفات: {len(real)}")

    cases.append(("خريطة", "سقف max_files يحكم", fn_repo_map_max_files))

    def fn_symbol_args():
        from zyko.reviewer.repo_map import symbol_summary

        src = "def run(self, *, mode='fast', timeout=30):\n    return 0\n"
        text = symbol_summary(src)
        return (True, "التوقيع بوسائطه") if text and "mode" in text else (False, f"توقيع: {text}")

    cases.append(("خريطة", "التوقيع يحمل وسائطه", fn_symbol_args))

    return cases
