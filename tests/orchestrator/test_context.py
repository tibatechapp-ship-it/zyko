r"""استخراج السياق — بوابة المسارات المطلقة والنسبية (~14 اختباراً).

الإصلاح الموثق: كان المستخرج يقتطع بداية المسار المطلق («/tmp/x.py» →
«tmp/x.py») فتفشل الأدوات على هدف طبيعي صحيح؛ والبادئات المطلقة على
ويندوز (C:\ و\\unc) لم تكن تُطابق أصلاً. الآن: المطلق أولاً، ثم النسبي
بمجلدات، ثم الملف بامتداد معروف — أول تطابق يفوز، بلا بيئة ولا زمن
(حتمي بالبايت).
"""

from __future__ import annotations

import pytest

from zyko.orchestrator.context import extract_context


class TestAbsolutePaths:
    def test_posix_absolute_keeps_leading_slash(self):
        ctx = extract_context("راجع /tmp/swarmdbg/widget.py")
        assert ctx["path"] == "/tmp/swarmdbg/widget.py"

    def test_windows_drive_letter(self):
        ctx = extract_context(r"راجع C:\a\zyko\widget.py")
        assert ctx["path"] == r"C:\a\zyko\widget.py"

    def test_windows_unc_prefix(self):
        ctx = extract_context(r"راجع \\server\share\widget.py")
        assert ctx["path"] == r"\\server\share\widget.py"

    def test_absolute_directory_without_extension(self):
        ctx = extract_context("حلل /home/user/proj")
        assert ctx["path"] == "/home/user/proj"


class TestRelativePaths:
    def test_relative_with_folders_unchanged(self):
        ctx = extract_context("راجع src/widget.py")
        assert ctx["path"] == "src/widget.py"

    def test_bare_file_with_known_extension(self):
        ctx = extract_context("راجع widget.py")
        assert ctx["path"] == "widget.py"

    def test_no_path_only_description(self):
        ctx = extract_context("الجو جميل اليوم")
        assert "path" not in ctx
        assert ctx["description"] == "الجو جميل اليوم"


class TestExtensionDispatch:
    def test_daad_file_fills_file_key(self):
        ctx = extract_context("حوّل src/main.daad")
        assert ctx["file"] == "src/main.daad"

    def test_json_receipt_fills_receipt_key(self):
        ctx = extract_context("تحقق من receipts/run.json")
        assert ctx["receipt"] == "receipts/run.json"

    def test_plain_python_file_has_no_receipt_key(self):
        ctx = extract_context("راجع src/widget.py")
        assert "receipt" not in ctx
        assert "file" not in ctx


class TestDescriptionAlwaysFull:
    def test_description_is_stripped_goal(self):
        ctx = extract_context("  راجع /tmp/x.py  ")
        assert ctx["description"] == "راجع /tmp/x.py"

    def test_description_kept_when_no_path(self):
        ctx = extract_context("اكتب لي مشروعاً جديداً")
        assert ctx["description"] == "اكتب لي مشروعاً جديداً"


class TestDeterminism:
    def test_hundred_runs_same_context(self):
        goal = "أصلح C:\\proj\\widget.py ثم راجع النتيجة"
        first = extract_context(goal)
        assert all(extract_context(goal) == first for _ in range(100))

    def test_first_match_wins_stable(self):
        ctx = extract_context("راجع a/x.py و b/y.py")
        assert ctx["path"] == "a/x.py"


@pytest.mark.parametrize(
    ("goal", "expected"),
    [
        ("راجع /abs/x.py", "/abs/x.py"),
        (r"راجع C:\w\x.py", r"C:\w\x.py"),
        ("راجع rel/x.py", "rel/x.py"),
        ("راجع bare.py", "bare.py"),
    ],
)
def test_path_extraction_matrix(goal: str, expected: str):
    assert extract_context(goal)["path"] == expected
