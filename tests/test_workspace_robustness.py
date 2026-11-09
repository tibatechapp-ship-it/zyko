"""اختبارات متانة zyko.workspace القصوى: ما لم يغطه المحرك يغطيه هذا الملف.

العقد المُختبر هنا:
- أي مدخل عدائي ⇒ نتيجة مهيكلة (failed_stage + سبب عربي + خروج 2) بلا استثناء
- ملفات فاسدة (ترميز/حجم/صلاحيات) تُتخطى بتوثيق عربي ولا تُسقط التشغيل
- محركات محقونة منهارة تُصدَّر فشلًا مهيكلاً لا انهيارًا
- الفشل نفسه حتمي: تشغيلان عدائيان متطابقان ⇒ حمولتان متطابقتان
"""

from __future__ import annotations

import os
import stat

import pytest

from zyko.workspace.engine import (
    STAGE_FIXER,
    STAGE_REVIEWER,
    STAGE_SCAN,
    WorkspaceEngine,
)

BUGGY = "import os\n\n\ndef f(x):\n    return x == None\n"
CLEAN = '"""نظيف."""\n\n\ndef add(a, b):\n    """يجمع."""\n    return a + b\n'


@pytest.fixture()
def engine():
    return WorkspaceEngine()


def _plant(tmp_path, name="proj", **files):
    src = tmp_path / name
    src.mkdir()
    for rel, content in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
    return src


# --------------------------------------------------- مدخلات مسار عدائية
@pytest.mark.parametrize(
    "bad", [None, 42, 3.5, b"/tmp/bytes", {"dict": 1}, ["list"], True, "", "   "]
)
def test_hostile_src_never_raises(engine, bad):
    r = engine.run(bad)
    assert not r.ok
    assert r.exit_code == 2
    assert r.failed_stage == STAGE_SCAN
    assert r.error_ar


def test_deep_missing_path_is_structured(engine, tmp_path):
    r = engine.run(tmp_path / "أ" / "ب" / "ج")
    assert not r.ok and "غير موجود" in r.error_ar


def test_unwritable_inplace_file_is_structured(engine, tmp_path):
    if os.name != "posix":
        pytest.skip("صلاحيات posix فقط")
    src = _plant(tmp_path, **{"m.py": BUGGY})
    (src / "m.py").chmod(stat.S_IREAD)  # قراءة فقط
    try:
        r = engine.run(src, write="inplace", confirm_inplace=True)
    finally:
        (src / "m.py").chmod(stat.S_IRWXU)
    assert not r.ok
    assert r.failed_stage in ("write", "workspace", STAGE_SCAN)
    assert r.error_ar


def test_unreadable_subdir_is_skipped_silently(engine, tmp_path):
    if os.name != "posix":
        pytest.skip("صلاحيات posix فقط")
    src = _plant(tmp_path, **{"good.py": BUGGY, "sub/hidden.py": CLEAN})
    (src / "sub").chmod(0)
    try:
        r = engine.run(src, rounds=1)
    finally:
        (src / "sub").chmod(stat.S_IRWXU)
    assert r.ok
    assert r.reviewed >= 1
    assert all(f["path"] != "sub/hidden.py" for f in r.per_file)


# --------------------------------------------------- ملفات فاسدة محددة
def test_oversized_file_is_skipped_with_reason(engine, tmp_path, monkeypatch):
    src = _plant(tmp_path, **{"big.py": BUGGY * 5, "small.py": "X = 1\n"})
    monkeypatch.setattr("zyko.workspace.engine.MAX_SOURCE_BYTES", 50)
    r = WorkspaceEngine().run(src)
    assert r.ok
    assert r.skipped == 1 and r.reviewed == 1
    entry = next(f for f in r.per_file if f["path"] == "big.py")
    assert "يتجاوز الحد" in entry["reason_ar"]


def test_bad_encoding_and_broken_syntax_together(engine, tmp_path):
    src = tmp_path / "فاسد"
    src.mkdir()
    (src / "enc.py").write_bytes("س = 1\n".encode("utf-16"))
    (src / "syn.py").write_text("def (:\n", encoding="utf-8")
    (src / "ok.py").write_text(BUGGY, encoding="utf-8")
    r = engine.run(src, rounds=1)
    assert r.ok
    assert r.skipped == 1 and r.reviewed == 2
    by = {f["path"]: f for f in r.per_file}
    assert by["enc.py"]["status"] == "skipped"
    assert by["syn.py"]["score_after"] == 0
    assert by["ok.py"]["changed"] is True


def test_all_files_broken_is_success_with_zero_exit(engine, tmp_path):
    src = tmp_path / "كل-فاسد"
    src.mkdir()
    (src / "a.py").write_bytes(b"\xff\xfe\x00x")  # ليس UTF-8 أصلًا
    (src / "b.py").write_bytes(b"\x9c\x8d\x7f\xff")  # ليس UTF-8 أيضًا
    r = engine.run(src)
    assert r.ok and r.skipped == 2 and r.reviewed == 0
    assert r.exit_code == 0


# --------------------------------------------------- محركات منهارة
def test_reviewer_crash_is_structured_and_deterministic(engine, tmp_path):
    src = _plant(tmp_path, **{"m.py": BUGGY})

    class Boom:
        def review_source(self, *_a, **_k):
            raise RuntimeError("انفجار مقصود")

    r1 = WorkspaceEngine(reviewer=Boom()).run(src)
    r2 = WorkspaceEngine(reviewer=Boom()).run(src)
    assert not r1.ok and r1.failed_stage == STAGE_REVIEWER
    d1, d2 = r1.to_dict(), r2.to_dict()
    assert d1 == d2, "الفشل نفسه يجب أن يكون حتميًا"


def test_fixer_crash_mid_round_is_structured(engine, tmp_path):
    src = _plant(tmp_path, **{"m.py": BUGGY})

    class OnceBoom:
        def __init__(self):
            self.calls = 0

        def fix_source(self, *_a, **_k):
            self.calls += 1
            raise RuntimeError("انفجار مقصود")

    boom = OnceBoom()
    r = WorkspaceEngine(fixer=boom).run(src, rounds=2)
    assert not r.ok
    assert r.failed_stage == STAGE_FIXER
    assert "المُصلِح" in r.error_ar


# --------------------------------------------------- فساد البيئة
def test_failure_payload_is_json_ready(engine, tmp_path):
    import json

    r = engine.run(None)
    d = r.to_dict()
    loaded = json.loads(json.dumps(d, ensure_ascii=False))
    assert loaded["ok"] is False
    assert loaded["error_ar"]
    assert r.exit_code == 2


def test_nested_weird_tree_does_not_confuse_order(engine, tmp_path):
    src = _plant(tmp_path, **{"z.py": BUGGY, "a/ب/ج.py": BUGGY, "a/x.py": CLEAN})
    r = engine.run(src, rounds=1)
    assert r.ok
    paths = [f["path"] for f in r.per_file]
    assert paths == sorted(paths), "ترتيب الملفات غير حتمي ألفبيًا"
    assert "a/ب/ج.py" in paths
