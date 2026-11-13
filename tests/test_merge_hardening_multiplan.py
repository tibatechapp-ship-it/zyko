"""تحصين ما بعد الدمج — محرك الترقيع متعدد الملفات (جولة 17).

‏`zyko.coder.multiplan` هو أحدث محرك في المستودع: مسح بالشجرة، رفض
الخطة إن تركت مرجعًا، وصفقة تُرجع بالبايت. فشل CI بعد الدمج كشف أن
فروعًا موثقة في الوحدة نفسها لم تُختبر قط — هنا يُختبر كل عقد بمثال
حقيقي على قرص مؤقت: استيراد نسبي، سقوف مسح، جراحة معرفية لا تلمس
سلسلة، إرجاع صفقة عند خرق، وبصمة إيصال حتمية بالبايت.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

from zyko.coder.multiplan import (
    MAX_PLAN_FILES,
    MultiFilePlan,
    MultiFilePlanError,
    PlanStep,
    _common_root,
    _module_of,
    _resolve_import_target,
    _text_token_count,
    apply_plan,
    build_rename_plan,
    find_symbol_references,
    rename_identifier_text,
)
from zyko.sandbox.contracts import PermissionContract

HELPER = "def calc(x):\n    return x\n"
APP = 'from helpers import calc\n\ns = "calc"  # سلسلة وتعليق لا يُسلمان للجراحة\n\nprint(calc(1))\nprint(calc(x=2))\n'


def _contract(tmp_path: Path, **kw: object) -> PermissionContract:
    return PermissionContract.for_roots(tmp_path, allow_patch=True, **kw)  # type: ignore[arg-type]


def _write(tmp_path: Path, rel: str, content: str) -> None:
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


# ------------------------------------------------------------------ أسماء الوحدات
def test_module_of_non_python_path_is_none() -> None:
    """مسار بلا لاحقة .py ليس وحدة — None صريح لا تخمين."""
    assert _module_of("notes.txt") is None
    assert _module_of("") is None


@pytest.mark.parametrize(
    ("rel", "expected"),
    [("pkg/__init__.py", "pkg"), ("a/b/c.py", "a.b.c")],
    ids=["package-init", "nested"],
)
def test_module_of_maps_paths_to_dotted_modules(rel: str, expected: str) -> None:
    """خريطة الوحدات: a/b.py ⇒ a.b وpkg/__init__.py ⇒ pkg — أساس فرز الاستيراد."""
    assert _module_of(rel) == expected


# ------------------------------------------------------------------ الاستيراد النسبي
def test_resolve_relative_import_level1_is_internal() -> None:
    """‏from .pkg import calc داخل حزمة — الهدف يُحسم داخليًا لا يُطرد خارجيًا."""
    import ast

    node = ast.parse("from .pkg import calc\n").body[0]
    assert _resolve_import_target("app/mod.py", node) == "app/pkg"


def test_resolve_relative_import_beyond_package_root_is_none() -> None:
    """‏from ... import x من عمق لا يحتمله الملف — None (خارج الجذور)."""
    import ast

    node = ast.parse("from ...deep import calc\n").body[0]
    assert _resolve_import_target("app/mod.py", node) is None


def test_resolve_relative_import_from_dot_only_yields_package() -> None:
    """‏from . import calc — الهدف حزمة الملف نفسها بلا لاحقة."""
    import ast

    node = ast.parse("from . import calc\n").body[0]
    assert _resolve_import_target("app/mod.py", node) == "app"


# ------------------------------------------------------------------ سقوف المسح
def test_scan_stops_at_max_files_cap(tmp_path: Path) -> None:
    """سقف ملفات المسح معلن: فوق السقف لا يُقرأ — والعدّ يوثق ما مُسح فعلاً."""
    _write(tmp_path, "a.py", HELPER)
    _write(tmp_path, "b.py", "print(calc(1))\n")
    scan = find_symbol_references(tmp_path, "calc", max_files=1)
    assert scan.files_scanned == 1
    assert scan.definitions and not scan.references  # b.py لم يمسح أصلًا


def test_scan_reports_oversized_files_not_silently_skip(tmp_path: Path) -> None:
    """ملف فوق سقف البايتات يُعلن متجاوَزًا بالاسم — لا تجاهل صامت."""
    _write(tmp_path, "a.py", HELPER)
    _write(tmp_path, "big.py", "# " + "ث" * 100 + "\nprint(calc(1))\n")
    scan = find_symbol_references(tmp_path, "calc", max_file_bytes=50)
    assert scan.skipped_oversized == ("big.py",)


def test_scan_reports_undecodable_file_as_parse_failure(tmp_path: Path) -> None:
    """ملف بترميز مكسور يُعلن في parse_failures — لا انهيار ولا إقصاء صامت."""
    _write(tmp_path, "a.py", HELPER)
    (tmp_path / "ثنائي.py").write_bytes(b"\xff\xfe\x00 broken")
    scan = find_symbol_references(tmp_path, "calc")
    assert scan.parse_failures == ("ثنائي.py",)
    assert scan.definitions  # السليم واصل رغم التالف


# ------------------------------------------------------------------ شجرة التعريف والمرجع
def test_annassign_target_is_a_definition(tmp_path: Path) -> None:
    """‏calc: int = 5 إسناد مشروح — تعريف لا مرجع (لا يعاد تسمية هدفه مرتين)."""
    _write(tmp_path, "a.py", "calc: int = 5\nprint(calc)\n")
    scan = find_symbol_references(tmp_path, "calc")
    assert scan.definitions == (("a.py", 1),)
    assert scan.references == (("a.py", 2),)


def test_keyword_argument_name_is_a_reference(tmp_path: Path) -> None:
    """‏calc(x=2) وسيطة مسماة — مرجع معرفي يُعاد تسميته لا نص يُتجاهل."""
    _write(tmp_path, "a.py", "def calc(x):\n    return x\ncalc(x=1)\n")
    scan = find_symbol_references(tmp_path, "calc")
    assert ("a.py", 3) in scan.references


def test_plain_import_module_statement_is_import_ref(tmp_path: Path) -> None:
    """‏import calc استيراد وحدة باسم الرمز — مرجع معرفي موثق في import_refs."""
    _write(tmp_path, "calc.py", "X = 1\n")
    _write(tmp_path, "app.py", "import calc\nprint(calc.X)\n")
    scan = find_symbol_references(tmp_path, "calc")
    assert ("app.py", 1) in scan.import_refs


@pytest.mark.parametrize(
    "symbol",
    ["not an id", "class", "9lives"],
    ids=["space", "keyword", "starts-with-digit"],
)
def test_scan_rejects_invalid_symbols_with_arabic_reason(tmp_path: Path, symbol: str) -> None:
    """رمز غير معرف (فراغ/كلمة مفتاحية/فراغ/رقم أول) يُرفض برسالة عربية."""
    with pytest.raises(MultiFilePlanError, match="معرف"):
        find_symbol_references(tmp_path, symbol)


def test_scan_rejects_missing_root_directory(tmp_path: Path) -> None:
    """جذر غير قائم يُرفض — لا مسح على وهم."""
    with pytest.raises(MultiFilePlanError, match="مجلد"):
        find_symbol_references(tmp_path / "لا-يوجد", "calc")


# ------------------------------------------------------------------ الجراحة المعرفية
def test_rename_on_untokenizable_source_raises_arabic() -> None:
    """نص لا يُرمَّز (قوس بلا إغلاق) يُرفض — لا جراحة عمياء على رقعة غير آمنة."""
    with pytest.raises(MultiFilePlanError, match="لا يُرمَّز"):
        rename_identifier_text("x = (1,\n", "x", "y")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('s = "calc"\n', 's = "calc"\n'),
        ("obj.calc()\n", "obj.compute()\n"),
        ("def calc():\n    return calc\n", "def compute():\n    return compute\n"),
    ],
    ids=["string-untouched", "attribute-renamed", "def-and-use-renamed"],
)
def test_rename_identifier_surgery_is_token_precise(source: str, expected: str) -> None:
    """الجراحة بالـtokenize: سلسلة وتعليق يُسلَمان، واسم وتعريف ووصول تُعاد."""
    assert rename_identifier_text(source, "calc", "compute") == expected


def test_text_token_count_counts_identifiers_only() -> None:
    """عدّاد المعرفات يحكي الحقيقة: سلسلة لا تحسب، وكسر الترميز يعيد -1."""
    assert _text_token_count('calc("calc")', "calc") == 1
    assert _text_token_count("x = (1,\n", "calc") == -1


# ------------------------------------------------------------------ الخطوات والتحقق
def test_plan_step_replace_to_dict_hashes_both_sides() -> None:
    """خطوة استبدال تُوثَّق ببصمتي الطرفين — القديم والجديد بالمتن نفسه."""
    step = PlanStep(path="a.py", kind="replace", old_text="x", new_text="y")
    d = step.to_dict()
    assert d["old_sha256"] != d["new_sha256"]
    assert "content_sha256" not in d


def test_plan_step_write_to_dict_measures_bytes_not_time() -> None:
    """خطوة كتابة تُوثَّق بطول بايتات المحتوى وبصمته — لا أي زمن."""
    step = PlanStep(path="a.py", kind="write", content="x = 1\n")
    d = step.to_dict()
    assert d["content_bytes"] == 6
    assert d["content_sha256"] != ""


def test_validate_rejects_plan_over_file_cap() -> None:
    """خطة فوق سقف 64 ملفًا تُرفض — الرقعة الأكبر تُقسَّم لا تُدفَع عمياء."""
    steps = tuple(
        PlanStep(path=f"f{i}.py", kind="write", content="x = 1\n")
        for i in range(MAX_PLAN_FILES + 1)
    )
    problems = MultiFilePlan(kind="custom", goal_ar="g", steps=steps).validate()
    assert any("سقف" in p for p in problems)


@pytest.mark.parametrize(
    ("step", "marker"),
    [
        (PlanStep(path="", kind="write", content="x = 1\n"), "مسار فارغ"),
        (PlanStep(path="a.py", kind="write", content=None), "بلا محتوى"),
        (PlanStep(path="a.py", kind="replace", old_text="x", new_text=None), "بلا new_text"),
        (PlanStep(path="a.py", kind="zap", content="x"), "نوع مجهول"),
        (PlanStep(path="a.py", kind="write", content="def :(\n"), "مكسور الصياغة"),
    ],
    ids=["empty-path", "no-content", "no-new-text", "unknown-kind", "broken-python"],
)
def test_validate_rejects_each_malformed_step(step: PlanStep, marker: str) -> None:
    """كل خطوة مشوهة تُرفض بمشكلة عربية مسماة — دفعة واحدة لا أول خطأ فقط."""
    problems = MultiFilePlan(kind="custom", goal_ar="g", steps=(step,)).validate()
    assert any(marker in p for p in problems), problems


def test_validate_rejects_step_outside_contract_roots(tmp_path: Path) -> None:
    """حارس مسار العقد يرفض الهروب بـ..‎ خارج الجذور — والخارج لا يُلمس."""
    allowed = tmp_path / "مسموح"
    allowed.mkdir()
    contract = PermissionContract.for_roots(allowed, allow_patch=True)
    step = PlanStep(path="../هروب.py", kind="write", content="x = 1\n")
    problems = MultiFilePlan(kind="custom", goal_ar="g", steps=(step,)).validate(contract)
    assert any("خارج" in p for p in problems)


# ------------------------------------------------------------------ رفض المخطِّط
def test_build_rejects_invalid_old_and_new_symbols_together(tmp_path: Path) -> None:
    """الرمزان السيئان يُرفضان دفعة واحدة — لا رفض أول ثم اكتشاف لاحق."""
    contract = _contract(tmp_path)
    with pytest.raises(MultiFilePlanError) as excinfo:
        build_rename_plan(tmp_path, contract, symbol="9lives", new_name="for")
    assert len(excinfo.value.problems) == 2


def test_build_rejects_same_name(tmp_path: Path) -> None:
    """إعادة تسمية إلى الاسم نفسه = لا تغيير — رفض صادق."""
    with pytest.raises(MultiFilePlanError, match="مطابق"):
        build_rename_plan(tmp_path, _contract(tmp_path), symbol="calc", new_name="calc")


def test_build_rejects_read_only_contract(tmp_path: Path) -> None:
    """عقد قراءة فقط لا يبني خطة كتابة — النية تُعلن في العقد لا في العلم."""
    _write(tmp_path, "a.py", HELPER)
    readonly = PermissionContract.for_roots(tmp_path, allow_patch=False)
    with pytest.raises(MultiFilePlanError, match="قراءة فقط"):
        build_rename_plan(tmp_path, readonly, symbol="calc", new_name="compute")


@pytest.mark.parametrize(
    ("layout", "marker"),
    [
        (("ref-only",), "بلا تعريف"),
        (("two-defs",), "الغموض مرفوض"),
        (("alias",), "أسماء مستعارة"),
        (("external",), "خارج الجذور"),
    ],
    ids=["no-definition", "ambiguous-defs", "alias-binding", "external-import"],
)
def test_build_rejection_matrix_covers_every_documented_refusal(
    tmp_path: Path, layout: tuple[str], marker: str
) -> None:
    """مصفوفة الرفض الموثقة: كل فجوة تغطية تُرفض قبل أي حساب محتوى."""
    if layout == ("ref-only",):
        _write(tmp_path, "app.py", "print(calc(1))\n")
    elif layout == ("two-defs",):
        _write(tmp_path, "a.py", HELPER)
        _write(tmp_path, "b.py", HELPER)
    elif layout == ("alias",):
        _write(tmp_path, "helpers.py", "def base():\n    return 1\n")
        _write(tmp_path, "app.py", "from helpers import base as calc\nprint(calc())\n")
    else:
        _write(tmp_path, "app.py", "from ext_lib import calc\nprint(calc())\n")
    with pytest.raises(MultiFilePlanError, match=marker):
        build_rename_plan(tmp_path, _contract(tmp_path), symbol="calc", new_name="compute")


def test_build_rejects_new_name_already_in_use(tmp_path: Path) -> None:
    """الاسم الجديد موجود أصلًا = خلط رمزين — رفض قبل أي كتابة."""
    _write(tmp_path, "a.py", HELPER)
    _write(tmp_path, "c.py", "def compute():\n    return 1\n")
    with pytest.raises(MultiFilePlanError, match="مستخدم أصلًا"):
        build_rename_plan(tmp_path, _contract(tmp_path), symbol="calc", new_name="compute")


def test_build_rejects_reference_file_over_scan_cap(tmp_path: Path) -> None:
    """ملف مرجعي فوق سقف المسح يرفض الخطة كها — تغطية ناقصة رفض لا تجاهل."""
    _write(tmp_path, "a.py", HELPER)
    pad = 'X = "' + "ث" * 1_100_000 + '"\n'
    _write(tmp_path, "big.py", pad + "print(calc(1))\n")
    with pytest.raises(MultiFilePlanError, match="فوق سقف المسح"):
        build_rename_plan(tmp_path, _contract(tmp_path), symbol="calc", new_name="compute")


def test_happy_plan_covers_every_touched_file_and_applies_by_bytes(tmp_path: Path) -> None:
    """الطريق السعيد الكامل: خطة تغطي كل ملف مرجعي، تطبيق بايتي، وتغطية مقاسة."""
    _write(tmp_path, "helpers.py", HELPER)
    _write(tmp_path, "app.py", APP)
    plan, scan = build_rename_plan(tmp_path, _contract(tmp_path), symbol="calc", new_name="compute")
    assert scan.touched_paths == ("app.py", "helpers.py")
    assert len(plan.steps) == 2
    receipt = apply_plan(_contract(tmp_path), plan, root=tmp_path)
    assert receipt.ok and receipt.applied and receipt.coverage_ok
    assert receipt.files_touched == 2
    new_app = (tmp_path / "app.py").read_text(encoding="utf-8")
    assert 's = "calc"' in new_app  # السلسلة سليمة — الجراحة معرفية
    assert "compute(x=2)" in new_app and "calc(" not in new_app.replace('s = "calc"', "")


# ------------------------------------------------------------------ التنفيذ والصفقة
def test_apply_infers_root_from_contract_for_single_file(tmp_path: Path) -> None:
    """بلا جذر معلن: أول مسار يجتاز العقد يحدد الجذر العملي — والصفقة تتم."""
    _write(tmp_path, "pkg/m.py", HELPER)
    step = PlanStep(
        path="pkg/m.py",
        kind="write",
        content=rename_identifier_text(HELPER, "calc", "compute"),
    )
    plan = MultiFilePlan(
        goal_ar="g", kind="rename", steps=(step,), symbol="calc", new_name="compute"
    )
    receipt = apply_plan(_contract(tmp_path), plan, root=None)
    assert receipt.ok and receipt.coverage_ok


def test_apply_infers_nested_common_root_from_second_step(tmp_path: Path) -> None:
    """خطوتان تحت حزمة واحدة: الجذر المشترك يُستنتج بعرض الشجرة (b تحت a)."""
    _write(tmp_path, "pkg/a.py", HELPER)
    _write(tmp_path, "pkg/b.py", "print(calc(1))\n")
    steps = tuple(
        PlanStep(
            path=rel,
            kind="write",
            content=rename_identifier_text(
                (tmp_path / rel).read_text(encoding="utf-8"), "calc", "compute"
            ),
        )
        for rel in ("pkg/a.py", "pkg/b.py")
    )
    plan = MultiFilePlan(goal_ar="g", kind="rename", steps=steps, symbol="calc", new_name="compute")
    receipt = apply_plan(_contract(tmp_path), plan, root=None)
    assert receipt.ok and receipt.files_touched == 2


def test_apply_infers_common_root_for_sibling_directories(tmp_path: Path) -> None:
    """مجلدان شقيقان: commonpath يرفع الجذر إلى المشترك — والتحقق يشمل الاثنين."""
    _write(tmp_path, "x/a.py", HELPER)
    _write(tmp_path, "y/b.py", "print(calc(1))\n")
    steps = tuple(
        PlanStep(
            path=rel,
            kind="write",
            content=rename_identifier_text(
                (tmp_path / rel).read_text(encoding="utf-8"), "calc", "compute"
            ),
        )
        for rel in ("x/a.py", "y/b.py")
    )
    plan = MultiFilePlan(goal_ar="g", kind="rename", steps=steps, symbol="calc", new_name="compute")
    receipt = apply_plan(_contract(tmp_path), plan, root=None)
    assert receipt.ok and receipt.files_touched == 2


def test_apply_without_root_rejects_second_step_outside_contract(tmp_path: Path) -> None:
    """محاولة عبور حدود العقد بمسار ثانٍ (..‎/خارج) تُرفض قبل أي لقطة."""
    _write(tmp_path, "a.py", HELPER)
    steps = (
        PlanStep(
            path="a.py", kind="write", content=rename_identifier_text(HELPER, "calc", "compute")
        ),
        PlanStep(path="../خارج.py", kind="write", content="x = 1\n"),
    )
    plan = MultiFilePlan(goal_ar="g", kind="rename", steps=steps, symbol="calc", new_name="compute")
    receipt = apply_plan(_contract(tmp_path), plan, root=None)
    assert not receipt.ok and "خارج" in receipt.reason_ar


def test_apply_rejects_missing_root_directory(tmp_path: Path) -> None:
    """جذر تنفيذ غير قائم = رفض صريح — لا إنشاء مجلدات على وهم."""
    _write(tmp_path, "a.py", HELPER)
    plan = MultiFilePlan(
        goal_ar="g",
        kind="rename",
        steps=(
            PlanStep(
                path="a.py", kind="write", content=rename_identifier_text(HELPER, "calc", "compute")
            ),
        ),
        symbol="calc",
        new_name="compute",
    )
    receipt = apply_plan(_contract(tmp_path), plan, root=tmp_path / "لا-يوجد")
    assert not receipt.ok and "مجلد" in receipt.reason_ar


def test_apply_snapshot_rejects_target_over_contract_byte_cap(tmp_path: Path) -> None:
    """ملف هدف فوق سقف بايتات العقد يُرفض عند اللقطة — الصفقة كاملة لا نصف ترقيع."""
    _write(tmp_path, "a.py", "x = 1\n" + "# " + "ث" * 40 + "\n")
    plan = MultiFilePlan(
        goal_ar="g",
        kind="custom",
        steps=(PlanStep(path="a.py", kind="write", content="x = 2\n"),),
    )
    receipt = apply_plan(_contract(tmp_path, max_file_bytes=16), plan, root=tmp_path)
    assert not receipt.ok and "سقف" in receipt.reason_ar


def test_apply_snapshot_rejects_undecodable_target(tmp_path: Path) -> None:
    """هدف بترميز مكسور يُرفض قبل أي كتابة — الصفقة تُسقط كاملة."""
    (tmp_path / "a.py").write_bytes(b"\xff\xfe\x00 broken")
    plan = MultiFilePlan(
        goal_ar="g",
        kind="custom",
        steps=(PlanStep(path="a.py", kind="write", content="x = 2\n"),),
    )
    receipt = apply_plan(_contract(tmp_path), plan, root=tmp_path)
    assert not receipt.ok and "قراءة" in receipt.reason_ar


def test_apply_write_step_creates_new_file_with_syntax_verified(tmp_path: Path) -> None:
    """كتابة ملف جديد: لقطة فارغة موثقة، إنشاء ذري، وصياغة موثقة من القرص."""
    plan = MultiFilePlan(
        goal_ar="g",
        kind="custom",
        steps=(PlanStep(path="جديد.py", kind="write", content="def hi():\n    return 1\n"),),
    )
    receipt = apply_plan(_contract(tmp_path), plan, root=tmp_path)
    assert receipt.ok and receipt.syntax_verified
    assert (tmp_path / "جديد.py").read_text(encoding="utf-8").startswith("def hi")


def test_apply_non_python_step_skips_syntax_check(tmp_path: Path) -> None:
    """خطوة .txt لا تدخل فحص الصياغة البايثوني — والنجاح موثق بلا ادعاء."""
    plan = MultiFilePlan(
        goal_ar="g",
        kind="custom",
        steps=(PlanStep(path="ملاحظات.txt", kind="write", content="نص عادي\n"),),
    )
    receipt = apply_plan(_contract(tmp_path), plan, root=tmp_path)
    assert receipt.ok and receipt.syntax_verified


def test_apply_midway_failure_rolls_back_applied_files_by_bytes(tmp_path: Path) -> None:
    """خرق في الخطوة الثانية يوقظ الإرجاع: الملف المطبَّق يعود بايتاته الأصلية."""
    _write(tmp_path, "f1.py", "x = 1\n")
    _write(tmp_path, "f2.py", "y = 2\n")
    steps = (
        PlanStep(path="f1.py", kind="write", content="x = 10\n"),
        PlanStep(path="f2.py", kind="replace", old_text="نص-غير-موجود", new_text="y = 20\n"),
    )
    plan = MultiFilePlan(goal_ar="g", kind="custom", steps=steps)
    receipt = apply_plan(_contract(tmp_path), plan, root=tmp_path)
    assert receipt.applied and receipt.rolled_back and not receipt.ok
    assert receipt.restored_paths == ("f1.py",)
    assert (tmp_path / "f1.py").read_text(encoding="utf-8") == "x = 1\n"
    assert "أُرجع 1" in receipt.reason_ar


def test_apply_rolls_back_when_late_reference_leaves_old_name_alive(tmp_path: Path) -> None:
    """ملف جديد يحيل الاسم القديم بعد بناء الخطة (سباق الحياة الواقعي) — الصفقة تُرجع."""
    _write(tmp_path, "a.py", HELPER)
    plan, _scan = build_rename_plan(
        tmp_path, _contract(tmp_path), symbol="calc", new_name="compute"
    )
    _write(tmp_path, "متأخر.py", "from a import calc\nprint(calc(9))\n")  # ظهر بعد البناء
    receipt = apply_plan(_contract(tmp_path), plan, root=tmp_path)
    assert receipt.rolled_back and not receipt.coverage_ok
    assert receipt.coverage_detail.get("old_left", 0) > 0
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == HELPER  # بايتات أصلية


# ------------------------------------------------------------------ الجذر المشترك وسطر الأوامر
def test_common_root_returns_the_ancestor_that_contains_both(tmp_path: Path) -> None:
    """أقرب جذر مشترك: الاحتواء يعيد السلف المشترك ثم commonpath للشقاق."""
    a = tmp_path / "pkg"
    b = tmp_path / "pkg" / "sub"
    assert _common_root(a, b) == a  # السلف المحتوي هو الجذر المشترك
    assert _common_root(a, a) == a  # النفس يبقى نفسه
    x = tmp_path / "x"
    y = tmp_path / "y"
    assert _common_root(x, y) == tmp_path  # شقّان: commonpath يرفع للمشترك


def test_cli_scan_rejects_invalid_symbol_with_arabic_rc1(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """‏scan على رمز غير معرف يطبع رفضًا عربيًا ويخرج برمز 1."""
    from zyko.coder.multiplan import _cli_main

    assert _cli_main(["scan", "--root", str(tmp_path), "--symbol", "غير-صالح"]) == 1
    assert "رفض المسح" in capsys.readouterr().out


def test_module_main_entrypoint_runs_scan_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """‏python -m zyko.coder.multiplan scan يعمل من __main__ نفسه — نقطة الدخول."""
    _write(tmp_path, "a.py", HELPER)
    monkeypatch.setattr(
        sys, "argv", ["multiplan", "scan", "--root", str(tmp_path), "--symbol", "calc"]
    )
    sys.modules.pop("zyko.coder.multiplan", None)  # إعادة تنفيذ نظيفة بلا تحذير الكاش
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("zyko.coder.multiplan", run_name="__main__")
    assert excinfo.value.code == 0
    assert "مسح الرمز" in capsys.readouterr().out
