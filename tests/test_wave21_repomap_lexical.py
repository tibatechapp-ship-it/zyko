"""اختبارات الموجة 21 — repo-map بتوقيع الرموز + المختار المعجمي الحتمي.

الموجة 21 تعالج الفجوة الثالثة الموثقة (تقرير 0.43.0 §7): الخريطة
الدلالية تُرقّى إلى توقيع الرموز (سطر وثيقة + أعضاء الأصناف + عائلات
لغات غير بايثون + عمل بلا git) والمختار المعجمي يعلن قيمتها بلا نموذج.
كل اختبار هنا مرساة عقد — لا سلوك مصادفة.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from zyko.benchmarks.lexical_chooser import (
    case_hit,
    precision_at_k,
    query_tokens,
    rank_files,
    summarize_hits,
    tokenize,
)
from zyko.reviewer.repo_map import (
    IGNORED_DIRS,
    MAX_DOC_CHARS,
    MAX_SYMBOLS_PER_FILE,
    build_repo_map,
    map_suffixes,
    regex_symbols,
)


# --------------------------------------------------------------- بايثون: التوقيع الدلالي
def test_python_docline_and_members(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "models.py").write_text(
        'class Session:\n    """إدارة جلسة HTTP بموصلات دائمة."""\n'
        "    def resolve_redirects(self, url, *, max_hops=3):\n        return url\n\n"
        'def chunked(url):\n    """بث مجزوء للحمولة الكبيرة."""\n    return url\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=repo, check=True)
    lines = build_repo_map(repo)
    assert len(lines) == 1
    text = lines[0]
    # التوقيع الدلالي: سطر الوثيقة بين محرفَي الاقتباس العربيين
    assert "class Session «إدارة جلسة HTTP بموصلات دائمة.»" in text
    # أعضاء الصنف باسمه الكامل وself مجردة
    assert "Session.resolve_redirects(url, *, max_hops)" in text
    # الدالة العليا بوثيقتها
    assert "def chunked(url) «بث مجزوء للحمولة الكبيرة.»" in text
    # الحتمية بالبايت
    assert build_repo_map(repo) == tuple(lines)


def test_long_docline_truncated():
    source = 'def f():\n    """' + "و" * (MAX_DOC_CHARS + 40) + '"""\n    return 1\n'
    summary = None
    from zyko.reviewer.repo_map import symbol_summary

    summary = symbol_summary(source)
    assert summary is not None and "…" in summary
    doc_part = summary.split("«", 1)[1]
    assert len(doc_part.rsplit("»", 1)[0]) == MAX_DOC_CHARS


def test_symbol_budget_cap_enforced():
    from zyko.reviewer.repo_map import symbol_summary

    source = "\n".join(f"def fn_{i}(): pass" for i in range(40)) + "\n"
    summary = symbol_summary(source)
    assert summary is not None
    assert summary.count("؛") == MAX_SYMBOLS_PER_FILE - 1  # السقف المعلن يحكم


# --------------------------------------------------------------- العائلات الأخرى
def test_regex_symbols_js_typescript():
    src = (
        "export default function makeSession(url) { return url }\n"
        "class AuthManager {}\n"
        "interface RetryPolicy {}\n"
        "export type Verdict = 'pass' | 'fail';\n"
        "const handler = async (req) => req;\n"
    )
    text = regex_symbols(src, ".ts")
    assert text is not None
    assert "fn makeSession()" in text and "class AuthManager" in text
    assert "interface RetryPolicy" in text and "type Verdict" in text
    assert "const handler ⇒" in text


def test_regex_symbols_go_rust():
    go = regex_symbols(
        "func (s *Store) Get(k string) error { return nil }\nfunc New() *Store { }\ntype Store struct {",
        ".go",
    )
    assert go is not None
    assert "func (*Store) Get()" in go and "func New()" in go and "type Store struct" in go
    rs = regex_symbols(
        "pub fn run() {}\nstruct Config;\ntrait Mux {}\nimpl Store { fn get() {} }", ".rs"
    )
    assert rs is not None
    assert "fn run()" in rs and "struct Config" in rs and "trait Mux" in rs and "impl Store" in rs


def test_regex_symbols_markdown_yaml_toml_json():
    md = regex_symbols("# التثبيت\n## بروتوكول القياس\nنص عادي\n", ".md")
    assert md is not None and "# التثبيت" in md and "## بروتوكول القياس" in md
    yml = regex_symbols("name: zyko\non:\n  push:\njobs: {}\n", ".yml")
    assert yml is not None and "name:" in yml and "on:" in yml and "jobs:" in yml
    # مفتاح متداخل لا يُلتقط — الجذر حصراً
    assert "push:" not in yml
    toml = regex_symbols("[tool.ruff]\nx = 1\n[project]\n", ".toml")
    assert toml is not None and "[tool.ruff]" in toml and "[project]" in toml
    js = regex_symbols('{"name": "zyko", "version": 1}', ".json")
    assert js is not None and "name:" in js and "version:" in js
    assert regex_symbols("{عطب", ".json") is None  # عطب JSON غير قابل للتحليل
    assert regex_symbols("[1, 2, 3]", ".json") == ""  # قائمة بلا رموز — فراغ موثق


def test_regex_symbols_unknown_family_is_none():
    assert regex_symbols("anything", ".xyz") is None
    assert regex_symbols("anything", ".cfg") is None


def test_ccpp_keywords_not_captured_as_functions():
    src = "int main(void) {\n  return 0;\n}\nif (x) { y(); }\nclass Widget {\n};\n"
    text = regex_symbols(src, ".cpp")
    assert text is not None
    assert "fn main()" in text and "class Widget" in text
    assert "fn if()" not in text


def test_map_suffixes_announced():
    suffixes = map_suffixes()
    for required in (
        ".py",
        ".pyi",
        ".ts",
        ".go",
        ".rs",
        ".java",
        ".md",
        ".yaml",
        ".json",
        ".sh",
        ".rb",
        ".php",
        ".toml",
    ):
        assert required in suffixes


# --------------------------------------------------------------- بلا git: المسح المعلن
def test_walk_fallback_deterministic_and_ignoring(tmp_path):
    plain = tmp_path / "hf-download"
    (plain / "src").mkdir(parents=True)
    (plain / "node_modules" / "left-pad").mkdir(parents=True)
    (plain / "__pycache__").mkdir()
    (plain / "src" / "model.py").write_text("def forward(x): return x\n", encoding="utf-8")
    (plain / "README.md").write_text("# نموذج\n", encoding="utf-8")
    (plain / "config.yaml").write_text("arch: transformer\n", encoding="utf-8")
    (plain / "node_modules" / "left-pad" / "index.js").write_text(
        "function pad(s) {}\n", encoding="utf-8"
    )
    (plain / "__pycache__" / "model.cpython-312.pyc").write_bytes(b"\x00\x01")
    a = build_repo_map(plain)
    b = build_repo_map(plain)
    assert a == b  # حتمية بالبايت في المسح
    text = "\n".join(a)
    assert "src/model.py :: def forward(x)" in text
    assert "README.md :: # نموذج" in text
    assert "config.yaml :: arch:" in text
    assert "node_modules" not in text  # التجاهل المعلن يحكم
    assert "__pycache__" not in text


def test_walk_fallback_max_files_cap(tmp_path):
    plain = tmp_path / "big"
    plain.mkdir()
    for i in range(8):
        (plain / f"mod{i}.py").write_text(f"def fn{i}(): pass\n", encoding="utf-8")
    lines = build_repo_map(plain, max_files=3)
    assert len(lines) == 3
    assert lines == lines[:3]  # القص بعد الفرز — أول ثلاثة مفروزة


def test_walk_fallback_reports_missing_and_unparseable(tmp_path):
    plain = tmp_path / "odd"
    plain.mkdir()
    (plain / "broken.py").write_text("def مقدمة(:\n", encoding="utf-8")
    lines = build_repo_map(plain)
    assert "broken.py :: غير قابل للتحليل" in "\n".join(lines)


def test_git_repo_maps_tracked_only(tmp_path):
    """مستودع git: المتعقّب حصراً — ملف لم يُضاف لا يدخل الخريطة."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "in.py").write_text("def tracked(): pass\n", encoding="utf-8")
    (repo / "out.py").write_text("def untracked(): pass\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "add", "in.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=repo, check=True)
    text = "\n".join(build_repo_map(repo))
    assert "in.py :: def tracked()" in text
    assert "out.py" not in text


def test_ignored_dirs_documented():
    for required in (".git", "node_modules", "__pycache__", ".venv", "dist", "build", "target"):
        assert required in IGNORED_DIRS


# --------------------------------------------------------------- المختار المعجمي
def test_tokenize_drops_stopwords_keeps_domain_words():
    toks = tokenize("The response body is not chunked; إدارة الجلسة")
    assert "response" in toks and "chunked" in toks
    assert "إدارة" in toks and "الجلسة" in toks
    assert "the" not in toks and "is" not in toks and "not" not in toks


def test_query_tokens_includes_node_sides():
    toks = query_tokens(
        "redirects loop with allow_redirects", ["tests/test_redirects.py::TestRedirect::test_loop"]
    )
    assert "redirects" in toks and "loop" in toks and "test_loop" in toks
    assert "testredirect" in toks or "testredirects" in toks  # أطراف العقدة الثلاثة


def test_rank_files_deterministic_and_map_breaks_ties(tmp_path):
    tree = ("requests/models.py", "requests/auth.py", "requests/utils.py")
    query = "Session resolve_redirects_max_hops redirect handling"
    no_map = rank_files(query, tree, ())
    assert rank_files(query, tree, ()) == no_map  # حتمية
    with_map = rank_files(
        query,
        tree,
        (
            "requests/models.py :: class Session «إدارة الجلسة»؛ Session.resolve_redirects(url, *, max_hops)",
        ),
    )
    assert with_map[0] == "requests/models.py"  # التوقيع الدلالي يقلب الترتيب
    assert len(with_map) == len(tree)


def test_rank_files_sorts_ties_by_path():
    tree = ("b/zz.py", "a/zz.py", "c/aa.py")
    ranked = rank_files("حالة بلا أي تطابق", tree, ())
    assert ranked == ("a/zz.py", "b/zz.py", "c/aa.py")


def test_case_hit_and_precision():
    ranked = ("requests/models.py", "requests/adapters.py", "requests/sessions.py")
    gold = ("requests/adapters.py",)
    assert case_hit(ranked, gold, 1) is False
    assert case_hit(ranked, gold, 3) is True
    assert precision_at_k(ranked, gold, 1) == 0.0
    assert precision_at_k(ranked, gold, 3) == pytest.approx(1 / 3)
    assert case_hit((), gold) is False
    assert precision_at_k(ranked, ()) is None


def test_summarize_hits_measured_and_gained():
    records = [
        {
            "instance_id": "a",
            "measured": True,
            "hit_top1_map": True,
            "hit_top1_no_map": False,
            "hit_top3_map": True,
        },
        {
            "instance_id": "b",
            "measured": True,
            "hit_top1_map": False,
            "hit_top1_no_map": False,
            "hit_top3_map": False,
        },
        {"instance_id": "c", "measured": False, "reason_ar": "فشل شجرة"},
    ]
    summary = summarize_hits(records)
    assert summary["measured"] is True
    assert summary["measurable_cases"] == 2
    assert summary["hit_top1_map"] == pytest.approx(0.5)
    assert summary["hit_top1_no_map"] == pytest.approx(0.0)
    assert summary["gained_by_map"] == ["a"]
    assert summary["misses_top1_map"] == ["b"]


def test_summarize_hits_honest_when_nothing_measured():
    summary = summarize_hits([{"instance_id": "x", "measured": False}])
    assert summary["measured"] is False and "reason_ar" in summary


# --------------------------------------------------------------- تكامل الوثيقة
def test_lexmap_doc_shape_if_present():
    """وثيقة القياس الموقعة — إن وُجدت فمخططها محكم: خلاصة معلنة وبصمة."""
    doc_path = Path("benchmarks/results/lexmap_wide_2026-11-13.json")
    if not doc_path.exists():
        pytest.skip("وثيقة القياس لم تُولَّد بعد في هذه الشجرة")
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    assert doc["aggregate"]["measured"] is True
    assert doc["aggregate"]["measurable_cases"] == len([r for r in doc["results"] if r["measured"]])
    assert "chain_hash" in doc and len(doc["chain_hash"]) == 16
    assert doc["data"]["gold_sha16"] and doc["data"]["instances_sha16"]


# --------------------------------------------------------------- عقد التلاقي (الموجة 22)
def test_choice_request_filters_map_lines_outside_tree():
    """عقد الموجة 22: الخريطة لا تسمّي ما ليس في شجرة الاختيار — الخريطة
    العامة (الموجة 21) ترى كل اللغات وشجرة البروتوكول بايثون حصراً؛ السطر
    الخارجي يُستبعد في نقطة التلاقي الواحدة لا في المتسابق ولا في العقل."""
    from zyko.benchmarks.swebench import SWEInstance, build_choice_request

    inst = SWEInstance(
        instance_id="x",
        repo="r",
        base_commit="b" * 40,
        version="1",
        problem_statement="ع",
        test_patch="t",
        fail_to_pass=("a::b",),
        pass_to_pass=(),
    )
    tree = ("requests/models.py", "requests/sessions.py")
    map_lines = (
        "requests/models.py :: class Session «إدارة الجلسة»",
        "README.md :: # النموذج",  # خارج الشجرة — يُستبعد
        "setup.cfg :: metadata:",  # خارج الشجرة — يُستبعد
    )
    request = build_choice_request(inst, tree, map_lines=map_lines)
    assert "requests/models.py :: class Session" in request
    assert "README.md ::" not in request
    assert "setup.cfg ::" not in request
    # خريطة كاملة خارج الشجرة — بلا قسم خريطة أصلاً (الفراغ الصادق)
    request_no_map = build_choice_request(inst, tree, map_lines=("README.md :: # النموذج",))
    assert "خريطة المستودع" not in request_no_map
