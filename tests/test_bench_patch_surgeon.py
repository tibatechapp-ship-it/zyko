"""اختبارات الجرّاح الصياغي (الموجة 20) — تشخيص محلي وتطبيق متسامح وإرجاع بالبايت.

علة العينة الواسعة الموثقة: 19 حالة من 44 بلا رقعة مطبقة — git يرفض
والعقل لا يعرف لماذا بالتفصيل. هذه الاختبارات تحكم ثلاثة عقود:
الفحص الصياغي يوصف الخطأ العربية بموضعه، والسلّم المتسامح ينقذ ما
ينقذ معلناً الجزئي، والإرجاع العكسي يعيد الشجرة إلى الأساس بالبايت.

كلها بلا شبكة وبلا نموذج — git حقيقي على مستودع مصغّر محلي.
"""

from __future__ import annotations

import subprocess

import pytest

from zyko.benchmarks.patch_surgeon import (
    MODE_FILES,
    MODE_FULL,
    MODE_HUNKS,
    apply_tolerant,
    revert_candidate,
    split_file_patches,
    split_hunk_patches,
    validate_syntax,
)

GOOD_RAW = "--- a/src.py\n+++ b/src.py\n@@ -1 +1 @@\n-value = 1\n+value = 2"
COUNTS_MISMATCH = "--- a/src.py\n+++ b/src.py\n@@ -1,2 +1,2 @@\n-value = 1\n+value = 2"
MISSING_PLUS = "--- a/src.py\n@@ -1 +1 @@\n-value = 1\n+value = 2"
BAD_PREFIX = "--- a/src.py\n+++ b/src.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\nجُملة عربية عارية"
MIXED_FILES = (
    "--- a/src.py\n+++ b/src.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
    "--- a/missing.py\n+++ b/missing.py\n@@ -1 +1 @@\n-x\n+y"
)


@pytest.fixture()
def mini_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src.py").write_text('value = 1\nextra = 0\nother = "keep"\n', encoding="utf-8")
    (repo / "alt.py").write_text("alt = 1\n", encoding="utf-8")
    (repo / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


# --------------------------------------------------------------- الفحص الصياغي
def test_validate_syntax_accepts_wellformed():
    ok, errors = validate_syntax(GOOD_RAW)
    assert ok and errors == ()
    ok2, errors2 = validate_syntax("value = 1")  # ليس رقعة أصلاً
    assert not ok2 and any("ليس نص رقعة" in e for e in errors2)


def test_validate_syntax_counts_mismatch_documented_with_position():
    ok, errors = validate_syntax(COUNTS_MISMATCH)
    assert not ok
    assert "عدّاد جزء مخالف" in errors[0]
    assert "src.py" in errors[0]
    assert "2 قديماً" in errors[0] and "1 قديماً" in errors[0]


def test_validate_syntax_missing_file_header():
    ok, errors = validate_syntax(MISSING_PLUS)
    assert not ok
    assert "ترويسة ناقصة" in errors[0]


def test_validate_syntax_bare_prefix_line_documented():
    ok, errors = validate_syntax(BAD_PREFIX)
    assert not ok
    assert any("بلا بادئة معلومة" in e for e in errors)
    assert any("جُملة عربية عارية" in e for e in errors)


def test_validate_syntax_is_deterministic():
    for patch in (COUNTS_MISMATCH, MISSING_PLUS, BAD_PREFIX):
        assert validate_syntax(patch) == validate_syntax(patch)


# --------------------------------------------------------------- التفكيك
def test_splits_are_deterministic_and_ordered():
    multi = (
        "--- a/alt.py\n+++ b/alt.py\n@@ -1 +1 @@\n-alt = 1\n+alt = 2\n"
        "--- a/src.py\n+++ b/src.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
        "@@ -2 +2 @@\n-extra = 0\n+extra = 1"
    )
    files = split_file_patches(multi)
    assert [p for p, _ in files] == ["alt.py", "src.py"]  # ترتيب الظهور لا الأبجدي
    hunks = split_hunk_patches(multi)
    assert hunks == split_hunk_patches(multi)
    assert [(p, i) for p, i, _ in hunks] == [("alt.py", 1), ("src.py", 1), ("src.py", 2)]


# --------------------------------------------------------------- السلّم المتسامح
def test_apply_tolerant_full_mode_saves_zero_context_with_declared_flags(mini_repo):
    """اكتشاف الموجة 20 بالبايت: git يُلزم الجزء عديم السياق اللاحق أن
    يمتد إلى نهاية الملف — «@@ -1 +1 @@» على ملف متعدد الأسطر يرفض بلا
    «--unidiff-zero». السلّم يُنجزه ويُعلن العلم لا يخفيه."""
    tol = apply_tolerant(mini_repo, GOOD_RAW, subprocess.run)
    assert tol.applied and tol.mode_ar == MODE_FULL
    assert tol.flags == ("--unidiff-zero",)
    assert "أعلام --unidiff-zero" in tol.reason_ar
    assert (mini_repo / "src.py").read_text(encoding="utf-8") == (
        'value = 2\nextra = 0\nother = "keep"\n'
    )


def test_apply_tolerant_file_ladder_salvages_good_file(mini_repo):
    """الرقعة متعددة الملفات يرفضها git بسبب ملف غير موجود — السلّم ينقذ
    الملف الصالح والجزئي معلن: المطبق بالمطبق والفاشل بسببه."""
    tol = apply_tolerant(mini_repo, MIXED_FILES, subprocess.run)
    assert tol.applied and tol.mode_ar == MODE_FILES
    assert tol.parts_applied == ("src.py",)
    assert tol.parts_failed[0][0] == "missing.py"
    assert "تطبيق جزئي معلن" in tol.reason_ar
    assert tol.flags == ("--unidiff-zero",)
    assert (mini_repo / "src.py").read_text(encoding="utf-8").startswith("value = 2\n")


def test_apply_tolerant_hunk_ladder_on_two_hunk_patch(mini_repo):
    """جزءان لملف واحد — الأول صحيح والثاني سياقه غير موجود: الجزء الصالح
    يُطبَّق والفاشل موثق، والوضع «بالأجزاء» لا يُظهر كأنه كامل."""
    patch = (
        "--- a/src.py\n+++ b/src.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
        "@@ -3 +3 @@\n-no_such_line\n+x"
    )
    tol = apply_tolerant(mini_repo, patch, subprocess.run)
    assert tol.applied and tol.mode_ar == MODE_HUNKS
    assert tol.parts_applied == ("src.py:1",)
    assert tol.parts_failed[0][0] == "src.py:2"
    assert tol.flags == ("--unidiff-zero",)
    body = (mini_repo / "src.py").read_text(encoding="utf-8")
    assert body.startswith("value = 2\n") and body.endswith('other = "keep"\n')


def test_apply_tolerant_total_failure_carries_syntax_and_git_reasons(mini_repo):
    """سياق لا يوجد في الملف إطلاقاً — كل الأعلام الأربعة تفشل، والسبب
    العربي يحمّل رفض git حرفياً (والصياغة سليمة هنا — العلة محتوى)."""
    corrupt = "--- a/src.py\n+++ b/src.py\n@@ -1 +1 @@\n no_such_context_ever"
    tol = apply_tolerant(mini_repo, corrupt, subprocess.run)
    assert not tol.applied
    assert "patch failed" in tol.reason_ar or "فشل فحص التطبيق" in tol.reason_ar
    assert tol.syntax_errors == ()  # الصياغة سليمة — الرفض سببه المحتوى
    assert (mini_repo / "src.py").read_text(encoding="utf-8").startswith("value = 1\n")


# --------------------------------------------------------------- الإرجاع العكسي
def test_revert_candidate_restores_base_after_full_apply(mini_repo):
    tol = apply_tolerant(mini_repo, GOOD_RAW, subprocess.run)
    assert tol.applied
    ok, reason = revert_candidate(mini_repo, GOOD_RAW, subprocess.run, tol.applied_subpatches)
    assert ok and "أُرجعت" in reason
    assert (mini_repo / "src.py").read_text(encoding="utf-8").startswith("value = 1\n")


def test_revert_candidate_partial_only_reverses_applied_parts(mini_repo):
    """التطبيق الجزئي يُرجَع بأجزائه المطبقة حصراً — عكس الرقعة كلها على
    شجرة ناقصة التطبيق يرفض ظلماً."""
    tol = apply_tolerant(mini_repo, MIXED_FILES, subprocess.run)
    assert tol.applied and len(tol.applied_subpatches) == 1
    ok, _ = revert_candidate(mini_repo, MIXED_FILES, subprocess.run, tol.applied_subpatches)
    assert ok
    assert (mini_repo / "src.py").read_text(encoding="utf-8").startswith("value = 1\n")
    assert not (mini_repo / "missing.py").exists()


def test_revert_candidate_on_unapplied_patch_fails_honestly(mini_repo):
    ok, reason = revert_candidate(mini_repo, GOOD_RAW, subprocess.run)
    assert not ok
    assert "فشل الإرجاع العكسي" in reason
