"""context.py — باني السياق المنظم (بنية 1 من النظام الهجين).

لا يُرسل الكود كاملاً لمحرك تفكير أبداً. المدخل: مصدر + نتيجة المراجع
الحتمي. المخرَج: سياق لكل ملاحظة — مقتطف محيط مضبوط + هوية المتغير
المنخرط + منشؤه (عائلة تلويث من taint) + وجهاته (أين يُستدعى/يُمرَّر/
يُعاد) — كل ذلك حتمي بالبايت وقابل للتحقق سطراً بسطر.

الحدود الموثقة: ملف لا يُحلَّل يعطي تدفقاً «غير معروف» لا سقوطاً؛
الاستعمالات مسقوفة (أول 5) لأن السياق إشارة لا نسخة.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from zyko.reviewer.engine import ReviewResult
from zyko.reviewer.taint import collect_taints

__all__ = ["StructuredContext", "build_contexts"]

_USAGES_CAP = 5

_FAMILY_AR = {
    "input": "ملوث من إدخال المستخدم (input/sys.argv)",
    "request": "ملوث من بيانات الطلب (request.*)",
    "both": "ملوث من الإدخال وبيانات الطلب معاً",
    "clean": "غير ملوث بمصادر معروفة",
    "unknown": "غير معروف — الملف لم يُحلَّل",
}


@dataclass
class StructuredContext:
    """سياق ملاحظة واحد: الموقع + المقتطف + التدفق — قابل للتسلسل."""

    schema: str = "zyko.hybrid.context/1"
    filename: str = "<text>"
    rule_id: str = ""
    severity: str = ""
    category: str = ""
    line: int = 0
    message_ar: str = ""
    suggestion_ar: str = ""
    snippet: tuple[str, ...] = ()
    variable: str | None = None
    taint_family_ar: str = _FAMILY_AR["clean"]
    tainted: bool = False
    first_assignment_line: int | None = None
    usages: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "filename": self.filename,
            "finding": {
                "rule_id": self.rule_id,
                "severity": self.severity,
                "category": self.category,
                "line": self.line,
                "message_ar": self.message_ar,
                "suggestion_ar": self.suggestion_ar,
            },
            "snippet": list(self.snippet),
            "flow": {
                "variable": self.variable,
                "tainted": self.tainted,
                "family_ar": self.taint_family_ar,
                "first_assignment_line": self.first_assignment_line,
                "usages": list(self.usages),
            },
        }


def _find_statement(tree: ast.Module, line: int) -> ast.stmt | None:
    """أضيق عبارة تحوي السطر المعلن (باستخدام lineno/end_lineno)."""
    best: ast.stmt | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", start)
        if start is None or end is None:
            continue
        if start <= line <= end:
            if best is None or (node.end_lineno - node.lineno) <= (best.end_lineno - best.lineno):
                best = node
    return best


def _involved_variable(stmt: ast.stmt | None) -> str | None:
    """المتغير المنخرط: هدف إسناد أولاً، ثم دالة نداء، ثم أول اسم وسيط."""
    if stmt is None:
        return None
    if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        target = stmt.targets[0] if isinstance(stmt, ast.Assign) else stmt.target
        for node in ast.walk(target):
            if isinstance(node, ast.Name):
                return node.id
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        func = stmt.value.func
        if isinstance(func, ast.Name):
            return func.id
        for arg in stmt.value.args:
            for node in ast.walk(arg):
                if isinstance(node, ast.Name):
                    return node.id
    for node in ast.walk(stmt):
        if isinstance(node, ast.Name):
            return node.id
    return None


def _first_assignment_line(tree: ast.Module, var: str) -> int | None:
    """أول سطر يُسند فيه الاسم — منشؤه الموثق."""
    best: int | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.For)):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            elif isinstance(node, ast.For):
                targets = [node.target]
            for t in targets:
                if any(isinstance(n, ast.Name) and n.id == var for n in ast.walk(t)):
                    if best is None or node.lineno < best:
                        best = node.lineno
    return best


def _usages(tree: ast.Module, var: str, cap: int = _USAGES_CAP) -> tuple[dict, ...]:
    """أين يذهب المتغير: استدعاء، تمرير، إعادة، إسناد — مسقوف مرتب بالسطر."""
    out: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == var:
                out.append({"kind": "called", "line": node.lineno, "name": var})
            for arg in node.args:
                if any(isinstance(n, ast.Name) and n.id == var for n in ast.walk(arg)):
                    fname = node.func.id if isinstance(node.func, ast.Name) else "<expr>"
                    out.append({"kind": "passed_to", "line": node.lineno, "name": fname})
        elif isinstance(node, ast.Return):
            if node.value is not None and any(
                isinstance(n, ast.Name) and n.id == var for n in ast.walk(node.value)
            ):
                out.append({"kind": "returned", "line": node.lineno, "name": var})
    out.sort(key=lambda d: (d["line"], d["kind"], d["name"]))
    return tuple(out[:cap])


def _family_for(var: str | None, taints) -> tuple[bool, str]:
    if var is None:
        return False, _FAMILY_AR["unknown"]
    in_input = var in taints.input_names
    in_request = var in taints.request_names
    if in_input and in_request:
        return True, _FAMILY_AR["both"]
    if in_input:
        return True, _FAMILY_AR["input"]
    if in_request:
        return True, _FAMILY_AR["request"]
    return False, _FAMILY_AR["clean"]


def _snippet(lines: list[str], line: int, window: int) -> tuple[str, ...]:
    """مقتطف مضبوط: نافذة حول السطر، السطر الملاحَظ بعلامة ``>``."""
    lo = max(1, line - window)
    hi = min(len(lines), line + window)
    out = []
    for n in range(lo, hi + 1):
        marker = ">" if n == line else " "
        out.append(f"{marker} {n:>4} | {lines[n - 1]}")
    return tuple(out)


def build_contexts(
    source: str,
    filename: str,
    result: ReviewResult,
    *,
    window: int = 3,
) -> tuple[StructuredContext, ...]:
    """سياق لكل ملاحظة بالترتيب نفسه — حتمي بالبايت، لا تحليل لا تدفق معروف."""
    try:
        tree = ast.parse(source)
        taints = collect_taints(tree)
        lines = source.splitlines()
    except (SyntaxError, ValueError):
        tree = None
        taints = None
        lines = source.splitlines()

    contexts: list[StructuredContext] = []
    for f in result.findings:
        stmt = _find_statement(tree, f.line) if tree is not None else None
        var = _involved_variable(stmt)
        if tree is not None and taints is not None:
            tainted, family = _family_for(var, taints)
            first_line = _first_assignment_line(tree, var) if var else None
            usages = _usages(tree, var) if var else ()
        else:
            tainted, family = False, _FAMILY_AR["unknown"]
            first_line = None
            usages = ()
        contexts.append(
            StructuredContext(
                filename=filename,
                rule_id=f.rule_id,
                severity=f.severity,
                category=f.category,
                line=f.line,
                message_ar=f.message_ar,
                suggestion_ar=f.suggestion_ar,
                snippet=_snippet(lines, f.line, window),
                variable=var,
                taint_family_ar=family,
                tainted=tainted,
                first_assignment_line=first_line,
                usages=usages,
            )
        )
    return tuple(contexts)
