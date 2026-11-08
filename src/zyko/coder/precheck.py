"""zyko.coder.precheck — فحص التوليد الحتمي قبل التسليم (D14).

A generated project reaches the user only after three deterministic
gates, in order:

1. **ast.parse** on every ``.py`` file (broken syntax is rejected here,
   structurally — it can never reach the user);
2. **compile()** of every file (the compileall semantic, in-process);
3. **RTL gate** via ``zyko.tools.rtl`` — errors block, warnings don't;
4. optional **pytest run** inside the project (fresh interpreter,
   timeout-bounded) — used by the acceptance gate (D20–21) and
   ``--run-tests``.

The report is structured with Arabic messages; ``ok`` means "deliver".
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .plan import TEMPLATES, ProjectPlan
from .templates import GenFile

# امتدادات تُفحص كنصوص RTL عامة (غير python/css/html التي لها فاحص خاص)
_TEXT_EXTS = {".md", ".txt"}

_SEV_ERROR = "error"


@dataclass
class PrecheckReport:
    """نتيجة الفحص: ok = يُسلَّم؛ problems = أسباب الرفض بالعربية."""

    ok: bool = True
    py_files: int = 0
    other_files: int = 0
    problems: list[str] = field(default_factory=list)
    test_output_tail: str = ""

    def add_problem(self, msg: str) -> None:
        self.problems.append(msg)
        self.ok = False


def _lang_for(path: str) -> str | None:
    ext = Path(path).suffix.lower()
    if ext == ".py":
        return "python"
    if ext == ".css":
        return "css"
    if ext == ".html":
        return "html"
    if ext in _TEXT_EXTS:
        return "text"
    return None


def check_source_tree(tree: dict[str, GenFile]) -> PrecheckReport:
    """البوابات 1–3 على الشجرة في الذاكرة (قبل الكتابة على القرص)."""
    report = PrecheckReport()

    from zyko.tools.rtl import RTLChecker  # استيراد متأخر: يبقي coder مستقلًا عن tools عند الاستيراد

    checker = RTLChecker()

    for path in sorted(tree):
        f = tree[path]
        lang = _lang_for(path)
        if lang is None:
            report.other_files += 1
            continue

        if lang == "python":
            report.py_files += 1
            try:
                ast.parse(f.content, filename=path)
            except SyntaxError as exc:
                report.add_problem(
                    f"«{path}»: تركيب بايثون مكسور سطر {exc.lineno}: {exc.msg} — ملف مرفوض قبل التسليم"
                )
                continue
            try:
                compile(f.content, path, "exec")
            except (ValueError, TypeError) as exc:  # حالات نادرة (null bytes...)
                report.add_problem(f"«{path}»: فشل الترجمة البنيوية: {exc}")

        try:
            findings = checker.check_source(f.content, lang=lang)
        except Exception as exc:  # noqa: BLE001 — الفاحص لا يعطّل التسليم أبدًا
            report.add_problem(
                f"«{path}»: تعذّر فحص RTL ({type(exc).__name__}) — أصلح الأداة لا المشروع"
            )
            continue
        for finding in findings:
            if finding.severity == _SEV_ERROR:
                report.add_problem(f"«{path}»: {finding.rule} — {finding.message}")

    return report


def check_directory(root: Path) -> PrecheckReport:
    """نفس البوابات على مجلد قائم (zyko coder check)."""
    root = Path(root)
    if not root.is_dir():
        report = PrecheckReport(ok=False)
        report.add_problem(f"«{root}» ليس مجلدًا")
        return report

    tree: dict[str, GenFile] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts or ".git" in p.parts:
            continue
        rel = p.relative_to(root).as_posix()
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            report = PrecheckReport(ok=False)
            report.add_problem(f"«{rel}»: ليس UTF-8 — الملفات المولَّدة كلها UTF-8")
            return report
        tree[rel] = GenFile(rel, text, "")
    return check_source_tree(tree)


def run_project_tests(root: Path, timeout: int = 180) -> PrecheckReport:
    """البوابة 4: pytest داخل المشروع بمفسّر نظيف ومهلة محدودة."""
    root = Path(root)
    report = PrecheckReport()
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        # sys.executable ثابت وأوسطات مبرمجة — بلا shell ولا مدخلات مستخدم
        # encoding صريح: رسائل pytest عربية والافتراضي على Windows cp1252
        proc = subprocess.run(  # nosec B603
            [sys.executable, "-m", "pytest", "-q", "--no-header", "-x"],
            cwd=str(root),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        report.add_problem(f"اختبارات المشروع تجاوزت المهلة ({timeout} ث) — مرفوض")
        return report

    tail = "\n".join((proc.stdout or "").splitlines()[-8:])
    report.test_output_tail = tail
    if proc.returncode == 5:
        # pytest: لا اختبارات مجمَّعة — الجناح كله تخطّى أو فارغ؛ لا يُحسب نجاحًا
        report.add_problem("لم تُجمَع أي اختبارات (كلها متخطاة أو الجناح فارغ) — لا يُحسب نجاحًا")
    elif proc.returncode != 0:
        first_fail = next(
            (ln for ln in (proc.stdout or "").splitlines() if ln.startswith("FAILED")),
            "",
        )
        report.add_problem(f"اختبارات المشروع لم تمر (كود {proc.returncode}) {first_fail}".strip())
    return report


def full_gate(
    plan: ProjectPlan,
    root: Path,
    run_tests: bool = True,
    test_timeout: int = 180,
) -> PrecheckReport:
    """البوابات كاملة على مشروع مكتوب على القرص (تُستخدم في بوابة القبول)."""
    if plan.template not in TEMPLATES:
        report = PrecheckReport(ok=False)
        report.add_problem(f"قالب غير معروف: {plan.template}")
        return report

    report = check_directory(root)
    if run_tests and report.ok:
        test_report = run_project_tests(root, timeout=test_timeout)
        report.py_files += 0
        report.problems.extend(test_report.problems)
        report.test_output_tail = test_report.test_output_tail
        if test_report.problems:
            report.ok = False
    return report


__all__ = [
    "PrecheckReport",
    "check_directory",
    "check_source_tree",
    "full_gate",
    "run_project_tests",
]
