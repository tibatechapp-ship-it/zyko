"""zyko.tools.synth.spec — قراءة عقد المهمة: دالة هيكلية بعقود معلنة.

المُقترِح الحتمي لا يخمّن المطلوب: المهمة ملف بايثون واحد فيه **دالة
هيكلية واحدة** (جسمها ``raise NotImplementedError`` أو ``...`` أو
``pass``) وتوجيهات الحاكم نفسها التي حاكمها v0.38.0 سكونيًا:

    # zyko:task: ضاعف المدخل
    # zyko:requires: x >= 0
    # zyko:ensures: result * 2 == x
    # zyko:domain: x = range(0, 8)
    def double(x):
        raise NotImplementedError

القراءة صادقة ثلاثية الحكم مثل الحاكم تمامًا:

* **سليمة** — توقيع واحد، دالة هيكلية واحدة، عقود قابلة للتحليل،
  وكل معامل تلمسه العقود له مجال معلن (قابل للتنفيذ التحققي).
* **مرفوضة** — لا توقيع، أكثر من دالة بعقود، توجيه مشوّه، أو معامل
  محجوز (``result``) زُيّف معاملاً.
* **غير قابلة للتحقق** — معامل تلمسه العقود بلا مجال معلن: البحث
  التنفيذي يستحيل بصدق، وهذا ليس فشلاً بل حكم.

المجالات: ``name = range(a, b)`` أو ``name = [قيم حرفية]`` — نفس شكل
الحاكم، والتحليل المعاد استخدامه من ``zyko.tools.formal.engine``
(محرّك توجيه واحد في المستودع كله).
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass

from zyko.tools.formal.engine import (
    ALLOWED_BUILTINS,
    RESULT_NAME,
    VerdictKind,
    function_directives,
    parse_domain_shape,
)

# سقف نقاط المجال الواحد — نفس سقف العدّة الأخلاقي: تنفيذ محدود معلن.
MAX_DOMAIN_POINTS = 64


class SpecError(ValueError):
    """عقد مهمة مرفوض — الرسالة عربية صريحة تُقرأ لا تُخمَّن."""


@dataclass(frozen=True)
class TaskSpec:
    """مواصفة مهمة مُقرأة — مدخلات البحث كاملة وحتمية بالبايت."""

    name: str
    params: tuple[str, ...]
    task_ar: str
    requires: tuple[str, ...]
    ensures: tuple[str, ...]
    domains: dict[str, tuple[object, ...]]
    directives_preserved: tuple[str, ...]
    source: str

    @property
    def sha256(self) -> str:
        """بصمة المصدر الخام — الهوية داخل الإيصال."""
        return hashlib.sha256(self.source.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SpecVerdict:
    """حكم القراءة الثلاثي — مثل الحاكم: قبول/رفض/تعذّر التحقق."""

    kind: VerdictKind
    reason_ar: str
    spec: TaskSpec | None = None


def _is_stub_body(fn: ast.FunctionDef) -> bool:
    """جسم الهيكل: docstring ثم علامة واحدة من علامات المهمة غير المنجَزة."""
    body = list(fn.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if len(body) != 1:
        return False
    node = body[0]
    if isinstance(node, ast.Pass):
        return True
    if (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and node.value.value is Ellipsis
    ):
        return True
    if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
        return isinstance(node.exc.func, ast.Name) and node.exc.func.id == "NotImplementedError"
    if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Name):
        return node.exc.id == "NotImplementedError"
    return False


def _expand_domain(shape: object) -> tuple[object, ...]:
    """افرد شكل المجال إلى نقاط تنفيذ محدودة — عيّنة خطوة ثابتة عند التجاوز."""
    if isinstance(shape, tuple) and len(shape) == 3 and shape[0] == "range":
        _, lo, hi = shape
        width = hi - lo
        if width <= 0:
            return ()
        if width <= MAX_DOMAIN_POINTS:
            return tuple(range(lo, hi))
        stride = (width + MAX_DOMAIN_POINTS - 1) // MAX_DOMAIN_POINTS
        return tuple(range(lo, hi, stride))
    if isinstance(shape, list):
        return tuple(shape[:MAX_DOMAIN_POINTS])
    return ()


def parse_task(source: str) -> SpecVerdict:
    """اقرأ عقد المهمة من مصدر واحد — حكم واحد، أسباب عربية كاملة."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return SpecVerdict(VerdictKind.REJECT, f"المصدر لا يُجمَّع أصلاً: {exc.msg}")

    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    stubs = [fn for fn in functions if _is_stub_body(fn)]
    if not stubs:
        return SpecVerdict(
            VerdictKind.REJECT,
            "لا دالة هيكلية — المهمة دالة واحدة جسمها raise NotImplementedError أو ... أو pass",
        )
    if len(stubs) > 1:
        names = ", ".join(sorted(fn.name for fn in stubs))
        return SpecVerdict(
            VerdictKind.REJECT,
            f"أكثر من دالة هيكلية ({names}) — مهمة واحدة في الملف",
        )

    fn = stubs[0]
    params = tuple(a.arg for a in fn.args.args + fn.args.kwonlyargs)
    if RESULT_NAME in params:
        return SpecVerdict(
            VerdictKind.REJECT,
            "result اسم محجوز للناتج — لا يجوز أن يكون معاملاً (عقد الحاكم نفسه)",
        )
    if fn.args.vararg or fn.args.kwarg:
        return SpecVerdict(
            VerdictKind.REJECT,
            "معاملات متغيرة (*args/**kwargs) خارج صنف المُقترِح — المجالات تنفرد لمعاملات مسماة فقط",
        )

    directives = function_directives(source, fn)
    task_ar = ""
    requires: list[str] = []
    ensures: list[str] = []
    domain_shapes: dict[str, object] = {}
    domain_order: list[str] = []
    preserved: list[str] = []

    for kind, content, lineno in directives:
        preserved.append(f"# zyko:{kind}: {content}")
        if kind == "task":
            task_ar = content
        elif kind == "requires":
            requires.append(content)
        elif kind == "ensures":
            ensures.append(content)
        else:
            parsed = parse_domain_shape(content)
            if parsed is None:
                return SpecVerdict(
                    VerdictKind.REJECT,
                    f"سطر {lineno}: شكل المجال غير مسموح — "
                    "name = range(a, b) أو name = [قيم حرفية] فقط",
                )
            dname, shape = parsed
            if dname not in params:
                return SpecVerdict(
                    VerdictKind.REJECT,
                    f"سطر {lineno}: المجال يعرّف {dname!r} وليست معاملاً في {fn.name!r}",
                )
            if dname in domain_shapes:
                return SpecVerdict(
                    VerdictKind.REJECT,
                    f"سطر {lineno}: مجال مكرر لـ{dname!r}",
                )
            domain_shapes[dname] = shape
            domain_order.append(dname)

    if not ensures:
        return SpecVerdict(
            VerdictKind.UNKNOWN,
            "عقد بلا شرط لاحق — لا شيء يُثبت، البحث بلا هدف؛ أعلن zyko:ensures أولاً",
        )

    # أي معامل تلمسه العقود بلا مجال ⇒ غير قابل للتحقق (نفس منطق الحاكم)
    touched: set[str] = set()
    for expr in requires + ensures:
        try:
            expr_tree = ast.parse(expr, mode="eval")
        except SyntaxError:
            return SpecVerdict(VerdictKind.REJECT, f"عقد غير قابل للتجميع: {expr!r}")
        for node in ast.walk(expr_tree):
            if isinstance(node, ast.Name):
                touched.add(node.id)
    touched.discard(RESULT_NAME)
    # أسماء خارج المعاملات والمسموح القياسي = رفض (عقد الحاكم نفسه)
    outside = sorted(t for t in touched if t not in params and t not in ALLOWED_BUILTINS)
    if outside:
        return SpecVerdict(
            VerdictKind.REJECT,
            "عقد يلمس أسماء خارج المعاملات: "
            + ", ".join(outside)
            + " — عقود الدالة محصورة بمعاملاتها والمسموح القياسي",
        )
    missing = sorted(p for p in touched if p in params and p not in domain_shapes)
    if missing:
        return SpecVerdict(
            VerdictKind.UNKNOWN,
            "عقود تلمس معاملات بلا مجال معلن ("
            + ", ".join(missing)
            + ") — البحث التنفيذي يستحيل بصدق؛ أعلن zyko:domain لكل معامل ملموس",
        )

    domains: dict[str, tuple[object, ...]] = {}
    for dname in domain_order:
        points = _expand_domain(domain_shapes[dname])
        if not points:
            return SpecVerdict(
                VerdictKind.REJECT,
                f"مجال {dname!r} فارغ بعد الفرد — لا نقاط تحقق",
            )
        domains[dname] = points

    spec = TaskSpec(
        name=fn.name,
        params=params,
        task_ar=task_ar,
        requires=tuple(requires),
        ensures=tuple(ensures),
        domains=domains,
        directives_preserved=tuple(preserved),
        source=source,
    )
    return SpecVerdict(VerdictKind.ACCEPT, "عقد مهمة سليم وقابل للتحقق التنفيذي", spec)


__all__ = [
    "MAX_DOMAIN_POINTS",
    "SpecError",
    "SpecVerdict",
    "TaskSpec",
    "parse_task",
]
