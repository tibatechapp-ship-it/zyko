"""اختبارات محرك zyko.workspace: التكامل، الكتابة المحروسة، ومصائر الملاحظات.

العقد المُختبر هنا:
- مجلد قائم فيه أخطاء ⇒ مراجعة كاملة ثم إصلاحات فعلية بلا أي شبكة أو نموذج
- الافتراضي تجربة جافة: لا بايت واحد يتغير على القرص بلا إذن صريح
- كل ملاحظة في النتيجة تحمل suggestion_ar عربيًا غير فارغ
- الحتمية: تشغيلان على نسختين متطابقتين ⇒ حمولتان متطابقتان (بعد توحيد المسار)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from zyko.workspace.engine import (
    FILE_STATUS_SKIPPED,
    MAX_ROUNDS,
    SCHEMA,
    STAGE_FIXER,
    STAGE_REVIEWER,
    STAGE_SCAN,
    STAGE_WORKSPACE,
    VERDICT_ALL_SKIPPED,
    VERDICT_NO_PY,
    WRITE_COPY,
    WRITE_INPLACE,
    WRITE_NONE,
    WorkspaceEngine,
)

BUGGY = """import os


def flip(flag):
    return flag == None


retry = lambda n: n - 1


def guarded(block):
    try:
        block()
    except:
        raise ValueError("فشل")


def load(path):
    f = open(path)
    data = f.read()
    f.close()
    return data
"""

CLEAN = '''"""ملف نظيف تمامًا — يجب أن يبقى كما هو."""


def add(a: int, b: int) -> int:
    """يجمع عددين."""
    return a + b
'''


@pytest.fixture()
def engine():
    return WorkspaceEngine()


def _plant(tmp_path, files: dict[str, str]) -> "os.PathLike[str]":
    src = tmp_path / "proj"
    src.mkdir()
    for rel, content in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
    return src


def _snapshot(root) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


# ------------------------------------------------------------ التكامل
def test_end_to_end_reviews_and_fixes_existing_dir(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY, "clean_mod.py": CLEAN})
    r = engine.run(src, rounds=1)
    assert r.ok is True
    assert r.failed_stage is None
    assert r.files_total == 2
    assert r.reviewed == 2 and r.skipped == 0
    assert r.fixed_total > 0, "المرساة يجب أن تُظهر إصلاحات فعلية"
    assert r.changed_files == 1, "النظيف لا يتغير"
    assert r.min_score_after >= r.min_score_before, "لا تراجع في أدنى درجة"
    assert r.verdict_ar
    assert r.exit_code in (0, 1)
    assert SCHEMA == "zyko.workspace/1"


def test_every_outcome_carries_suggestion_ar(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    r = engine.run(src, rounds=1)
    assert r.ok
    assert r.per_file
    for f in r.per_file:
        for o in f["outcomes"]:
            assert o["suggestion_ar"], f"ملاحظة بلا إصلاح مقترح: {o['rule_id']}"
            assert o["message_ar"]


def test_fixed_finding_reports_fixer_action_ar(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    r = engine.run(src, rounds=1)
    fates = {o["rule_id"]: o for o in r.per_file[0]["outcomes"]}
    assert fates["R-QLT-206"]["status"] == "fixed"
    assert fates["R-QLT-206"]["action_ar"]
    manual = [o for o in fates.values() if o["status"] == "manual"]
    assert manual, "قواعد يدوية يجب أن تبقى يدويًا بتفسير عربي"
    for o in manual:
        assert o["action_ar"] == o["suggestion_ar"] or o["action_ar"]


def test_dry_run_is_the_default(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    before = _snapshot(src)
    r = engine.run(src, rounds=1)
    assert r.ok and r.write_mode == WRITE_NONE
    assert r.written == []
    assert _snapshot(src) == before, "التجربة الجافة تغيّرت فيها الملفات!"


def test_determinism_same_tree_same_bytes(engine, tmp_path):
    a = _plant(tmp_path, {"mod.py": BUGGY})
    b = tmp_path / "proj2"
    b.mkdir()
    (b / "mod.py").write_text(BUGGY, encoding="utf-8", newline="\n")
    r1 = engine.run(a, rounds=1)
    r2 = engine.run(b, rounds=1)
    d1, d2 = r1.to_dict(), r2.to_dict()
    d1["src"] = d2["src"] = "<anchor>"
    assert d1 == d2, "نفس الشجرة أعطت حمولتين مختلفتين"


def test_idempotence_on_own_output(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    first = engine.run(src, rounds=1)
    assert first.fixed_total > 0
    out = tmp_path / "final"
    out.mkdir()
    for rel, content in first.final_sources.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
    again = engine.run(out, rounds=1)
    assert again.ok
    assert again.changed_files == 0, "المحرك على ناتجه غيّر شيئًا!"


# ------------------------------------------------------------ الكتابة
def test_copy_writes_py_mirror_only(engine, tmp_path):
    src = _plant(tmp_path, {"pkg/mod.py": BUGGY, "clean_mod.py": CLEAN, "notes.txt": "نص"})
    out = tmp_path / "fixed"
    r = engine.run(src, rounds=1, write=WRITE_COPY, out_dir=out)
    assert r.ok
    assert out.is_dir()
    assert set(r.written) == {"pkg/mod.py"}
    assert (out / "pkg" / "mod.py").read_text(encoding="utf-8") == r.final_sources["pkg/mod.py"]
    assert (out / "clean_mod.py").read_text(encoding="utf-8") == CLEAN
    assert not (out / "notes.txt").exists(), "غير البايثون لا يُنسخ"
    assert any("لم تُنسخ" in n for n in r.notes)


def test_copy_refuses_non_empty_out_dir(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    out = tmp_path / "occupied"
    out.mkdir()
    (out / "يوجد.txt").write_text("لا تمسّني", encoding="utf-8")
    r = engine.run(src, write=WRITE_COPY, out_dir=out)
    assert not r.ok
    assert r.exit_code == 2
    assert r.failed_stage == STAGE_WORKSPACE
    assert "غير فارغ" in r.error_ar


def test_copy_requires_out_dir(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    r = engine.run(src, write=WRITE_COPY)
    assert not r.ok and r.exit_code == 2
    assert "out_dir" in r.error_ar


def test_inplace_requires_explicit_confirm(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    before = _snapshot(src)
    r = engine.run(src, write=WRITE_INPLACE)
    assert not r.ok
    assert "تأكيدًا صريحًا" in r.error_ar
    assert _snapshot(src) == before, "بلا تأكيد لمس الملفات!"


def test_inplace_with_confirm_writes_only_changed(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY, "clean_mod.py": CLEAN})
    clean_bytes = (src / "clean_mod.py").read_bytes()
    r = engine.run(src, rounds=1, write=WRITE_INPLACE, confirm_inplace=True)
    assert r.ok and r.write_mode == WRITE_INPLACE
    assert r.written == ["mod.py"]
    assert (src / "mod.py").read_text(encoding="utf-8") == r.final_sources["mod.py"]
    assert (src / "clean_mod.py").read_bytes() == clean_bytes


def test_out_and_inplace_together_rejected(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    r = engine.run(src, write=WRITE_INPLACE, out_dir=tmp_path / "x", confirm_inplace=True)
    assert not r.ok
    assert "لا كليهما" in r.error_ar


def test_out_dir_with_none_mode_rejected(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    r = engine.run(src, write=WRITE_NONE, out_dir=tmp_path / "x")
    assert not r.ok
    assert "copy" in r.error_ar


def test_unknown_write_mode_rejected(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    r = engine.run(src, write="حذف")
    assert not r.ok and r.failed_stage == STAGE_WORKSPACE


# ------------------------------------------------------------- الجولات
def test_rounds_zero_reviews_without_fixing(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    r = engine.run(src, rounds=0)
    assert r.ok and r.rounds_ran == 0
    assert r.fixed_total == 0 and r.changed_files == 0
    for f in r.per_file:
        for o in f["outcomes"]:
            if o["rule_id"] in ("R-QLT-206", "R-QLT-209"):
                assert o["status"] == "open"
                assert "جولات=0" in o["action_ar"]


def test_rounds_above_cap_is_capped_with_note(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    r = engine.run(src, rounds=99)
    assert r.ok
    assert r.rounds_requested == 99
    assert 1 <= r.rounds_ran <= MAX_ROUNDS
    assert any("السقف" in n for n in r.notes)


@pytest.mark.parametrize("bad", [-1, "كثيرة", True, 2.5, None])
def test_hostile_rounds_are_structured_failures(engine, tmp_path, bad):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    r = engine.run(src, rounds=bad)
    assert not r.ok
    assert r.exit_code == 2
    assert r.error_ar


# --------------------------------------------------------- مسارات فاسدة
@pytest.mark.parametrize("bad_src", [None, 42, 3.5, b"/tmp/bytes", ["قائمة"], True])
def test_hostile_src_types_are_structured_failures(engine, tmp_path, bad_src):
    r = engine.run(bad_src)
    assert not r.ok
    assert r.exit_code == 2
    assert r.failed_stage == STAGE_SCAN
    assert r.error_ar


def test_missing_dir_is_structured_failure(engine, tmp_path):
    r = engine.run(tmp_path / "لا-يوجد")
    assert not r.ok and r.failed_stage == STAGE_SCAN
    assert "غير موجود" in r.error_ar


def test_file_instead_of_dir_is_structured_failure(engine, tmp_path):
    p = tmp_path / "ملف.txt"
    p.write_text("ملف لا مجلد", encoding="utf-8")
    r = engine.run(p)
    assert not r.ok and "ليس مجلدًا" in r.error_ar


def test_empty_dir_is_no_py_success(engine, tmp_path):
    src = tmp_path / "فارغ"
    src.mkdir()
    r = engine.run(src)
    assert r.ok and r.verdict_ar == VERDICT_NO_PY
    assert r.exit_code == 0 and r.reviewed == 0


def test_txt_only_dir_is_no_py_success(engine, tmp_path):
    src = _plant(tmp_path, {})  # مجلد فارغ ثم نضيف نصًا
    (src / "notes.txt").write_text("نص", encoding="utf-8")
    r = engine.run(src)
    assert r.ok and r.verdict_ar == VERDICT_NO_PY


def test_all_unreadable_is_all_skipped_success(engine, tmp_path):
    src = tmp_path / "فاسد"
    src.mkdir()
    (src / "legacy.py").write_bytes("print('مرحبا')\n".encode("utf-16"))
    r = engine.run(src)
    assert r.ok
    assert r.verdict_ar == VERDICT_ALL_SKIPPED
    assert r.skipped == 1 and r.reviewed == 0
    assert r.per_file[0]["status"] == FILE_STATUS_SKIPPED
    assert "UTF-8" in r.per_file[0]["reason_ar"]
    assert r.exit_code == 0


def test_mixed_tree_skips_bad_and_fixes_good(engine, tmp_path):
    src = tmp_path / "مختلط"
    src.mkdir()
    (src / "legacy.py").write_bytes("x = 1\n".encode("utf-16"))
    (src / "broken.py").write_text("def half(:\n    return 1\n", encoding="utf-8")
    (src / "good.py").write_text(BUGGY, encoding="utf-8")
    r = engine.run(src, rounds=1)
    assert r.ok
    assert r.files_total == 3 and r.skipped == 1 and r.reviewed == 2
    assert r.fixed_total > 0
    by_path = {f["path"]: f for f in r.per_file}
    assert "UTF-8" in by_path["legacy.py"]["reason_ar"]
    assert by_path["broken.py"]["score_after"] == 0
    assert "خطأ صياغة" in by_path["broken.py"]["parse_error_ar"]
    assert by_path["good.py"]["score_after"] > by_path["good.py"]["score_before"]


def test_max_files_cap_truncates_with_note(engine, tmp_path, monkeypatch):
    src = tmp_path / "كثير"
    src.mkdir()
    for i in range(3):
        (src / f"m{i}.py").write_text(CLEAN, encoding="utf-8")
    monkeypatch.setattr("zyko.workspace.engine.MAX_FILES", 2)
    assert engine.run(src).ok is True  # فحص سلامة قبل استيراد الثابت المُعدَّل
    from zyko.workspace import engine as eng

    r = eng.WorkspaceEngine().run(src)
    assert r.files_total == 2
    assert any(str(eng.MAX_FILES) in n for n in r.notes)


# ------------------------------------------------- عطب المحركات المحقونة
def test_crashing_reviewer_is_structured(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})

    class Boom:
        def review_source(self, *_a, **_k):
            raise RuntimeError("انفجار مقصود")

    r = WorkspaceEngine(reviewer=Boom()).run(src)
    assert not r.ok
    assert r.failed_stage == STAGE_REVIEWER
    assert "عطب غير متوقع في المراجع" in r.error_ar


def test_crashing_fixer_is_structured(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})

    class Boom:
        def fix_source(self, *_a, **_k):
            raise RuntimeError("انفجار مقصود")

    r = WorkspaceEngine(fixer=Boom()).run(src)
    assert not r.ok
    assert r.failed_stage == STAGE_FIXER
    assert "عطب غير متوقع في المُصلِح" in r.error_ar


# --------------------------------------------------------- تفاصيل الحزمة
def test_symlinked_entries_are_skipped(engine, tmp_path):
    if os.name != "posix":
        pytest.skip("الروابط الرمزية على ويندوز تحتاج صلاحيات")
    src = _plant(tmp_path, {"mod.py": BUGGY})
    outside = tmp_path / "خارجي"
    outside.mkdir()
    (outside / "far.py").write_text(BUGGY, encoding="utf-8")
    (src / "link.py").symlink_to(outside / "far.py")
    r = engine.run(src, rounds=1)
    assert r.ok
    assert r.files_total == 1, "الرابط الرمزي دخل المسح!"


def test_arabic_file_names_are_reported(engine, tmp_path):
    src = _plant(tmp_path, {"ملف عربي.py": BUGGY})
    r = engine.run(src, rounds=1)
    assert r.ok
    assert r.per_file[0]["path"] == "ملف عربي.py"


def test_to_dict_shape_and_timing_opt_in(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    r = engine.run(src)
    d = r.to_dict()
    assert d["schema"] == SCHEMA
    assert "seconds" not in d
    assert "seconds" in r.to_dict(include_timing=True)
    assert d["ok"] is True and d["verdict_ar"]


# ------------------------------------------------------------ العيّنة
def _sample_dir() -> "object | None":
    root = Path(__file__).resolve().parent.parent / "samples" / "workspace" / "small_tool"
    return root if root.is_dir() else None


def test_sample_small_tool_matches_manifest():
    """عيّنة المستودع تعيد نفس المصائر الموثقة في manifest.json — حتمية العيّنة."""
    import json

    root = _sample_dir()
    if root is None:
        pytest.skip("عيّنة workspace غير موجودة")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    r = WorkspaceEngine().run(root, rounds=1)
    assert r.ok
    by_path = {f["path"]: f for f in r.per_file}
    for entry in manifest["files"]:
        f = by_path[entry["file"]]
        assert f["score_before"] == entry["score_before"], entry["file"]
        assert f["score_after"] == entry["score_after"], entry["file"]
        assert f["changed"] == entry["expect_changed"], entry["file"]
        fates: dict[str, list[str]] = {}
        for o in f["outcomes"]:
            fates.setdefault(o["status"], []).append(o["rule_id"])
        assert sorted(fates.get("fixed", [])) == sorted(entry["expect_fixed"]), entry["file"]
        assert sorted(fates.get("manual", [])) == sorted(entry["expect_manual"]), entry["file"]
        assert sorted(fates.get("open", [])) == sorted(entry["expect_open"]), entry["file"]
