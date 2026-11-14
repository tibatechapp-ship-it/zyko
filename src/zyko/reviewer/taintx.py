"""taintx — التلوث بين الإجرائيات (بنية 5 من النظام الهجين).

الزبدة المعلنة: تحليل taint الملفي (الموجة ميزان) يقف عند حدود الدوال
موثقاً — هذه الوحدة تعبر الحدود داخل الملف الواحد: رسم دوال (call
graph) ثم انتشار حتى الثبات بثلاث قنوات موثقة:

  * **معاملات**: نداء ``g(x_ملوث)`` يجعل معامل g المظاهر ملوثاً
  * **عوائد**: دالة تعيد تعبيراً ملوثاً ⇒ كل ``x = g()`` يجعل x ملوثاً
  * **مصادر**: مصادر taint الأصلية (input/sys.argv/request.*) داخل كل دالة

الحدود الموثقة قبل التوسيع (روح taint الأم): ملف واحد، نداءات بالاسم
البسيط، الاسم الغامض (تعريفان بنفس الاسم) يُتخطى معلناً لا يُخمَّن،
والوسائط المسماة (keyword) تحسم معاملها بالاسم لا بالموضع.

حتمية بالبايت، بلا شبكة، ولا تستورد rules (طبقة taint أدمى من المراجعة).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from zyko.reviewer.taint import (
    _MAX_FIXPOINT_PASSES,
    _collect_assignments,
    expr_tainted,
    is_input_source,
    is_request_source,
)

__all__ = ["InterTaintResult", "collect_inter_taints", "inter_taint"]

_FIXPOINT_PASSES = 20


@dataclass
class InterTaintResult:
    """نتيجة عائلة مصادر واحدة: حالات الدوال + تدفقات الحواف."""

    family: str
    functions: dict  # qualname ⇒ {tainted_params, tainted_locals, returns_tainted}
    flows: tuple  # {caller, callee, param, line} مرتبة

    def to_dict(self) -> dict:
        return {
            "schema": "zyko.taintx/1",
            "family": self.family,
            "functions": {
                q: {
                    "tainted_params": sorted(v["tainted_params"]),
                    "tainted_locals": sorted(v["tainted_locals"]),
                    "returns_tainted": v["returns_tainted"],
                }
                for q, v in sorted(self.functions.items())
            },
            "flows": sorted(
                (dict(f) for f in self.flows),
                key=lambda d: (d["caller"], d["callee"], d["param"], d["line"]),
            ),
        }


def _collect_funcs(tree: ast.Module) -> tuple[dict, frozenset]:
    """qualname ⇒ عقدة الدالة + أسماء بسيطة مكررة (الغموض يُعلن لا يُحل)."""
    out: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    dups: set[str] = set()

    def visit(node, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = f"{prefix}{child.name}"
                if q in out:
                    dups.add(q.rsplit(".", 1)[-1])
                else:
                    out[q] = child
                visit(child, q + ".")
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            else:
                visit(child, prefix)

    visit(tree, "")
    return out, frozenset(dups)


def _simple_names(funcs: dict) -> dict:
    """الاسم البسيط ⇒ قائمة مؤهلات — الغموض لا يُحل بالتخمين."""
    by_simple: dict[str, list[str]] = {}
    for q in funcs:
        simple = q.rsplit(".", 1)[-1]
        by_simple.setdefault(simple, []).append(q)
    return by_simple


def _call_sites(fn, funcs: dict, by_simple: dict) -> list:
    """مواقع النداء داخل دالة: (سطر، مؤهل محسوم، [(اسم معامل، تعبير)])."""
    sites: list[tuple[int, str, list[tuple[str, ast.expr]]]] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        candidates = by_simple.get(node.func.id, [])
        if len(candidates) != 1:
            continue  # غامض أو غير موجود — تخطٍ معلن
        callee = candidates[0]
        params = [a.arg for a in funcs[callee].args.args if a.arg != "self"]
        mapping: list[tuple[str, ast.expr]] = []
        for i, arg in enumerate(node.args):
            if i < len(params):
                mapping.append((params[i], arg))
        for kw in node.keywords:
            if kw.arg and kw.arg in params:
                mapping.append((kw.arg, kw.value))
        if mapping:
            sites.append((node.lineno, callee, mapping))
    return sites


def _local_propagate(fn, seeds: frozenset, source_pred) -> frozenset:
    """ثبات محلي على جسد الدالة مع بذور المعاملات والعوائد الواردة."""
    pairs = _collect_assignments(fn)
    tainted = set(seeds)
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


def inter_taint(tree: ast.Module, family: str, source_pred) -> InterTaintResult:
    """انتشار بين الإجرائيات حتى الثبات — عائلة مصادر واحدة."""
    funcs, ambiguous = _collect_funcs(tree)
    by_simple = {s: qs for s, qs in _simple_names(funcs).items() if s not in ambiguous}

    param_seeds: dict[str, set] = {q: set() for q in funcs}
    ret_seeds: dict[str, set] = {q: set() for q in funcs}
    ret_tainted: dict[str, bool] = {q: False for q in funcs}
    flows: list[dict] = []

    for _ in range(_FIXPOINT_PASSES):
        changed = False
        locals_ = {
            q: _local_propagate(fn, frozenset(param_seeds[q] | ret_seeds[q]), source_pred)
            for q, fn in funcs.items()
        }
        # عوائد
        for q, fn in funcs.items():
            t = locals_[q]
            for r in ast.walk(fn):
                if isinstance(r, ast.Return) and r.value is not None:
                    if expr_tainted(r.value, t, source_pred) and not ret_tainted[q]:
                        ret_tainted[q] = True
                        changed = True
        # بذور العوائد: x = g() مع عائد g ملوث
        for q, fn in funcs.items():
            for targets, value in _collect_assignments(fn):
                if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                    cands = by_simple.get(value.func.id, [])
                    if len(cands) == 1 and ret_tainted[cands[0]]:
                        new = set(targets) - ret_seeds[q]
                        if new:
                            ret_seeds[q].update(new)
                            changed = True
        # حواف المعاملات
        for q, fn in funcs.items():
            t = locals_[q]
            for line, callee, mapping in _call_sites(fn, funcs, by_simple):
                for pname, arg in mapping:
                    if expr_tainted(arg, t, source_pred):
                        record = {"caller": q, "callee": callee, "param": pname, "line": line}
                        if record not in flows:
                            flows.append(record)
                        if pname not in param_seeds[callee]:
                            param_seeds[callee].add(pname)
                            changed = True
        if not changed:
            break

    # لقطة نهائية بالحالات المستقرة
    final_locals = {
        q: _local_propagate(fn, frozenset(param_seeds[q] | ret_seeds[q]), source_pred)
        for q, fn in funcs.items()
    }
    functions = {}
    for q, fn in funcs.items():
        params = [a.arg for a in fn.args.args]
        functions[q] = {
            "tainted_params": sorted(
                set(params) & (param_seeds[q] | (final_locals[q] & set(params)))
            ),
            "tainted_locals": sorted(final_locals[q] - set(params)),
            "returns_tainted": ret_tainted[q],
        }
    return InterTaintResult(family=family, functions=functions, flows=tuple(flows))


def collect_inter_taints(tree: ast.Module) -> dict:
    """العائلتان معاً بالاصطلاح نفسه الذي تتبعه collect_taints."""
    return {
        "input": inter_taint(tree, "input", is_input_source),
        "request": inter_taint(tree, "request", is_request_source),
    }
