"""zyko.reviewer.rules — سجل القواعد الحتمية لمراجعة الشيفرة (المرحلة 2، D22–40).

كل قاعدة دالة AST خالصة: نفس المدخل ⇒ نفس الملاحظات نفس الترتيب نفس النتيجة،
بلا شبكة وبلا نموذج وبلا عشوائية. لا تُخترع ملاحظات: كل ملاحظة مرتبطة بسطر
وعمود ومعرّف قاعدة قابل للتحقق يدويًا — هذا ما يميزنا عن مراجعي النماذج اللغوية
الذين «يرون» مشكلات غير موجودة في الشيفرة.

الفئات الثلاث:
  error_handling — معالجة الأخطاء (أولًا بأول كما يريد المشروع)
  security       — الأمن
  quality        — الجودة

الخطورة: critical > high > medium > low > info، ولكل منها وزن يُخصم من 100.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Callable

# --------------------------------------------------------------- التصنيفات
CATEGORIES: tuple[str, ...] = ("error_handling", "security", "quality")

CATEGORY_AR: dict[str, str] = {
    "error_handling": "معالجة الأخطاء",
    "security": "الأمن",
    "quality": "الجودة",
}

SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low", "info")

SEVERITY_AR: dict[str, str] = {
    "critical": "حرج",
    "high": "عالي",
    "medium": "متوسط",
    "low": "منخفض",
    "info": "معلومة",
}

# وزن الخصم من الدرجة 100 لكل ملاحظة (المعلومة لا تخصم).
SEVERITY_WEIGHT: dict[str, int] = {
    "critical": 15,
    "high": 8,
    "medium": 4,
    "low": 2,
    "info": 0,
}


# ------------------------------------------------------------------ الأنواع
@dataclass(frozen=True)
class Finding:
    """ملاحظة واحدة قابلة للتحقق: معرّف قاعدة + موقع دقيق + نص عربي."""

    rule_id: str
    severity: str
    category: str
    line: int
    col: int
    message_ar: str
    suggestion_ar: str
    detail_ar: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "severity_ar": SEVERITY_AR[self.severity],
            "category": self.category,
            "category_ar": CATEGORY_AR[self.category],
            "line": self.line,
            "col": self.col + 1,  # أعمدة البشر تبدأ من 1
            "message_ar": self.message_ar,
            "suggestion_ar": self.suggestion_ar,
        }
        if self.detail_ar:
            out["detail_ar"] = self.detail_ar
        return out


# مُرجَع القاعدة: (سطر، عمود، تفصيل اختياري) — يُفرز حتميًا قبل التغليف.
Anchor = tuple[int, int, str | None]
Checker = Callable[[ast.Module, "RuleConfig"], list[Anchor]]


@dataclass(frozen=True)
class Rule:
    """قاعدة واحدة: هوية + خطوة كشف AST ثابتة."""

    rule_id: str
    severity: str
    category: str
    message_ar: str
    suggestion_ar: str
    checker: Checker

    def run(self, tree: ast.Module, cfg: "RuleConfig") -> list[Finding]:
        anchors = sorted(self.checker(tree, cfg), key=lambda a: (a[0], a[1], a[2] or ""))
        return [
            Finding(
                rule_id=self.rule_id,
                severity=self.severity,
                category=self.category,
                line=line,
                col=col,
                message_ar=self.message_ar,
                suggestion_ar=self.suggestion_ar,
                detail_ar=detail,
            )
            for line, col, detail in anchors
        ]


@dataclass(frozen=True)
class RuleConfig:
    """عتبات القواعد القابلة للضبط (قيم افتراضية حتمية)."""

    max_func_lines: int = 50
    max_depth: int = 4
    max_args: int = 6


DEFAULT_CONFIG = RuleConfig()


# ------------------------------------------------------------ أدوات مشتركة
def _name_of(node: ast.expr | None) -> str:
    """اسم تعبيري مبسط للعقدة (Name/Attribute/Call) للعرض في التفصيل."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _name_of(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _name_of(node.func)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _iter_funcs(tree: ast.Module) -> Iterator[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """كل الدوال (المتزامنة وغير المتزامنة) مع اسمها المؤهل."""
    parents: dict[int, str] = {}

    def _walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{prefix}{child.name}"
                parents[id(child)] = qual
                _walk(child, f"{qual}.")
            elif isinstance(child, ast.ClassDef):
                _walk(child, f"{prefix}{child.name}.")

    _walk(tree, "")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield parents.get(id(node), node.name), node


def _is_trivial_body(body: list[ast.stmt]) -> bool:
    """جسم لا يفعل شيئًا: pass فقط، أو تعبير ثابت (نص/...)."""
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue
        return False
    return True


def _iter_except_actions(nodes: list[ast.stmt]) -> Iterator[ast.AST]:
    """يجول جسم except مع النزول في if/with لكن ليس في try أو دالة جديدة."""
    for stmt in nodes:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Try)):
            continue
        yield stmt
        yield from _iter_except_actions(list(ast.iter_child_nodes(stmt)))


_SQL_DML_RE = re.compile(
    r"(?is)\bselect\b[\s\S]{0,400}?\bfrom\b"
    r"|\binsert\s+into\b|\bupdate\s+\S+\s+set\b|\bdelete\s+from\b"
)

_SECRET_NAME_RE = re.compile(
    r"(?i)(password|passwd|pwd|secret|api_?key|apikey|access_?key|private_?key|auth_?token|token)"
)

_SHADOWABLE_BUILTINS = frozenset(
    {
        "list",
        "dict",
        "set",
        "tuple",
        "str",
        "int",
        "float",
        "bool",
        "bytes",
        "id",
        "type",
        "len",
        "max",
        "min",
        "sum",
        "map",
        "filter",
        "input",
        "print",
        "open",
        "format",
        "hash",
        "next",
        "iter",
        "vars",
        "dir",
    }
)

_DOCSTRING_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_BRANCH_TYPES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)


# --------------------------------------------- قواعد معالجة الأخطاء (R-ERR)
def _bare_except(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    return [
        (n.lineno, n.col_offset, None)
        for n in ast.walk(tree)
        if isinstance(n, ast.ExceptHandler) and n.type is None
    ]


def _swallowed_exception(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    return [
        (n.lineno, n.col_offset, None)
        for n in ast.walk(tree)
        if isinstance(n, ast.ExceptHandler) and _is_trivial_body(n.body)
    ]


def _raise_without_from(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.ExceptHandler):
            continue
        for sub in _iter_except_actions(n.body):
            if isinstance(sub, ast.Raise) and sub.exc is not None and sub.cause is None:
                out.append((sub.lineno, sub.col_offset, _name_of(sub.exc) or None))
    return out


def _open_outside_with(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []

    def _visit(node: ast.AST, in_with: int) -> None:
        for child in ast.iter_child_nodes(node):
            next_in_with = in_with
            if isinstance(child, (ast.With, ast.AsyncWith)):
                next_in_with = in_with + 1
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "open"
                and next_in_with == 0
            ):
                detail = None
                if child.args and isinstance(child.args[0], ast.Constant):
                    detail = str(child.args[0].value)
                out.append((child.lineno, child.col_offset, detail))
            _visit(child, next_in_with)

    _visit(tree, 0)
    return out


def _shell_true(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        for kw in n.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                out.append((n.lineno, n.col_offset, _name_of(n.func) or None))
    return out


def _mutable_default(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []
    for qual, func in _iter_funcs(tree):
        defaults = list(func.args.defaults) + [d for d in func.args.kw_defaults if d is not None]
        for d in defaults:
            risky = isinstance(d, (ast.List, ast.Dict, ast.Set)) or (
                isinstance(d, ast.Call) and _name_of(d.func) in ("list", "dict", "set")
            )
            if risky:
                out.append((d.lineno, d.col_offset, qual))
    return out


def _assert_validation(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    return [(n.lineno, n.col_offset, None) for n in ast.walk(tree) if isinstance(n, ast.Assert)]


def _return_in_finally(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Try):
            continue
        for stmt in n.finalbody:
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Return):
                    out.append((sub.lineno, sub.col_offset, None))
    return out


def _broad_except(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    return [
        (n.lineno, n.col_offset, None)
        for n in ast.walk(tree)
        if isinstance(n, ast.ExceptHandler)
        and isinstance(n.type, ast.Name)
        and n.type.id == "Exception"
    ]


def _base_except(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    return [
        (n.lineno, n.col_offset, None)
        for n in ast.walk(tree)
        if isinstance(n, ast.ExceptHandler)
        and isinstance(n.type, ast.Name)
        and n.type.id == "BaseException"
    ]


# ------------------------------------------------------- قواعد الأمن (R-SEC)
def _eval_exec(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id in ("eval", "exec")
        ):
            out.append((n.lineno, n.col_offset, n.func.id))
    return out


def _pickle_load(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    # استيراد مباشر: from pickle import loads
    direct: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module in ("pickle", "_pickle"):
            direct.update(a.name for a in n.names)
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        if isinstance(n.func, ast.Attribute) and n.func.attr in ("load", "loads"):
            if _name_of(n.func.value) in ("pickle", "_pickle"):
                out.append((n.lineno, n.col_offset, _name_of(n.func)))
        elif (
            isinstance(n.func, ast.Name) and n.func.id in ("load", "loads") and n.func.id in direct
        ):
            out.append((n.lineno, n.col_offset, n.func.id))
    return out


def _unsafe_yaml(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []
    safe_loaders = ("SafeLoader", "CSafeLoader")
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        if _name_of(n.func.value) != "yaml":
            continue
        if n.func.attr in ("full_load", "full_load_all", "unsafe_load"):
            out.append((n.lineno, n.col_offset, f"yaml.{n.func.attr}"))
        elif n.func.attr == "load":
            loader_ok = False
            for kw in n.keywords:
                if kw.arg == "Loader" and _name_of(kw.value).rsplit(".", 1)[-1] in safe_loaders:
                    loader_ok = True
            if len(n.args) >= 2 and _name_of(n.args[1]).rsplit(".", 1)[-1] in safe_loaders:
                loader_ok = True
            if not loader_ok:
                out.append((n.lineno, n.col_offset, "yaml.load بدون Loader آمن"))
    return out


def _sql_string_build(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []

    def _check_text(text: str, node: ast.AST, detail: str) -> None:
        if _SQL_DML_RE.search(text):
            out.append((node.lineno, node.col_offset, detail))

    for n in ast.walk(tree):
        if isinstance(n, ast.JoinedStr):
            literal = "".join(p.value for p in n.values if isinstance(p, ast.Constant))
            _check_text(literal, n, "f-string SQL")
        elif (
            isinstance(n, ast.BinOp)
            and isinstance(n.op, ast.Mod)
            and isinstance(n.left, ast.Constant)
        ):
            _check_text(str(n.left.value), n, "تنسيق % لاستعلام SQL")
        elif (
            isinstance(n, ast.BinOp)
            and isinstance(n.op, ast.Add)
            and isinstance(n.left, ast.Constant)
            and not isinstance(n.right, ast.Constant)
        ):
            _check_text(str(n.left.value), n, "دمج سلاسل لاستعلام SQL")
    return out


def _hardcoded_secret(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []

    def _check_target(name: str, value: ast.expr, node: ast.AST) -> None:
        if not _SECRET_NAME_RE.search(name):
            return
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            return
        secret = value.value
        if not (8 <= len(secret) <= 200):
            return
        if "$" in secret or "{" in secret:  # قوالب ومتغيرات بيئة ليست أسرارًا مصمتة
            return
        out.append((node.lineno, node.col_offset, name))

    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    _check_target(t.id, n.value, n)
                elif isinstance(t, ast.Attribute):
                    _check_target(t.attr, n.value, n)
        elif (
            isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.value is not None
        ):
            _check_target(n.target.id, n.value, n)
        elif isinstance(n, ast.Call):
            for kw in n.keywords:
                if kw.arg:
                    _check_target(kw.arg, kw.value, n)
    return out


def _weak_hash(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("md5", "sha1")
            and _name_of(n.func.value) == "hashlib"
        ):
            out.append((n.lineno, n.col_offset, f"hashlib.{n.func.attr}"))
    return out


def _tls_verify_off(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            for kw in n.keywords:
                if (
                    kw.arg == "verify"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is False
                ):
                    out.append((n.lineno, n.col_offset, _name_of(n.func) or None))
        elif isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Attribute):
            t = n.targets[0]
            if (
                t.attr in ("verify", "check_hostname")
                and isinstance(n.value, ast.Constant)
                and n.value.value is False
            ):
                out.append((n.lineno, n.col_offset, _name_of(t) or None))
    return out


def _os_exec(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    risky = ("system", "popen", "execv", "execve", "execvp", "spawnl", "spawnle", "spawnv")
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in risky
            and _name_of(n.func.value) == "os"
        ):
            out.append((n.lineno, n.col_offset, f"os.{n.func.attr}"))
    return out


# ----------------------------------------------------- قواعد الجودة (R-QLT)
def _long_function(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []
    for qual, func in _iter_funcs(tree):
        end = getattr(func, "end_lineno", None) or func.lineno
        lines = end - func.lineno + 1
        if lines > cfg.max_func_lines:
            out.append(
                (func.lineno, func.col_offset, f"{qual} ({lines} سطرًا > {cfg.max_func_lines})")
            )
    return out


def _deep_nesting(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []
    limit = cfg.max_depth + 1  # نُرسّي عند أول مستوى يتجاوز العتبة

    def _visit(node: ast.AST, depth: int) -> None:
        for child in ast.iter_child_nodes(node):
            new_depth = depth + 1 if isinstance(child, _BRANCH_TYPES) else depth
            if isinstance(child, _BRANCH_TYPES) and new_depth == limit:
                out.append((child.lineno, child.col_offset, f"عمق {new_depth}"))
            _visit(child, new_depth)

    _visit(tree, 0)
    return out


def _too_many_args(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []
    for qual, func in _iter_funcs(tree):
        a = func.args
        count = len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs)
        if a.vararg:
            count += 1
        if a.kwarg:
            count += 1
        if a.args and a.args[0].arg in ("self", "cls"):
            count -= 1
        if count > cfg.max_args:
            out.append((func.lineno, func.col_offset, f"{qual} ({count} معاملًا > {cfg.max_args})"))
    return out


def _missing_docstring(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if not isinstance(n, _DOCSTRING_TYPES):
            continue
        if n.name.startswith("_"):
            continue
        if n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
            continue
        out.append((n.lineno, n.col_offset, n.name))
    return out


def _no_type_hints(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []
    for qual, func in _iter_funcs(tree):
        if func.name.startswith("_"):
            continue
        params_clean = [
            a for a in func.args.args if a.arg not in ("self", "cls")
        ] or func.args.kwonlyargs
        no_param_hints = all(a.annotation is None for a in params_clean)
        if no_param_hints and func.returns is None:
            out.append((func.lineno, func.col_offset, qual))
    return out


def _none_compare(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Compare):
            continue
        if not any(isinstance(op, (ast.Eq, ast.NotEq)) for op in n.ops):
            continue
        operands = [n.left, *n.comparators]
        if any(isinstance(o, ast.Constant) and o.value is None for o in operands):
            out.append((n.lineno, n.col_offset, None))
    return out


def _string_identifiers(tree: ast.Module) -> set[str]:
    """المعرّفات الظاهرة داخل نصوص الملف (توثيق/مراجع نصية) — تُحسب استخدامًا."""
    names: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            names.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", n.value))
    return names


def _unused_import(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    used: set[str] = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= _string_identifiers(tree)
    exported: set[str] = set()
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in n.targets
        ):
            if isinstance(n.value, (ast.List, ast.Tuple, ast.Set)):
                exported = {
                    e.value
                    for e in n.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                }
    out: list[Anchor] = []
    for stmt in tree.body:
        pairs: list[tuple[ast.alias, int, int]] = []
        if isinstance(stmt, ast.Import):
            pairs = [(a, stmt.lineno, stmt.col_offset) for a in stmt.names]
        elif isinstance(stmt, ast.ImportFrom) and stmt.module != "__future__":
            pairs = [(a, stmt.lineno, stmt.col_offset) for a in stmt.names]
        for alias, lineno, col in pairs:
            if alias.name == "*":
                continue
            bound = alias.asname or alias.name.split(".")[0]
            if bound in ("_", "annotations") or bound in exported:
                continue
            if bound not in used:
                out.append((lineno, col, bound))
    return out


def _builtin_shadow(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id in _SHADOWABLE_BUILTINS:
                    out.append((n.lineno, n.col_offset, t.id))
    for _, func in _iter_funcs(tree):
        all_args = [*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs]
        for a in all_args:
            if a.arg in _SHADOWABLE_BUILTINS:
                out.append((func.lineno, func.col_offset, f"{a.arg} (معامل)"))
    return out


def _lambda_assign(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Lambda):
            names = [t.id for t in n.targets if isinstance(t, ast.Name)]
            out.append((n.lineno, n.col_offset, names[0] if names else None))
        elif (
            isinstance(n, ast.AnnAssign)
            and isinstance(n.value, ast.Lambda)
            and isinstance(n.target, ast.Name)
        ):
            out.append((n.lineno, n.col_offset, n.target.id))
    return out


# ------------------------------------------------------------------ السجل
def _rule(
    rule_id: str,
    severity: str,
    category: str,
    message_ar: str,
    suggestion_ar: str,
    fn: Checker,
) -> Rule:
    return Rule(rule_id, severity, category, message_ar, suggestion_ar, fn)


RULES: tuple[Rule, ...] = (
    # ---- معالجة الأخطاء: الفئة الرائدة في هذه المرحلة
    _rule(
        "R-ERR-001",
        "high",
        "error_handling",
        "except عارٍ بلا نوع يلتقط كل شيء حتى SystemExit وKeyboardInterrupt",
        "حدّد نوع الاستثناء المتوقع مثل except ValueError",
        _bare_except,
    ),
    _rule(
        "R-ERR-002",
        "high",
        "error_handling",
        "الاستثناء يُبتلع بصمت (جسم except لا يفعل شيئًا)",
        "سجّل الخطأ أو أعِد رفعه أو تعامل معه صراحة — لا تمرّ صامتًا",
        _swallowed_exception,
    ),
    _rule(
        "R-ERR-003",
        "medium",
        "error_handling",
        "رفع استثناء جديد داخل except بدون from يفقد أثر الخطأ الأصلي",
        "أضف from exc للحفاظ على سلسلة الأسباب",
        _raise_without_from,
    ),
    _rule(
        "R-ERR-004",
        "medium",
        "error_handling",
        "فتح ملف بـ open خارج with يتركه مفتوحًا عند وقوع خطأ",
        "استخدم with open(...) as f لضمان الإغلاق",
        _open_outside_with,
    ),
    _rule(
        "R-ERR-005",
        "critical",
        "error_handling",
        "shell=True في استدعاء عملية يفتح بابًا لحقن الأوامر",
        "مرّر الأمر ووسائطه كقائمة واحدة بدون shell",
        _shell_true,
    ),
    _rule(
        "R-ERR-006",
        "high",
        "error_handling",
        "وسيط افتراضي قابل للتغيير (قائمة/قاموس/مجموعة) يُشارك بين الاستدعاءات",
        "استخدم None افتراضيًا ثم أنشئ الحاوية داخل الدالة",
        _mutable_default,
    ),
    _rule(
        "R-ERR-007",
        "low",
        "error_handling",
        "assert للتحقق من المدخلات يختفي عند التشغيل بخيار -O",
        "ارفع استثناء صريحًا مثل ValueError للتحقق من المدخلات",
        _assert_validation,
    ),
    _rule(
        "R-ERR-008",
        "high",
        "error_handling",
        "return داخل finally يبتلع الاستثناءات الجارية ويخفي الأعطال",
        "أخرج القيمة قبل finally واترك finally للتنظيف فقط",
        _return_in_finally,
    ),
    _rule(
        "R-ERR-009",
        "medium",
        "error_handling",
        "except Exception واسع جدًا ويخفي أعطالًا غير متوقعة",
        "التقط أنواعًا محددة، وإن أردت العام فسجّل ثم أعِد الرفع",
        _broad_except,
    ),
    _rule(
        "R-ERR-010",
        "high",
        "error_handling",
        "except BaseException يلتقط حتى SystemExit وKeyboardInterrupt",
        "التقط Exception أو استثناءات محددة فقط",
        _base_except,
    ),
    # ---- الأمن
    _rule(
        "R-SEC-101",
        "critical",
        "security",
        "eval/exec ينفّذ شيفرة عشوائية من مدخلات غير موثوقة",
        "أعد التصميم بجدول توجيه أو ast.literal_eval للبيانات فقط",
        _eval_exec,
    ),
    _rule(
        "R-SEC-102",
        "high",
        "security",
        "إزالة تسلسل pickle من بيانات غير موثوقة تنفّذ شيفرة",
        "استخدم JSON أو تنسيقًا بلا تنفيذ شيفرة للمدخلات الخارجية",
        _pickle_load,
    ),
    _rule(
        "R-SEC-103",
        "high",
        "security",
        "yaml.load بدون Loader آمن يسمح بتنفيذ كائنات بايثون",
        "استخدم yaml.safe_load أو Loader=yaml.SafeLoader",
        _unsafe_yaml,
    ),
    _rule(
        "R-SEC-104",
        "high",
        "security",
        "بناء استعلام SQL بدمج نصوص يفتح بابًا لحقن SQL",
        "استخدم استعلامات معاملات (placeholders) عبر مكتبة قاعدة البيانات",
        _sql_string_build,
    ),
    _rule(
        "R-SEC-105",
        "high",
        "security",
        "سر مصمت في الشيفرة (كلمة سر أو مفتاح) يُكشف مع المستودع كله",
        "اقرأ الأسرار من متغيرات البيئة أو مدير أسرار خارجي",
        _hardcoded_secret,
    ),
    _rule(
        "R-SEC-106",
        "medium",
        "security",
        "خوارزمية هاش ضعيفة (md5/sha1) غير آمنة للتوقيع وكلمات السر",
        "استخدم sha256 أو أعلى، وللأسرار استخدم argon2 أو bcrypt",
        _weak_hash,
    ),
    _rule(
        "R-SEC-107",
        "high",
        "security",
        "تعطيل التحقق من شهادة TLS يفتح باب هجمات الوسيط",
        "أبقِ التحقق مفعّلًا، وللشهادات الداخلية أضف CA موثوقًا",
        _tls_verify_off,
    ),
    _rule(
        "R-SEC-108",
        "critical",
        "security",
        "استدعاء os.system أو os.popen ينفّذ أوامر النظام مباشرة",
        "استخدم subprocess.run بقائمة وسيطات وبدون shell",
        _os_exec,
    ),
    # ---- الجودة
    _rule(
        "R-QLT-201",
        "medium",
        "quality",
        "دالة أطول من الحد المسموح يصعب اختبارها ومراجعتها",
        "قسّمها إلى دوال أصغر بمسؤولية واحدة لكل منها",
        _long_function,
    ),
    _rule(
        "R-QLT-202",
        "medium",
        "quality",
        "تداخل فروع أعمق من الحد يجعل القراءة والتتبع صعبين",
        "اطوِ الفروع بعودة مبكرة أو استخرج دوال مساعدة",
        _deep_nesting,
    ),
    _rule(
        "R-QLT-203",
        "medium",
        "quality",
        "دالة بمعاملات أكثر من الحد يصعب استدعاؤها صحيحة",
        "اجمع المعاملات المتقاربة في dataclass أو استخدم وسائط مفتاحية",
        _too_many_args,
    ),
    _rule(
        "R-QLT-204",
        "low",
        "quality",
        "رمز عام بلا docstring يخفي نيّته عن القارئ والمراجع",
        "أضف docstring عربيًا يشرح الغرض والوسائط والقيمة المرجعة",
        _missing_docstring,
    ),
    _rule(
        "R-QLT-205",
        "info",
        "quality",
        "دالة عامة بلا توصيف أنواع تفقد فحص mypy وحافة التوضيح",
        "أضف توصيفات الأنواع للوسائط والقيمة المرجعة",
        _no_type_hints,
    ),
    _rule(
        "R-QLT-206",
        "low",
        "quality",
        "مقارنة None بـ == بدل is تربك القراءة وقد تفشل مع __eq__ مخصص",
        "استخدم is None أو is not None",
        _none_compare,
    ),
    _rule(
        "R-QLT-207",
        "low",
        "quality",
        "استيراد غير مستخدم يشوّش الملف ويخفي الاعتماديات الحقيقية",
        "احذف الاستيراد أو استخدمه — لا تُبقه ميتًا",
        _unused_import,
    ),
    _rule(
        "R-QLT-208",
        "low",
        "quality",
        "تظليل اسم مدمج (list/dict/id/…) يقطع استخدام الأصل لاحقًا",
        "اختر اسمًا آخر لا يتعارض مع أسماء بايثون المدمجة",
        _builtin_shadow,
    ),
    _rule(
        "R-QLT-209",
        "low",
        "quality",
        "إسناد lambda إلى اسم يخالف توصية PEP 8 ويفقد أثر التتبع",
        "عرّف دالة بـ def تحمل اسمًا وdocstring",
        _lambda_assign,
    ),
)

RULES_BY_ID: dict[str, Rule] = {r.rule_id: r for r in RULES}

__all__ = [
    "CATEGORIES",
    "CATEGORY_AR",
    "DEFAULT_CONFIG",
    "Finding",
    "RULES",
    "RULES_BY_ID",
    "Rule",
    "RuleConfig",
    "SEVERITIES",
    "SEVERITY_AR",
    "SEVERITY_WEIGHT",
]
