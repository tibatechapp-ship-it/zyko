"""اختبارات zyko.coder.multiplan — محرك الترقيع متعدد الملفات.

العقود المُختبرة هنا:
- المسح بالشجرة يرى التعريفات والمراجع ولا يغلط في سلاسل ولا تعليقات
- المخطِّط يرفض الغموض دفعة واحدة: تعريف مزدوج، alias ملتقط، استيراد
  خارجي، اسم جديد مصادم، عقد قراءة
- التنفيذ صفقة: لقطة قبل أي كتابة، وتحقق صياغة من القرص، وتحقق تغطية
  بمسح جديد، وأي خرق بعد اللقطة يُرجع بالبايت
- الإيصال حتمي بالبايت: نفس الشجرة ⇒ نفس JSON ونفس بصمة السلسلة
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zyko.coder.multiplan import (
    MAX_PLAN_FILES,
    MultiFilePlan,
    MultiFilePlanError,
    MultiFileReceipt,
    PlanStep,
    apply_plan,
    build_rename_plan,
    find_symbol_references,
    rename_identifier_text,
)
from zyko.sandbox.contracts import PermissionContract


def _write(root: Path, files: dict[str, str]) -> None:
    for rel in sorted(files):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(files[rel], encoding="utf-8")


def _project(root: Path) -> None:
    """مشروع بذرة موحد: تعريف واحد ومرجعان واستيراد داخلي."""
    _write(
        root,
        {
            "core.py": "def calc(x):\n    return x * 2\n\n\ndef use(y):\n    return calc(y)\n",
            "app.py": "from core import calc\n\n\ndef run():\n    return calc(5)\n",
        },
    )


def _contract(root: Path, *, patch: bool = True) -> PermissionContract:
    return PermissionContract.for_roots(root, allow_patch=patch)


# ------------------------------------------------------------------ المسح
class TestScan:
    def test_def_and_references_found(self, tmp_path: Path) -> None:
        _project(tmp_path)
        scan = find_symbol_references(tmp_path, "calc")
        assert scan.definitions == (("core.py", 1),)
        assert "core.py" in scan.touched_paths and "app.py" in scan.touched_paths
        assert scan.files_scanned == 2

    def test_strings_and_comments_are_not_references(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                "core.py": 'def calc(x):\n    """calc يعني الحساب"""\n    # calc تعليق\n    return x\n',
            },
        )
        scan = find_symbol_references(tmp_path, "calc")
        assert scan.definitions == (("core.py", 1),)
        assert scan.references == ()

    def test_attribute_and_keyword_references(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {
                "a.py": ("def audit(items, limit=0):\n    return len(items) + limit\n"),
                "b.py": "import a\n\n\ndef go(x):\n    return a.audit(x)\n",
                "c.py": "from a import audit\n\n\ndef kw(x):\n    return audit(x, limit=1)\n",
            },
        )
        scan = find_symbol_references(tmp_path, "audit")
        assert set(scan.touched_paths) == {"a.py", "b.py", "c.py"}
        assert len(scan.references) == 2  # a.audit وaudit(x) — الوسيطة limit ليست audit

    def test_internal_import_declared(self, tmp_path: Path) -> None:
        _project(tmp_path)
        scan = find_symbol_references(tmp_path, "calc")
        assert scan.import_refs == (("app.py", 1),)
        assert scan.external_imports == ()

    def test_external_import_declared(self, tmp_path: Path) -> None:
        _write(tmp_path, {"x.py": "from os.path import join\nprint(join)\n"})
        scan = find_symbol_references(tmp_path, "join")
        assert scan.definitions == ()
        assert scan.external_imports == (("x.py", 1),)

    def test_alias_binding_declared(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {"a.py": "def calc(x):\n    return x\n", "b.py": "import json as calc\nprint(calc)\n"},
        )
        scan = find_symbol_references(tmp_path, "calc")
        assert scan.alias_bindings == (("b.py", 1),)

    def test_assign_definition_is_a_definition(self, tmp_path: Path) -> None:
        _write(tmp_path, {"cfg.py": "LIMIT = 7\n\n\ndef cap(n):\n    return min(n, LIMIT)\n"})
        scan = find_symbol_references(tmp_path, "LIMIT")
        assert scan.definitions == (("cfg.py", 1),)
        assert scan.references == (("cfg.py", 5),)  # سطر الاستخدام لا سطر الإسناد

    def test_invalid_symbol_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(MultiFilePlanError):
            find_symbol_references(tmp_path, "not a name")
        with pytest.raises(MultiFilePlanError):
            find_symbol_references(tmp_path, "class")

    def test_invalid_root_rejected(self) -> None:
        with pytest.raises(MultiFilePlanError):
            find_symbol_references("/nonexistent-root-zyko", "calc")

    def test_parse_failure_declared_by_name(self, tmp_path: Path) -> None:
        _write(tmp_path, {"good.py": "def calc():\n    return 1\n", "bad.py": "def broken(:\n"})
        scan = find_symbol_references(tmp_path, "calc")
        assert scan.parse_failures == ("bad.py",)
        assert scan.definitions == (("good.py", 1),)

    def test_sensitive_file_skipped_and_declared(self, tmp_path: Path, monkeypatch) -> None:
        import zyko.coder.multiplan as mp

        _write(tmp_path, {"core.py": "def calc():\n    return 1\n"})
        original = mp.is_sensitive_file

        def fake(path: object) -> bool:
            return original(path) or "core.py" in str(path)

        monkeypatch.setattr(mp, "is_sensitive_file", fake)
        scan = mp.find_symbol_references(tmp_path, "calc")
        assert scan.skipped_sensitive == ("core.py",)
        assert scan.definitions == ()

    def test_scan_deterministic_by_bytes(self, tmp_path: Path) -> None:
        _project(tmp_path)
        first = find_symbol_references(tmp_path, "calc").to_dict()
        second = find_symbol_references(tmp_path, "calc").to_dict()
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    def test_table_ar_summarizes(self, tmp_path: Path) -> None:
        _project(tmp_path)
        text = find_symbol_references(tmp_path, "calc").table_ar()
        assert "calc" in text and "التعريفات" in text and "المراجع" in text


# ------------------------------------------------------------------ الجراحة
class TestRenameSurgery:
    def test_def_call_attribute_keyword(self) -> None:
        src = (
            "def calc(x):\n"
            "    return x\n"
            "\n"
            "\n"
            "def go(m):\n"
            "    return m.calc(1) + calc(2)\n"
            "\n"
            "\n"
            "def kw(calc=None):\n"
            "    return calc\n"
        )
        out = rename_identifier_text(src, "calc", "compute")
        assert "def compute(x)" in out
        assert "m.compute(1)" in out and "compute(2)" in out
        assert "def kw(compute=None)" in out
        assert "calc" not in out

    def test_strings_and_comments_untouched(self) -> None:
        src = 'S = "calc هنا"\n# calc تعليق\ncalc = 1\n'
        out = rename_identifier_text(src, "calc", "compute")
        assert '"calc هنا"' in out
        assert "# calc تعليق" in out
        assert "compute = 1" in out

    def test_multiple_occurrences_one_line(self) -> None:
        out = rename_identifier_text("x = calc() + calc()\n", "calc", "f")
        assert out == "x = f() + f()\n"

    def test_keyword_only_when_exact(self) -> None:
        src = "calc_2 = 1\ncalc = 2\n"
        out = rename_identifier_text(src, "calc", "f")
        assert "calc_2" in out and out.endswith("f = 2\n")


# ------------------------------------------------------------------ المخطِّط
class TestBuildRenamePlan:
    def test_plan_covers_all_references(self, tmp_path: Path) -> None:
        _project(tmp_path)
        plan, scan = build_rename_plan(
            tmp_path, _contract(tmp_path), symbol="calc", new_name="compute"
        )
        assert plan.kind == "rename" and plan.symbol == "calc"
        assert {s.path for s in plan.steps} == set(scan.touched_paths)
        assert all(s.kind == "write" and s.content is not None for s in plan.steps)
        # نواتج الجراحة سليمة الصياغة ومفرغة من القديم
        for step in plan.steps:
            compile(step.content or "", step.path, "exec")
            assert "calc" not in (step.content or "")

    def test_rejects_same_name(self, tmp_path: Path) -> None:
        _project(tmp_path)
        with pytest.raises(MultiFilePlanError):
            build_rename_plan(tmp_path, _contract(tmp_path), symbol="calc", new_name="calc")

    def test_rejects_no_definition(self, tmp_path: Path) -> None:
        _write(tmp_path, {"a.py": "print(1)\n"})
        with pytest.raises(MultiFilePlanError):
            build_rename_plan(tmp_path, _contract(tmp_path), symbol="ghost", new_name="x")

    def test_rejects_multi_file_definition(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {"a.py": "def calc():\n    return 1\n", "b.py": "def calc():\n    return 2\n"},
        )
        with pytest.raises(MultiFilePlanError) as exc:
            build_rename_plan(tmp_path, _contract(tmp_path), symbol="calc", new_name="x")
        assert any("معرَّف في 2" in p for p in exc.value.problems)

    def test_rejects_alias_binding(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            {"a.py": "def calc():\n    return 1\n", "b.py": "import json as calc\nprint(calc)\n"},
        )
        with pytest.raises(MultiFilePlanError) as exc:
            build_rename_plan(tmp_path, _contract(tmp_path), symbol="calc", new_name="x")
        assert any("بأسماء مستعارة" in p for p in exc.value.problems)

    def test_rejects_external_definition(self, tmp_path: Path) -> None:
        _write(tmp_path, {"a.py": "from os.path import join\nprint(join)\n"})
        with pytest.raises(MultiFilePlanError) as exc:
            build_rename_plan(tmp_path, _contract(tmp_path), symbol="join", new_name="link")
        assert any("بلا تعريف" in p for p in exc.value.problems)

    def test_rejects_new_name_collision(self, tmp_path: Path) -> None:
        _project(tmp_path)
        with pytest.raises(MultiFilePlanError) as exc:
            build_rename_plan(tmp_path, _contract(tmp_path), symbol="calc", new_name="run")
        assert any("مستخدم أصلًا" in p for p in exc.value.problems)

    def test_rejects_read_only_contract(self, tmp_path: Path) -> None:
        _project(tmp_path)
        with pytest.raises(MultiFilePlanError):
            build_rename_plan(
                tmp_path, _contract(tmp_path, patch=False), symbol="calc", new_name="x"
            )

    def test_rejects_above_plan_cap(self, tmp_path: Path) -> None:
        files = {"core.py": "def calc():\n    return 1\n"}
        for i in range(MAX_PLAN_FILES + 1):
            files[f"f{i:03}.py"] = "from core import calc\nprint(calc())\n"
        _write(tmp_path, files)
        with pytest.raises(MultiFilePlanError) as exc:
            build_rename_plan(tmp_path, _contract(tmp_path), symbol="calc", new_name="x")
        assert any("فوق السقف" in p for p in exc.value.problems)

    def test_rejects_parse_failures(self, tmp_path: Path) -> None:
        _write(tmp_path, {"a.py": "def calc():\n    return 1\n", "bad.py": "def x(:\n"})
        with pytest.raises(MultiFilePlanError) as exc:
            build_rename_plan(tmp_path, _contract(tmp_path), symbol="calc", new_name="x")
        assert any("لا تُحلل صياغتها" in p for p in exc.value.problems)


# ------------------------------------------------------------------ الخطة
class TestPlanValidation:
    def _write_step(self, path: str, content: str) -> PlanStep:
        return PlanStep(path=path, kind="write", content=content, purpose_ar="اختبار")

    def test_empty_plan_rejected(self, tmp_path: Path) -> None:
        plan = MultiFilePlan(goal_ar="فارغة", kind="custom", steps=())
        problems = plan.validate(_contract(tmp_path))
        assert any("بلا خطوات" in p for p in problems)

    def test_duplicate_path_rejected(self, tmp_path: Path) -> None:
        step = self._write_step("a.py", "x = 1\n")
        plan = MultiFilePlan(goal_ar="مكررة", kind="custom", steps=(step, step))
        problems = plan.validate(_contract(tmp_path))
        assert any("يتكرر" in p for p in problems)

    def test_broken_python_content_rejected(self, tmp_path: Path) -> None:
        step = self._write_step("a.py", "def broken(:\n")
        plan = MultiFilePlan(goal_ar="مكسورة", kind="custom", steps=(step,))
        problems = plan.validate(_contract(tmp_path))
        assert any("مكسور الصياغة" in p for p in problems)

    def test_unknown_kind_rejected(self, tmp_path: Path) -> None:
        step = PlanStep(path="a.py", kind="chmod", purpose_ar="مجهول")
        plan = MultiFilePlan(goal_ar="مجهولة", kind="custom", steps=(step,))
        problems = plan.validate(_contract(tmp_path))
        assert any("نوع مجهول" in p for p in problems)

    def test_path_outside_contract_rejected(self, tmp_path: Path) -> None:
        step = self._write_step("../escape.py", "x = 1\n")
        plan = MultiFilePlan(goal_ar="هاربة", kind="custom", steps=(step,))
        problems = plan.validate(_contract(tmp_path))
        assert any("حارس المسار" in p for p in problems)

    def test_sensitive_target_rejected(self, tmp_path: Path) -> None:
        step = self._write_step(".env", "X=1\n")
        plan = MultiFilePlan(goal_ar="أسرار", kind="custom", steps=(step,))
        problems = plan.validate(_contract(tmp_path))
        assert any("حساس" in p for p in problems)

    def test_replace_step_contract(self, tmp_path: Path) -> None:
        good = PlanStep(path="a.py", kind="replace", old_text="x = 1", new_text="x = 2")
        no_old = PlanStep(path="b.py", kind="replace", new_text="y")
        plan = MultiFilePlan(goal_ar="استبدال", kind="custom", steps=(good, no_old))
        problems = plan.validate(_contract(tmp_path))
        assert any("بلا old_text" in p for p in problems)

    def test_to_json_is_sorted_and_stable(self, tmp_path: Path) -> None:
        _project(tmp_path)
        plan, _ = build_rename_plan(
            tmp_path, _contract(tmp_path), symbol="calc", new_name="compute"
        )
        assert plan.to_json() == plan.to_json()
        parsed = json.loads(plan.to_json())
        assert parsed["kind"] == "rename" and len(parsed["steps"]) == 2


# ------------------------------------------------------------------ التنفيذ
class TestApplyPlan:
    def test_successful_transaction(self, tmp_path: Path) -> None:
        _project(tmp_path)
        plan, _ = build_rename_plan(
            tmp_path, _contract(tmp_path), symbol="calc", new_name="compute"
        )
        receipt = apply_plan(_contract(tmp_path), plan, root=tmp_path)
        assert receipt.ok and receipt.applied and not receipt.rolled_back
        assert receipt.coverage_ok and receipt.files_touched == 2
        assert "compute" in (tmp_path / "core.py").read_text(encoding="utf-8")
        assert "calc" not in (tmp_path / "app.py").read_text(encoding="utf-8")

    def test_receipt_chain_deterministic(self, tmp_path: Path) -> None:
        _project(tmp_path)
        plan, _ = build_rename_plan(
            tmp_path, _contract(tmp_path), symbol="calc", new_name="compute"
        )
        first = apply_plan(_contract(tmp_path), plan, root=tmp_path)
        _project(tmp_path)  # أعد البذر لنفس الحالة
        second = apply_plan(_contract(tmp_path), plan, root=tmp_path)
        assert first.chain_sha256 == second.chain_sha256
        assert first.to_json() == second.to_json()

    def test_static_rejection_without_writes(self, tmp_path: Path) -> None:
        _project(tmp_path)
        step = PlanStep(path="a.py", kind="write", content="x = 1\n", purpose_ar="اختبار")
        plan = MultiFilePlan(goal_ar="مرفوضة", kind="custom", steps=(step,))
        receipt = apply_plan(_contract(tmp_path, patch=False), plan, root=tmp_path)
        assert not receipt.ok and not receipt.applied and not receipt.rolled_back
        assert "قراءة فقط" in receipt.reason_ar
        # القرص لم يُلمس
        assert (tmp_path / "core.py").read_text(encoding="utf-8").startswith("def calc")

    def test_mid_plan_failure_rolls_back(self, tmp_path: Path) -> None:
        _project(tmp_path)
        plan = MultiFilePlan(
            goal_ar="صفقة تنكسر وسطًا",
            kind="custom",
            steps=(
                PlanStep(
                    path="core.py",
                    kind="write",
                    content="def calc(x):\n    return 99\n",
                    purpose_ar="سليمة",
                ),
                PlanStep(
                    path="app.py",
                    kind="replace",
                    old_text="النص غير موجود",
                    new_text="y",
                    purpose_ar="كاسرة",
                ),
            ),
        )
        receipt = apply_plan(_contract(tmp_path), plan, root=tmp_path)
        assert not receipt.ok and receipt.rolled_back
        assert receipt.restored_paths == ("core.py",)
        assert "return 99" not in (tmp_path / "core.py").read_text(encoding="utf-8")
        assert "return x * 2" in (tmp_path / "core.py").read_text(encoding="utf-8")

    def test_post_write_syntax_failure_rolls_back(self, tmp_path: Path) -> None:
        _project(tmp_path)
        plan = MultiFilePlan(
            goal_ar="استبدال يكسر الصياغة",
            kind="custom",
            steps=(
                PlanStep(
                    path="core.py",
                    kind="write",
                    content="def calc(x):\n    return 5\n",
                    purpose_ar="سليمة",
                ),
                PlanStep(
                    path="app.py",
                    kind="replace",
                    old_text="from core import calc",
                    new_text="from core import calc\ndef broken(:",
                    purpose_ar="كاسرة الصياغة",
                ),
            ),
        )
        receipt = apply_plan(_contract(tmp_path), plan, root=tmp_path)
        assert not receipt.ok and receipt.rolled_back and receipt.syntax_failures
        assert "return x * 2" in (tmp_path / "core.py").read_text(encoding="utf-8")

    def test_missing_coverage_rolls_back(self, tmp_path: Path) -> None:
        _project(tmp_path)
        # خطة يدوية تلمس التعريف وتترك app.py المرجعي خارجها
        plan = MultiFilePlan(
            goal_ar="خطة ناقصة التغطية",
            kind="rename",
            symbol="calc",
            new_name="compute",
            steps=(
                PlanStep(
                    path="core.py",
                    kind="write",
                    content="def compute(x):\n    return x * 2\n",
                    purpose_ar="تعريف فقط",
                ),
            ),
        )
        receipt = apply_plan(_contract(tmp_path), plan, root=tmp_path)
        assert not receipt.ok and receipt.rolled_back
        assert receipt.coverage_detail.get("old_left", 0) > 0
        assert "def calc" in (tmp_path / "core.py").read_text(encoding="utf-8")

    def test_verify_off_skips_coverage(self, tmp_path: Path) -> None:
        _project(tmp_path)
        step = PlanStep(
            path="core.py",
            kind="write",
            content="def calc(x):\n    return 3\n",
            purpose_ar="بلا تحقق",
        )
        plan = MultiFilePlan(goal_ar="بلا تغطية", kind="custom", steps=(step,))
        receipt = apply_plan(_contract(tmp_path), plan, root=tmp_path, verify_coverage=False)
        assert receipt.ok and receipt.coverage_ok is False and receipt.applied

    def test_snapshot_failure_aborts_before_writes(self, tmp_path: Path) -> None:
        _project(tmp_path)
        (tmp_path / "core.py").chmod(0o000)
        plan = MultiFilePlan(
            goal_ar="لقطة فاشلة",
            kind="custom",
            steps=(
                PlanStep(path="app.py", kind="write", content="x = 1\n", purpose_ar="أولى"),
                PlanStep(path="core.py", kind="write", content="x = 2\n", purpose_ar="ثانية"),
            ),
        )
        try:
            receipt = apply_plan(_contract(tmp_path), plan, root=tmp_path)
        finally:
            (tmp_path / "core.py").chmod(0o644)
        assert not receipt.ok and not receipt.applied
        # app.py لم يُكتب — الصفقة تُرفض قبل أي كتابة
        assert (tmp_path / "app.py").read_text(encoding="utf-8").startswith("from core")

    def test_replace_transaction_success(self, tmp_path: Path) -> None:
        _project(tmp_path)
        plan = MultiFilePlan(
            goal_ar="استبدال سليم",
            kind="custom",
            steps=(
                PlanStep(
                    path="core.py",
                    kind="replace",
                    old_text="return x * 2",
                    new_text="return x * 3",
                    purpose_ar="نشر",
                ),
            ),
        )
        receipt = apply_plan(_contract(tmp_path), plan, root=tmp_path, verify_coverage=False)
        assert receipt.ok and not receipt.rolled_back
        assert "return x * 3" in (tmp_path / "core.py").read_text(encoding="utf-8")

    def test_receipt_type_and_dict(self, tmp_path: Path) -> None:
        _project(tmp_path)
        plan, _ = build_rename_plan(
            tmp_path, _contract(tmp_path), symbol="calc", new_name="compute"
        )
        receipt = apply_plan(_contract(tmp_path), plan, root=tmp_path)
        assert isinstance(receipt, MultiFileReceipt)
        parsed = json.loads(receipt.to_json())
        assert parsed["applied"] is True and parsed["files_touched"] == 2


# ------------------------------------------------------------------ السطر
class TestCli:
    def test_scan_and_rename_and_reject(self, tmp_path: Path, capsys) -> None:
        from zyko.coder.multiplan import _cli_main

        _project(tmp_path)
        assert _cli_main(["scan", "--root", str(tmp_path), "--symbol", "calc"]) == 0
        assert (
            _cli_main(
                ["rename", "--root", str(tmp_path), "--symbol", "calc", "--new-name", "compute"]
            )
            == 0
        )
        assert "بلا كتابة" in capsys.readouterr().out
        assert (
            _cli_main(["rename", "--root", str(tmp_path), "--symbol", "calc", "--new-name", "run"])
            == 1
        )  # run معرّف أصلًا في app.py — الاسم مصادم فتُرفض الخطة
