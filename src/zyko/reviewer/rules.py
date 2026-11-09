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

موجة ميزان (v0.15.0): 11 قاعدة أمنية جديدة (R-SEC-109…119) منقولة بإعادة
بناء من محرك ميزان المُثبت ميدانيًا (حملة 50 مستودعًا حقيقيًا)، وقواعد
R-SEC-118/R-SEC-119/R-SEC-109 تعتمد على تحليل تدفق البيانات في taint.py.
كل قاعدة منها تحمل إصلاحات الإنذارات الكاذبة المُقاسة ميدانيًا في ميزان:
استثناء zipfile من tarfile-extractall، وعدم إطلاق request-without-timeout
على جلسات، وعدم كشف قيم العناصر النائبة في استعلامات IN الديناميكية.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Callable

from zyko.reviewer import taint as _taint

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


# عائلات إزالة التسلسل الخطرة (موجة ميزان): كلها تنفذ شيفرة عند التحميل،
# وshelve.open يزيل تسلسل القيم عبر pickle عند الوصول إليها.
_UNSAFE_DESERIALIZERS = frozenset({"pickle", "_pickle", "cPickle", "marshal", "dill"})


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
        if isinstance(n.func, ast.Attribute):
            root = _name_of(n.func.value)
            if n.func.attr in ("load", "loads") and root in _UNSAFE_DESERIALIZERS:
                out.append((n.lineno, n.col_offset, _name_of(n.func)))
            # موجة ميزان: shelve.open يزيل تسلسل القيم عبر pickle عند القراءة
            elif n.func.attr == "open" and root == "shelve":
                out.append((n.lineno, n.col_offset, "shelve.open"))
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


# ------------------------------------------ قواعد الأمن — موجة ميزان (R-SEC-109+)
def _collect_zipfile_vars(tree: ast.Module) -> set[str]:
    """أسماء مرتبطة بنسخ zipfile.* (استثناء قواعد B202): أهداف الإسناد
    وروابط with — قوس أمان مُقاس ميدانيًا في ميزان لأن اجتياز روابط
    symlinks الخاص بـ tar لا ينطبق على صيغة zip."""
    names: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.With, ast.AsyncWith)):
            for item in n.items:
                expr, optional = item.context_expr, item.optional_vars
                if (
                    isinstance(expr, ast.Call)
                    and isinstance(expr.func, ast.Attribute)
                    and _name_of(expr.func) == "zipfile.ZipFile"
                    and isinstance(optional, ast.Name)
                ):
                    names.add(optional.id)
        elif isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
            func = n.value.func
            if isinstance(func, ast.Attribute) and _name_of(func) == "zipfile.ZipFile":
                for target in n.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
    return names


def _path_traversal(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    """R-SEC-109 (path-traversal في ميزان): فتح ملف بمسار منسل من
    input()/sys.argv — تدفق بيانات مؤكد، لا تخمين بنيوي."""
    tainted = _taint.propagate(tree, _taint.is_input_source)
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "open"
            and n.args
            and _taint.expr_tainted(n.args[0], tainted, _taint.is_input_source)
        ):
            out.append((n.lineno, n.col_offset, _name_of(n.args[0])[:60] or None))
    return out


def _ssl_unverified_context(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    """R-SEC-110 (B323 في ميزان): ssl._create_unverified_context() يعطل
    التحقق من الشهادات للعملية كلها — مؤهلًا أو مستوردًا بالاسم."""
    direct = False
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "ssl":
            direct = direct or any(a.name == "_create_unverified_context" for a in n.names)
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        if isinstance(n.func, ast.Name) and n.func.id == "_create_unverified_context" and direct:
            out.append((n.lineno, n.col_offset, None))
        elif (
            isinstance(n.func, ast.Attribute)
            and n.func.attr == "_create_unverified_context"
            and _name_of(n.func.value) == "ssl"
        ):
            out.append((n.lineno, n.col_offset, None))
    return out


_HTTP_VERB_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "request"}
)


def _request_without_timeout(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    """R-SEC-111 (B113 في ميزان): نداءات requests.<فعل HTTP> بلا وسيط
    timeout. أضيق من Bandit عمدًا: مستقبلات الجلسات (session.get) خارج
    النطاق — انحراف موثق يبقي القاعدة بلا إنذارات كاذبة."""
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
            continue
        if n.func.attr not in _HTTP_VERB_METHODS:
            continue
        if _name_of(n.func.value) != "requests":
            continue
        if any(kw.arg == "timeout" for kw in n.keywords):
            continue
        out.append((n.lineno, n.col_offset, f"requests.{n.func.attr}"))
    return out


def _torch_unsafe_load(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    """R-SEC-112 (B614 في ميزان): torch.load يزيل التسلسل عبر pickle ما لم
    يُصرَّح بـ weights_only=True (تخفيف PyTorch)."""
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if not (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "load"
            and _name_of(n.func.value) == "torch"
        ):
            continue
        safe = any(
            kw.arg == "weights_only"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for kw in n.keywords
        )
        if not safe:
            out.append((n.lineno, n.col_offset, None))
    return out


def _hf_trust_remote_code(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    """R-SEC-113 (B615 في ميزان): أي نداء يفعّل trust_remote_code=True
    ينفذ شيفرة منسلة من مستودع نموذج بعيد."""
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        if any(
            kw.arg == "trust_remote_code"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for kw in n.keywords
        ):
            out.append((n.lineno, n.col_offset, _name_of(n.func)[:60] or None))
    return out


def _jinja2_autoescape_false(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    """R-SEC-114 (B701 في ميزان): autoescape=False يعطل تهريب HTML —
    باب هجمات XSS (القاعدة على شكل الوسيط أينما ظهر)."""
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        if any(
            kw.arg == "autoescape"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is False
            for kw in n.keywords
        ):
            out.append((n.lineno, n.col_offset, _name_of(n.func)[:60] or None))
    return out


def _django_mark_safe(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    """R-SEC-115 (B703 في ميزان): mark_safe يعلن المحتوى آمنًا لـ HTML
    دون تهريب — راجع مسار المدخل."""
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        if (isinstance(n.func, ast.Name) and n.func.id == "mark_safe") or (
            isinstance(n.func, ast.Attribute) and n.func.attr == "mark_safe"
        ):
            out.append((n.lineno, n.col_offset, _name_of(n.func)[:60]))
    return out


_TARFILE_SAFE_FILTERS = frozenset({"data", "tar"})


def _tarfile_extractall(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    """R-SEC-116 (B202 في ميزان): extractall بلا فلتر آمن (PEP 706) قد
    يكتب خارج المجلد الهدف (اجتياز مسارات). مستقبلات zipfile مستثناة —
    اجتياز روابط symlink الخاص بـ tar لا ينطبق على صيغة zip."""
    zipfile_vars = _collect_zipfile_vars(tree)
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if not (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "extractall"
        ):
            continue
        filter_safe = any(
            kw.arg == "filter"
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
            and kw.value.value in _TARFILE_SAFE_FILTERS
            for kw in n.keywords
        )
        receiver_root = _taint.root_name(n.func.value)
        direct_zip_call = (
            isinstance(n.func.value, ast.Call) and _taint.root_name(n.func.value.func) == "zipfile"
        )
        if (
            receiver_root not in ({"zipfile"} | zipfile_vars)
            and not direct_zip_call
            and not filter_safe
        ):
            out.append((n.lineno, n.col_offset, receiver_root or None))
    return out


def _check_tmp_value(node: ast.AST, value: ast.expr | str | None, out: list[Anchor]) -> None:
    """فحص قيمة واحدة: نص /tmp أو /var/tmp في موضع قيمة، بمستوى تداخل
    واحد داخل قوائم/صفوف/مجموعات (حدود المقاطع آمنة)."""
    if isinstance(value, ast.Constant):
        value = value.value
    if isinstance(value, str) and (
        value == "/tmp"  # nosec B108 — هذا الكاشف نفسه لقاعدة R-SEC-117
        or value.startswith("/tmp/")  # nosec B108 — كاشف لا كود إنتاجي
        or value == "/var/tmp"  # nosec B108 — كاشف لا كود إنتاجي
        or value.startswith("/var/tmp/")  # nosec B108 — كاشف لا كود إنتاجي
    ):
        out.append((node.lineno, node.col_offset, value[:40]))
    elif isinstance(value, (ast.Tuple, ast.List, ast.Set)):
        for elt in value.elts:
            if isinstance(elt, ast.Constant):
                _check_tmp_value(node, elt.value, out)


def _hardcoded_tmp_path(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    """R-SEC-117 (B108 في ميزان): مسارات /tmp و/var/tmp مصمتة في مواضع
    قيم الاستدعاءات والإسناد — نصوص التوثيق والتعبيرات العارية لا تُكشف
    (انحراف دقة موثق)."""
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            for arg in n.args:
                _check_tmp_value(n, arg, out)
            for kw in n.keywords:
                _check_tmp_value(n, kw.value, out)
        elif isinstance(n, ast.Assign):
            _check_tmp_value(n, n.value, out)
        elif isinstance(n, ast.AnnAssign) and n.value is not None:
            _check_tmp_value(n, n.value, out)
    return out


_PROCESS_SINK_METHODS = frozenset(
    {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}
)


def _input_to_subprocess(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    """R-SEC-118 (input-to-subprocess في ميزان): نص أمر منسل من input()
    أو sys.argv يصل مضخة عملية — تدفق مؤكد لا شكلي. يغطي subprocess.*
    المؤهل وأسماء os.system/os.popen المستوردة بالاسم."""
    bare_sinks: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module in ("os", "subprocess"):
            bare_sinks.update(a.name for a in n.names if a.name in ("system", "popen"))
    tainted = _taint.propagate(tree, _taint.is_input_source)
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        is_sink = False
        if isinstance(n.func, ast.Attribute):
            if n.func.attr in _PROCESS_SINK_METHODS and _name_of(n.func.value) == "subprocess":
                is_sink = True
            elif n.func.attr in ("system", "popen") and _name_of(n.func.value) == "os":
                is_sink = True
        elif (
            isinstance(n.func, ast.Name)
            and n.func.id in ("system", "popen")
            and n.func.id in bare_sinks
        ):
            is_sink = True
        if not is_sink:
            continue
        if any(_taint.expr_tainted(a, tainted, _taint.is_input_source) for a in n.args):
            out.append((n.lineno, n.col_offset, _name_of(n.func)[:60] or None))
    return out


def _sql104_covers(arg0: ast.expr) -> bool:
    """صحيح إذا كان شكل وسيط الاستعلام مغطى أصلًا بـ R-SEC-104 البنيوي
    (الدمج بـ % أو + أو f-string يحوي DML في جزئه الحرفي) — الهدف عدم
    إصدار ملاحظة مكررة على السطر نفسه، لا تفويت تغطية."""
    if isinstance(arg0, ast.JoinedStr):
        literal = "".join(p.value for p in arg0.values if isinstance(p, ast.Constant))
        return bool(_SQL_DML_RE.search(literal))
    if (
        isinstance(arg0, ast.BinOp)
        and isinstance(arg0.op, ast.Mod)
        and isinstance(arg0.left, ast.Constant)
    ):
        return bool(_SQL_DML_RE.search(str(arg0.left.value)))
    if (
        isinstance(arg0, ast.BinOp)
        and isinstance(arg0.op, ast.Add)
        and isinstance(arg0.left, ast.Constant)
        and not isinstance(arg0.right, ast.Constant)
    ):
        return bool(_SQL_DML_RE.search(str(arg0.left.value)))
    return False


def _request_to_sql(tree: ast.Module, cfg: RuleConfig) -> list[Anchor]:
    """R-SEC-119 (request-to-sql في ميزان): نص استعلام ملوث ببيانات
    request.* يصل execute()/executemany()/executescript() — تدفق مؤكد.
    لا يُطلق على الأشكال التي تغطيها R-SEC-104 أصلًا — لا ملاحظة مكررة
    على السطر نفسه."""
    tainted = _taint.propagate(tree, _taint.is_request_source)
    out: list[Anchor] = []
    for n in ast.walk(tree):
        if not (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("execute", "executemany", "executescript")
            and n.args
        ):
            continue
        arg0 = n.args[0]
        if _sql104_covers(arg0):
            continue
        if _taint.expr_tainted(arg0, tainted, _taint.is_request_source):
            out.append((n.lineno, n.col_offset, _name_of(n.func)[:60] or None))
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
    # ---- الأمن — موجة ميزان (v0.15.0): إعادة بناء لقواعد مُثبتة ميدانيًا
    _rule(
        "R-SEC-109",
        "medium",
        "security",
        "فتح ملف بمسار منسل من input() أو sys.argv يفتح باب اجتياز المسارات",
        "تحقق من المسار وطبّعه مقابل جذر مسموح قبل الفتح",
        _path_traversal,
    ),
    _rule(
        "R-SEC-110",
        "high",
        "security",
        "ssl._create_unverified_context يعطل التحقق من الشهادات للعملية كلها",
        "استخدم ssl.create_default_context وأضف CA موثوقًا للشهادات الداخلية",
        _ssl_unverified_context,
    ),
    _rule(
        "R-SEC-111",
        "low",
        "security",
        "طلب HTTP عبر requests بلا timeout قد يعلّق التطبيق إلى ما لا نهاية",
        "أضف timeout=(اتصال، قراءة) إلى كل نداءات الشبكة",
        _request_without_timeout,
    ),
    _rule(
        "R-SEC-112",
        "high",
        "security",
        "torch.load يزيل التسلسل عبر pickle وقد ينفذ شيفرة من نقطة تفتيش غير موثوقة",
        "أضف weights_only=True لتحميل الأوزان فقط",
        _torch_unsafe_load,
    ),
    _rule(
        "R-SEC-113",
        "high",
        "security",
        "trust_remote_code=True ينفذ شيفرة منسلة من مستودع نموذج بعيد",
        "أزل الخيار أو راجع شيفرة النموذج وثبّت نسخة مفحوصة محليًا",
        _hf_trust_remote_code,
    ),
    _rule(
        "R-SEC-114",
        "high",
        "security",
        "autoescape=False يعطل تهريب HTML ويفتح باب هجمات XSS",
        "أبقِ autoescape مفعّلًا أو استخدم select_autoescape",
        _jinja2_autoescape_false,
    ),
    _rule(
        "R-SEC-115",
        "medium",
        "security",
        "mark_safe يعلن المحتوى آمنًا لـ HTML دون تهريب وقد يمرر XSS",
        "راجع مسار المدخل وفضّل Escape أو القوالب ذات التهريب التلقائي",
        _django_mark_safe,
    ),
    _rule(
        "R-SEC-116",
        "high",
        "security",
        "extractall بلا فلتر آمن قد يكتب خارج المجلد الهدف عبر روابط symlink",
        "مرّر filter='data' (PEP 706) أو افحص الأعضاء قبل الاستخراج",
        _tarfile_extractall,
    ),
    _rule(
        "R-SEC-117",
        "low",
        "security",
        "مسار /tmp مصمت يدعو لسباقات symlink وأسماء ملفات قابلة للتخمين",
        "استخدم وحدة tempfile لإنشاء مسارات مؤقتة آمنة",
        _hardcoded_tmp_path,
    ),
    _rule(
        "R-SEC-118",
        "high",
        "security",
        "نص أمر منسل من input() أو sys.argv يصل مضخة عملية — حقن أوامر مؤكد بالتدفق",
        "فكّك الأمر إلى قائمة وسائط ثابتة ولا تمرر إدخال المستخدم خامًا",
        _input_to_subprocess,
    ),
    _rule(
        "R-SEC-119",
        "high",
        "security",
        "استعلام يصل execute() من بيانات request.* — حقن SQL مؤكد بتدفق البيانات",
        "استخدم استعلامات معاملات ومرر قيم الطلب كوسائط لا كنص استعلام",
        _request_to_sql,
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
