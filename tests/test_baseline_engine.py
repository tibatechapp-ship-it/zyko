"""اختبارات محرك zyko.baseline: خط الأساس، كشف التراجع والتحسن، والحتمية.

العقد المُختبر هنا:
- update يسجّل حالة القرص الفعلية ويكتب ملفًا واحدًا فقط بلا طوابع زمنية
- check قراءة فقط: لا يكتب بايتًا واحدًا مهما كانت الظروف
- التراجع (درجة أقل أو ملاحظات جديدة) يُكشف ويُسمّى بالملف (خروج 1)
- التحسن والملفات الجديدة والمفقودة والمتخطاة كلها موثقة بأرقام
- الحتمية: شجرتان متطابقتان ⇒ نفس بايتات خط الأساس ونفس الحمولة
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zyko.baseline.engine import (
    BASELINE_DIRNAME,
    BASELINE_FILENAME,
    F_GONE,
    F_IMPROVED,
    F_NEW,
    F_REGRESSED,
    F_UNCHANGED,
    HISTORY_CAP,
    SCHEMA,
    VERDICT_MISSING,
    BaselineEngine,
    default_baseline_path,
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
"""

CLEAN = '''"""ملف نظيف تمامًا — يجب أن يبقى كما هو."""


def add(a: int, b: int) -> int:
    """يجمع عددين."""
    return a + b
'''


def _plant(tmp_path: Path, files: dict[str, object], name: str = "proj") -> Path:
    src = tmp_path / name
    src.mkdir()
    for rel, content in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(str(content), encoding="utf-8", newline="\n")
    return src


@pytest.fixture()
def engine():
    return BaselineEngine()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


# ------------------------------------------------------------ update
def test_update_creates_deterministic_baseline(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY, "clean.py": CLEAN})
    r = engine.update(src)
    assert r.ok and r.exit_code == 0
    assert r.created and r.run_no == 1
    assert r.reviewed == 2 and r.skipped == 0
    assert r.min_score is not None and 0 <= r.min_score <= 100
    assert r.findings_total > 0  # BUGGY فيه ملاحظات
    bfile = src / BASELINE_DIRNAME / BASELINE_FILENAME
    assert bfile.is_file()
    stored = json.loads(bfile.read_text(encoding="utf-8"))
    assert stored["schema"] == SCHEMA
    assert stored["run_no"] == 1
    assert stored["history"][-1]["run_no"] == 1
    assert "mod.py" in stored["files"] and "clean.py" in stored["files"]
    rec = stored["files"]["clean.py"]
    assert rec["score"] == 100 and rec["findings"] == []
    assert len(rec["sha256"]) == 64
    # لا طوابع زمنية إطلاقًا: كل المفاتيح أعلاه حتمية


def test_update_writes_only_the_baseline_file(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    before = _snapshot(src)
    r = engine.update(src)
    after = _snapshot(src)
    assert r.ok
    new = set(after) - set(before)
    assert new == {str(Path(BASELINE_DIRNAME) / BASELINE_FILENAME)}
    # مشروعك لم يُمس: بايتات الملفات الأصلية كما هي
    for rel in before:
        assert after[rel] == before[rel]


def test_update_twice_bumps_run_no_and_history(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    r1 = engine.update(src)
    r2 = engine.update(src)
    assert r1.ok and r2.ok
    assert not r2.created and r2.run_no == 2
    assert r2.history_len == 2
    stored = json.loads((src / BASELINE_DIRNAME / BASELINE_FILENAME).read_text("utf-8"))
    assert [h["run_no"] for h in stored["history"]] == [1, 2]


def test_update_history_capped(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    for _ in range(HISTORY_CAP + 4):
        r = engine.update(src)
        assert r.ok
    assert r.history_len == HISTORY_CAP
    stored = json.loads((src / BASELINE_DIRNAME / BASELINE_FILENAME).read_text("utf-8"))
    runs = [h["run_no"] for h in stored["history"]]
    assert runs == list(range(HISTORY_CAP + 4 - HISTORY_CAP + 1, HISTORY_CAP + 4 + 1))


def test_update_identical_trees_give_identical_bytes(engine, tmp_path):
    files = {"pkg/a.py": BUGGY, "pkg/b.py": CLEAN, "notes.txt": "ليس بايثون"}
    src1 = _plant(tmp_path, files, name="one")
    src2 = _plant(tmp_path, files, name="two")
    r1, r2 = engine.update(src1), engine.update(src2)
    assert r1.ok and r2.ok
    b1 = src1 / BASELINE_DIRNAME / BASELINE_FILENAME
    b2 = src2 / BASELINE_DIRNAME / BASELINE_FILENAME
    assert b1.read_bytes() == b2.read_bytes()


def test_update_over_corrupt_baseline_recovers(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    assert engine.update(src).ok
    bfile = src / BASELINE_DIRNAME / BASELINE_FILENAME
    bfile.write_text("{ليس json", encoding="utf-8")
    r = engine.update(src)
    assert r.ok and r.run_no == 1 and r.created
    assert any("من جديد" in n for n in r.notes)
    assert json.loads(bfile.read_text("utf-8"))["schema"] == SCHEMA


def test_update_empty_dir_succeeds_without_review(engine, tmp_path):
    src = tmp_path / "empty"
    src.mkdir()
    r = engine.update(src)
    assert r.ok and r.reviewed == 0 and r.min_score is None
    assert r.verdict_ar == "لا مراجعة — لا ملفات بايثون في المجلد"


def test_skipped_files_are_not_stored(engine, tmp_path):
    u16 = "def س(ن):\n    return ن\n".encode("utf-16")
    src = _plant(tmp_path, {"mod.py": BUGGY, "legacy.py": u16})
    r = engine.update(src)
    assert r.ok and r.reviewed == 1 and r.skipped == 1
    stored = json.loads((src / BASELINE_DIRNAME / BASELINE_FILENAME).read_text("utf-8"))
    assert "legacy.py" not in stored["files"]
    # ثم صار مقروءًا ⇒ «جديد» في الفحص التالي
    (src / "legacy.py").write_text("X = 1\n", encoding="utf-8")
    chk = engine.check(src)
    entry = next(f for f in chk.per_file if f["path"] == "legacy.py")
    assert entry["status"] == F_NEW


# ------------------------------------------------------------- check
def test_check_without_baseline_is_documented_not_failure(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    r = engine.check(src)
    assert r.ok and r.baseline_status == "missing"
    assert r.exit_code == 1
    assert r.verdict_ar == VERDICT_MISSING
    assert not (src / BASELINE_DIRNAME).exists()  # check لا يكتب شيئًا


def test_check_same_tree_is_clean_and_writes_nothing(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY, "clean.py": CLEAN})
    assert engine.update(src).ok
    before = _snapshot(src)
    r = engine.check(src)
    assert r.ok and r.exit_code == 0
    assert r.regressed_files == 0 and r.unchanged_files == 2
    assert r.verdict_ar == "الجودة ثابتة — لا تراجع ولا تحسن منذ خط الأساس"
    assert _snapshot(src) == before  # قراءة فقط دائمًا


def test_check_detects_regression_names_file_and_counts(engine, tmp_path):
    src = _plant(tmp_path, {"good.py": CLEAN, "other.py": "Y = 2\n"})
    assert engine.update(src).ok
    (src / "good.py").write_text(
        CLEAN + "\n\n\ndef probe(x):\n    return eval(x)\n", encoding="utf-8"
    )
    r = engine.check(src)
    assert r.ok and r.exit_code == 1
    assert r.regressed_files == 1 and r.new_findings_total >= 1
    hit = next(f for f in r.per_file if f["path"] == "good.py")
    assert hit["status"] == F_REGRESSED
    assert hit["score_current"] < hit["score_baseline"]
    assert hit["new_findings"] >= 1
    assert hit["sha_changed"] is True
    assert "تراجع" in r.verdict_ar
    untouched = next(f for f in r.per_file if f["path"] == "other.py")
    assert untouched["status"] == F_UNCHANGED


def test_check_detects_improvement_and_suggests_update(engine, tmp_path):
    src = _plant(tmp_path, {"bad.py": BUGGY, "good.py": CLEAN})
    assert engine.update(src).ok
    (src / "bad.py").write_text(CLEAN, encoding="utf-8")
    r = engine.check(src)
    assert r.ok and r.exit_code == 0
    assert r.improved_files == 1 and r.resolved_findings_total > 0
    hit = next(f for f in r.per_file if f["path"] == "bad.py")
    assert hit["status"] == F_IMPROVED
    assert hit["score_current"] > hit["score_baseline"]
    assert "تحسّن" in r.verdict_ar and "update" in r.verdict_ar


def test_check_reports_new_and_gone_files(engine, tmp_path):
    src = _plant(tmp_path, {"a.py": CLEAN})
    assert engine.update(src).ok
    (src / "a.py").unlink()
    (src / "new.py").write_text(BUGGY, encoding="utf-8")
    r = engine.check(src)
    assert r.ok
    assert r.gone_files == 1 and r.new_files == 1
    statuses = {f["path"]: f["status"] for f in r.per_file}
    assert statuses["a.py"] == F_GONE
    assert statuses["new.py"] == F_NEW


def test_check_skipped_file_now_is_skipped_not_gone(engine, tmp_path):
    u16 = "def س(ن):\n    return ن\n".encode("utf-16")
    src = _plant(tmp_path, {"legacy.py": u16, "a.py": CLEAN})
    # الملف غير قابل للمراجعة عند التحديث ⇒ ليس في خط الأساس
    assert engine.update(src).ok
    # اجعله ملفًا كسر القراءة: استبدله بمجلد — المسح يتخطاه دون مراجعة
    (src / "a.py").unlink()
    (src / "a.py").mkdir()
    r = engine.check(src)
    assert r.ok
    assert r.gone_files == 1  # a.py اختفت (صارت مجلدًا)


def test_check_zero_reviewed_with_existing_baseline_flags_attention(engine, tmp_path):
    src = _plant(tmp_path, {"a.py": CLEAN})
    assert engine.update(src).ok
    (src / "a.py").unlink()
    r = engine.check(src)
    assert r.ok and r.reviewed == 0
    assert "القياس متوقف" in r.verdict_ar
    assert r.exit_code == 1


def test_check_custom_baseline_path(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    custom = tmp_path / "guard" / "baseline.json"
    r1 = engine.update(src, baseline_path=custom)
    assert r1.ok and r1.baseline_path == str(custom)
    assert custom.is_file()
    r2 = engine.check(src, baseline_path=custom)
    assert r2.ok and r2.exit_code == 0 and r2.baseline_status == "ok"


def test_default_baseline_path_helper(tmp_path):
    p = default_baseline_path(tmp_path)
    assert p == tmp_path / ".zyko" / "baseline.json"
    assert BASELINE_DIRNAME == ".zyko" and BASELINE_FILENAME == "baseline.json"


def test_update_structured_failures(engine, tmp_path):
    missing = engine.update(tmp_path / "لا-يوجد")
    assert not missing.ok and missing.exit_code == 2 and missing.error_ar
    assert missing.failed_stage == "scan"
    as_file = tmp_path / "f.txt"
    as_file.write_text("x", encoding="utf-8")
    r = engine.update(as_file)
    assert not r.ok and "ليس مجلدًا" in r.error_ar
    src = _plant(tmp_path, {"a.py": CLEAN})
    r2 = engine.update(src, baseline_path="")
    assert not r2.ok and "فارغ" in r2.error_ar
    r3 = engine.update(src, baseline_path=b"bytes-path")
    assert not r3.ok and "bytes" in r3.error_ar
    bdir = tmp_path / "bdir"
    bdir.mkdir()
    r4 = engine.update(src, baseline_path=bdir)
    assert not r4.ok and "مجلد لا ملف" in r4.error_ar


def test_check_corrupt_baseline_is_structured_failure(engine, tmp_path):
    src = _plant(tmp_path, {"mod.py": BUGGY})
    bad = tmp_path / "bad.json"
    bad.write_text("{ليس json", encoding="utf-8")
    r = engine.check(src, baseline_path=bad)
    assert not r.ok and r.exit_code == 2
    assert r.failed_stage == "baseline"
    assert "update" in r.error_ar  # طريق الإصلاح موثق في الرسالة


def test_result_to_dict_is_json_and_deterministic(engine, tmp_path):
    files = {"mod.py": BUGGY, "clean.py": CLEAN}
    src1 = _plant(tmp_path, files, name="p1")
    src2 = _plant(tmp_path, files, name="p2")
    u1, u2 = engine.update(src1), engine.update(src2)
    d1, d2 = u1.to_dict(), u2.to_dict()
    d1["src"] = d2["src"] = d1["baseline_path"] = d2["baseline_path"] = "<x>"
    assert json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True)
    c1 = engine.check(src1)
    c2 = engine.check(src2)
    e1, e2 = c1.to_dict(), c2.to_dict()
    e1["src"] = e2["src"] = e1["baseline_path"] = e2["baseline_path"] = "<x>"
    assert json.dumps(e1, sort_keys=True) == json.dumps(e2, sort_keys=True)
    # include_timing يضيف seconds فقط
    t = engine.update(src1).to_dict(include_timing=True)
    assert "seconds" in t and "seconds" not in u1.to_dict()
