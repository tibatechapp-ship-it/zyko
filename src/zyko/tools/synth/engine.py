"""zyko.tools.synth.engine — حلقة البحث: «المُقترِح ينفّذ، والحاكم يحكم».

الطبقة التي تكمل ثنائية v0.38.0: الحاكم الشكلي يحكم سكونيًا بلا
تنفيذ، والمُقترِح الحتمي هنا **يبحث وينفّذ** داخل الصنف المعلن ثم
يُسلّم فائزه إلى الحاكم للتحكيم الأخير. بلا شبكة، بلا نموذج لغوي،
بلا عشوائية:

1. اقرأ عقد المهمة (``spec.parse_task``) — حكم ثلاثي صادق.
2. اعدد مرشحي النحو المغلق (``grammar.CandidateSpace``) بترتيب
   ثابت بالبايت، مع شعاع كتل معلن وميزانية مرشحين معلنة.
3. لكل مرشح: فحص بنيوي مُغلق، تجميع، ثم تنفيذ على نقاط المجال
   المعلن في مساحة أسماء مبيّضة (``__builtins__`` مُفرَّغ والمسموح
   القياسي نفسه الذي يحاكم به الحاكم): المسبقات تُقصي النقاط،
   واللاحقات تحكم — أي استثناء أو شرط لاحق مخالف يُسقط المرشح
   فوراً.
4. الفائز يُعاد بناؤه مصدراً مع توجيهاته الأصلية، ثم يُحاكم بـ
   ``formal.check_source`` — الفائز لا يخرج بلا حكم الحاكم.
5. إيصال حتمي بالبايت: الحكم، العدّادات، فضاء البحث المعلن كاملاً،
   وبصمة سلسلة sha256 فوق (المهمة + الحكم + الفائز).

الأحكام الخمسة الصادقة (وأكواد الخروج في ``__main__``):

* ``synthesized`` (0) — فائز اجتاز النقاط وحاكمه الحاكم.
* ``exhausted``  (1) — الفضاء المعلن كله استُنفد بلا فائز: برهان
  غياب داخل الصنف المعلن.
* ``budget``     (1) — توقف التعداد بالميزانية قبل استنفاد الفضاء:
  بحث غير مكتمل بصدق — قد يوجد فائز خارج ما فُحص.
* ``invalid_spec`` (2) — عقد المهمة مرفوض من القارئ.
* ``unverifiable`` (2) — العقد تلمس معاملات بلا مجال، أو فائز
  نطري رفضه الحاكم — تعذّر التحقق بصدق.
"""

from __future__ import annotations

import ast
import builtins as _builtins_module
import hashlib
import itertools
import json
from dataclasses import dataclass, field
from typing import Any

from zyko.tools.formal.engine import ALLOWED_BUILTINS, VerdictKind, check_source, summarize
from zyko.tools.synth.grammar import (
    DEFAULT_BLOCK_BEAM,
    DEFAULT_BUDGET,
    DEFAULT_MAX_NODES,
    CandidateSpace,
    StructuralViolation,
    expr_source,
    harvest_constants,
    structural_check,
)
from zyko.tools.synth.spec import SpecVerdict, TaskSpec, parse_task

RECEIPT_KIND = "zyko.synth.receipt"

VERDICT_SYNTHESIZED = "synthesized"
VERDICT_EXHAUSTED = "exhausted"
VERDICT_BUDGET = "budget"
VERDICT_INVALID_SPEC = "invalid_spec"
VERDICT_UNVERIFIABLE = "unverifiable"

EXIT_SYNTHESIZED = 0
EXIT_NOT_FOUND = 1
EXIT_SPEC_BAD = 2


@dataclass(frozen=True)
class SynthReceipt:
    """إيصال التركيب — حتمي بالبايت، بلا أزمنة، مفاتيح مفرزة."""

    task: str
    spec_sha256: str
    verdict: str
    reason_ar: str
    emitted: int = 0
    tried: int = 0
    structural_skips: int = 0
    unjudgeable: int = 0
    winner_expr: str | None = None
    winner_source: str | None = None
    formal: dict[str, object] = field(default_factory=dict)
    search: dict[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.verdict == VERDICT_SYNTHESIZED

    @property
    def chain_hash(self) -> str:
        """بصمة السلسلة — sha256 فوق (المهمة + الحكم + الفائز)."""
        payload = "\x1f".join(
            [self.task, self.verdict, self.winner_expr or ""]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        """ممثل JSON حتمي — مفاتيح مفرزة وبلا أزمنة."""
        return {
            "chain_hash": self.chain_hash,
            "emitted": self.emitted,
            "formal": self.formal,
            "kind": RECEIPT_KIND,
            "reason_ar": self.reason_ar,
            "search": self.search,
            "spec_sha256": self.spec_sha256,
            "structural_skips": self.structural_skips,
            "task": self.task,
            "tried": self.tried,
            "unjudgeable": self.unjudgeable,
            "verdict": self.verdict,
            "winner_expr": self.winner_expr,
            "winner_source": self.winner_source,
        }

    def to_json(self) -> str:
        """سطر JSON واحد حتمي بالبايت — نفس الإيصال نفس البايتات."""
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )


def _compile_contracts(exprs: tuple[str, ...]) -> list[Any]:
    """جمّع تعابير العقود مرة واحدة — فشل التجميع استثناء للمُنادي."""
    compiled: list[Any] = []
    for expr in exprs:
        tree = ast.parse(expr, mode="eval")
        compiled.append(compile(tree, "<zyko:contract>", "eval"))
    return compiled


def _guided_seeds(spec: TaskSpec) -> list[ast.expr]:
    """بذور موجّهة بالعقد — كل «result == EXPR» في اللاحقات تعطي EXPR.

    ترتيب المشي الثابت، بلا تكرار بـast.dump، وبشرط ألا يلمس EXPR
    اسم الناتج المحجوز. البذور ليست حلّاً مجانياً: تُحكَم على نقاط
    المجال مثل أي مرشح ولا تخرج بلا قبول الحاكم.
    """
    seeds: list[ast.expr] = []
    seen: set[str] = set()
    for expr_src in spec.ensures:
        try:
            tree = ast.parse(expr_src, mode="eval").body
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Compare) and len(node.ops) == 1
                    and isinstance(node.ops[0], ast.Eq)):
                continue
            left, right = node.left, node.comparators[0]
            for a, b in ((left, right), (right, left)):
                if not (isinstance(a, ast.Name) and a.id == "result"):
                    continue
                inner = {n.id for n in ast.walk(b) if isinstance(n, ast.Name)}
                if "result" in inner:
                    continue
                key = ast.dump(b)
                if key not in seen:
                    seen.add(key)
                    seeds.append(b)
    return seeds


def _judge_point(
    requires_code: list[Any], ns: dict[str, Any]
) -> bool:
    """هل النقطة داخل المسبقات؟ False أو استثناء = خارج القياس."""
    for code in requires_code:
        try:
            if not eval(code, _SAFE_GLOBALS, ns):  # noqa: S307 — نحو مُغلق ومساحة مبيّضة
                return False
        except Exception:
            return False
    return True


def _safe_eval(code: Any, ns: dict[str, Any]) -> Any:
    """تقييم واحد مبيّض — الاستثناءات تعود لمُناديها كقرار مرشح."""
    return eval(code, _SAFE_GLOBALS, ns)  # noqa: S307 — نحو مُغلق ومساحة مبيّضة


# مساحة الأسماء المبيّضة: بلا builtins مفتوحة — المسموح القياسي نفسه
# الذي يحاكم به الحاكم الشكلي، مفرزاً ومعلناً.
_SAFE_GLOBALS: dict[str, Any] = {
    "__builtins__": {},
    **{name: getattr(_builtins_module, name) for name in sorted(ALLOWED_BUILTINS)},
}


def search(
    spec: TaskSpec,
    *,
    max_nodes: int = DEFAULT_MAX_NODES,
    budget: int = DEFAULT_BUDGET,
    block_beam: int = DEFAULT_BLOCK_BEAM,
) -> SynthReceipt:
    """ابحث عن برنامج يفي بالعقد — حكم واحد، إيصال كامل، بلا شك."""
    search_meta: dict[str, object] = {
        "block_beam": block_beam,
        "budget": budget,
        "max_nodes": max_nodes,
        "points_per_param": {k: len(v) for k, v in sorted(spec.domains.items())},
    }

    try:
        requires_code = _compile_contracts(spec.requires)
        ensures_code = _compile_contracts(spec.ensures)
    except SyntaxError as exc:
        return SynthReceipt(
            task=spec.name,
            spec_sha256=spec.sha256,
            verdict=VERDICT_UNVERIFIABLE,
            reason_ar=f"عقد غير قابل للتجميع أثناء البحث: {exc.msg}",
            search=search_meta,
        )

    param_names = [p for p in spec.params if p in spec.domains]
    value_lists = [spec.domains[p] for p in param_names]
    points: list[dict[str, Any]] = [
        dict(zip(param_names, combo))
        for combo in itertools.product(*value_lists)
    ]
    if not points:
        return SynthReceipt(
            task=spec.name,
            spec_sha256=spec.sha256,
            verdict=VERDICT_UNVERIFIABLE,
            reason_ar="لا نقاط تحقق — المجالات المعلنة فارغة",
            search=search_meta,
        )

    constants = harvest_constants(spec.requires, spec.ensures, spec.domains)
    try:
        space = CandidateSpace(
            spec.params, constants, max_nodes=max_nodes, budget=budget,
            block_beam=block_beam,
        )
    except ValueError as exc:
        return SynthReceipt(
            task=spec.name,
            spec_sha256=spec.sha256,
            verdict=VERDICT_UNVERIFIABLE,
            reason_ar=f"فضاء بحث غير صالح — {exc}",
            search=search_meta,
        )
    search_meta["constants"] = list(constants)
    search_meta["params"] = list(spec.params)

    tried = 0
    structural_skips = 0
    unjudgeable = 0
    winner: ast.expr | None = None

    def _try_candidate(candidate: ast.expr) -> bool | None:
        """تحكيم مرشح واحد — True فائز / False سقط / None غير قابل للحكم.

        تعدّل العدّادات المغلقة (tried وstructural_skips وunjudgeable)
        — حلقة واحدة فوق مرحلتي البحث بلا تكرار المنطق.
        """
        nonlocal tried, structural_skips, unjudgeable
        try:
            structural_check(candidate, spec.params)
        except StructuralViolation:
            structural_skips += 1
            return False
        try:
            candidate = ast.fix_missing_locations(candidate)
            code = compile(ast.Expression(body=candidate), "<zyko:candidate>", "eval")
        except (SyntaxError, ValueError, TypeError):
            structural_skips += 1
            return False

        judged = False
        for point in points:
            ns: dict[str, Any] = dict(point)
            if not _judge_point(requires_code, ns):
                continue  # نقطة خارج المسبقات — لا حكم عليها
            try:
                ns["result"] = _safe_eval(code, ns)
            except Exception:
                tried += 1
                return False
            violated = False
            for ensure in ensures_code:
                try:
                    if not _safe_eval(ensure, ns):
                        violated = True
                        break
                except Exception:
                    violated = True
                    break
            if violated:
                tried += 1
                return False
            judged = True
        if not judged:
            unjudgeable += 1
            return None
        tried += 1
        return True

    # المرحلة صفر — بذور موجهة بالعقد: كل «result == EXPR» ظاهرة في
    # اللاحقات تعطي مرشحاً EXPR مباشرة (بلا result داخله، مفرزاً
    # بلا تكرار، بترتيب المشي الثابت). هذا إعلان صادق لا خداع: البذرة
    # تُحكَم على النقاط نفسها ولا تخرج بلا حكم الحاكم.
    seeds = _guided_seeds(spec)
    search_meta["guided_seeds"] = len(seeds)
    won_by = "enumeration"
    for seed in seeds:
        outcome = _try_candidate(seed)
        if outcome is True:
            winner = seed
            won_by = "seed"
            break

    # المرحلة واحدة — التعداد النقي للنحو المغلق (لا تُشغَّل إذا وجدت
    # البذور فائزاً — الأصغر أولاً يبقى عقد الترتيب).
    if winner is None:
        for candidate in space.candidates():
            outcome = _try_candidate(candidate)
            if outcome is True:
                winner = candidate
                break

    emitted = space.emitted
    search_meta["won_by"] = won_by
    if winner is not None:
        winner_src = expr_source(winner)
        directives = "\n".join(spec.directives_preserved)
        params_sig = ", ".join(spec.params)
        program = (
            f"{directives}\n"
            f"def {spec.name}({params_sig}):\n"
            f"    return {winner_src}\n"
        )
        report = check_source(program)
        formal_summary = summarize(report)
        if report.verdict is not VerdictKind.ACCEPT:
            return SynthReceipt(
                task=spec.name,
                spec_sha256=spec.sha256,
                verdict=VERDICT_UNVERIFIABLE,
                reason_ar=(
                    "فائز نطري رفضه الحاكم الشكلي — لا يُسلَّم بلا حكم قبول"
                ),
                emitted=emitted,
                tried=tried,
                structural_skips=structural_skips,
                unjudgeable=unjudgeable,
                winner_expr=winner_src,
                formal=formal_summary,
                search=search_meta,
            )
        return SynthReceipt(
            task=spec.name,
            spec_sha256=spec.sha256,
            verdict=VERDICT_SYNTHESIZED,
            reason_ar=(
                "فائز اجتاز كل نقاط المجال وكل اللاحقات، وقبله الحاكم الشكلي"
            ),
            emitted=emitted,
            tried=tried,
            structural_skips=structural_skips,
            unjudgeable=unjudgeable,
            winner_expr=winner_src,
            winner_source=program,
            formal=formal_summary,
            search=search_meta,
        )

    if unjudgeable > 0 and tried == 0:
        return SynthReceipt(
            task=spec.name,
            spec_sha256=spec.sha256,
            verdict=VERDICT_EXHAUSTED,
            reason_ar=(
                "كل نقاط المجال خارج المسبقات — لا مرشح يُحكَم أصلاً؛ "
                "افحص zyko:requires مقابل zyko:domain"
            ),
            emitted=emitted,
            tried=tried,
            structural_skips=structural_skips,
            unjudgeable=unjudgeable,
            search=search_meta,
        )
    if space.budget_hit:
        return SynthReceipt(
            task=spec.name,
            spec_sha256=spec.sha256,
            verdict=VERDICT_BUDGET,
            reason_ar=(
                f"توقف التعداد بالميزانية ({budget} مرشح) قبل استنفاد الفضاء — "
                "بحث غير مكتمل بصدق: قد يوجد فائز خارج ما فُحص"
            ),
            emitted=emitted,
            tried=tried,
            structural_skips=structural_skips,
            unjudgeable=unjudgeable,
            search=search_meta,
        )
    return SynthReceipt(
        task=spec.name,
        spec_sha256=spec.sha256,
        verdict=VERDICT_EXHAUSTED,
        reason_ar=(
            "الفضاء المعلن كله استُنفد بلا فائز — برهان غياب داخل صنف "
            f"النحو المغلق ({max_nodes} عقدة، شعاع {block_beam})"
        ),
        emitted=emitted,
        tried=tried,
        structural_skips=structural_skips,
        unjudgeable=unjudgeable,
        search=search_meta,
    )


def run(
    source: str,
    *,
    max_nodes: int = DEFAULT_MAX_NODES,
    budget: int = DEFAULT_BUDGET,
    block_beam: int = DEFAULT_BLOCK_BEAM,
) -> SynthReceipt:
    """من مصدر مهمة خام إلى إيصال — المسار الكامل بلا استثناءات خارج."""
    verdict: SpecVerdict = parse_task(source)
    if verdict.kind is VerdictKind.REJECT:
        return SynthReceipt(
            task="?",
            spec_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
            verdict=VERDICT_INVALID_SPEC,
            reason_ar=verdict.reason_ar,
        )
    if verdict.kind is VerdictKind.UNKNOWN or verdict.spec is None:
        return SynthReceipt(
            task="?",
            spec_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
            verdict=VERDICT_UNVERIFIABLE,
            reason_ar=verdict.reason_ar,
        )
    return search(
        verdict.spec, max_nodes=max_nodes, budget=budget, block_beam=block_beam
    )


__all__ = [
    "EXIT_NOT_FOUND",
    "EXIT_SPEC_BAD",
    "EXIT_SYNTHESIZED",
    "RECEIPT_KIND",
    "SynthReceipt",
    "run",
    "search",
]
