"""zyko.fixer.fixes — سجل الإصلاحات الحتمية للمرحلة 3 (D41–58).

فلسفة الإصلاح (ما يميزنا عن مصلحي النماذج اللغوية):
  - لا اختراع: كل إصلاح قاعدة AST ثابتة بنفس منطق كشف المراجع (المرحلة 2)
    حرفيًا — الملاحظة نفسها التي ظهرت هي التي تُصلَح.
  - لا طموح مفرط: القاعدة إما لها «مسار آمن» محفوظ الدلالة أو تبقى يدوية
    مع suggestion_ar — نرفض إصلاحًا قد يكسر المعنى.
  - تحقق مزدوج: الناتج يُعاد تحليله بـ ast قبل القبول (المحرك يفرض ذلك).

12 قاعدة قابلة للإصلاح الآلي، و15 قاعدة يدوية تبقى بإصلاح مقترح عربي.
سلاسل الإصلاح الموثقة (إصلاح قاعدة يُظهر التالية — تصحيح تدريجي لا عيب):
  R-ERR-001 ⇒ R-ERR-009 (except Exception ما تزال واسعة: قلّصها يدويًا)
  R-QLT-209 ⇒ R-QLT-204 (الدالة الجديدة من اللامدا تحتاج docstring — المحرك
              يكمل السلسلة تلقائيًا في جولة ثانية)
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass

from zyko.fixer.edits import Edit, SourceText, indent_of, shift_lines
from zyko.reviewer.rules import _iter_except_actions, _iter_funcs, _name_of

__all__ = [
    "ACTION_AR",
    "AUTO_FIXABLE",
    "FIX_PLANNERS",
    "FixContext",
    "MANUAL_RULES",
    "Planner",
    "manual_reason_ar",
]


# ------------------------------------------------------------ السياق
@dataclass
class FixContext:
    """ما يحتاجه المُخطِّط: الشجرة، النص المفهرس، مسار الملف (لقاعدة __init__)."""

    tree: ast.Module
    src: SourceText
    path: str

    def seg(self, node: ast.AST) -> str:
        """مقطع المصدر الأصلي لعقدة — كما كتبه المؤلف حرفيًا."""
        return self.src.segment(
            node.lineno,
            node.col_offset,
            node.end_lineno,
            node.end_col_offset,  # type: ignore[attr-defined]
        )


Planner = Callable[[FixContext], list[Edit]]


# --------------------------------------------------- أدوات مشتركة للحذر
def _edit_span(node: ast.AST, replacement: str, rule_id: str, note_ar: str) -> Edit:
    """قطعة تستبدل نطاق عقدة كاملةً."""
    return Edit(
        node.lineno,
        node.col_offset,
        node.end_lineno,
        node.end_col_offset,
        replacement,
        rule_id,
        note_ar,
    )


def _attr_name_edit(attr_node: ast.Attribute, new_attr: str, rule_id: str, note_ar: str) -> Edit:
    """استبدال اسم السمة الأخير في تعبير (md5 → sha256 مثلًا) بموقع دقيق.

    ast.Attribute لا يوفر موقع اسم السمة وحده؛ الاسم يحتل آخر len(attr)
    بايت من نهاية التعبير (أسماء السمات ASCII فبايتها حرفها).
    """
    end_line = attr_node.end_lineno
    end_col = attr_node.end_col_offset
    return Edit(
        end_line,
        end_col - len(attr_node.attr),
        end_line,
        end_col,
        new_attr,
        rule_id,
        note_ar,
    )


def _has_hash(segment: str) -> bool:
    """هل يحتوي المقطع على «#»؟ (تعليق داخل نطاق القطع ⇒ نتراجع احتياطًا)."""
    return "#" in segment


def _tail_of_line_clear(st: SourceText, node: ast.AST) -> bool:
    """ما بعد نهاية العقدة في سطرها الأخير فارغ أو تعليق؟
    حارس أساسي: نرفض الاستبدال بأسطر كاملة إن وُجد بيان آخر بعد «;»."""
    line = st.line_text(node.end_lineno)
    tail = line[SourceText.char_col(line, node.end_col_offset) :]
    stripped = tail.strip()
    return stripped == "" or stripped.startswith("#")


def _has_multiline_string(stmt: ast.stmt) -> bool:
    """هل يحوي البيان نصًا حرفيًا ممتدًا على أسطر؟ (إزاحة بادئته تفسد محتواه)."""
    for n in ast.walk(stmt):
        if isinstance(n, ast.JoinedStr) and n.lineno != n.end_lineno:
            return True
        if isinstance(n, ast.Constant) and isinstance(n.value, (str, bytes)):
            if n.lineno != n.end_lineno or "\n" in str(n.value):
                return True
    return False


def _all_bound_names(tree: ast.Module) -> set[str]:
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def _removal_span(call: ast.Call, kw: ast.keyword) -> tuple[tuple[int, int], tuple[int, int]]:
    """نطاق حذف وسيط مسمى من استدعاء مع إدارة الفواصل — ثلاثة أشكال:
    (سابق، kw) نمسح من نهاية السابق، (kw، لاحق) حتى بداية اللاحق، (kw) وحيد."""
    elements: list[ast.AST] = [*call.args, *call.keywords]
    ordered = sorted(elements, key=lambda x: (x.lineno, x.col_offset))
    idx = next(i for i, el in enumerate(ordered) if el is kw)
    if idx > 0:
        p = ordered[idx - 1]
        return (p.end_lineno, p.end_col_offset), (kw.end_lineno, kw.end_col_offset)
    if idx + 1 < len(ordered):
        nx = ordered[idx + 1]
        return (kw.lineno, kw.col_offset), (nx.lineno, nx.col_offset)
    return (kw.lineno, kw.col_offset), (kw.end_lineno, kw.end_col_offset)


def _kw_removal_edit(
    call: ast.Call, kw: ast.keyword, rule_id: str, note_ar: str, src: SourceText
) -> Edit | None:
    """قطعة حذف وسيط مسمى — ترفع None إذا تسرب تعليق داخل نطاق الحذف."""
    (s_line, s_col), (e_line, e_col) = _removal_span(call, kw)
    if _has_hash(src.segment(s_line, s_col, e_line, e_col)):
        return None
    return Edit(s_line, s_col, e_line, e_col, "", rule_id, note_ar)


def _is_none_const(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _has_none_guard(func: ast.FunctionDef | ast.AsyncFunctionDef, param: str) -> bool:
    """هل يحوي جسم الدالة حراسة `if param is None` أصلًا؟ (منع التكرار).
    نفحص كل عبارات الجسم المباشرة لا أولها فقط — لأن التوثيق قد يسبق الحارس."""
    for stmt in func.body:
        if isinstance(stmt, ast.If):
            t = stmt.test
            if (
                isinstance(t, ast.Compare)
                and len(t.ops) == 1
                and isinstance(t.ops[0], ast.Is)
                and isinstance(t.left, ast.Name)
                and t.left.id == param
                and _is_none_const(t.comparators[0])
            ):
                return True
    return False


def _containing_body(tree: ast.Module, target: ast.stmt) -> list[ast.stmt] | None:
    """جسم البيانات المركّب الذي يضم target مباشرة (بمطابقة هوية الكائن)."""
    for n in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            v = getattr(n, field, None)
            if isinstance(v, list) and any(s is target for s in v if isinstance(s, ast.stmt)):
                return v
    return None


# --------------------------------------- مسارات الإصلاح (12 قاعدة آلية)
def _fix_bare_except(ctx: FixContext) -> list[Edit]:
    """R-ERR-001: `except:` ⇒ `except Exception:` (الإصلاح المعياري E722)."""
    out: list[Edit] = []
    pat = re.compile(r"except\s*:")

    def to_byte(text: str, char_index: int) -> int:
        return len(text[:char_index].encode("utf-8"))

    for n in ast.walk(ctx.tree):
        if not (isinstance(n, ast.ExceptHandler) and n.type is None):
            continue
        line_text = ctx.src.line_text(n.lineno)
        char_start = SourceText.char_col(line_text, n.col_offset)
        m = pat.match(line_text, char_start)
        if not m:
            continue  # صياغة نادرة (except في سطر و: في سطر آخر) ⇒ تبقى يدوية
        out.append(
            Edit(
                n.lineno,
                to_byte(line_text, m.start()),
                n.lineno,
                to_byte(line_text, m.end()),
                "except Exception:",
                "R-ERR-001",
                "استُبدلت except: العامة بـ except Exception:",
            )
        )
    return out


def _fix_raise_from(ctx: FixContext) -> list[Edit]:
    """R-ERR-003: `raise X` داخل معالج ⇒ `raise X from <الاسم>`."""
    out: list[Edit] = []
    taken = _all_bound_names(ctx.tree)
    for n in ast.walk(ctx.tree):
        if not isinstance(n, ast.ExceptHandler):
            continue
        raises = [
            sub
            for sub in _iter_except_actions(n.body)
            if isinstance(sub, ast.Raise) and sub.exc is not None and sub.cause is None
        ]
        if not raises:
            continue
        bind = n.name
        if not bind:
            bind = "_zk_exc"
            while bind in taken:
                bind = "_zk_exc" + str(len(taken))
            taken.add(bind)
            if n.type is not None:
                out.append(
                    Edit(
                        n.type.end_lineno,
                        n.type.end_col_offset,
                        n.type.end_lineno,
                        n.type.end_col_offset,
                        f" as {bind}",
                        "R-ERR-003",
                        "سُمّي معالج الاستثناء لربط السبب",
                    )
                )
        for r in raises:
            out.append(
                Edit(
                    r.exc.end_lineno,
                    r.exc.end_col_offset,
                    r.exc.end_lineno,
                    r.exc.end_col_offset,
                    f" from {bind}",
                    "R-ERR-003",
                    "أُضيف from للحفاظ على سلسلة الأسباب",
                )
            )
    return out


def _open_assign_targets(ctx: FixContext) -> list[tuple[ast.Assign, ast.Name, ast.Call]]:
    """إسنادات `var = open(...)` خارج with — جولة واحدة بلا تكرار، بنفس
    منطق كشف المراجع في تعقب عمق with داخل الأجساد المتداخلة."""
    found: list[tuple[ast.Assign, ast.Name, ast.Call]] = []

    def _walk_body(body: list[ast.stmt], in_with: int) -> None:
        for stmt in body:
            if (
                in_with == 0
                and isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Name)
                and stmt.value.func.id == "open"
            ):
                found.append((stmt, stmt.targets[0], stmt.value))
            next_in_with = in_with
            if isinstance(stmt, (ast.With, ast.AsyncWith)):
                next_in_with = in_with + 1
            for field in ("body", "orelse", "finalbody"):
                sub = getattr(stmt, field, None)
                if isinstance(sub, list) and sub and isinstance(sub[0], ast.stmt):
                    _walk_body(sub, next_in_with)

    module_body = list(ctx.tree.body)
    _walk_body(module_body, 0)
    return found


def _uses_name(stmt: ast.stmt, var: str) -> bool:
    return any(isinstance(n, ast.Name) and n.id == var for n in ast.walk(stmt))


def _fix_open_with(ctx: FixContext) -> list[Edit]:
    """R-ERR-004: `var = open(...)` ⇒ `with open(...) as var:` مع لف ما يليه."""
    out: list[Edit] = []
    for assign, target, call in _open_assign_targets(ctx):
        var = target.id
        body = _containing_body(ctx.tree, assign)
        if body is None:
            continue
        i = body.index(assign)
        run: list[ast.stmt] = []
        for nxt in body[i + 1 :]:
            if _uses_name(nxt, var):
                run.append(nxt)
            else:
                break
        if not run:
            continue  # لا شيء يعتمد المتغير ⇒ لا فائدة من with هنا (تبقى يدوية)
        if any(_uses_name(nxt, var) for nxt in body[i + 1 + len(run) :]):
            continue  # استخدام لاحق خارج النطاق الملفوف ⇒ نتركها يدوية
        if run[0].lineno == assign.end_lineno:
            continue  # بيانات على سطر واحد بـ «;» ⇒ نرفض احتياطًا
        if any(_has_multiline_string(s) for s in run):
            continue  # نص متعدد الأسطر تفسده إزاحة البادئة
        if not _tail_of_line_clear(ctx.src, assign):
            continue
        call_src = ctx.seg(call)
        out.append(
            Edit(
                assign.lineno,
                assign.col_offset,
                assign.end_lineno,
                assign.end_col_offset,
                f"with {call_src} as {var}:",
                "R-ERR-004",
                "وُضعت open داخل with ووُلّفت العبارات التابعة للمتغير",
            )
        )
        for ln in range(run[0].lineno, run[-1].end_lineno + 1):
            if ctx.src.line_text(ln).strip():
                out.append(
                    Edit(
                        ln,
                        0,
                        ln,
                        0,
                        "    ",
                        "R-ERR-004",
                        "أُزاحت بادئة عبارات جسم with",
                    )
                )
    return out


def _fix_shell_true(ctx: FixContext) -> list[Edit]:
    """R-ERR-005: حذف shell=True عندما يكون الأمر قائمة/صف وسائط أصلًا
    (موضعيًا أو عبر الوسيط المسمى args كما في توقيع subprocess)."""
    out: list[Edit] = []

    def command_is_list(call: ast.Call) -> bool:
        if call.args and isinstance(call.args[0], (ast.List, ast.Tuple)):
            return True
        args_kw = next((k for k in call.keywords if k.arg == "args"), None)
        return args_kw is not None and isinstance(args_kw.value, (ast.List, ast.Tuple))

    for n in ast.walk(ctx.tree):
        if not isinstance(n, ast.Call):
            continue
        for kw in n.keywords:
            if not (
                kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True
            ):
                continue
            if not command_is_list(n):
                continue  # الأمر نص أو مجهول ⇒ إزالة shell تكسر المعنى ⇒ يدوي
            edit = _kw_removal_edit(
                n, kw, "R-ERR-005", "حُذف shell=True لأن الأمر قائمة وسائط", ctx.src
            )
            if edit is not None:
                out.append(edit)
    return out


def _fix_mutable_default(ctx: FixContext) -> list[Edit]:
    """R-ERR-006: القيمة الافتراضية المتحورة ⇒ None + حراسة إنشاء داخلية."""
    out: list[Edit] = []

    def risky(d: ast.expr) -> bool:
        if isinstance(d, (ast.List, ast.Dict, ast.Set)):
            return True
        return isinstance(d, ast.Call) and _name_of(d.func) in ("list", "dict", "set")

    per_func: dict[
        int, tuple[ast.FunctionDef | ast.AsyncFunctionDef, list[tuple[str, ast.expr]]]
    ] = {}
    for _qual, func in _iter_funcs(ctx.tree):
        pairs: list[tuple[str, ast.expr]] = []
        all_args = [*func.args.posonlyargs, *func.args.args]
        defaults = func.args.defaults
        # القيم الافتراضية تحاذي آخر N وسيطًا موضعيًا (اصطلاح CPython)
        aligned = all_args[-len(defaults) :] if defaults else []
        for arg, d in zip(aligned, defaults):
            if risky(d):
                pairs.append((arg.arg, d))
        for arg, d in zip(func.args.kwonlyargs, func.args.kw_defaults):
            if d is not None and risky(d):
                pairs.append((arg.arg, d))
        if pairs:
            per_func[id(func)] = (func, pairs)

    for func, pairs in per_func.values():
        body0 = func.body[0] if func.body else None
        if body0 is None or body0.lineno == func.lineno:
            continue  # دالة بسطر واحد ⇒ لا مكان سليم للحارس (تبقى يدوية)
        pairs = [(p, d) for p, d in pairs if not _has_none_guard(func, p)]
        if not pairs:
            continue
        ind = indent_of(ctx.src.line_text(body0.lineno))
        guard = "".join(f"{ind}if {p} is None:\n{ind}    {p} = {ctx.seg(d)}\n" for p, d in pairs)
        # التوثيق لا يُزح عن مقدمة الدالة: الحارس يُدرج بعده إن كان أول جسم التوثيق
        if isinstance(body0, ast.Expr) and isinstance(body0.value, ast.Constant):
            insert_line = body0.end_lineno + 1
        else:
            insert_line = body0.lineno
        if insert_line > ctx.src.line_count():
            # التوثيق آخر سطر بلا سطر لاحق: نلحق الحارس بنهاية النص بسطر جديد
            last = ctx.src.line_count()
            last_text = ctx.src.line_text(last)
            out.append(
                Edit(
                    last,
                    len(last_text.encode("utf-8")),
                    last,
                    len(last_text.encode("utf-8")),
                    "\n" + guard,
                    "R-ERR-006",
                    "أُضيفت حراسة تنشئ القيمة المتحورة داخل الدالة",
                )
            )
        else:
            out.append(
                Edit(
                    insert_line,
                    0,
                    insert_line,
                    0,
                    guard,
                    "R-ERR-006",
                    "أُضيفت حراسة تنشئ القيمة المتحورة داخل الدالة",
                )
            )
        for _p, d in pairs:
            out.append(
                Edit(
                    d.lineno,
                    d.col_offset,
                    d.end_lineno,
                    d.end_col_offset,
                    "None",
                    "R-ERR-006",
                    "استُبدلت القيمة الافتراضية المتحورة بـ None",
                )
            )
    return out


def _fix_yaml(ctx: FixContext) -> list[Edit]:
    """R-SEC-103: yaml غير آمن ⇒ safe_load (وحذف Loader غير الآمن المسمّى)."""
    out: list[Edit] = []
    safe_loaders = ("SafeLoader", "CSafeLoader")

    def loader_ok_text(expr: ast.expr) -> bool:
        return _name_of(expr).rsplit(".", 1)[-1] in safe_loaders

    for n in ast.walk(ctx.tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        if _name_of(n.func.value) != "yaml":
            continue
        attr = n.func.attr
        if attr in ("full_load", "full_load_all", "unsafe_load"):
            new_attr = "safe_load_all" if attr == "full_load_all" else "safe_load"
            out.append(
                _attr_name_edit(n.func, new_attr, "R-SEC-103", f"استُبدلت {attr} بـ {new_attr}")
            )
        elif attr == "load":
            if len(n.args) >= 2:
                # وسيط Loader موضعي: تغيير الاسم يكسر توقيع safe_load ⇒ يدوي
                continue
            kw_loader = next((k for k in n.keywords if k.arg == "Loader"), None)
            if kw_loader is not None and loader_ok_text(kw_loader.value):
                continue  # آمن أصلًا — لن تكون مرسومة أصلًا
            out.append(
                _attr_name_edit(
                    n.func, "safe_load", "R-SEC-103", "استُبدل yaml.load بـ yaml.safe_load"
                )
            )
            if kw_loader is not None:
                edit = _kw_removal_edit(
                    n, kw_loader, "R-SEC-103", "حُذف وسيط Loader غير الآمن", ctx.src
                )
                if edit is not None:
                    out.append(edit)
    return out


def _fix_weak_hash(ctx: FixContext) -> list[Edit]:
    """R-SEC-106: hashlib.md5/sha1 ⇒ sha256."""
    out: list[Edit] = []
    for n in ast.walk(ctx.tree):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("md5", "sha1")
            and _name_of(n.func.value) == "hashlib"
        ):
            out.append(
                _attr_name_edit(n.func, "sha256", "R-SEC-106", f"استُبدلت {n.func.attr} بـ sha256")
            )
    return out


def _fix_tls_verify(ctx: FixContext) -> list[Edit]:
    """R-SEC-107: تعطيل التحقق من الشهادات ⇒ تفعيله (حذف الوسيط أو ردّ القيمة)."""
    out: list[Edit] = []
    for n in ast.walk(ctx.tree):
        if isinstance(n, ast.Call):
            for kw in n.keywords:
                if not (
                    kw.arg == "verify"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is False
                ):
                    continue
                edit = _kw_removal_edit(
                    n, kw, "R-SEC-107", "حُذف verify=False وعاد التحقق مفعّلًا", ctx.src
                )
                if edit is not None:
                    out.append(edit)
        elif isinstance(n, ast.Assign) and n.targets and isinstance(n.targets[0], ast.Attribute):
            t = n.targets[0]
            if (
                t.attr in ("verify", "check_hostname")
                and isinstance(n.value, ast.Constant)
                and n.value.value is False
            ):
                out.append(_edit_span(n.value, "True", "R-SEC-107", "رُدّت قيمة التحقق إلى True"))
    return out


def _fix_docstring(ctx: FixContext) -> list[Edit]:
    """R-QLT-204: إدراج docstring عربي أولي للدوال والفئات العامة."""
    out: list[Edit] = []
    for n in ast.walk(ctx.tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if n.name.startswith("_"):
            continue
        if n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
            continue
        body0 = n.body[0] if n.body else None
        if body0 is None:
            continue
        ind = indent_of(ctx.src.line_text(body0.lineno))
        if isinstance(n, ast.ClassDef):
            doc = f'"""الفئة {n.name}: أضف وصفًا عربيًا للمسؤولية والسلوك."""'
        else:
            doc = f'"""دالة {n.name}: أضف وصفًا عربيًا للغرض والوسائط والقيمة المرجعة."""'
        if body0.lineno == n.lineno:
            # دالة بسطر واحد: نستبدل فراغ ما بعد النقطتين بكتلة (توثيق + إزاحة)
            # فتعود بقيّة السطر مزاحةً بشكل سليم على سطر مستقل
            line_text = ctx.src.line_text(body0.lineno)
            char_start = SourceText.char_col(line_text, body0.col_offset)
            scan = char_start - 1
            while scan >= 0 and line_text[scan] in " \t":
                scan -= 1
            if scan >= 0 and line_text[scan] == ":":
                byte_after_colon = len(line_text[: scan + 1].encode("utf-8"))
                out.append(
                    Edit(
                        body0.lineno,
                        byte_after_colon,
                        body0.lineno,
                        body0.col_offset,
                        f"\n{ind}    {doc}\n{ind}    ",
                        "R-QLT-204",
                        "أُدرج docstring عربي أولي",
                    )
                )
            else:
                # صياغة غير متوقعة ⇒ الإدراج قبل الجسم كما هو (بآخر فراغها)
                out.append(
                    Edit(
                        body0.lineno,
                        body0.col_offset,
                        body0.lineno,
                        body0.col_offset,
                        f"\n{ind}    {doc}\n{ind}    ",
                        "R-QLT-204",
                        "أُدرج docstring عربي أولي",
                    )
                )
        else:
            out.append(
                Edit(
                    body0.lineno,
                    0,
                    body0.lineno,
                    0,
                    f"{ind}{doc}\n",
                    "R-QLT-204",
                    "أُدرج docstring عربي أولي",
                )
            )
    return out


def _fix_none_compare(ctx: FixContext) -> list[Edit]:
    """R-QLT-206: == None / != None ⇒ is / is not.

    عقد المعاملات (ast.Eq/NotEq) لا تحمل مواقع في AST — نحدد موضع
    المعامل بالبحث الحتمي في «الفجوة» بين نهاية المعامل وبداية ما بعده،
    ثم نستبدل الفجوة كاملةً بـ « repl » بمسافاتها.
    """
    out: list[Edit] = []
    st = ctx.src
    for n in ast.walk(ctx.tree):
        if not isinstance(n, ast.Compare):
            continue
        if not any(isinstance(op, (ast.Eq, ast.NotEq)) for op in n.ops):
            continue
        operands = [n.left, *n.comparators]
        if not any(_is_none_const(o) for o in operands):
            continue
        for i, op in enumerate(n.ops):
            if not isinstance(op, (ast.Eq, ast.NotEq)):
                continue
            left = operands[i]
            right = operands[i + 1]
            touches_none = _is_none_const(right) or (i == 0 and _is_none_const(left))
            if not touches_none:
                continue
            # الفجوة بين نهاية المعامل الأيسر وبداية الأيمن
            gap = st.segment(left.end_lineno, left.end_col_offset, right.lineno, right.col_offset)
            m = re.search(r"==|!=", gap)
            if not m or "#" in gap:
                continue  # تعليق داخل الفجوة أو صياغة غير متوقعة ⇒ تبقى يدوية
            # نحوّل إزاحة المطابقة الحرفية داخل الفجوة إلى (سطر، عمود بايت)
            offset = m.start()
            line = left.end_lineno
            on_first_line = True
            for ln_text in gap.split("\n"):
                seg_len = len(ln_text) + 1
                if offset < seg_len:
                    base = left.end_col_offset if on_first_line else 0
                    byte_col = base + len(ln_text[:offset].encode("utf-8"))
                    break
                offset -= seg_len
                line += 1
                on_first_line = False
            else:  # pragma: no cover — لا يُبلغ حسابيًا
                continue
            match_len = len(m.group(0))
            replacement = "is" if isinstance(op, ast.Eq) else "is not"
            out.append(
                Edit(
                    line,
                    byte_col,
                    line,
                    byte_col + match_len,
                    replacement,
                    "R-QLT-206",
                    "استُخدمت مقارنة الهوية is/is not مع None",
                )
            )
    return out


def _fix_unused_import(ctx: FixContext) -> list[Edit]:
    """R-QLT-207: حذف الاستيراد الميت — بنفس منطق كشف المراجع حرفيًا."""
    base_name = ctx.path.replace("\\", "/").rsplit("/", 1)[-1]
    if base_name == "__init__.py":
        return []  # ملفات الحزم تعيد التصدير عمدًا ⇒ لا حذف آليًا إطلاقًا
    tree = ctx.tree
    used: set[str] = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            used.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", n.value))
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
    out: list[Edit] = []
    for stmt in tree.body:
        if not isinstance(stmt, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__":
            continue
        for alias in stmt.names:
            if alias.name == "*":
                continue
            bound = alias.asname or alias.name.split(".")[0]
            if bound in ("_", "annotations") or bound in exported or bound in used:
                continue
            if len(stmt.names) == 1:
                if not _tail_of_line_clear(ctx.src, stmt):
                    continue
                out.append(
                    Edit(
                        stmt.lineno,
                        0,
                        stmt.end_lineno + 1,  # +1 لبلع سطر جديد العبارة المحذوفة
                        0,
                        "",
                        "R-QLT-207",
                        f"حُذف استيراد {bound} غير المستخدم",
                    )
                )
            else:
                idx = stmt.names.index(alias)
                if idx + 1 < len(stmt.names):
                    nxt = stmt.names[idx + 1]
                    seg = ctx.src.segment(
                        alias.lineno, alias.col_offset, nxt.lineno, nxt.col_offset
                    )
                    if _has_hash(seg):
                        continue
                    out.append(
                        Edit(
                            alias.lineno,
                            alias.col_offset,
                            nxt.lineno,
                            nxt.col_offset,
                            "",
                            "R-QLT-207",
                            f"حُذف استيراد {bound} غير المستخدم من قائمة متعددة",
                        )
                    )
                else:
                    p = stmt.names[idx - 1]
                    seg = ctx.src.segment(
                        p.end_lineno, p.end_col_offset, alias.end_lineno, alias.end_col_offset
                    )
                    if _has_hash(seg):
                        continue
                    out.append(
                        Edit(
                            p.end_lineno,
                            p.end_col_offset,
                            alias.end_lineno,
                            alias.end_col_offset,
                            "",
                            "R-QLT-207",
                            f"حُذف استيراد {bound} غير المستخدم من قائمة متعددة",
                        )
                    )
    return out


def _fix_lambda_assign(ctx: FixContext) -> list[Edit]:
    """R-QLT-209: `name = lambda …` ⇒ `def name(…): return …` مكافئة."""
    out: list[Edit] = []
    for n in ast.walk(ctx.tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Lambda):
            names = [t for t in n.targets if isinstance(t, ast.Name)]
            if len(names) != 1 or len(n.targets) != 1:
                continue  # إسناد متعدد الأهداف ⇒ نرفض احتياطًا
            _emit_def(ctx, out, n, names[0].id, n.value)
        elif (
            isinstance(n, ast.AnnAssign)
            and isinstance(n.value, ast.Lambda)
            and isinstance(n.target, ast.Name)
        ):
            _emit_def(ctx, out, n, n.target.id, n.value)
    return out


def _split_lambda_head(head: str) -> str | None:
    """يستخرج نص الوسائط من مقطع رأس اللامدا (بين كلمة lambda وبداية الجسم).

    نقطتا args:body هي آخر «:» عند عمق أقواس صفر وخارج النصوص الحرفية —
    حتمية تمامًا وتتحمل الأقواس التجميعية المتعددة والقيم الافتراضية المعقدة.
    ترجع None إذا لم توجد نقطتان صالحتان.
    """
    depth = 0
    quote: str | None = None
    colon_idx = -1
    i = 0
    while i < len(head):
        ch = head[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == ":" and depth == 0:
            colon_idx = i
        i += 1
    if colon_idx < 0:
        return None
    return head[:colon_idx].strip()


def _emit_def(ctx: FixContext, out: list[Edit], stmt: ast.stmt, name: str, lam: ast.Lambda) -> None:
    if not _tail_of_line_clear(ctx.src, stmt):
        return
    st = ctx.src
    whole = st.segment(stmt.lineno, stmt.col_offset, stmt.end_lineno, stmt.end_col_offset)
    if _has_hash(whole):
        return
    # رأس اللامدا: ما بين كلمة lambda وبداية الجسم — قد يتجاوز أقواس تجميع
    # وأسطرًا لأن مواقع AST تشير إلى داخل الأقواس لا إليها
    kw_end_col = lam.col_offset + len("lambda")  # كلمة ASCII فالبايت حرف
    head = st.segment(lam.lineno, kw_end_col, lam.body.lineno, lam.body.col_offset)
    args_src = _split_lambda_head(head)
    if args_src is None:
        return  # لا نقطتين فاصلتين صالحتين (تعليق غريب مثلًا) ⇒ تبقى يدوية
    body_src = st.segment(
        lam.body.lineno, lam.body.col_offset, lam.body.end_lineno, lam.body.end_col_offset
    )
    ind = indent_of(st.line_text(stmt.lineno))
    if "\n" in body_src:
        base_now = SourceText.char_col(st.line_text(lam.body.lineno), lam.body.col_offset)
        base_want = len(ind) + 4 + len("return ")
        body_src = shift_lines(body_src, base_want - base_now)
    replacement = f"{ind}def {name}({args_src}):\n{ind}    return {body_src}\n"
    out.append(
        Edit(
            stmt.lineno,
            0,
            stmt.end_lineno + 1,  # +1 لبلع سطر جديد العبارة المستبدلة
            0,
            replacement,
            "R-QLT-209",
            f"حُوّلت اللامدا {name} إلى دالة def مكافئة",
        )
    )


# ------------------------------------------------------------- السجل
FIX_PLANNERS: dict[str, Planner] = {
    "R-ERR-001": _fix_bare_except,
    "R-ERR-003": _fix_raise_from,
    "R-ERR-004": _fix_open_with,
    "R-ERR-005": _fix_shell_true,
    "R-ERR-006": _fix_mutable_default,
    "R-SEC-103": _fix_yaml,
    "R-SEC-106": _fix_weak_hash,
    "R-SEC-107": _fix_tls_verify,
    "R-QLT-204": _fix_docstring,
    "R-QLT-206": _fix_none_compare,
    "R-QLT-207": _fix_unused_import,
    "R-QLT-209": _fix_lambda_assign,
}

AUTO_FIXABLE: tuple[str, ...] = tuple(sorted(FIX_PLANNERS))

ACTION_AR: dict[str, str] = {
    "R-ERR-001": "استُبدلت except: العامة بـ except Exception: — الإصلاح المعياري؛ قلّص النوع لاحقًا يدويًا",
    "R-ERR-003": "أُضيف from للاستثناء المرفوع مع تسمية المعالج إن لم يكن مسمّى",
    "R-ERR-004": "وُضعت open داخل with ووُلّفت العبارات المعتمدة على المتغير",
    "R-ERR-005": "حُذف shell=True لأن الأمر قائمة وسائط أصلًا",
    "R-ERR-006": "عُوّضت القيمة الافتراضية المتحورة بـ None مع حراسة إنشاء داخلية",
    "R-SEC-103": "استُبدل التحميل غير الآمن بـ yaml.safe_load وحُذف Loader غير الآمن",
    "R-SEC-106": "استُبدلت الخوارزمية الضعيفة بـ sha256",
    "R-SEC-107": "عاد التحقق من الشهادات مفعّلًا",
    "R-QLT-204": "أُدرج docstring عربي أولي يوضح المطلوب توثيقه",
    "R-QLT-206": "استُخدمت مقارنة الهوية is/is not مع None",
    "R-QLT-207": "حُذف الاستيراد غير المستخدم بعد التحقق من النصوص و__all__",
    "R-QLT-209": "حُوّلت اللامدا إلى دالة def مكافئة",
}

MANUAL_RULES: tuple[str, ...] = (
    "R-ERR-002",
    "R-ERR-007",
    "R-ERR-008",
    "R-ERR-009",
    "R-ERR-010",
    "R-SEC-101",
    "R-SEC-102",
    "R-SEC-104",
    "R-SEC-105",
    "R-SEC-108",
    "R-SEC-109",
    "R-SEC-110",
    "R-SEC-111",
    "R-SEC-112",
    "R-SEC-113",
    "R-SEC-114",
    "R-SEC-115",
    "R-SEC-116",
    "R-SEC-117",
    "R-SEC-118",
    "R-SEC-119",
    "R-QLT-201",
    "R-QLT-202",
    "R-QLT-203",
    "R-QLT-205",
    "R-QLT-208",
)


def manual_reason_ar(rule_id: str) -> str:
    """سبب بقاء القاعدة يدوية — عربي صريح لكل قاعدة بلا استثناء."""
    reasons = {
        "R-ERR-002": "إثبات النية مطلوب: سجّل الخطأ أو أعد رفعه أو وثّق أن الصمت مقصود",
        "R-ERR-007": "استبدال assert بتحقق حقيقي يغيّر عقد الاستدعاء — قرار تصميمي",
        "R-ERR-008": "إخراج القيمة من finally يعيد ترتيب التحكم — يحتاج فهم التدفق",
        "R-ERR-009": "تضييق except Exception يتطلب معرفة الاستثناءات المتوقعة",
        "R-ERR-010": "التقاط BaseException غالبًا مقصود لسجْل ثم إعادة رفع — قرار يدوي",
        "R-SEC-101": "لا بديل آلي لتصميم eval/exec — أعد التصميم بجدول توجيه",
        "R-SEC-102": "استبدال pickle يتطلب اتفاقية تنسيق بديلة بين الطرفين",
        "R-SEC-104": "تحويل بناء الاستعلام إلى استعلامات معاملات يغيّر واجهة النداء",
        "R-SEC-105": "نقل السر إلى البيئة يتطلب تجهيز البيئة قبل التشغيل",
        "R-SEC-108": "إعادة تصميم os.system إلى subprocess.run بقائمة تتطلب تفكيك الأمر",
        "R-SEC-109": "تنظيف المسار مقابل جذر مسموح يتطلب قرارًا بنطاق الوصول المشروع",
        "R-SEC-110": "إزالة السياق غير الموثوق قد تكسر الشهادات الداخلية — راجع بيئة الشهادات",
        "R-SEC-111": "اختيار قيمة المهلة يتطلب معرفة زمن الاستجابة المتوقع للخدمة",
        "R-SEC-112": "تفعيل weights_only قد يكسر تحميل نقاط تفتيش ذات كائنات مخصصة",
        "R-SEC-113": "إزالة trust_remote_code توقف النماذج التي تتطلبه — قرار توريد يدوي",
        "R-SEC-114": "تفعيل autoescape قد يغيّر مخرجات القوالب المقصودة — راجع القالب",
        "R-SEC-115": "إزالة mark_safe قد تكسر إخراج HTML المقصود — راجع مسار المدخل",
        "R-SEC-116": "اختيار فلتر الاستخراج المناسب يتطلب فهم بنية الأرشيف المتوقع",
        "R-SEC-117": "الانتقال إلى tempfile يتطلب إعادة تصميم مسارات الملفات المستهلكة",
        "R-SEC-118": "تفكيك نص الأمر إلى قائمة يتطلب فهم بنية الإدخال المتوقعة",
        "R-SEC-119": "تحويل الاستعلام إلى معاملات يغيّر واجهة النداء بين الطبقات",
        "R-QLT-201": "تجزئة الدالة الطويلة قرار تصميمي يحتاج فهم المسؤوليات",
        "R-QLT-202": "طي التداخل العميق بإعادة هيكلة الفروع — قرار يدوي",
        "R-QLT-203": "تجميع المعاملات في dataclass يغيّر التوقيع العام للدالة",
        "R-QLT-205": "استنتاج الأنواع يحتاج فهم نطاقات القيم — لا يُخمَّن آليًا",
        "R-QLT-208": "إعادة تسمية متغير يظلّل مدمجًا تتطلب تحديث كل مواضع الاستخدام",
    }
    return reasons.get(rule_id, "لا مسار إصلاح آمن حتمي لهذه القاعدة — عالجها يدويًا")
