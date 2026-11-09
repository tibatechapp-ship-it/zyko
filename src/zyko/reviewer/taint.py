"""zyko.reviewer.taint — تحليل تدفق البيانات (تبسيط مقصود، موجة ميزان).

المنشأ: المحرك المُثبت ميدانيًا في مشروع MIZAN (موجة v0.14.0، حملة
فحص 50 مستودعًا حقيقيًا) — أُعيد بناؤه هنا بروح ZYKO: AST خالص، بلا
شبكة، بلا نموذج، بلا عشوائية، وحتمية بايتيًا.

النطاق المتعمد (ضيق ومُقاس قبل التوسيع):
  * AST بايثون فقط، ملف واحد، انتشار أسماء على مستوى الوحدة.
  * عائلتان مقاستان من المصادر:
      - مصادر الإدخال: ``input()`` و ``sys.argv`` (مع الفهرسة أو بدونها)
      - مصادر الطلبات: سلاسل ``request.<خاصية>`` حيث الخاصية من خصائص
        بيانات Flask/Django (args, form, values, json, data, GET, POST,
        files, headers, cookies) بما فيها النداءات عليها
        (``request.form.get(...)``).
  * انتشار حتى نقطة الثبات (fixpoint) عبر الإسناد والإسناد الموصوف
    والإسناد المركب وأهداف ``for`` وتعبئات الأغلفة (f-strings، الدمج،
    ``str()``، الفهرسة، الخصائص، تعبير if، العمليات المنطقية).

حدود الإثبات الأولي (موثقة ومقاسة قبل التوسيع):
  * لا عزل لحدود الدوال (اسم أُسند في دالة واستُخدم في أخرى يُعد
    موثبًا — هذه الشيفرة لم تكن لتعمل أصلًا، فكلفة الإنذار الكاذب
    العملية معدومة)؛
  * لا تدفق بين الإجراءات أو بين الوحدات؛
  * لا تسمية بديلة للخصائص وعناصر القواميس (الأسماء البسيطة فقط
    تنتشر التلويث).

هذه الوحدة يجب ألا تستورد analyzer أو rules (rules يستورد taint).
"""

from __future__ import annotations

import ast

# خصائص بيانات الطلب في Flask/Django — ما يتحكم فيه العميل.
REQUEST_DATA_ATTRS = frozenset(
    {
        "args",
        "form",
        "values",
        "json",
        "data",
        "GET",
        "POST",
        "files",
        "headers",
        "cookies",
    }
)

# حد أقصى لجولات الثبات: أعمق سلسلة إسناد واقعية أقل بكثير من هذا الرقم.
_MAX_FIXPOINT_PASSES = 20


def root_name(node: ast.expr | None) -> str | None:
    """الجذر المعرفي لسلسلة خصائص: ``request.form`` ⇒ ``request``."""
    while isinstance(node, ast.Attribute):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id
    return None


def is_sys_argv(node: ast.expr | None) -> bool:
    """صحيح لتعبير ``sys.argv`` (مفهرسًا أو غير مفهرس)."""
    if isinstance(node, ast.Subscript):
        node = node.value
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "argv"
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    )


def is_input_source(node: ast.expr | None) -> bool:
    """صحيح لنداءات ``input()`` وتعبيرات ``sys.argv`` الخام."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "input":
        return True
    return is_sys_argv(node)


def is_request_source(node: ast.expr | None) -> bool:
    """صحيح للتعبيرات المتجذرة في ``request`` الحاملة لخاصية بيانات.

    تطابق ``request.args`` و ``request.form.get("x")`` و
    ``request.headers["X"]`` وأي سلسلة أطول مبنية عليها.
    ``request`` وحده (مثل ``request.method``) ليس مصدر بيانات.
    """
    seen_attr = False
    while True:
        if isinstance(node, ast.Call):
            node = node.func
            continue
        if isinstance(node, ast.Subscript):
            node = node.value
            continue
        if isinstance(node, ast.Attribute):
            if node.attr in REQUEST_DATA_ATTRS:
                seen_attr = True
            node = node.value
            continue
        if isinstance(node, ast.Name):
            return seen_attr and node.id == "request"
        return False


class TaintSets:
    """نتيجة الانتشار: أي الأسماء البسيطة ملوثة بأي عائلة مصادر."""

    __slots__ = ("input_names", "request_names")

    def __init__(self, input_names, request_names):
        self.input_names = frozenset(input_names)
        self.request_names = frozenset(request_names)


def expr_tainted(node: ast.expr | None, tainted, source_pred) -> bool:
    """صحيح إذا أشار ``node`` (مباشرة أو عبر الأغلفة) إلى اسم ملوث
    أو طابق مصدر التلويث."""
    if node is None:
        return False
    if source_pred(node):
        return True
    if isinstance(node, ast.Name):
        return node.id in tainted
    if isinstance(node, ast.Call):
        return (
            expr_tainted(node.func, tainted, source_pred)
            or any(expr_tainted(a, tainted, source_pred) for a in node.args)
            or any(expr_tainted(kw.value, tainted, source_pred) for kw in node.keywords)
        )
    if isinstance(node, (ast.Attribute, ast.Subscript, ast.Starred)):
        return expr_tainted(node.value, tainted, source_pred)
    if isinstance(node, ast.JoinedStr):
        return any(
            expr_tainted(part.value, tainted, source_pred)
            for part in node.values
            if isinstance(part, ast.FormattedValue)
        )
    if isinstance(node, ast.BinOp):
        return expr_tainted(node.left, tainted, source_pred) or expr_tainted(
            node.right, tainted, source_pred
        )
    if isinstance(node, ast.BoolOp):
        return any(expr_tainted(v, tainted, source_pred) for v in node.values)
    if isinstance(node, ast.IfExp):
        return expr_tainted(node.body, tainted, source_pred) or expr_tainted(
            node.orelse, tainted, source_pred
        )
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return any(expr_tainted(e, tainted, source_pred) for e in node.elts)
    if isinstance(node, ast.Await):
        return expr_tainted(node.value, tainted, source_pred)
    return False


def _assign_targets(node: ast.AST) -> list[str]:
    """أهداف بسيطة (اسم أو مجموعة أسماء) لعقدة على شكل إسناد."""
    targets: list[str] = []
    if isinstance(node, ast.Assign):
        raw = node.targets
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        raw = [node.target]
    elif isinstance(node, ast.For):
        raw = [node.target]
    else:
        return targets
    for target in raw:
        if isinstance(target, ast.Name):
            targets.append(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                if isinstance(elt, ast.Name):
                    targets.append(elt.id)
    return targets


def _collect_assignments(tree: ast.Module):
    """أزواج (الأهداف، القيمة) لكل عقدة على شكل إسناد في الملف."""
    pairs: list[tuple[list[str], ast.expr]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            value = getattr(node, "value", None)
            if value is None:  # إسناد موصوف بلا قيمة
                continue
            pairs.append((_assign_targets(node), value))
        elif isinstance(node, ast.For):
            # ``for p in <متكرر>:`` — المتكرر في .iter وليس .value
            pairs.append((_assign_targets(node), node.iter))
        elif isinstance(node, ast.With):
            # روابط with تُترك خارج نطاق الإثبات الأولي (المصدر هو
            # وسيط النداء، وبوابات الكشف تراه مباشرة).
            continue
    return pairs


def propagate(tree: ast.Module, source_pred) -> frozenset[str]:
    """الثبات: الأسماء الملوثة انتقالياً بمصدر ``source_pred`` (نطاق الملف)."""
    pairs = _collect_assignments(tree)
    tainted: set[str] = set()
    for _ in range(_MAX_FIXPOINT_PASSES):
        grew = False
        for targets, value in pairs:
            if not targets:
                continue
            if expr_tainted(value, tainted, source_pred) and not set(targets) <= tainted:
                tainted.update(targets)
                grew = True
        if not grew:
            break
    return frozenset(tainted)


def collect_taints(tree: ast.Module) -> TaintSets:
    """تشغيل انتشاري المصادر معًا؛ يعيد :class:`TaintSets`."""
    return TaintSets(
        input_names=propagate(tree, is_input_source),
        request_names=propagate(tree, is_request_source),
    )
