"""zyko.reviewer.repo_map — الخريطة الدلالية للمستودع: عقل يختار من رموز لا مسارات عمياء.

جولة 11 ولدت الخريطة: لكل ملف بايثون متعقّب سطر واحد يوثّق رموز
المستوى الأعلى بتوقيعها — فيرى العقل «من يسكن أين» بدل «ما أسماء
الشوارع». الموجة 21 ترفع الخريطة إلى **repo-map بتوقيع الرموز**
(الفجوة الثالثة الموثقة في تقرير تقييم 0.43.0 §7 — علاج إخفاقات
الاختيار بنمط الجوار الدلالي):

1. **توقيع دلالي**: سطر الوثيقة الأول (docstring) لكل صنف ودالة يُلحق
   بالرمز — العقل يطابق معنى التقرير مع معنى المقيم لا اسمَه فقط.
2. **أعضاء الأصناف**: دوال الأصناف مباشرة تحت صنفها باسمها الكامل
   ``class Name.method`` — علة الجوار تُعالج من الجذر: ``Session``
   التي يسكنها ``resolve_redirects`` لا تُشبه بعدُ ملفًا غريبًا.
3. **متعددة اللغات**: بايثون بالـ``ast`` من المكتبة القياسية، وبقية
   العائلات (JS/TS، Rust، Go، Java/Kotlin، C/C++، Ruby، PHP، Shell)
   مستخرجات قوالب معلنة — ووثائق المستودع (Markdown عناوينها، YAML/JSON/
   TOML مفاتيحها الجذرية) في الخريطة أيضًا. صفر اعتماديات عقد ثابت.
4. **عمل بلا git**: مستودع بلا ``.git`` (تنزيل Hugging Face، فك ضغط
   أرشيف، شجرة عمل مرفوعة يدويًا) يُمشى على القرص بقائمة تجاهل معلنة
   ``IGNORED_DIRS`` — الخريطة لا تعرف «مستودعًا غير مدعوم».

العقود (جولة 11 + تعديلها الموثق في الموجة 21):
- **حتمية بالبايت**: المسارات مرتبة، والرموز مرتبة، والأزمنة خارجها —
  نفس الشجرة على أي جهاز = نفس الخريطة.
- **بلا اعتماديات**: ``ast`` و``re`` و``subprocess`` من المكتبة القياسية.
- **فشل مفتوح**: ملف غير قابل للتحليل يوثَّق في سطره ولا يفجّر الخريطة.
- **سقوف معلنة**: ``max_files`` ملفًا و``MAX_SYMBOLS_PER_FILE`` رمزًا
  للملف و``MAX_DOC_CHARS`` حرفًا للوثيقة — الحجم محكوم لا منفلت.
- **تعديل الموجة 21 الموثق**: بلا git كانت الخريطة فارغة معلنة () —
  صارت تُمشى على القرص بالسقوف نفسها؛ الفارق الوحيد مصدر قائمة
  الملفات، وصف الملفات نفسه لا يتغير.

    from zyko.reviewer.repo_map import build_repo_map

    lines = build_repo_map(Path("."))          # سطور الخريطة
    text = "\n".join(lines)                    # النص الحتمي
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import warnings
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "IGNORED_DIRS",
    "MAX_DOC_CHARS",
    "MAX_FILES_DEFAULT",
    "MAX_SYMBOLS_PER_FILE",
    "NO_SYMBOLS_MARK",
    "UNPARSEABLE_MARK",
    "build_repo_map",
    "map_suffixes",
    "regex_symbols",
    "symbol_summary",
]

Runner = Callable[..., Any]

MAX_FILES_DEFAULT = 400
MAX_SYMBOLS_PER_FILE = 24
MAX_DOC_CHARS = 72
UNPARSEABLE_MARK = "غير قابل للتحليل"
NO_SYMBOLS_MARK = "بلا رموز مستوى أعلى"

#: أدلة تُشذَّب في مسح القرص (وضع بلا git) — قائمة معلنة لا سرية
IGNORED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".next",
        ".cache",
        "target",
        "site-packages",
        ".idea",
        ".vscode",
    }
)


# --------------------------------------------------------------- بايثون
def _docline(node: ast.AST) -> str:
    """سطر الوثيقة الأول — توقيع دلالي مقصوص بسقف معلن، أو الفراغ الصادق."""
    doc = (
        ast.get_docstring(node)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        else None
    )
    if not doc:
        return ""
    first = doc.strip().splitlines()[0].strip() if doc.strip() else ""
    if not first:
        return ""
    if len(first) > MAX_DOC_CHARS:
        first = first[: MAX_DOC_CHARS - 1] + "…"
    return f" «{first}»"


def _params(node: ast.FunctionDef | ast.AsyncFunctionDef, *, drop_first: bool = False) -> str:
    args = list(node.args.args)
    if drop_first and args and args[0].arg in ("self", "cls"):
        args = args[1:]
    names = [a.arg for a in args]
    if node.args.vararg:
        names.append(f"*{node.args.vararg.arg}")
    elif node.args.kwonlyargs:
        names.append("*")
    names.extend(a.arg for a in node.args.kwonlyargs)
    return ", ".join(names)


def symbol_summary(source: str) -> str | None:
    """ملخص رموز بايثون: أصناف ودوال وأعضاء الأصناف بتوقيعها وسطر وثيقتها — مرتبة.

    ``None`` للملف غير القابل للتحليل فقط؛ سلسلة فارغة تعني ملفًا سليمًا
    بلا رموز دوال/أصناف — الفراغان حالتان موثقتان لا واحدة. رموز كل صنف
    تظهر باسمه الكامل ``class Name.method`` — أعضاء الأصناف جزء من
    التوقيع لا ضيف مخفي (الموجة 21).
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(source)
    except SyntaxError:
        return None

    symbols: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = len(node.bases)
            suffix = f" ({bases} أساس)" if bases else ""
            symbols.append(f"class {node.name}{suffix}{_docline(node)}")
            for member in node.body:
                if isinstance(member, ast.FunctionDef):
                    symbols.append(
                        f"{node.name}.{member.name}({_params(member, drop_first=True)}){_docline(member)}"
                    )
                elif isinstance(member, ast.AsyncFunctionDef):
                    symbols.append(
                        f"{node.name}.{member.name}({_params(member, drop_first=True)}){_docline(member)}"
                    )
        elif isinstance(node, ast.FunctionDef):
            symbols.append(f"def {node.name}({_params(node)}){_docline(node)}")
        elif isinstance(node, ast.AsyncFunctionDef):
            symbols.append(f"async def {node.name}({_params(node)}){_docline(node)}")
    if not symbols:
        return ""
    return "؛ ".join(sorted(symbols)[:MAX_SYMBOLS_PER_FILE])


# --------------------------------------------------------------- العائلات الأخرى
_C_KEYS = frozenset({"if", "for", "while", "switch", "return", "else", "do", "sizeof", "catch"})

#: لكل لغة قوالبها المعلنة: (النمط، قالب التوقيع) — الأسماء من المجموعة الأولى
_LANG_PATTERNS: dict[str, tuple[tuple[re.Pattern[str], str], ...]] = {
    "js": (
        (
            re.compile(
                r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)",
                re.M,
            ),
            "fn {}()",
        ),
        (
            re.compile(r"^[ \t]*(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)", re.M),
            "class {}",
        ),
        (re.compile(r"^[ \t]*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)", re.M), "interface {}"),
        (re.compile(r"^[ \t]*(?:export\s+)?type\s+([A-Za-z_$][\w$]*)\s*=", re.M), "type {}"),
        (
            re.compile(
                r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>",
                re.M,
            ),
            "const {} ⇒",
        ),
    ),
    "rust": (
        (re.compile(r"\bfn\s+([a-z_]\w*)"), "fn {}()"),
        (re.compile(r"\bstruct\s+([A-Za-z_]\w*)"), "struct {}"),
        (re.compile(r"\benum\s+([A-Za-z_]\w*)"), "enum {}"),
        (re.compile(r"\btrait\s+([A-Za-z_]\w*)"), "trait {}"),
        (
            re.compile(r"\bimpl(?:<[^>]*>)?\s+(?:[A-Za-z_][\w<>,\s]*\s+for\s+)?([A-Za-z_]\w*)"),
            "impl {}",
        ),
        (re.compile(r"\bmod\s+([a-z_]\w*)"), "mod {}"),
    ),
    "go": (
        (
            re.compile(
                r"^[ \t]*func\s+(?:\([^)]*?\s(\*?[A-Za-z_]\w*)\)\s*)?([A-Za-z_]\w*)\s*\(", re.M
            ),
            "go-func",
        ),
        (re.compile(r"^[ \t]*type\s+(\w+)\s+(struct|interface)\b", re.M), "type {} {}"),
    ),
    "jvm": (
        (
            re.compile(
                r"^[ \t]*(?:@\w+\s+)*(?:public\s+|private\s+|protected\s+|final\s+|abstract\s+|static\s+)*(?:class|interface|object|enum)\s+(\w+)",
                re.M,
            ),
            "class {}",
        ),
        (
            re.compile(
                r"^[ \t]*(?:@\w+\s+)*(?:public\s+|private\s+|protected\s+|internal\s+|override\s+|suspend\s+|inline\s+)*(?:fun\s+)(\w+)\s*[(<]",
                re.M,
            ),
            "fn {}()",
        ),
    ),
    "ccpp": (
        (re.compile(r"^[ \t]*(?:class|struct)\s+([A-Z]\w*)", re.M), "class {}"),
        (
            re.compile(r"^[ \t]*[A-Za-z_][\w\s\*&:<>,]*?([a-zA-Z_]\w*)\s*\([^;{]*\)\s*\{", re.M),
            "fn {}()",
        ),
    ),
    "ruby": (
        (re.compile(r"^[ \t]*def\s+([\w?.=!]+)", re.M), "def {}()"),
        (re.compile(r"^[ \t]*class\s+([A-Z][\w:]*)", re.M), "class {}"),
        (re.compile(r"^[ \t]*module\s+([A-Z][\w:]*)", re.M), "module {}"),
    ),
    "php": (
        (re.compile(r"^[ \t]*function\s+([\w]+)", re.M), "fn {}()"),
        (re.compile(r"^[ \t]*(?:abstract\s+|final\s+)?class\s+(\w+)", re.M), "class {}"),
    ),
    "shell": (
        (re.compile(r"^[ \t]*function\s+([A-Za-z_]\w*)", re.M), "fn {}()"),
        (re.compile(r"^[ \t]*([A-Za-z_]\w*)\s*\(\)\s*\{", re.M), "fn {}()"),
    ),
    "yaml": ((re.compile(r"^([A-Za-z_][\w .-]*):(?:\s|$)", re.M), "{}:"),),
    "toml": ((re.compile(r"^\[([^\]]+)\]", re.M), "[{}]"),),
    "markdown": ((re.compile(r"^(#{1,3})\s+(.+)$", re.M), "md-head"),),
}

#: الامتداد → عائلة اللغة — بايثون مستثناة (ast لا قوالب)
_SUFFIX_LANG: dict[str, str] = {}
for _suffixes, _lang in (
    ((".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"), "js"),
    ((".rs",), "rust"),
    ((".go",), "go"),
    ((".java", ".kt", ".kts"), "jvm"),
    ((".c", ".h", ".cpp", ".hpp", ".cc", ".hh"), "ccpp"),
    ((".rb",), "ruby"),
    ((".php",), "php"),
    ((".sh", ".bash"), "shell"),
    ((".yaml", ".yml"), "yaml"),
    ((".toml",), "toml"),
    ((".md",), "markdown"),
):
    for _s in _suffixes:
        _SUFFIX_LANG[_s] = _lang

#: الامتدادات المدعومة كلها — بايثون + العائلات القالبية + JSON
PYTHON_SUFFIXES: frozenset[str] = frozenset({".py", ".pyi"})
JSON_SUFFIXES: frozenset[str] = frozenset({".json"})


def map_suffixes() -> frozenset[str]:
    """كل الامتدادات التي تدخل الخريطة — معلنة لا مخمّنة."""
    return PYTHON_SUFFIXES | JSON_SUFFIXES | frozenset(_SUFFIX_LANG)


def regex_symbols(source: str, suffix: str) -> str | None:
    """رموز ملف غير بايثون بقوالب معلنة — ``None`` للعائلة المجهولة حصراً.

    JSON يُقرأ بمحلل المكتبة القياسية (مفاتيح الجذر حصراً) وعطبُه
    غير قابل للتحليل؛ بناء JSON قائمةٌ يُعلن بلا رموز. القوالب
    لا تفهم اللغة كلها — تلتقط التوقيعات المتعارَف عليها، والالتقاط
    الزائد أمن من الصمت: رمز ملتقط زائداً يوقّع السطر ولا يفسد الاختيار.
    """
    if suffix in JSON_SUFFIXES:
        try:
            doc = json.loads(source)
        except ValueError:
            return None
        if isinstance(doc, dict):
            keys = [f"{k}:" for k in doc]
            return "؛ ".join(sorted(keys)[:MAX_SYMBOLS_PER_FILE]) if keys else ""
        return ""
    lang = _SUFFIX_LANG.get(suffix)
    if lang is None:
        return None
    symbols: list[str] = []
    for pattern, template in _LANG_PATTERNS[lang]:
        for match in pattern.finditer(source):
            groups = [g for g in match.groups() if g is not None]
            if template == "go-func":
                # المجموعتان: المستقبِل ثم الاسم — أو الاسم وحده
                if len(groups) == 2:
                    symbols.append(f"func ({groups[0]}) {groups[1]}()")
                elif groups:
                    symbols.append(f"func {groups[0]}()")
                continue
            if template == "md-head":
                head = " ".join(groups[-1].split())
                if len(head) > MAX_DOC_CHARS:
                    head = head[: MAX_DOC_CHARS - 1] + "…"
                symbols.append(f"{groups[0]} {head}")
                continue
            name = groups[-1] if groups else ""
            if not name or (lang == "ccpp" and name in _C_KEYS):
                continue
            symbols.append(template.format(*groups))
    if not symbols:
        return ""
    seen: set[str] = set()
    unique = [s for s in symbols if not (s in seen or seen.add(s))]
    return "؛ ".join(sorted(unique)[:MAX_SYMBOLS_PER_FILE])


def _file_summary(path: Path, rel: str) -> str:
    """سطر الخريطة لملف واحد — كل عجز موثق في سطره، الخريطة لا تسقط."""
    suffix = path.suffix.lower()
    try:
        if not path.is_file():
            return f"{rel} :: مفقود من القرص"
        size = path.stat().st_size
        if size > 200_000:
            return f"{rel} :: ملف كبير ({size} بايت) — خارج الخريطة"
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return f"{rel} :: فشل قراءة"
    if suffix in PYTHON_SUFFIXES:
        summary = symbol_summary(source)
    else:
        summary = regex_symbols(source, suffix)
    if summary is None:
        return f"{rel} :: {UNPARSEABLE_MARK}"
    if summary == "":
        return f"{rel} :: {NO_SYMBOLS_MARK}"
    return f"{rel} :: {summary}"


def _tracked_mapped_files(root: Path, runner: Runner, max_files: int) -> tuple[str, ...]:
    """الملفات المتعقّبة ذات الامتدادات المدعومة — مرتبة، مسقوفة بسقف معلن.

    بلا git (ليس مستودعًا أو git غائب) يُمشى على القرص بقائمة التجاهل
    المعلنة — تعديل الموجة 21 الموثق: الخريطة تعمل في كل ظرف لا في
    المستودع المثالي فقط.
    """
    try:
        proc = runner(
            ["git", "ls-files"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except OSError:
        proc = None
    suffixes = map_suffixes()
    if proc is not None and getattr(proc, "returncode", 1) == 0:
        paths = {
            line.strip()
            for line in (proc.stdout or "").splitlines()
            if line.strip() and Path(line.strip()).suffix.lower() in suffixes
        }
        return tuple(sorted(paths)[:max_files])
    return tuple(_walked_mapped_files(root, suffixes)[:max_files])


def _walked_mapped_files(root: Path, suffixes: frozenset[str]) -> list[str]:
    """مسح القرص بقائمة التجاهل المعلنة — الترتيب فرز لا أمر نظام."""
    found: list[str] = []
    root = Path(root)
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name in IGNORED_DIRS:
                    continue
                stack.append(entry)
            elif entry.is_file() and entry.suffix.lower() in suffixes:
                try:
                    rel = entry.relative_to(root).as_posix()
                except ValueError:
                    continue
                found.append(rel)
    return sorted(found)


def build_repo_map(
    root: Path,
    *,
    runner: Runner = subprocess.run,
    max_files: int = MAX_FILES_DEFAULT,
) -> tuple[str, ...]:
    """سطور الخريطة الدلالية — سطر لكل ملف: المسار ثم رموزه أو وثيقة العجز.

    ملف يتجاوز 200KB يُختصر بسطر حجم موثق (الخريطة إشارة اختيار لا
    نسخة مصدر)، وكل فشل قراءة يوثَّق في سطره — الخريطة لا تسقط أبداً.
    بلا git تُمشى الشجرة على القرص بالسقوف نفسها (تعديل الموجة 21
    الموثق — كانت الخريطة فارغة معلنة ()).
    """
    root = Path(root)
    return tuple(
        _file_summary(root / rel, rel) for rel in _tracked_mapped_files(root, runner, max_files)
    )
