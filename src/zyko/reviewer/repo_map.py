"""zyko.reviewer.repo_map — الخريطة الدلالية للمستودع: عقل يختار من رموز لا مسارات عمياء (جولة 11).

درس الجولتين 8–9 بالبايت: عقل اختيار الملف رأى **قائمة مسارات** فقط —
فاختار الجار الأشهر (``models.py``) لا صاحب العلة الحقيقي، واختار
``urllib3/exceptions.py`` في حالة كان جوهرها ``adapters``. الخريطة
الدلالية ترفع الإشارة: لكل ملف بايثون متعقّب سطر واحد يوثّق رموز
المستوى الأعلى (أصناف ودوال بتوقيعها) — فيرى العقل «من يسكن أين»
بدل «ما أسماء الشوارع».

العقود:
- **حتمية بالبايت**: المسارات مرتبة من ``git ls-files``، والرموز مرتبة،
  والأزمنة خارجها — نفس المستودع على أي جهاز = نفس الخريطة.
- **بلا اعتماديات**: ``ast`` و``subprocess`` من المكتبة القياسية.
- **فشل مفتوح**: ملف غير قابل للتحليل يوثَّق في سطره ولا يفجّر الخريطة،
  ومستودع بلا git يعيد خريطة فارغة معلنة.
- **سقف معلن**: ``max_files`` ملف كحد أعلى — الحجم محكوم لا منفلت.

    from zyko.reviewer.repo_map import build_repo_map

    lines = build_repo_map(Path("."))          # سطور الخريطة
    text = "\n".join(lines)                    # النص الحتمي
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "MAX_FILES_DEFAULT",
    "NO_SYMBOLS_MARK",
    "UNPARSEABLE_MARK",
    "build_repo_map",
    "symbol_summary",
]

Runner = Callable[..., Any]

MAX_FILES_DEFAULT = 400
UNPARSEABLE_MARK = "غير قابل للتحليل"
NO_SYMBOLS_MARK = "بلا رموز مستوى أعلى"


def symbol_summary(source: str) -> str | None:
    """ملخص رموز المستوى الأعلى: أصناف ودوال بتوقيعها — مرتبة.

    ``None`` الصادقة للملف غير القابل للتحليل فقط؛ سلسلة فارغة تعني
    ملفاً سليماً بلا رموز دوال/أصناف — الفراغان حالتان موثقتان لا واحدة.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    def _params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        names = [a.arg for a in node.args.args]
        if node.args.vararg:
            names.append(f"*{node.args.vararg.arg}")
        elif node.args.kwonlyargs:
            names.append("*")
        names.extend(a.arg for a in node.args.kwonlyargs)
        return ", ".join(names)

    symbols: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = len(node.bases)
            suffix = f" ({bases} أساس)" if bases else ""
            symbols.append(f"class {node.name}{suffix}")
        elif isinstance(node, ast.FunctionDef):
            symbols.append(f"def {node.name}({_params(node)})")
        elif isinstance(node, ast.AsyncFunctionDef):
            symbols.append(f"async def {node.name}({_params(node)})")
    if not symbols:
        return ""
    return "؛ ".join(sorted(symbols))


def _tracked_py_files(root: Path, runner: Runner, max_files: int) -> tuple[str, ...]:
    """مسارات بايثون المتعقّبة من ``git ls-files`` — مرتبة، مسقوفة بسقف معلن."""
    proc = runner(
        ["git", "ls-files", "*.py"], cwd=str(root), capture_output=True,
        text=True, timeout=30,
    )
    if getattr(proc, "returncode", 1) != 0:
        return ()
    paths = sorted({line.strip() for line in (proc.stdout or "").splitlines() if line.strip()})
    return tuple(paths[:max_files])


def build_repo_map(
    root: Path,
    *,
    runner: Runner = subprocess.run,
    max_files: int = MAX_FILES_DEFAULT,
) -> tuple[str, ...]:
    """سطور الخريطة الدلالية — سطر لكل ملف: المسار ثم رموزه أو وثيقة العجز.

    ملف يتجاوز 200KB يُختصر بسطر حجم موثق (الخريطة إشارة اختيار لا
    نسخة مصدر)، وكل فشل قراءة يوثَّق في سطره — الخريطة لا تسقط أبداً.
    بلا git (ليس مستودعًا) الخريطة فارغة معلنة () — عقد الجولة 11.
    """
    root = Path(root)
    lines: list[str] = []
    for rel in _tracked_py_files(root, runner, max_files):
        path = root / rel
        try:
            if not path.is_file():
                lines.append(f"{rel} :: مفقود من القرص")
                continue
            size = path.stat().st_size
            if size > 200_000:
                lines.append(f"{rel} :: ملف كبير ({size} بايت) — خارج الخريطة")
                continue
            summary = symbol_summary(path.read_text(encoding="utf-8", errors="replace"))
            if summary is None:
                lines.append(f"{rel} :: {UNPARSEABLE_MARK}")
            elif summary == "":
                lines.append(f"{rel} :: {NO_SYMBOLS_MARK}")
            else:
                lines.append(f"{rel} :: {summary}")
        except OSError:
            lines.append(f"{rel} :: فشل قراءة")
    return tuple(lines)
