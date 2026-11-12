"""zyko.tools.synth.grammar — النحو المغلق: فضاء المرشحين حتمي بالبايت.

المُقترِح لا يولّد نصًا حرًا ولا يستدعي نموذجًا: المرشحون **أشجار
تعبير مبنية برمجيًا** من نحو مغلق التصريح، تُعدَّد بترتيب ثابت
(الصغرى أولاً، وداخل كل حجمٍ ترتيب الكتل المعلن، وكل كتلة تسهم
بحد أقصى مُعلن). نفس المهمة ⇒ نفس سلسلة المرشحين بالبايت — وهذا
عقد الحتمية P6 في كل المستودع.

**صنف التركيب الصادق** (مُعلن لا مُفترَض):

* أوراق: المعاملات بترتيب التوقيع، ثم ثوابت مُحصودة من العقود نفسها
  (أعداد ظهرت في requires/ensures/domain) مع ``0`` و``1`` دائمًا —
  الثوابت من المهمة لا من الهواء، وهذا يُضيّق الفضاء بصدق.
* كتل كل حجم (بالترتيب): ``min``/``max`` ثنائيا الوسيط، ثم المقارنات
  الست (المسندات أوّلاً — أكثر العقود شائعاً)، ثم الحسابي السبع، ثم
  ``and``/``or``، ثم السلب ``-e``، ثم
  استدعاءات المسموح أحادية الوسيط (``abs`` و``round`` و``int`` و
  ``float`` و``bool`` و``len`` و``sum`` و``sorted`` و``str``)، ثم
  الثلاثي ``a if c else b`` (الشرط مقارنة محضة — ينشط عند
  ``max_nodes >= 6`` حصراً).
* أزواج الأحجام داخل كل كتلة: ``(i, n-1-i)`` ثم ``(n-1-i, i)`` عند
  الاختلاف، و``(k, k)`` عند الزوجية — بترتيب معلن.

كل مرشح يمر على **فحص بنيوي مُغلق** قبل التجميع: أصناف AST المسموحة
معلنة كثابت مجموعة، وأي عقدة خارجها تُرفض قبل التشغيل — المرشح
الذاتي الإنتاج يُفحص كما لو كان أجنبيًا (دفاع في العمق).
"""

from __future__ import annotations

import ast
import itertools
from collections.abc import Iterator

CALLS_UNARY: tuple[str, ...] = (
    "abs", "round", "int", "float", "bool", "len", "sum", "sorted", "str",
)
CALLS_BINARY: tuple[str, ...] = ("min", "max")
ARITH_OPS: tuple[str, ...] = ("+", "-", "*", "//", "%", "**", "/")
CMP_OPS: tuple[str, ...] = ("<", "<=", ">", ">=", "==", "!=")
BASE_CONSTANTS: tuple[int, ...] = (0, 1)
MAX_EXPONENT = 32  # حرس التوليد: أس ثابت فوق هذا لا يُولَّد أصلاً
DEFAULT_MAX_NODES = 5
DEFAULT_BUDGET = 200_000
DEFAULT_BLOCK_BEAM = 1_500  # سقف إسهام الكتلة الواحدة — شعاع مُعلن

_ARITH_CLASSES: dict[str, type[ast.operator]] = {
    "+": ast.Add, "-": ast.Sub, "*": ast.Mult, "//": ast.FloorDiv,
    "%": ast.Mod, "**": ast.Pow, "/": ast.Div,
}
_CMP_CLASSES: dict[str, type[ast.cmpop]] = {
    "<": ast.Lt, "<=": ast.LtE, ">": ast.Gt, ">=": ast.GtE,
    "==": ast.Eq, "!=": ast.NotEq,
}

_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression, ast.Constant, ast.Name, ast.UnaryOp, ast.USub, ast.UAdd,
    ast.Not, ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod,
    ast.Pow, ast.Div, ast.Compare, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Eq, ast.NotEq, ast.BoolOp, ast.And, ast.Or, ast.IfExp, ast.Call,
    ast.Load, ast.List, ast.Tuple,
)


class StructuralViolation(ValueError):
    """مرشح خارج النحو المغلق — يُرفض بنيوياً قبل التجميع."""


def harvest_constants(
    requires: tuple[str, ...],
    ensures: tuple[str, ...],
    domains: dict[str, tuple[object, ...]],
) -> tuple[int | float, ...]:
    """ثوابت المهمة من عقودها — أعداد حرفية ظاهرة فقط، مفرزة بلا تكرار.

    ثوابت نص العقود بلا سقف عددي (أرقام المهمة نفسها)، وثوابت المجال
    مسقوفة: |v| ≤ 20 وبحد أقصى 12 قيمة — فضاء أوراق محدود معلن لا
    انفجار فيه.
    """
    found: set[int | float] = set(BASE_CONSTANTS)
    for expr in requires + ensures:
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(
                node.value, (int, float)
            ) and not isinstance(node.value, bool):
                found.add(node.value)
    domain_consts: set[int | float] = set()
    for points in domains.values():
        for v in points:
            if isinstance(v, (int, float)) and not isinstance(v, bool) \
                    and abs(v) <= 20:
                domain_consts.add(v)
    for v in sorted(domain_consts, key=lambda v: (isinstance(v, float), v))[:12]:
        found.add(v)
    return tuple(sorted(found, key=lambda v: (isinstance(v, float), v)))


def _size_pairs(size: int) -> tuple[tuple[int, int], ...]:
    """أزواج أحجام الأوبراند لحجم معين — ``(i, n-1-i)`` بلا تكرار مُضِع."""
    pairs: list[tuple[int, int]] = []
    for i in range(1, (size - 1) // 2 + 1):
        j = size - 1 - i
        pairs.append((i, j))
        if i < j:
            pairs.append((j, i))
    return tuple(pairs)


class CandidateSpace:
    """فضاء المرشحين المُعدَّد — مُنشئ ثابت الترتيب، مغلق النحو.

    الأحجام أدنى السقف تُخزَّن مُجسّدة (إعادة استخدام بلا توليد من
    جديد)، والحجم الأعلى يُبثّ دون تجسيد كامل — والكتل مسقوفة
    بالشعاع المعلن حتى لا تبتلع كتلة واحدة الميزانية.
    """

    def __init__(
        self,
        params: tuple[str, ...],
        constants: tuple[int | float, ...],
        *,
        max_nodes: int = DEFAULT_MAX_NODES,
        budget: int = DEFAULT_BUDGET,
        block_beam: int = DEFAULT_BLOCK_BEAM,
    ) -> None:
        if max_nodes < 1 or max_nodes > 8:
            raise ValueError("max_nodes بين 1 و8 — فضاء مُعلن لا سقف لا نهائي")
        self.params = params
        self.constants = constants
        self.max_nodes = max_nodes
        self.budget = budget
        self.block_beam = block_beam
        self.leaves: tuple[ast.expr, ...] = tuple(
            [ast.Name(id=p, ctx=ast.Load()) for p in params]
            + [ast.Constant(value=c) for c in constants]
        )
        self._cache: dict[int, list[ast.expr]] = {}
        self._emitted = 0
        self._budget_hit = False

    # --- البناء بالحجم -----------------------------------------------

    def _by_size(self, size: int) -> list[ast.expr]:
        """قائمة حجم مخزّنة — الأحجام أدنى السقف فقط تُجسَّد كاملة."""
        cached = self._cache.get(size)
        if cached is not None:
            return cached
        out: list[ast.expr] = []
        seen: set[str] = set()
        for expr in self._stream_size(size):
            key = ast.dump(expr)
            if key in seen:
                continue
            seen.add(key)
            out.append(expr)
        self._cache[size] = out
        return out

    def _stream_size(self, size: int) -> Iterator[ast.expr]:
        """مرشحو الحجم ``size`` بالترتيب المعلن — كتلة كتلة."""
        leaves = self.leaves
        if size == 1:
            yield from leaves
            return
        pairs = _size_pairs(size)
        # 1) min/max ثنائيا الوسيط
        for name in CALLS_BINARY:
            for i, j in pairs:
                count = 0
                for l, r in itertools.product(self._sub(i), self._sub(j)):
                    yield ast.Call(
                        func=ast.Name(id=name, ctx=ast.Load()),
                        args=[l, r], keywords=[],
                    )
                    count += 1
                    if count >= self.block_beam:
                        break
        # 2) المقارنات الست — المسندات أوّلاً: أكثر العقود شائعاً
        for sym in CMP_OPS:
            op_cls = _CMP_CLASSES[sym]
            for i, j in pairs:
                count = 0
                for l, r in itertools.product(self._sub(i), self._sub(j)):
                    yield ast.Compare(left=l, ops=[op_cls()], comparators=[r])
                    count += 1
                    if count >= self.block_beam:
                        break
        # 3) الحسابي السبع
        for sym in ARITH_OPS:
            op_cls = _ARITH_CLASSES[sym]
            for i, j in pairs:
                count = 0
                for l, r in itertools.product(self._sub(i), self._sub(j)):
                    yield ast.BinOp(left=l, op=op_cls(), right=r)
                    count += 1
                    if count >= self.block_beam:
                        break
        # 4) المنطقي الثنائي
        for sym, op_cls in (("and", ast.And), ("or", ast.Or)):
            for i, j in pairs:
                count = 0
                for l, r in itertools.product(self._sub(i), self._sub(j)):
                    yield ast.BoolOp(op=op_cls(), values=[l, r])
                    count += 1
                    if count >= self.block_beam:
                        break
        # 5) السلب
        if size >= 2:
            count = 0
            for e in self._sub(size - 1):
                yield ast.UnaryOp(op=ast.USub(), operand=e)
                count += 1
                if count >= self.block_beam:
                    break
        # 6) الاستدعاءات أحادية الوسيط
        for name in CALLS_UNARY:
            count = 0
            for e in self._sub(size - 1):
                yield ast.Call(
                    func=ast.Name(id=name, ctx=ast.Load()),
                    args=[e], keywords=[],
                )
                count += 1
                if count >= self.block_beam:
                    break
        # 7) الثلاثي — الشرط مقارنة محضة (ينشط عند max_nodes >= 6)
        for val_size in range(1, size - 2):
            cond_size = size - 1 - val_size
            if cond_size < 3:
                continue
            for sym in CMP_OPS:
                op_cls = _CMP_CLASSES[sym]
                for i, j in _size_pairs(cond_size):
                    count = 0
                    for v in self._sub(val_size):
                        for l, r in itertools.product(self._sub(i), self._sub(j)):
                            cond = ast.Compare(
                                left=l, ops=[op_cls()], comparators=[r]
                            )
                            yield ast.IfExp(test=cond, body=v, orelse=v)
                            count += 1
                            if count >= self.block_beam:
                                break

    def _sub(self, size: int) -> list[ast.expr]:
        """قائمة حجم فرعي — مجسّدة دائماً (أحجام أدنى الحالي)."""
        return self._by_size(size)

    def candidates(self) -> Iterator[ast.expr]:
        """سلسلة المرشحين كاملة — حتمية بالبايت، مسقوفة بالميزانية."""
        self._emitted = 0
        self._budget_hit = False
        seen: set[str] = set()
        for size in range(1, self.max_nodes + 1):
            for expr in self._stream_size(size):
                if self._emitted >= self.budget:
                    self._budget_hit = True
                    return
                key = ast.dump(expr)
                if key in seen:
                    continue
                seen.add(key)
                self._emitted += 1
                yield expr

    @property
    def budget_hit(self) -> bool:
        """هل توقف التعداد بالميزانية قبل استنفاد الفضاء كله؟"""
        return self._budget_hit

    @property
    def emitted(self) -> int:
        """عدد المرشحين الفريدين المُعدَّين فعلاً في آخر تشغيل."""
        return self._emitted


def structural_check(expr: ast.expr, params: tuple[str, ...]) -> None:
    """فحص بنيوي مُغلق — أي صنف خارج النحو يُرفض قبل التجميع."""
    # أسماء الدوال المُستدعاة تُعفى من فحص الأسماء — Call نفسه يفحصها أدناه
    func_node_ids = {
        id(n.func) for n in ast.walk(expr) if isinstance(n, ast.Call)
    }
    for node in ast.walk(expr):
        if not isinstance(node, _ALLOWED_NODES):
            raise StructuralViolation(
                f"عقدة خارج النحو المغلق: {type(node).__name__}"
            )
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            rhs = node.right
            if isinstance(rhs, ast.Constant) and isinstance(
                rhs.value, (int, float)
            ) and abs(rhs.value) > MAX_EXPONENT:
                raise StructuralViolation(
                    f"أس ثابت فوق الحرس المُعلن ({MAX_EXPONENT})"
                )
        if isinstance(node, ast.Name) and id(node) not in func_node_ids:
            if node.id not in params and node.id != "result":
                raise StructuralViolation(f"اسم خارج النطاق: {node.id!r}")
        if isinstance(node, ast.Call):
            if not (isinstance(node.func, ast.Name)
                    and node.func.id in CALLS_UNARY + CALLS_BINARY):
                raise StructuralViolation("استدعاء خارج المسموح القياسي")


def expr_source(expr: ast.expr) -> str:
    """نص التعبير المُنشأ — ast.unparse حتمي لشجرة واحدة."""
    return ast.unparse(expr)


__all__ = [
    "ARITH_OPS",
    "BASE_CONSTANTS",
    "CALLS_BINARY",
    "CALLS_UNARY",
    "CMP_OPS",
    "DEFAULT_BLOCK_BEAM",
    "DEFAULT_BUDGET",
    "DEFAULT_MAX_NODES",
    "MAX_EXPONENT",
    "CandidateSpace",
    "StructuralViolation",
    "expr_source",
    "harvest_constants",
    "structural_check",
]
