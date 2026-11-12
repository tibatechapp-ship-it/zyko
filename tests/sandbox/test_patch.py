"""اختبارات patch_file — تطابق وحيد، كتابة ذرية، قفل مسارات، سقوف صادقة."""

from __future__ import annotations

import hashlib

from zyko.sandbox.contracts import PermissionContract
from zyko.sandbox.patcher import patch_file


def _write_contract(tmp_path, **kw):
    return PermissionContract.for_roots(tmp_path, allow_patch=True, **kw)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- النجاح
def test_replace_unique_match_writes(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    result = patch_file(
        _write_contract(tmp_path),
        path=f,
        old_text="return a + b",
        new_text="return a + b + 0",
    )
    assert result.ok and result.changed and result.mode == "replace"
    assert f.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b + 0\n"
    assert result.sha_after == _sha(f.read_text(encoding="utf-8"))


def test_write_mode_creates_new_file(tmp_path):
    result = patch_file(
        _write_contract(tmp_path), path=tmp_path / "new" / "x.py", content="print('جديد')\n"
    )
    assert result.ok and result.mode == "write" and result.changed
    assert (tmp_path / "new" / "x.py").read_text(encoding="utf-8") == "print('جديد')\n"


def test_write_same_content_is_unchanged(tmp_path):
    f = tmp_path / "same.py"
    f.write_text("ثابت", encoding="utf-8")
    result = patch_file(_write_contract(tmp_path), path=f, content="ثابت")
    assert result.ok and not result.changed
    assert "بلا تغيير" in result.reason_ar


def test_replace_identical_old_new_is_unchanged(tmp_path):
    f = tmp_path / "same.py"
    f.write_text("نص", encoding="utf-8")
    result = patch_file(_write_contract(tmp_path), path=f, old_text="نص", new_text="نص")
    assert result.ok and not result.changed


def test_no_temp_file_left_behind(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("a\n", encoding="utf-8")
    patch_file(_write_contract(tmp_path), path=f, old_text="a", new_text="b")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "app.py"]
    assert leftovers == []


# ---------------------------------------------------------------- الرفوض
def test_patch_denied_without_flag(tmp_path):
    contract = PermissionContract.for_roots(tmp_path)  # allow_patch=False افتراضي
    result = patch_file(contract, path=tmp_path / "x.py", content="hi")
    assert not result.ok and "قراءة" in result.reason_ar
    assert not (tmp_path / "x.py").exists()


def test_patch_denied_outside_roots(tmp_path):
    contract = _write_contract(tmp_path / "proj")
    result = patch_file(contract, path=tmp_path / "خارج.py", content="hi")
    assert not result.ok and "حارس المسار" in result.reason_ar


def test_replace_missing_file_rejected(tmp_path):
    result = patch_file(
        _write_contract(tmp_path),
        path=tmp_path / "مفقود.py",
        old_text="a",
        new_text="b",
    )
    assert not result.ok and "غير موجود" in result.reason_ar


def test_replace_zero_matches_rejected(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("النص الأصلي", encoding="utf-8")
    result = patch_file(_write_contract(tmp_path), path=f, old_text="لا-يوجد", new_text="x")
    assert not result.ok and result.matches == 0
    assert f.read_text(encoding="utf-8") == "النص الأصلي"  # القرص لم يُمس


def test_replace_ambiguous_matches_rejected(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("متكرر متكرر متكرر", encoding="utf-8")
    result = patch_file(_write_contract(tmp_path), path=f, old_text="متكرر", new_text="وحيد")
    assert not result.ok and result.matches == 3 and "غامض" in result.reason_ar
    assert f.read_text(encoding="utf-8") == "متكرر متكرر متكرر"  # لا قصّ أول تكرار


def test_mixed_modes_rejected(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("نص", encoding="utf-8")
    result = patch_file(
        _write_contract(tmp_path),
        path=f,
        old_text="نص",
        new_text="جديد",
        content="أيضاً",
    )
    assert not result.ok and "خلط" in result.reason_ar


def test_empty_patch_rejected(tmp_path):
    result = patch_file(_write_contract(tmp_path), path=tmp_path / "x.py")
    assert not result.ok and "بلا محتوى" in result.reason_ar


def test_empty_old_text_rejected(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("نص", encoding="utf-8")
    result = patch_file(_write_contract(tmp_path), path=f, old_text="", new_text="x")
    assert not result.ok


# ---------------------------------------------------------------- السقوف
def test_file_over_size_cap_rejected(tmp_path):
    f = tmp_path / "big.py"
    f.write_text("x" * 50, encoding="utf-8")
    contract = _write_contract(tmp_path, max_file_bytes=10)
    result = patch_file(contract, path=f, old_text="x", new_text="y")
    assert not result.ok and "سقف" in result.reason_ar


def test_output_over_size_cap_rejected(tmp_path):
    f = tmp_path / "small.py"
    f.write_text("ab", encoding="utf-8")
    contract = _write_contract(tmp_path, max_file_bytes=3)
    result = patch_file(contract, path=f, old_text="ab", new_text="كبير جداً هنا")
    assert not result.ok and "ناتج الرقعة" in result.reason_ar
    assert f.read_text(encoding="utf-8") == "ab"


def test_write_mode_over_size_cap_rejected(tmp_path):
    contract = _write_contract(tmp_path, max_file_bytes=5)
    result = patch_file(contract, path=tmp_path / "new.py", content="م" * 100)
    assert not result.ok
    assert not (tmp_path / "new.py").exists()


def test_binary_nul_content_rejected(tmp_path):
    f = tmp_path / "bin.py"
    f.write_text("نص", encoding="utf-8")
    result = patch_file(_write_contract(tmp_path), path=f, old_text="نص", new_text="ن\x00ص")
    assert not result.ok and "NUL" in result.reason_ar


def test_non_utf8_file_rejected_for_replace(tmp_path):
    f = tmp_path / "bin.dat"
    f.write_bytes(b"\xff\xfe\x00\x01")
    result = patch_file(_write_contract(tmp_path), path=f, old_text="x", new_text="y")
    assert not result.ok and "قراءة" in result.reason_ar


# ---------------------------------------------------------------- الدقة
def test_arabic_content_roundtrip(tmp_path):
    """النص العربي يعبر الرقعة بلا تحريف — ترميز واحد UTF-8 في كل الاتجاهات."""
    f = tmp_path / "عربي.py"
    f.write_text('message = "مرحباً بالعالم"\n', encoding="utf-8")
    result = patch_file(
        _write_contract(tmp_path),
        path=f,
        old_text="مرحباً بالعالم",
        new_text="أهلاً بكم",
    )
    assert result.ok
    assert f.read_text(encoding="utf-8") == 'message = "أهلاً بكم"\n'


def test_multiline_replace(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("def a():\n    pass\n\ndef b():\n    pass\n", encoding="utf-8")
    result = patch_file(
        _write_contract(tmp_path),
        path=f,
        old_text="def a():\n    pass\n",
        new_text="def a():\n    return 1\n",
    )
    assert result.ok
    assert "return 1" in f.read_text(encoding="utf-8")
    assert f.read_text(encoding="utf-8").count("def b()") == 1


def test_result_to_dict_deterministic(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("نص", encoding="utf-8")
    a = patch_file(_write_contract(tmp_path), path=f, old_text="نص", new_text="جديد")
    import json

    once = json.dumps(a.to_dict(), ensure_ascii=False, sort_keys=True)
    twice = json.dumps(
        patch_file(_write_contract(tmp_path), path=tmp_path / "app2.py", content="جديد").to_dict(),
        ensure_ascii=False,
        sort_keys=True,
    )
    assert isinstance(json.loads(once), dict) and isinstance(json.loads(twice), dict)
    keys = list(a.to_dict())
    assert keys == sorted(keys)


def test_sha_evidence_is_real_sha256(tmp_path):
    f = tmp_path / "app.py"
    original = "evidence"
    f.write_text(original, encoding="utf-8")
    result = patch_file(_write_contract(tmp_path), path=f, old_text="evidence", new_text="changed")
    assert result.sha_before == _sha(original)
    assert result.sha_after == _sha("changed")


def test_symlink_inside_root_resolved_not_replaced(tmp_path):
    """رقعة عبر رمز ارتباط تكتب الهدف الحقيقي الموجود داخل الجذور."""
    proj = tmp_path / "proj"
    proj.mkdir()
    real = proj / "real.py"
    real.write_text("أصل", encoding="utf-8")
    link = proj / "alias.py"
    link.symlink_to(real)
    result = patch_file(_write_contract(proj), path=link, old_text="أصل", new_text="معدّل")
    assert result.ok
    assert real.read_text(encoding="utf-8") == "معدّل"


# ------------------------------------------------- حرس الاعتماد الحساس
# الرقعة تقرأ الهدف قبل أن تكتبه — فلا قراءة ولا رقعة على مخازن الأسرار.
def test_patch_denied_on_secret_store_replace(tmp_path):
    secret = tmp_path / ".env"
    secret.write_text("TOKEN=x\n", encoding="utf-8")
    result = patch_file(
        _write_contract(tmp_path), path=secret, old_text="TOKEN=x", new_text="TOKEN=y"
    )
    assert not result.ok
    assert "حساس" in result.reason_ar
    assert secret.read_text(encoding="utf-8") == "TOKEN=x\n"  # لم تُقرأ ولا تُرقَّع


def test_patch_denied_on_secret_store_write(tmp_path):
    result = patch_file(_write_contract(tmp_path), path=tmp_path / "id_rsa", content="private-key")
    assert not result.ok
    assert not (tmp_path / "id_rsa").exists()  # لم يُنشأ ملف سرّ عبر الرقعة


def test_patch_key_suffix_denied(tmp_path):
    result = patch_file(_write_contract(tmp_path), path=tmp_path / "server.pem", content="cert")
    assert not result.ok and "server.pem" in result.reason_ar
