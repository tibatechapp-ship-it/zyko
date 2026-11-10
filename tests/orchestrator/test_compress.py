"""المكوّن 4 — بوابة compress: هضم المستودع ضمن ميزانية الرموز (~30 اختباراً).

المحاور: التحقق من المدخل، تخطي الثنائي والثرثارة، ترتيب الأولوية المعلن،
صدق الميزانية (العقد: estimate(to_text) <= tokens_used <= max_tokens)،
الاقتطاع المعلن، الحذف المعلن، الحتمية (مقارنة كاملة + 100 تشغيل على
نفس المستودع — P6: لا ادعاء حتمية بلا إثبات)، والبصمة sha256.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zyko.exceptions import ConfigError
from zyko.orchestrator import compress
from zyko.orchestrator.compress import (
    MIN_MAX_TOKENS,
    TRUNCATION_MARKER,
    _estimate_tokens,
    _priority_of,
)
from zyko.orchestrator.run import _canonical  # عقد التسلسل الكنسي المشترك


# ------------------------------------------------------------------ مجسمات
@pytest.fixture()
def mini_repo(tmp_path: Path) -> Path:
    """مستودع صغير منظّم: README، مصدر، اختبار، docs، ثنائي، قمامة."""
    (tmp_path / "README.md").write_text("# مرحباً\nهذا المستودع للتجربة\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    return 42\n", encoding="utf-8")
    (src / "note.bin").write_bytes(b"\x00\x01binary\xff")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'mini'\n", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("دليل الاستخدام بالعربية\n", encoding="utf-8")
    tst = tmp_path / "tests"
    tst.mkdir()
    (tst / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    junk = tmp_path / "__pycache__"
    junk.mkdir()
    (junk / "app.cpython-311.pyc").write_bytes(b"\x00junk")
    return tmp_path


# ------------------------------------------------------------------ تقدير الرموز
class TestEstimateTokens:
    def test_ceil_of_four_chars_is_one(self):
        assert _estimate_tokens("abcd") == 1

    def test_ceil_rounds_up_not_down(self):
        assert _estimate_tokens("abc") == 1  # ceil(3/4) = 1 — تحفّظ لا تهور
        assert _estimate_tokens("abcde") == 2

    def test_empty_text_is_zero(self):
        assert _estimate_tokens("") == 0

    def test_deterministic_across_runs(self):
        sample = "نص عربي وأخطاء bug fix — deterministic \U0001f600"
        first = _estimate_tokens(sample)
        assert all(_estimate_tokens(sample) == first for _ in range(100))


# ------------------------------------------------------------------ الأولوية المعلنة
class TestPriority:
    @pytest.mark.parametrize(
        ("rel", "rank"),
        [
            ("README.md", 0),
            ("readme.rst", 0),
            ("pyproject.toml", 1),
            ("CITATION.cff", 1),
            ("src/zyko/app.py", 2),
            ("src/app.py", 2),
            ("docs/guide.md", 3),
            ("tests/test_app.py", 4),
            ("config.yaml", 5),
            ("notes.txt", 6),
            ("scripts/run.sh", 6),
        ],
    )
    def test_priority_table_exact(self, rel: str, rank: int):
        assert _priority_of(rel) == rank


# ------------------------------------------------------------------ التحقق من المدخل
class TestValidation:
    def test_missing_path_raises_arabic(self, tmp_path: Path):
        with pytest.raises(ConfigError) as err:
            compress(tmp_path / "لا_يوجد")
        assert "غير موجود" in str(err.value)

    def test_file_not_directory_raises(self, tmp_path: Path):
        f = tmp_path / "file.txt"
        f.write_text("x", encoding="utf-8")
        with pytest.raises(ConfigError) as err:
            compress(f)
        assert "ليس مجلداً" in str(err.value)

    def test_budget_below_floor_raises_arabic(self, mini_repo: Path):
        with pytest.raises(ConfigError) as err:
            compress(mini_repo, max_tokens=MIN_MAX_TOKENS - 1)
        assert "الحد الأدنى" in str(err.value)

    def test_floor_budget_accepted(self, mini_repo: Path):
        ctx = compress(mini_repo, max_tokens=MIN_MAX_TOKENS)
        assert ctx.max_tokens == MIN_MAX_TOKENS


# ------------------------------------------------------------------ التخطي المعلن
class TestSkipping:
    def test_binary_files_reported_not_silent(self, mini_repo: Path):
        ctx = compress(mini_repo)
        assert "src/note.bin" in ctx.skipped_binary

    def test_pyc_in_pycache_skipped_entirely(self, mini_repo: Path):
        ctx = compress(mini_repo)
        assert all("__pycache__" not in rel for rel in ctx.tree)

    def test_skipped_binary_sorted(self, mini_repo: Path):
        ctx = compress(mini_repo)
        assert list(ctx.skipped_binary) == sorted(ctx.skipped_binary)

    def test_tree_deterministic_posix(self, mini_repo: Path):
        """الشجرة مرتبة بالأولوية لا أبجدياً — العقد: حتمية + فواصل POSIX فقط."""
        ctx = compress(mini_repo)
        assert list(ctx.tree) == list(compress(mini_repo).tree)
        assert all("\\" not in rel for rel in ctx.tree)

    def test_tree_priority_prefix_order(self, mini_repo: Path):
        """README قبل pyproject قبل المصادر — الترتيب المعلن في الشجرة أيضاً."""
        tree = list(compress(mini_repo).tree)
        assert tree.index("README.md") < tree.index("pyproject.toml") < tree.index("src/app.py")


# ------------------------------------------------------------------ الأولوية في الحزم
class TestPackingOrder:
    def test_readme_first_then_package_then_sources(self, mini_repo: Path):
        ctx = compress(mini_repo, max_tokens=4_000)
        paths = [f.path for f in ctx.files]
        assert paths[0] == "README.md"
        assert paths.index("pyproject.toml") < paths.index("src/app.py")
        assert paths.index("docs/guide.md") < paths.index("tests/test_app.py")

    def test_every_tree_entry_accounted(self, mini_repo: Path):
        """كل ملف نصي إما داخل files أو في omitted — لا صف ثالث."""
        ctx = compress(mini_repo, max_tokens=150)
        in_files = {f.path for f in ctx.files}
        assert in_files | set(ctx.omitted) == set(ctx.tree)
        assert not (in_files & set(ctx.omitted))


# ------------------------------------------------------------------ صدق الميزانية
class TestBudgetHonesty:
    @pytest.mark.parametrize("budget", [32, 100, 150, 400, 1_000, 10_000])
    def test_invariant_estimate_le_used_le_max(self, mini_repo: Path, budget: int):
        ctx = compress(mini_repo, max_tokens=budget)
        assert ctx.tokens_used <= ctx.max_tokens
        assert _estimate_tokens(ctx.to_text()) <= ctx.tokens_used

    def test_bigger_budget_includes_more(self, mini_repo: Path):
        small = compress(mini_repo, max_tokens=200)
        big = compress(mini_repo, max_tokens=10_000)
        assert len(big.files) >= len(small.files)
        assert big.tokens_used >= small.tokens_used

    def test_default_budget_is_10k(self, mini_repo: Path):
        assert compress(mini_repo).max_tokens == 10_000

    def test_tiny_budget_keeps_readme_or_reports_omission(self, mini_repo: Path):
        ctx = compress(mini_repo, max_tokens=60)
        assert ("README.md" in [f.path for f in ctx.files]) or ctx.omitted


# ------------------------------------------------------------------ الاقتطاع المعلن
class TestTruncation:
    @pytest.fixture()
    def fat_repo(self, tmp_path: Path) -> Path:
        (tmp_path / "README.md").write_text("# بداية\n", encoding="utf-8")
        src = tmp_path / "src"
        src.mkdir()
        # small.py بمصدر أولوية أعلى (src=2) ليُدخل قبل اقتطاع fat.py (رتبة 6)
        (src / "small.py").write_text("y = 2\n", encoding="utf-8")
        (tmp_path / "fat.py").write_text("x = 1\n" * 5_000, encoding="utf-8")
        return tmp_path

    def test_fat_file_truncated_with_marker(self, fat_repo: Path):
        ctx = compress(fat_repo, max_tokens=600)
        slices = {f.path: f for f in ctx.files}
        assert "fat.py" in slices
        assert slices["fat.py"].truncated is True
        assert TRUNCATION_MARKER in slices["fat.py"].content

    def test_small_file_never_truncated(self, fat_repo: Path):
        ctx = compress(fat_repo, max_tokens=600)
        slices = {f.path: f for f in ctx.files}
        assert slices["src/small.py"].truncated is False
        assert slices["src/small.py"].content == "y = 2\n"

    def test_slice_sha256_matches_content_field(self, fat_repo: Path):
        import hashlib

        ctx = compress(fat_repo, max_tokens=600)
        for f in ctx.files:
            assert f.sha256 == hashlib.sha256(f.content.encode("utf-8")).hexdigest()

    def test_unfittable_file_reported_omitted(self, fat_repo: Path):
        """ميزانية لا تسمح حتى برأس معقول → حذف كامل معلن، لا مقتطع عديم الفائدة."""
        ctx = compress(fat_repo, max_tokens=80)
        assert "fat.py" in ctx.omitted


# ------------------------------------------------------------------ الحتمية P6
class TestDeterminism:
    def test_two_runs_byte_identical_dict(self, mini_repo: Path):
        a = compress(mini_repo, max_tokens=1_000).to_dict()
        b = compress(mini_repo, max_tokens=1_000).to_dict()
        assert _canonical(a) == _canonical(b)

    def test_hundred_runs_same_fingerprint(self, mini_repo: Path):
        fp = compress(mini_repo, max_tokens=2_000).fingerprint
        assert all(compress(mini_repo, max_tokens=2_000).fingerprint == fp for _ in range(100))

    def test_content_change_changes_fingerprint(self, mini_repo: Path):
        before = compress(mini_repo).fingerprint
        (mini_repo / "src" / "app.py").write_text("def main():\n    return 43\n", encoding="utf-8")
        after = compress(mini_repo).fingerprint
        assert before != after

    def test_real_repo_self_digest_within_budget(self):
        """اختبار ذاتي: هضم مستودع zyko نفسه — شجرته أكبر من الميزانية،
        فتُقتطع الشجرة بإعلان حتمي وتبقى الميزانية صادقة بالبايت."""
        root = Path(__file__).resolve().parents[2]
        ctx = compress(root, max_tokens=10_000)
        assert ctx.files and ctx.files[0].path.lower().startswith("readme")
        assert ctx.tree_dropped > 0 and ctx.tree_marker_rendered
        assert _estimate_tokens(ctx.to_text()) <= ctx.tokens_used <= 10_000
        assert "اقتُطعت من الشجرة" in ctx.summary_ar

    def test_tree_truncation_announced(self, tmp_path: Path):
        """شجرة أكبر من ميزانيتها (نصفها) تُقتطع من النهاية مع إعلان."""
        for i in range(60):
            (tmp_path / f"zz_file_{i:02d}.py").write_text(f"x{i} = {i}\n", encoding="utf-8")
        (tmp_path / "README.md").write_text("# بداية\n", encoding="utf-8")
        ctx = compress(tmp_path, max_tokens=120)
        assert ctx.tree_dropped > 0
        assert ctx.tree  # README وملفات الأولوية الأولى بقيت
        assert ctx.tree[-1].startswith("zz_file_")  # القصّ من النهاية
        assert _estimate_tokens(ctx.to_text()) <= ctx.tokens_used <= 120


# ------------------------------------------------------------------ البصمة والتسلسل
class TestSerialization:
    def test_to_dict_keys_stable(self, mini_repo: Path):
        d = compress(mini_repo).to_dict()
        assert set(d) == {
            "repo_path",
            "max_tokens",
            "files",
            "tree",
            "tree_dropped",
            "tree_marker_rendered",
            "skipped_binary",
            "omitted",
            "tokens_used",
            "summary_ar",
            "fingerprint",
        }

    def test_to_dict_json_serializable(self, mini_repo: Path):
        d = compress(mini_repo).to_dict()
        assert isinstance(json.dumps(d, ensure_ascii=False), str)

    def test_fingerprint_is_sha256_hex(self, mini_repo: Path):
        fp = compress(mini_repo).fingerprint
        assert len(fp) == 64 and all(c in "0123456789abcdef" for c in fp)

    def test_file_slice_sha256_is_sha256_hex(self, mini_repo: Path):
        for f in compress(mini_repo).files:
            assert len(f.sha256) == 64 and all(c in "0123456789abcdef" for c in f.sha256)

    def test_frozen_immutability(self, mini_repo: Path):
        ctx = compress(mini_repo)
        with pytest.raises(Exception):  # noqa: B017 — الفئة المجمّدة ترفض الكتابة
            ctx.max_tokens = 5  # type: ignore[misc]
        f = ctx.files[0]
        with pytest.raises(Exception):  # noqa: B017
            f.path = "x"  # type: ignore[misc]

    def test_exports_surface(self):
        import zyko.orchestrator as pkg

        assert {"CompressedContext", "FileSlice", "compress"} <= set(pkg.__all__)


# ------------------------------------------------------------------ الملخص العربي
class TestSummaryAr:
    def test_summary_counts_consistent(self, mini_repo: Path):
        ctx = compress(mini_repo, max_tokens=300)
        s = ctx.summary_ar
        assert s and "هضم حتمي" in s
        assert f"دخل منها {len(ctx.files)}" in s
        assert f"حُذف للميزانية {len(ctx.omitted)}" in s
        assert f"تخطي ثنائي {len(ctx.skipped_binary)}" in s

    def test_summary_mentions_budget_usage(self, mini_repo: Path):
        ctx = compress(mini_repo, max_tokens=500)
        assert f"استُخدم {ctx.tokens_used} من 500 رمزاً" in ctx.summary_ar

    def test_to_text_renders_files_in_order(self, mini_repo: Path):
        ctx = compress(mini_repo, max_tokens=4_000)
        text = ctx.to_text()
        assert text.startswith("سياق المستودع — ")
        positions = [text.index(f"=== {f.path} ===") for f in ctx.files]
        assert positions == sorted(positions)
