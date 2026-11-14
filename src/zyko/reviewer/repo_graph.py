"""repo_graph — رسم بياني للمستودع فوق الخريطة الدلالية (الموجة 26).

الزبدة المُستقادة بهندسة عكسية معلنة (منهج المشروع: نأخذ زبدة كل فكرة
ونطوّرها بأسلوبنا): فكرة «الوكيل يستعلم رسمَ البياني بدل قراءة كل
الملفات» التي خفّضت التوكن ورفعت الدقة في المستودعات الكبيرة. أسلوبنا
في تصليتها: AST خالص، حتمية بالبايت، بلا شبكة، بلا git إلزامياً
(الشجرة تُمشى على القرص بالسقوف نفسها التي تمشي بها الخريطة الدلالية).

العقد: ملفات بايثون فقط (مسارات نسبية مرتبة).
الحواف — نوعان فقط، كلاهما قابل للتحقق سطراً بسطر:
  * حافة استيراد: ملف ⇒ ملف (عبارات ``import``/``from`` تُحل إلى ملفات
    الشجرة فعلاً؛ الاستيراد الخارجي (``json``، ``os``) لا يصبح عقدة
    إطلاقاً — لا وحوش في الرسم)
  * حافة اختبار: ملف اختبار (``test_*.py``/``*_test.py``) ⇒ ملف مصدر
    يستورده مباشرة — خريطة «أي اختبارات تغطي أي مصدر»

الاستعلام: :func:`neighborhood` يعيد جوار ملف واحد (يستورد، يُستورد
منه، اختباراته، اختباراته العكسية) — غذاء التخطيط بلا قراءة شاملة.

هذه الوحدة لا تستورد rules ولا engine (طبقة الخريطة أدمى من المراجعة)،
وتمشي على البنية نفسها التي بناها ``repo_map`` فتتكامل معها لا تكررها.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path, PurePosixPath

__all__ = [
    "RepoGraph",
    "build_repo_graph",
    "neighborhood",
    "neighborhood_lines",
    "neighborhood_note_for",
    "graph_to_json",
]

# سقف الملفات الموثق (الخريطة إشارة لا نسخة — السقف نفسه معلن)
MAX_FILES_DEFAULT = 400

# مجلدات لا تمشى أبداً (نفس روح سقوف repo_map)
SKIP_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        ".mypy_cache",
        ".pytest_cache",
        "htmlcov",
    }
)


def _is_test_rel(rel: str) -> bool:
    name = PurePosixPath(rel).name
    return name.startswith("test_") or name.endswith("_test.py")


def _module_names(rel: str) -> tuple[str, ...]:
    """أسماء الوحدات التي يقدّمها ملف: ``pkg/sub/mod.py`` ⇒ ``pkg.sub.mod``؛
    ``pkg/__init__.py`` ⇒ ``pkg``؛ الجذر ``__init__.py`` ⇒ لا اسم."""
    p = PurePosixPath(rel)
    parts = p.parts[:-1]
    if p.stem == "__init__":
        return (".".join(parts),) if parts else ()
    return (".".join(parts + (p.stem,)),)


def _walked_py_files(root: Path, max_files: int) -> tuple[str, ...]:
    """مسارات .py النسبية مرتبة — بلا git، بلا مفاجآت."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        rel_dir = os.path.relpath(dirpath, root)
        for fn in sorted(filenames):
            if not fn.endswith(".py"):
                continue
            rel = fn if rel_dir == "." else f"{rel_dir.replace(os.sep, '/')}/{fn}"
            found.append(rel)
            if len(found) >= max_files:
                return tuple(found)
    return tuple(found)


def _imports_of(tree: ast.Module, rel: str) -> tuple[str, ...]:
    """أسماء الوحدات المستوردة داخل ملف، محسولة — مرتبة بلا تكرار."""
    parts = PurePosixPath(rel).parts[:-1]
    cands: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                cands.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # استيراد نسبي: القاعدة حزمة المستورد
                base = (
                    list(parts[: len(parts) - (node.level - 1)]) if len(parts) >= node.level else []
                )
                if node.module:
                    cands.add(".".join(base + node.module.split(".")))
                else:
                    for alias in node.names:
                        cands.add(".".join(base + [alias.name]))
            elif node.module:
                cands.add(node.module)
    return tuple(sorted(cands))


def _resolve(cand: str, mods: dict[str, str]) -> str | None:
    """حسم اسم مستورد إلى ملف شجرة: تام، وإلا أطول حزمة سلفية موجودة."""
    if cand in mods:
        return mods[cand]
    pieces = cand.split(".")
    for k in range(len(pieces) - 1, 0, -1):
        prefix = ".".join(pieces[:k])
        if prefix in mods:
            return mods[prefix]
    return None


class RepoGraph:
    """رسم بياني حتمي: عقد ملفات + حواف استيراد + حواف اختبار."""

    __slots__ = ("root", "files", "import_edges", "test_edges", "_mods")

    def __init__(
        self,
        root: Path,
        files: tuple[str, ...],
        import_edges: tuple[tuple[str, str], ...],
        test_edges: tuple[tuple[str, str], ...],
        mods: dict[str, str],
    ) -> None:
        self.root = root
        self.files = files
        self.import_edges = import_edges
        self.test_edges = test_edges
        self._mods = mods

    def to_dict(self) -> dict:
        return {
            "schema": "zyko.repo_graph/1",
            "file_count": len(self.files),
            "files": list(self.files),
            "import_edges": [[a, b] for a, b in self.import_edges],
            "test_edges": [[a, b] for a, b in self.test_edges],
        }

    def neighborhood(self, rel: str) -> dict:
        """جوار ملف واحد — حتمي بالبايت، الملف المجهول رفض معلن لا تخمين."""
        if rel not in self.files:
            raise KeyError(f"الملف خارج الرسم: {rel}")
        imports = sorted({b for a, b in self.import_edges if a == rel})
        imported_by = sorted({a for a, b in self.import_edges if b == rel})
        tests = sorted({b for a, b in self.test_edges if a == rel})
        tested_by = sorted({a for a, b in self.test_edges if b == rel})
        return {
            "file": rel,
            "imports": imports,
            "imported_by": imported_by,
            "tests": tests,
            "tested_by": tested_by,
        }


def build_repo_graph(root: Path | str, *, max_files: int = MAX_FILES_DEFAULT) -> RepoGraph:
    """بناء الرسم من شجرة على القرص — AST خالص، فشل قراءة ملف سطر عجز لا سقوط."""
    root = Path(root)
    files = _walked_py_files(root, max_files)
    mods: dict[str, str] = {}
    for rel in files:
        for name in _module_names(rel):
            mods.setdefault(name, rel)

    import_edges: set[tuple[str, str]] = set()
    test_edges: set[tuple[str, str]] = set()
    for rel in files:
        path = root / rel
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (SyntaxError, ValueError, OSError):
            continue  # ملف غير قابل للتحليل لا ينتج حواف — موثق بسكوت صامت مقصود
        for cand in _imports_of(tree, rel):
            target = _resolve(cand, mods)
            if target is None or target == rel:
                continue
            import_edges.add((rel, target))
            if _is_test_rel(rel) and not _is_test_rel(target):
                test_edges.add((rel, target))
    return RepoGraph(
        root=root,
        files=files,
        import_edges=tuple(sorted(import_edges)),
        test_edges=tuple(sorted(test_edges)),
        mods=mods,
    )


def graph_to_json(graph: RepoGraph) -> str:
    """تسلسل حتمي بالبايت — نفس الرسم ⇒ نفس البايتات دائماً."""
    return json.dumps(graph.to_dict(), ensure_ascii=False, sort_keys=True, indent=1)


def neighborhood(graph: RepoGraph, rel: str) -> dict:
    """واجهة الاستعلام الموثقة — تمرير صريح بدل استدعاء خاصية."""
    return graph.neighborhood(rel)


# ------------------------------------------ تغذية التخطيط بجوار الرسم (الموجة 28)
# العقد النصية للتغذية — أقسام بالترتيب الثابت، القسم الفارغ يُحذف لا يُعبَّأ
_LINE_IMPORTS = "يستورد: {0}"
_LINE_IMPORTED_BY = "يُستورد منه: {0}"
_LINE_TEST_COVER = "مصادر يغطيها كاختبار: {0}"
_LINE_TESTED_BY = "اختبارات تستورده: {0}"
_LINE_ISOLATED = "الملف {0} بلا حواف استيراد أو تغطية اختبارية داخل السقف المعلن"
_ROOT_MARKERS = ("pyproject.toml", "setup.py", "setup.cfg", ".git")
_ROOT_SEARCH_LEVELS = 6


def neighborhood_lines(graph: RepoGraph, rel: str) -> tuple[str, ...]:
    """سطور غذاء التخطيط لملف واحد — فراغ معلن للمسار خارج الرسم.

    اختلاف العقد الموثق عن :func:`neighborhood`: الملف المجهول يعيد
    ``()`` لا استثناء — لأن المختار من شجرة ``git ls-files`` قد يقع
    خارج سقف المشي على القرص، واستثناء هناك يُسقط المحاولة كلها بلا
    دليل. أما العزل الكامل فيُسمّى سطراً موثقاً لا فراغاً.
    """
    if rel not in graph.files:
        return ()
    nb = graph.neighborhood(rel)
    # أقسام الارتباط بالكود تستبعد ملفات الاختبار — تغطيتها لها قسمان
    # مخصصان أسفلهما (خريطة الاختبار حدة مستقلة لا خليط)
    imports = [x for x in nb["imports"] if not _is_test_rel(x)]
    imported_by = [x for x in nb["imported_by"] if not _is_test_rel(x)]
    lines: list[str] = []
    if imports:
        lines.append(_LINE_IMPORTS.format(", ".join(imports)))
    if imported_by:
        lines.append(_LINE_IMPORTED_BY.format(", ".join(imported_by)))
    if nb["tests"]:
        lines.append(_LINE_TEST_COVER.format(", ".join(nb["tests"])))
    if nb["tested_by"]:
        lines.append(_LINE_TESTED_BY.format(", ".join(nb["tested_by"])))
    if not lines:
        return (_LINE_ISOLATED.format(rel),)
    return tuple(lines)


def _find_root(start: Path) -> Path:
    """جذر المستودع: أول علامة صاعدة ضمن سقف ستة مستويات، وإلا المجلد الحامل."""
    cur = start.parent
    for _ in range(_ROOT_SEARCH_LEVELS):
        if any((cur / m).exists() for m in _ROOT_MARKERS):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start.parent


def neighborhood_note_for(target: Path | str, *, max_files: int = MAX_FILES_DEFAULT) -> str:
    """غذاء تخطيط جاهز للحقن في طلب الخطة — فراغ عند كل عجز معلن.

    العقد: ملف غير موجود أو غير بايثوني أو خارج الرسم أو معزول تماماً
    (لا حواف من أي نوع) ⇒ ``""`` — التخطيط لا يُضجَّر بسطر بلا معلومة.
    الجذر يُحسم بأول علامة صاعدة (``pyproject.toml``/``setup.py``/
    ``setup.cfg``/``.git``) ضمن ستة مستويات، وإلا المجلد الحامل للملف.
    """
    try:
        path = Path(target).resolve()
        if path.suffix != ".py" or not path.is_file():
            return ""
        root = _find_root(path)
        rel = path.relative_to(root).as_posix()
        graph = build_repo_graph(root, max_files=max_files)
        nb = graph.neighborhood(rel)
    except (OSError, ValueError, KeyError):
        return ""  # عجز موثق: مسار خارج الجذر أو خارج الرسم — فراغ لا استثناء
    if not (nb["imports"] or nb["imported_by"] or nb["tests"] or nb["tested_by"]):
        return ""  # عزل كامل — لا غذاء تخطيط
    return "\n".join(neighborhood_lines(graph, rel))
