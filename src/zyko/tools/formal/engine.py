"""الحاكم الشكلي — «المُقترح يبحث، والحاكم يحكم» داخل ZYKO.

الطبقة الشكلية الحتمية 100% (قياسي فقط، بلا تنفيذ للمقترح): تقرأ
الكود المُقترَح كنص، تُحلّله بـ``ast``، وتحاكم **العقود المعلنة
صراحة** بتوجيهات التعليق — بلا شبكة ولا نماذج ولا عشوائية:

    # zyko:requires: x >= 0
    # zyko:ensures: result * 2 == x
    # zyko:domain: x = range(0, 8)
    def double(x):
        return x * 2

العقد الحاكم (غير قابل للتفاوض):
  * الحاكم حتمي ونقي — نفس المصدر يعطي نفس الحكم حرفياً.
  * الحكم ثلاثي: قبول (كل العقود المعلنة سليمة ومتسقة سكونياً) /
    رفض (عقد مشوّه الصياغة أو متناقض النطاق — يُرفض مع الدليل) /
    تعذّر التحقق (توجيه يلمس أسماء خارج نطاق الدالة، أو دالة معلنة
    العقود ناقصة المجال).
  * **لا تنفيذ للمقترح أبداً** — الفحص سكوني خالص: تجميع التعابير،
    تحليل الأسماء بمقارنة معامل الدالة، التحقق من أشكال المجال.
    تنفيذ العقود على مدخلات فعلية قرار المشغّل عبر صندوق الرمل.
  * بوابة الحاكم **اختيارية صريحة**: مقترح بلا توجيهات يمر نظيفاً
    وبتصريح في التفاصيل — لا افتراض صامت ولا إخفاء.

أكواد الخروج في ``__main__``: 0 قبول / 1 رفض / 2 تعذّر التحقق —
نفس عقد MIZAN وطبقة nexus-core الشكلية.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum

DIRECTIVE_PREFIX = "zyko:"
REQUIRES_DIRECTIVE = "requires"
ENSURES_DIRECTIVE = "ensures"
DOMAIN_DIRECTIVE = "domain"
RESULT_NAME = "result"

# المسموح استخدامه داخل تعابير العقود — مجموعة مقفلة، لا أسماء مفتوحة
ALLOWED_BUILTINS: frozenset[str] = frozenset(
    {
        "min",
        "max",
        "abs",
        "len",
        "round",
        "sum",
        "sorted",
        "any",
        "all",
        "int",
        "float",
        "str",
        "bool",
    }
)


class VerdictKind(Enum):
    """الحكم الثلاثي الصادق — الثالث ليس «ربما»: هو «تعذّر التحقق»."""

    ACCEPT = "accept"
    REJECT = "reject"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ContractFinding:
    """دليل واحد من الحاكم — يُقرأ لا يُخمَّن."""

    function: str
    kind: VerdictKind
    reason_ar: str
    directive: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class FormalReport:
    """تقرير الحاكم الشكلي على مصدر واحد — حتمي بالبايت."""

    verdict: VerdictKind
    findings: tuple[ContractFinding, ...] = ()
    functions_with_contracts: int = 0
    directives_checked: int = 0
    details: dict[str, object] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return self.verdict is VerdictKind.ACCEPT

    @property
    def rejected(self) -> bool:
        return self.verdict is VerdictKind.REJECT


def _directive_parts(comment_text: str) -> tuple[str, str] | None:
    """افصل توجيه zyko من نص التعليق — ``(النوع، المحتوى)`` أو لا شيء."""
    stripped = comment_text.strip()
    if not stripped.startswith(DIRECTIVE_PREFIX):
        return None
    body = stripped[len(DIRECTIVE_PREFIX) :].strip()
    for kind in (REQUIRES_DIRECTIVE, ENSURES_DIRECTIVE, DOMAIN_DIRECTIVE):
        if body.startswith(kind + ":"):
            content = body[len(kind) + 1 :].strip()
            return kind, content
    return None


def _source_directives_for(source: str, fn: ast.FunctionDef) -> list[tuple[str, str, int]]:
    """توجيهات الدالة من نص المصدر — الكتلة الملتصقة أعلى ``def`` وجسمها.

    الاتفاق الصادق: التوجيهات تعليقات، إما مباشرة فوق سطر التعريف
    (كتلة متصلة لا ينفصلها سطر كود) أو داخل جسم الدالة.
    """
    lines = source.splitlines()
    out: list[tuple[str, str, int]] = []

    def harvest(line_no: int) -> None:
        if 1 <= line_no <= len(lines):
            line = lines[line_no - 1]
            if "#" in line:
                parts = _directive_parts(line.split("#", 1)[1])
                if parts:
                    out.append((parts[0], parts[1], line_no))

    # 1) الكتلة الملتصقة فوق سطر def: تصعد على التعليقات والفراغات فقط
    probe = fn.lineno - 1
    while probe >= 1:
        stripped = lines[probe - 1].strip()
        if stripped == "" or stripped.startswith("#"):
            harvest(probe)
            probe -= 1
        else:
            break

    # 2) التعليقات داخل جسم الدالة حتى نهايتها
    end = fn.end_lineno or fn.lineno
    for lineno in range(fn.lineno, end + 1):
        harvest(lineno)
    return out


def _expression_names(expr_source: str) -> tuple[set[str], str | None]:
    """أسماء التعبير المُشار إليها — أو سبب عدم قابلية التجميع."""
    try:
        tree = ast.parse(expr_source, mode="eval")
    except SyntaxError as exc:
        return set(), f"صياغة غير صالحة: {exc.msg}"
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            return set(), "سمات الكائنات غير مسموحة في تعابير العقود"
        elif isinstance(node, (ast.Call,)):
            func = node.func
            if not (isinstance(func, ast.Name) and func.id in ALLOWED_BUILTINS):
                return set(), "الاستدعاءات مقصورة على المسموح القياسي المُدرج"
    return names, None


def _parse_domain(content: str) -> tuple[str, tuple[int, int] | list[object]] | None:
    """افحص شكل المجال سكونياً: ``name = range(a, b)`` أو ``name = [literals]``.

    يعيد ``(الاسم، الشكل)`` أو None إن كان الشكل غير مسموح.
    """
    try:
        tree = ast.parse(content, mode="exec")  # الإسناد عبارة لا تعبير
    except SyntaxError:
        return None
    body = tree.body
    if len(body) != 1:
        return None
    expr = body[0]
    if not (
        isinstance(expr, ast.Assign)
        and len(expr.targets) == 1
        and isinstance(expr.targets[0], ast.Name)
    ):
        return None
    name = expr.targets[0].id
    value = expr.value

    def _int_or_negated(e: ast.expr) -> int | None:
        """عدد صحيح حرفي أو مسبوبه — ``5`` و``-5`` كلاهما مقبولان."""
        if (
            isinstance(e, ast.Constant)
            and isinstance(e.value, int)
            and not isinstance(e.value, bool)
        ):
            return e.value
        if (
            isinstance(e, ast.UnaryOp)
            and isinstance(e.op, ast.USub)
            and isinstance(e.operand, ast.Constant)
            and isinstance(e.operand.value, int)
            and not isinstance(e.operand.value, bool)
        ):
            return -e.operand.value
        return None

    def _literal_value(e: ast.expr) -> object | None:
        if isinstance(e, ast.Constant) and isinstance(e.value, (int, float, str)):
            return e.value
        if (
            isinstance(e, ast.UnaryOp)
            and isinstance(e.op, ast.USub)
            and isinstance(e.operand, ast.Constant)
            and isinstance(e.operand.value, (int, float))
        ):
            return -e.operand.value
        return None

    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "range"
        and len(value.args) == 2
    ):
        lo = _int_or_negated(value.args[0])
        hi = _int_or_negated(value.args[1])
        if lo is not None and hi is not None:
            return name, ("range", lo, hi)

    if isinstance(value, (ast.List, ast.Tuple)):
        extracted = [_literal_value(e) for e in value.elts]
        if value.elts and all(v is not None for v in extracted):
            return name, extracted
    return None


def check_source(source: str) -> FormalReport:
    """حاكم العقود السكوني — المصدر الكامل، حكم واحد، أدلة كاملة."""
    findings: list[ContractFinding] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return FormalReport(
            verdict=VerdictKind.REJECT,
            findings=(
                ContractFinding(
                    function="<module>",
                    kind=VerdictKind.REJECT,
                    reason_ar=f"الكود المُقترح لا يُجمَّع أصلاً: {exc.msg}",
                    line=exc.lineno,
                ),
            ),
        )

    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    contracted = 0
    directives_total = 0

    for fn in functions:
        directives = _source_directives_for(source, fn)
        if not directives:
            continue
        contracted += 1
        params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        domains: dict[str, object] = {}
        requires_list: list[tuple[str, int]] = []
        ensures_list: list[tuple[str, int]] = []
        fn_findings: list[ContractFinding] = []

        for kind, content, lineno in directives:
            directives_total += 1
            if kind == DOMAIN_DIRECTIVE:
                parsed = _parse_domain(content)
                if parsed is None:
                    fn_findings.append(
                        ContractFinding(
                            function=fn.name,
                            kind=VerdictKind.REJECT,
                            reason_ar=(
                                "شكل المجال غير مسموح — name = range(a, b) أو "
                                "name = [قيم حرفية] فقط"
                            ),
                            directive=content,
                            line=lineno,
                        )
                    )
                    continue
                domain_name, domain_shape = parsed
                if domain_name not in params:
                    fn_findings.append(
                        ContractFinding(
                            function=fn.name,
                            kind=VerdictKind.REJECT,
                            reason_ar=f"المجال يعرّف {domain_name!r} وليست معاملاً في {fn.name!r}",
                            directive=content,
                            line=lineno,
                        )
                    )
                    continue
                domains[domain_name] = domain_shape
            elif kind == REQUIRES_DIRECTIVE:
                requires_list.append((content, lineno))
            else:
                ensures_list.append((content, lineno))

        # كل معامل مستخدم في عقود يجب أن يكون له مجال معلن — وإلا UNKNOWN
        # (result محجوز للناتج — لا يُطلب مجالاً له، ومصادرة اسمه كمعامل
        # تُرفض في فحص اللاحقات أدناه)
        contract_params: set[str] = set()
        for expr, _lineno in requires_list + ensures_list:
            names, error = _expression_names(expr)
            if error is None:
                contract_params |= names
        contract_params.discard(RESULT_NAME)
        missing_domain = sorted(p for p in contract_params if p in params and p not in domains)
        if missing_domain and not fn_findings:
            fn_findings.append(
                ContractFinding(
                    function=fn.name,
                    kind=VerdictKind.UNKNOWN,
                    reason_ar=(
                        "عقود معلنة بلا مجال مدخلات معلن لـ"
                        f"{', '.join(missing_domain)} — تعذّر التحقق السكوني؛ "
                        "أعلن zyko:domain أو احكم بالصندوق"
                    ),
                )
            )

        # تجميع التعابير وتحليل أسمائها — رفض بناء أو نطاق
        for expr, lineno in requires_list:
            names, error = _expression_names(expr)
            if error:
                fn_findings.append(
                    ContractFinding(
                        function=fn.name,
                        kind=VerdictKind.REJECT,
                        reason_ar=f"شرط مسبق مرفوض: {error}",
                        directive=expr,
                        line=lineno,
                    )
                )
                continue
            outside = names - params - ALLOWED_BUILTINS
            if outside:
                fn_findings.append(
                    ContractFinding(
                        function=fn.name,
                        kind=VerdictKind.REJECT,
                        reason_ar=(
                            f"شرط مسبق يلمس أسماء خارج معاملات الدالة: {', '.join(sorted(outside))}"
                        ),
                        directive=expr,
                        line=lineno,
                    )
                )
        for expr, lineno in ensures_list:
            names, error = _expression_names(expr)
            if error:
                fn_findings.append(
                    ContractFinding(
                        function=fn.name,
                        kind=VerdictKind.REJECT,
                        reason_ar=f"شرط لاحق مرفوض: {error}",
                        directive=expr,
                        line=lineno,
                    )
                )
                continue
            outside = names - params - ALLOWED_BUILTINS - {RESULT_NAME}
            if outside:
                fn_findings.append(
                    ContractFinding(
                        function=fn.name,
                        kind=VerdictKind.REJECT,
                        reason_ar=(
                            "شرط لاحق يلمس أسماء خارج المعاملات وresult: "
                            f"{', '.join(sorted(outside))}"
                        ),
                        directive=expr,
                        line=lineno,
                    )
                )
            if RESULT_NAME in params:
                fn_findings.append(
                    ContractFinding(
                        function=fn.name,
                        kind=VerdictKind.REJECT,
                        reason_ar="result اسم محجوز للناتج — لا يجوز أن يكون معاملاً",
                        directive=expr,
                        line=lineno,
                    )
                )
        if not ensures_list and not fn_findings:
            fn_findings.append(
                ContractFinding(
                    function=fn.name,
                    kind=VerdictKind.UNKNOWN,
                    reason_ar="عقد بلا شرط لاحق — لا شيء يُثبت، تعذّر التحقق",
                )
            )

        findings.extend(fn_findings)

    if contracted == 0:
        return FormalReport(
            verdict=VerdictKind.ACCEPT,
            findings=(
                ContractFinding(
                    function="<module>",
                    kind=VerdictKind.ACCEPT,
                    reason_ar="لا عقود معلنة — الحاكم الشكلي اختياري صريح، لا افتراضي صامت",
                ),
            ),
            functions_with_contracts=0,
            directives_checked=0,
            details={"no_contracts": True},
        )

    if any(f.kind is VerdictKind.REJECT for f in findings):
        verdict = VerdictKind.REJECT
    elif any(f.kind is VerdictKind.UNKNOWN for f in findings):
        verdict = VerdictKind.UNKNOWN
    else:
        verdict = VerdictKind.ACCEPT
    return FormalReport(
        verdict=verdict,
        findings=tuple(findings),
        functions_with_contracts=contracted,
        directives_checked=directives_total,
    )


def evidence_lines(report: FormalReport) -> tuple[str, ...]:
    """أسطر الدليل الجاهزة للإيصال — من الأحكام لا من الحلم."""
    lines: list[str] = []
    for f in report.findings:
        line = f"[{f.function}] {f.kind.value}: {f.reason_ar}"
        if f.directive is not None:
            line += f" | التوجيه: {f.directive}"
        if f.line is not None:
            line += f" (سطر {f.line})"
        lines.append(line)
    return tuple(lines)


def summarize(report: FormalReport) -> dict[str, object]:
    """ملخص قابل للتوقيع داخل الإيصال — حتمي بالبايت."""
    return {
        "verdict": report.verdict.value,
        "functions_with_contracts": report.functions_with_contracts,
        "directives_checked": report.directives_checked,
        "rejects": sum(1 for f in report.findings if f.kind is VerdictKind.REJECT),
        "unknowns": sum(1 for f in report.findings if f.kind is VerdictKind.UNKNOWN),
    }


# أسماء عامة للشراكة الطبقية: المُقترِح الحتمي (zyko.tools.synth) يعيد
# استخدام المُحلِّلات نفسها بلا نسخ — محرّك توجيه واحد في المستودع كله.
function_directives = _source_directives_for
parse_domain_shape = _parse_domain

__all__ = [
    "ALLOWED_BUILTINS",
    "ContractFinding",
    "FormalReport",
    "VerdictKind",
    "check_source",
    "evidence_lines",
    "function_directives",
    "parse_domain_shape",
    "summarize",
]
