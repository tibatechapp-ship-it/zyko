"""zyko.coder.multiplan — محرك الترقيع متعدد الملفات: الخطة تُرفض إن تركت مرجعًا.

الفجوة الموثقة في EVAL بعد الجولة 8 كانت «العمق الوكيلي متعدد الملفات —
البنية جاهزة والناقص سياسة التخطيط متعدد الملفات فوق عقود
``patch_file``». هذه الوحدة هي السياسة، بروح zyko كلها: حتمية بالبايت،
عقود صلاحيات، رفض صادق بالعربية، وإيصال موقَّع ضد العبث.

الثلاثية الموثقة:
1. **الاستكشاف يرى بالشجرة لا بالنص**: مسح AST على كل ``*.py`` تحت
   الجذر (مسارات مرتبة، ملفات مسقوفة) يجمع تعريفات الرمز ومراجعه —
   ``ast.Name`` و``ast.Attribute`` والوسائط المسماة وأسماء الدوال
   والأصناف. النصوص والتعليقات **ليست مراجع** — إعادة التسمية بالشجرة
   لا تغلط في سلسلة تحمل الاسم نفسه.
2. **الخطة تُرفض إن تركت مرجعًا**: مُخطِّط إعادة التسمية يبني خطوة
   «كتابة كاملة» لكل ملف يعرفه، ويرفض كله عند: رمز بلا تعريف، تعريف
   في ملفين (غموض)، اسْتيراد بأسماء مستعارة يلتقط الاسم، استيراد من
   خارج الجذور (تعريف لا نملكه)، الاسم الجديد موجود أصلًا، أو ملف
   مرجعي فوق السقف — كل رفض عربي موثق لا صمت.
3. **التنفيذ صفقة تُرجَع عند أول خرق**: كل ملفات الهدف تُقرأ في
   الذاكرة **قبل** أي كتابة (فشل قراءة واحد يُسقط الخطة كاملة بلا
   نصف ترقيع)، ثم تُطبَّق الخطوات بالترتيب عبر ``patch_file`` (عقد +
   كتابة ذرية + حرس أسرار)، وكل ملف بايثون يُتحقق من صياغته من
   **القرص** لا من الذاكرة، وفشلٌ في أي خطوة يُرجع كل ما سبقها من
   الذاكرة نفسها — والفشل في الإرجاع نفسه يُعلن لا يُطمس.

الجراحة معرفية بالـ``tokenize`` لا بتعويض نصي: كل ``NAME`` يحمل
الاسم حرفيًا يُستبدل موقعه — يغطي التعريف والمرجع والوصول عبر
``attr`` والوسيطة المسماة — ولا يلمس سلسلة ولا تعليق، والترتيب
عكسي داخل السطر فيبقى الإزاحة صحيحة.

    from zyko.coder.multiplan import build_rename_plan, apply_plan
    from zyko.sandbox.contracts import PermissionContract

    contract = PermissionContract.for_roots(tmp, allow_patch=True)
    plan = build_rename_plan(tmp, contract, symbol="old_fn", new_name="new_fn")
    receipt = apply_plan(contract, plan)
    assert receipt.applied and not receipt.rolled_back

الإيصال حتمي بالبايت: مفاتيح مفرزة، مسارات posix نسبية، بلا أزمنة —
والسلسلة ``chain_sha256`` تُبنى فوق الخطوات مرتبة كما في كل عدّة.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import keyword
import os
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zyko.sandbox.contracts import PermissionContract, is_sensitive_file

__all__ = [
    "MAX_PLAN_FILES",
    "MAX_SCAN_FILES",
    "MultiFilePlan",
    "MultiFilePlanError",
    "MultiFileReceipt",
    "PlanStep",
    "ReferenceScan",
    "apply_plan",
    "build_rename_plan",
    "find_symbol_references",
    "rename_identifier_text",
]

MAX_SCAN_FILES = 400
"""سقف ملفات المسح — نفس سقف خريطة المستودع في ``zyko.reviewer``."""

MAX_PLAN_FILES = 64
"""سقف ملفات الخطة الواحدة — الرقعة الأكبر تُقسَّم يدويًا لا تُدفَع عمياء."""

MAX_SCAN_FILE_BYTES = 1_000_000
"""سقف بايتات الملف الواحد في المسح — الثقيل يُعلن متجاوَزًا لا يُقرأ صامتًا."""

_MAX_SYMBOL_LEN = 120


class MultiFilePlanError(ValueError):
    """رفض الخطة أو التنفيذ — يحمل كل المشاكل دفعة واحدة بالعربية."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        bullet = "\n  - ".join(self.problems)
        super().__init__(f"رُفض متعدد الملفات ({len(self.problems)} مشكلة):\n  - {bullet}")


def _sha256_text(text: str) -> str:
    """بصمة النص — sha256 بايتات UTF-8 لا الزمن."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _module_of(rel_posix: str) -> str | None:
    """اسم وحدة ملف من مساره النسبي — ``a/b.py`` ⇒ ``a.b`` و``a/__init__.py`` ⇒ ``a``."""
    if rel_posix.endswith("/__init__.py"):
        base = rel_posix[: -len("/__init__.py")]
        return base.replace("/", ".") or None
    if rel_posix.endswith(".py"):
        return rel_posix[: -len(".py")].replace("/", ".")
    return None


def _resolve_import_target(file_posix: str, node: ast.ImportFrom) -> str | None:
    """حسم هدف الاستيراد (المطلق والنسبي) إلى اسم وحدة — None إن خرج عن الحزمة."""
    if not node.level:
        return node.module or None
    parts = file_posix.split("/")[:-1]  # حزمة الملف المعرِّف
    if len(parts) < node.level:
        return None
    base = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
    prefix = "/".join(base)
    target = f"{prefix}/{node.module}" if node.module else prefix
    return target


# ------------------------------------------------------------------ المسح
@dataclass(frozen=True)
class ReferenceScan:
    """نتيجة مسح رمز واحد عبر المستودع — حتمية بالبايت ومسارات posix نسبية.

    ``definitions`` أزواج ``(مسار، سطر)`` للتعريفات، و``references`` لكل
    مرجع معرفي، و``import_refs`` لاستيرادات ``from m import sym``
    الداخلية، و``alias_bindings`` لكل استيراد يلتقط الاسم باسم مستعار
    (خطر غموض يرفضه المخطِّط)، و``external_imports`` لاستيرادات من
    خارج الجذور (تعريف لا نملكه). النصوص والتعليقات لا تدخل هنا أصلًا.
    """

    symbol: str
    root_posix: str
    definitions: tuple[tuple[str, int], ...]
    references: tuple[tuple[str, int], ...]
    import_refs: tuple[tuple[str, int], ...]
    alias_bindings: tuple[tuple[str, int], ...]
    external_imports: tuple[tuple[str, int], ...]
    files_scanned: int
    parse_failures: tuple[str, ...]
    skipped_sensitive: tuple[str, ...]
    skipped_oversized: tuple[str, ...]

    @property
    def touched_paths(self) -> tuple[str, ...]:
        """كل ملف يحمل تعريفًا أو مرجعًا أو استيرادًا — مرتبًا، أساس الخطة."""
        paths: set[str] = set()
        for p, _ in self.definitions + self.references + self.import_refs:
            paths.add(p)
        return tuple(sorted(paths))

    @property
    def definition_paths(self) -> tuple[str, ...]:
        """الملفات التي تعرّف الرمز — أكثر من واحد غموض مرفوض."""
        return tuple(sorted({p for p, _ in self.definitions}))

    def to_dict(self) -> dict[str, Any]:
        """ممثل JSON حتمي — مفاتيح مفرزة بلا أي زمن."""
        return {
            "alias_bindings": [[p, ln] for p, ln in self.alias_bindings],
            "definitions": [[p, ln] for p, ln in self.definitions],
            "external_imports": [[p, ln] for p, ln in self.external_imports],
            "files_scanned": int(self.files_scanned),
            "import_refs": [[p, ln] for p, ln in self.import_refs],
            "parse_failures": list(self.parse_failures),
            "references": [[p, ln] for p, ln in self.references],
            "root_posix": self.root_posix,
            "skipped_oversized": list(self.skipped_oversized),
            "skipped_sensitive": list(self.skipped_sensitive),
            "symbol": self.symbol,
        }

    def table_ar(self) -> str:
        """جدول عربي موجز للمسح — للتشخيص لا للاستهلاك الآلي."""
        return "\n".join(
            [
                f"مسح الرمز «{self.symbol}» تحت {self.root_posix}:",
                f"  الملفات الممسوحة: {self.files_scanned}",
                f"  التعريفات: {len(self.definitions)} — "
                + (", ".join(f"{p}:{ln}" for p, ln in self.definitions[:8]) or "لا شيء"),
                f"  المراجع: {len(self.references)} عبر {len(self.touched_paths)} ملفًا",
                f"  استيراد داخلي: {len(self.import_refs)} — "
                f"بأسماء مستعارة: {len(self.alias_bindings)} — خارجي: {len(self.external_imports)}",
                f"  تعذّر تحليله: {len(self.parse_failures)} — حساس مُتخطى: "
                f"{len(self.skipped_sensitive)} — متجاوَز: {len(self.skipped_oversized)}",
            ]
        )


def find_symbol_references(
    root: object,
    symbol: object,
    *,
    max_files: int = MAX_SCAN_FILES,
    max_file_bytes: int = MAX_SCAN_FILE_BYTES,
) -> ReferenceScan:
    """امسح كل ``*.py`` تحت الجذر عن تعريفات الرمز ومراجعه — AST حتمي.

    جولتان: الأولى تجمع الملفات وتحللها وتبني جدول الوحدات، والثانية
    تفرز التعريفات والمراجع والاستيراد بمعرفة الأسماء الداخلية. المسارات
    نسبية posix مرتبة، والملفات الحساسة لا تُقرأ أصلًا، وفشل التحليل
    يُعلن بالاسم لا يُطمس.
    """
    sym = str(symbol or "").strip()
    root_path = Path(str(root or "")).resolve()
    if not sym or len(sym) > _MAX_SYMBOL_LEN or not sym.isidentifier() or keyword.iskeyword(sym):
        raise MultiFilePlanError([f"الرمز الممسوح ليس معرفًا صالحًا — «{sym}»"])
    if not root_path.is_dir():
        raise MultiFilePlanError([f"الجذر ليس مجلدًا قائمًا — {root_path.as_posix()}"])

    candidates = sorted(root_path.rglob("*.py"), key=lambda p: p.as_posix())
    parsed: list[tuple[str, ast.Module]] = []
    parse_failures: list[str] = []
    skipped_sensitive: list[str] = []
    skipped_oversized: list[str] = []
    module_map: dict[str, str] = {}

    for path in candidates:
        rel = path.relative_to(root_path).as_posix()
        if is_sensitive_file(path) or is_sensitive_file(rel):
            skipped_sensitive.append(rel)
            continue
        if len(parsed) >= max_files:
            break
        try:
            if path.stat().st_size > max_file_bytes:
                skipped_oversized.append(rel)
                continue
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            parse_failures.append(rel)
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            parse_failures.append(rel)
            continue
        parsed.append((rel, tree))
        mod = _module_of(rel)
        if mod:
            module_map[mod] = rel

    definitions: list[tuple[str, int]] = []
    references: list[tuple[str, int]] = []
    import_refs: list[tuple[str, int]] = []
    alias_bindings: list[tuple[str, int]] = []
    external_imports: list[tuple[str, int]] = []
    # أهداف الإسناد المعرفية: تعريفات لا مراجع — تُستبعد من فرع الاسم
    assign_target_ids: set[int] = set()

    for rel, tree in parsed:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == sym:
                    definitions.append((rel, node.lineno))
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == sym:
                        definitions.append((rel, node.lineno))
                        assign_target_ids.add(id(target))
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == sym:
                    definitions.append((rel, node.lineno))
                    assign_target_ids.add(id(node.target))
            elif isinstance(node, ast.Name):
                if node.id == sym and id(node) not in assign_target_ids:
                    references.append((rel, node.lineno))
            elif isinstance(node, ast.Attribute):
                if node.attr == sym:
                    references.append((rel, node.lineno))
            elif isinstance(node, ast.keyword):
                if node.arg == sym:
                    references.append((rel, node.lineno))
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.asname == sym:
                        alias_bindings.append((rel, node.lineno))
                    elif not alias.asname and alias.name == sym:
                        if isinstance(node, ast.ImportFrom):
                            target = _resolve_import_target(rel, node)
                            if target is not None and _module_of(f"{target}.py") in module_map:
                                import_refs.append((rel, node.lineno))
                            else:
                                external_imports.append((rel, node.lineno))
                        # ``import sym`` بلا alias: استيراد وحدة باسم الرمز —
                        # يُعد مرجعًا معرفيًا لأن الاسم نفسه يتغير في الموقع
                        else:
                            import_refs.append((rel, node.lineno))

    return ReferenceScan(
        symbol=sym,
        root_posix=root_path.as_posix(),
        definitions=tuple(sorted(definitions)),
        references=tuple(sorted(references)),
        import_refs=tuple(sorted(import_refs)),
        alias_bindings=tuple(sorted(alias_bindings)),
        external_imports=tuple(sorted(external_imports)),
        files_scanned=len(parsed),
        parse_failures=tuple(sorted(parse_failures)),
        skipped_sensitive=tuple(sorted(skipped_sensitive)),
        skipped_oversized=tuple(sorted(skipped_oversized)),
    )


# ------------------------------------------------------------------ الجراحة
def rename_identifier_text(source: str, symbol: str, new_name: str) -> str:
    """استبدل كل معرف ``symbol`` في الكود بـ``new_name`` — بالـ``tokenize``.

    الوسيط السلسلة والتعليق لا يُلمسان — فقط معرفات الـ``NAME`` الحقيقية،
    بما فيها أسماء التعريف والوصول عبر ``attr`` والوسائط المسماة.
    ترتيب الاستبدال عكسي بالسطر فلا تنزاح الإزاحات.
    """
    spans: list[tuple[int, int, int]] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type == tokenize.NAME and tok.string == symbol:
                row, col = tok.start
                _, end_col = tok.end
                spans.append((row, col, end_col))
    except (tokenize.TokenError, IndentationError) as exc:
        raise MultiFilePlanError(
            [f"الجراحة تعذّرت: لا يُرمَّز النص رقعة آمنة — {type(exc).__name__}"]
        ) from exc
    lines = source.splitlines(keepends=True)
    for row, c0, c1 in sorted(spans, key=lambda t: (t[0], t[1]), reverse=True):
        line = lines[row - 1]
        lines[row - 1] = line[:c0] + new_name + line[c1:]
    return "".join(lines)


def _text_token_count(source: str, symbol: str) -> int:
    """عدد معرفات ``symbol`` في النص — لقياس التغطية بعد التنفيذ."""
    count = 0
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type == tokenize.NAME and tok.string == symbol:
                count += 1
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return -1
    return count


# ------------------------------------------------------------------ الخطة
@dataclass(frozen=True)
class PlanStep:
    """خطوة واحدة في خطة متعددة الملفات — كتابة كاملة أو استبدال وحيد.

    ``write`` تحمل ``content`` كاملًا (ناتج محسوب حتميًا)، و``replace``
    تحمل ``old_text``/``new_text`` بشرط التطابق الوحيد في عقد
    ``patch_file`` نفسه. ``purpose_ar`` سبب الخطوة بالعربية كما في
    كل الإيصالات.
    """

    path: str  # posix نسبي عن جذر العقد
    kind: str  # "write" أو "replace"
    content: str | None = None
    old_text: str | None = None
    new_text: str | None = None
    purpose_ar: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": self.kind,
            "path": self.path,
            "purpose_ar": self.purpose_ar,
        }
        if self.kind == "write":
            d["content_sha256"] = _sha256_text(self.content or "")
            d["content_bytes"] = len((self.content or "").encode("utf-8"))
        else:
            d["old_sha256"] = _sha256_text(self.old_text or "")
            d["new_sha256"] = _sha256_text(self.new_text or "")
        return d


@dataclass(frozen=True)
class MultiFilePlan:
    """خطة ترقيع متعددة الملفات — مرتبة، مسقوفة، ومتحقق منها قبل التنفيذ.

    البناء عبر ``MultiFilePlan.build(...)`` يتحقق ويُرفض دفعة واحدة،
    والبناء المباشر ممكن لمن يدفع خطة مدروسة — والتنفيذ يعيد
    التحقق قبل أي كتابة.
    """

    goal_ar: str
    kind: str  # "rename" أو "custom"
    steps: tuple[PlanStep, ...]
    symbol: str = ""
    new_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_ar": self.goal_ar,
            "kind": self.kind,
            "steps": [s.to_dict() for s in self.steps],
            "symbol": self.symbol,
            "new_name": self.new_name,
        }

    def to_json(self) -> str:
        """JSON حتمي بالبايت — للمقارنة والتخزين."""
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=1)

    # ------------------------------------------------------- التحقق
    def validate(self, contract: PermissionContract | None = None) -> list[str]:
        """كل مشاكل الخطة دفعة واحدة بالعربية — قائمة فارغة تعني صالحة."""
        problems: list[str] = []
        if not self.steps:
            problems.append("الخطة بلا خطوات — لا ترقيع فارغ")
            return problems
        if len(self.steps) > MAX_PLAN_FILES:
            problems.append(
                f"الخطة فوق سقف الملفات ({len(self.steps)} > {MAX_PLAN_FILES}) — "
                "قسّمها إلى خطط مسقوفة"
            )
        seen_paths: set[str] = set()
        for i, step in enumerate(self.steps, start=1):
            path = str(step.path or "").strip()
            if not path:
                problems.append(f"الخطوة {i}: مسار فارغ")
                continue
            if path in seen_paths:
                problems.append(
                    f"الخطوة {i}: المسار {path} يتكرر في الخطة — ملف واحد يُكتب مرة واحدة"
                )
            seen_paths.add(path)
            if step.kind == "write":
                if step.content is None:
                    problems.append(f"الخطوة {i} ({path}): كتابة بلا محتوى")
                elif path.endswith(".py"):
                    try:
                        ast.parse(step.content)
                    except SyntaxError as exc:
                        problems.append(
                            f"الخطوة {i} ({path}): محتوى بايثون مكسور الصياغة — "
                            f"{type(exc).__name__} سطر {exc.lineno}"
                        )
            elif step.kind == "replace":
                if step.old_text is None or not str(step.old_text):
                    problems.append(f"الخطوة {i} ({path}): استبدال بلا old_text")
                if step.new_text is None:
                    problems.append(f"الخطوة {i} ({path}): استبدال بلا new_text")
            else:
                problems.append(
                    f"الخطوة {i} ({path}): نوع مجهول «{step.kind}» — النوعان write وreplace فقط"
                )
            if contract is not None and path:
                target, reason = contract.check_path(path)
                if target is None:
                    problems.append(f"الخطوة {i} ({path}): حارس المسار يرفض — {reason}")
                elif is_sensitive_file(target):
                    problems.append(f"الخطوة {i} ({path}): مخزن اعتماد حساس — لا رقعة على الأسرار")
        return problems


# ------------------------------------------------------------- المخطِّط
def build_rename_plan(
    root: object,
    contract: PermissionContract,
    *,
    symbol: str,
    new_name: str,
    max_files: int = MAX_SCAN_FILES,
) -> tuple[MultiFilePlan, ReferenceScan]:
    """ابنِ خطة إعادة تسمية كاملة التغطية — أو ارفض كها بالعربية.

    يفحص الاسم الجديد والقديم، يمسح المراجع، يرفض الغموض (تعريف في
    ملفين، اسم مستعار يلتقط الرمز، استيراد خارجي، تعارض الاسم الجديد)،
    ثم يحسب محتوى كل ملف بالجراحة المعرفية ويبني خطوة كتابة لكل ملف.
    يعيد ``(الخطة، المسح)`` — والمسح معاد للإيصال والتوثيق.
    """
    sym = str(symbol or "").strip()
    new = str(new_name or "").strip()
    problems: list[str] = []

    if not sym or len(sym) > _MAX_SYMBOL_LEN or not sym.isidentifier() or keyword.iskeyword(sym):
        problems.append(f"الرمز القديم ليس معرفًا صالحًا — «{sym}»")
    if not new or len(new) > _MAX_SYMBOL_LEN or not new.isidentifier() or keyword.iskeyword(new):
        problems.append(f"الاسم الجديد ليس معرفًا صالحًا — «{new}»")
    if problems:
        raise MultiFilePlanError(problems)
    if sym == new:
        raise MultiFilePlanError(["الاسم الجديد مطابق للقديم — لا ترقيع بلا تغيير"])
    if not contract.allow_patch:
        raise MultiFilePlanError(["العقد لا يفعّل الكتابة (patch) — عقد قراءة فقط"])

    scan = find_symbol_references(root, sym, max_files=max_files)
    if scan.parse_failures:
        problems.append(
            f"ملفات لا تُحلل صياغتها فلا تُضمن تغطيتها: "
            f"{', '.join(scan.parse_failures[:5])} — أصلح الصياغة أولًا"
        )
    if not scan.definitions:
        problems.append(f"الرمز «{sym}» بلا تعريف تحت الجذر — لا تعيد تسمية ما لا يوجد")
    if len(scan.definition_paths) > 1:
        problems.append(
            f"الرمز معرَّف في {len(scan.definition_paths)} ملفات "
            f"({', '.join(scan.definition_paths)}) — الغموض مرفوض، حدّد التعريف الأصل"
        )
    if scan.alias_bindings:
        problems.append(
            f"استيراد بأسماء مستعارة يلتقط الاسم في {len(scan.alias_bindings)} موقع — "
            "الالتقاط بالـalias يكسر التمييز بين تعريف ومرجع، رفض صادق"
        )
    if scan.external_imports:
        problems.append(
            f"الرمز مستورد من خارج الجذور في {len(scan.external_imports)} موقع — "
            "تعريف لا نملكه لا يُعاد تسميته"
        )
    if scan.skipped_oversized:
        problems.append(
            f"ملفات مرجعية فوق سقف المسح: {', '.join(scan.skipped_oversized[:5])} — "
            "تغطية ناقصة رفض لا تجاهل"
        )
    if problems:
        raise MultiFilePlanError(problems)

    touched = scan.touched_paths
    if len(touched) > MAX_PLAN_FILES:
        raise MultiFilePlanError(
            [
                f"الخطة تغطي {len(touched)} ملفات فوق السقف {MAX_PLAN_FILES} — "
                "قسّم إعادة التسمية إلى دفعات مسقوفة"
            ]
        )

    # تعارض الاسم الجديد: إن ظهر معرفًا أو اسْتُقِط باسم مستعار في أي
    # ملف مسموع فالخطة تخلط بين رمزين — رفض قبل أي حساب محتوى
    new_scan = find_symbol_references(root, new, max_files=max_files)
    new_hits = (
        new_scan.definitions + new_scan.references + new_scan.import_refs + new_scan.alias_bindings
    )
    if new_hits:
        where = sorted({p for p, _ in new_hits})
        raise MultiFilePlanError(
            [
                f"الاسم الجديد «{new}» مستخدم أصلًا في {len(where)} ملفات "
                f"({', '.join(where[:5])}) — الخلط بين رمزين رفض"
            ]
        )

    root_path = Path(scan.root_posix)
    steps: list[PlanStep] = []
    for rel in touched:
        try:
            source = (root_path / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise MultiFilePlanError(
                [f"قراءة {rel} فشلت بعد المسح ({type(exc).__name__}) — الخطة تُرفض لا تُخمَّن"]
            ) from exc
        updated = rename_identifier_text(source, sym, new)
        if updated == source:
            raise MultiFilePlanError(
                [f"الجراحة لم تغيّر {rel} رغم مراجعه — علة جلخة رفض قبل الكتابة"]
            )
        steps.append(
            PlanStep(
                path=rel,
                kind="write",
                content=updated,
                purpose_ar=f"إعادة تسمية «{sym}» إلى «{new}» — {rel}",
            )
        )
    plan = MultiFilePlan(
        goal_ar=f"إعادة تسمية الرمز «{sym}» إلى «{new}» عبر {len(steps)} ملفات بتغطية كاملة",
        kind="rename",
        steps=tuple(steps),
        symbol=sym,
        new_name=new,
    )
    remaining = plan.validate(contract)
    if remaining:
        raise MultiFilePlanError(remaining)
    return plan, scan


# ------------------------------------------------------------------ التنفيذ
@dataclass(frozen=True)
class MultiFileReceipt:
    """إيصال تنفيذ خطة متعددة الملفات — حتمي بالبايت وموقَّع بسلسلة."""

    goal_ar: str
    kind: str
    applied: bool
    ok: bool
    rolled_back: bool = False
    steps_results: tuple[dict[str, Any], ...] = ()
    restored_paths: tuple[str, ...] = ()
    restore_failures: tuple[str, ...] = ()
    syntax_verified: bool = False
    syntax_failures: tuple[str, ...] = ()
    coverage_ok: bool = False
    coverage_detail: dict[str, Any] = field(default_factory=dict)
    files_touched: int = 0
    reason_ar: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": bool(self.applied),
            "coverage_detail": self.coverage_detail,
            "coverage_ok": bool(self.coverage_ok),
            "files_touched": int(self.files_touched),
            "goal_ar": self.goal_ar,
            "kind": self.kind,
            "ok": bool(self.ok),
            "reason_ar": self.reason_ar,
            "restore_failures": list(self.restore_failures),
            "restored_paths": list(self.restored_paths),
            "rolled_back": bool(self.rolled_back),
            "steps_results": [dict(s) for s in self.steps_results],
            "syntax_failures": list(self.syntax_failures),
            "syntax_verified": bool(self.syntax_verified),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=1)

    @property
    def chain_sha256(self) -> str:
        """بصمة السلسلة: sha256 فوق JSON المفرز — حتمية بالبايت."""
        return _sha256_text(self.to_json())


def apply_plan(
    contract: PermissionContract,
    plan: MultiFilePlan,
    *,
    root: object | None = None,
    verify_syntax: bool = True,
    verify_coverage: bool = True,
    max_files: int = MAX_SCAN_FILES,
) -> MultiFileReceipt:
    """نفّذ الخطة كصفقة واحدة — أو ارفض أو ارجع، بلا نصف ترقيع أبديًا.

    المراحل بالترتيب: تحقق ساكن (عقد + حساس + صياغة)، لقطة كل الملفات
    في الذاكرة، تطبيق خطوة خطوة عبر ``patch_file``، تحقق صياغة من
    القرص، تحقق تغطية (لمسحٍ جديد لا يجد الرمز القديم ولا يفقد الجديد)،
    وعند أول خرق بعد اللقطة: إرجاع حتمي لكل ما طُبّق.
    """
    from zyko.sandbox.patcher import patch_file

    def _fail(
        reason: str,
        *,
        steps_results: tuple[dict, ...] = (),
        applied: bool = False,
        rolled_back: bool = False,
        restored: tuple[str, ...] = (),
        restore_failures: tuple[str, ...] = (),
        syntax_verified: bool = False,
        syntax_failures: tuple[str, ...] = (),
        coverage_ok: bool = False,
        coverage_detail: dict | None = None,
    ) -> MultiFileReceipt:
        return MultiFileReceipt(
            goal_ar=plan.goal_ar,
            kind=plan.kind,
            applied=applied,
            ok=False,
            rolled_back=rolled_back,
            steps_results=steps_results,
            restored_paths=restored,
            restore_failures=restore_failures,
            syntax_verified=syntax_verified,
            syntax_failures=syntax_failures,
            coverage_ok=coverage_ok,
            coverage_detail=coverage_detail or {},
            files_touched=len({s["path"] for s in steps_results if s.get("ok")}),
            reason_ar=reason,
        )

    # 1) التحقق الساكن — بلا كتابة قبل اجتيازه
    problems: list[str] = []
    if not contract.allow_patch:
        problems.append("العقد لا يفعّل الكتابة (patch) — عقد قراءة فقط")
    problems.extend(plan.validate(contract))
    if problems:
        return _fail("رُفضت الخطة ساكنًا: " + "؛ ".join(problems[:4]))

    root_path = Path(str(root or "")).resolve() if root else None
    if root_path is None:
        # جذر الاستنتاج: أول مسار تمرّه حارسة العقد يحدد الجذر العملي
        probe_target, probe_reason = contract.check_path(plan.steps[0].path)
        if probe_target is None:
            return _fail(f"لا جذر معلن وأول مسار لا يجتاز العقد — {probe_reason}")
        root_path = probe_target.parent
        for step in plan.steps[1:]:
            t, r = contract.check_path(step.path)
            if t is None:
                return _fail(f"مسار الخطة خارج العقد ({step.path}) — {r}")
            cand = _common_root(root_path, t)
            if cand is None:
                return _fail(
                    f"مسارات الخطة لا تجتمع تحت جذر واحد للتحقق ({plan.steps[0].path} و{step.path})"
                )
            root_path = cand
    if not root_path.is_dir():
        return _fail(f"الجذر ليس مجلدًا قائمًا — {root_path.as_posix()}")

    # 2) اللقطة — كل الملفات تُقرأ قبل أي كتابة (الصفقة تبدأ هنا)
    snapshot: dict[str, str] = {}
    for step in plan.steps:
        target, reason = contract.check_path(step.path)
        if target is None:
            return _fail(f"لقطة: حارس المسار رفض {step.path} — {reason}")
        if step.kind == "replace" or target.is_file():
            try:
                if target.stat().st_size > contract.max_file_bytes:
                    return _fail(f"لقطة: {step.path} فوق سقف العقد — رفض الصفقة كاملة قبل أي كتابة")
                snapshot[step.path] = target.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                return _fail(
                    f"لقطة: قراءة {step.path} فشلت ({type(exc).__name__}) — "
                    "الصفقة تُرفض كاملة لا نصف ترقيع"
                )
        else:
            snapshot[step.path] = ""

    # 3) التطبيق خطوة خطوة عبر patch_file — كل رفض خطوة يوقظ الإرجاع
    steps_results: list[dict[str, Any]] = []
    applied_paths: list[str] = []
    for i, step in enumerate(plan.steps, start=1):
        result = patch_file(
            contract,
            path=step.path,
            content=step.content if step.kind == "write" else None,
            old_text=step.old_text if step.kind == "replace" else None,
            new_text=step.new_text if step.kind == "replace" else None,
        )
        entry = dict(result.to_dict())
        entry["step_index"] = i
        entry["purpose_ar"] = step.purpose_ar
        steps_results.append(entry)
        if not result.ok:
            return _rollback(
                contract,
                snapshot,
                applied_paths,
                steps_results,
                _fail,
                f"الخطوة {i} رُفضت: {result.reason_ar}",
            )
        applied_paths.append(step.path)

    # 4) تحقق الصياغة من القرص لا من الذاكرة
    syntax_failures: list[str] = []
    if verify_syntax:
        for step in plan.steps:
            if not step.path.endswith(".py"):
                continue
            target, _ = contract.check_path(step.path)
            if target is None:
                continue
            try:
                ast.parse(target.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, SyntaxError) as exc:
                syntax_failures.append(
                    f"{step.path}: {type(exc).__name__}"
                    + (f" سطر {getattr(exc, 'lineno', '')}" if isinstance(exc, SyntaxError) else "")
                )
        if syntax_failures:
            return _rollback(
                contract,
                snapshot,
                applied_paths,
                steps_results,
                _fail,
                "صياغة مكسورة بعد التنفيذ: " + "؛ ".join(syntax_failures[:3]),
                syntax_failures=tuple(syntax_failures),
            )

    # 5) تحقق التغطية — مسح جديد لا يرى القديم ولا يفقد الجديد
    coverage_detail: dict[str, Any] = {}
    coverage_ok = False  # لا تغطية معلنة قبل أن تُقاس فعلاً
    if verify_coverage and plan.kind == "rename" and plan.symbol and plan.new_name:
        try:
            old_after = find_symbol_references(root_path, plan.symbol, max_files=max_files)
            new_after = find_symbol_references(root_path, plan.new_name, max_files=max_files)
        except MultiFilePlanError as exc:
            return _rollback(
                contract,
                snapshot,
                applied_paths,
                steps_results,
                _fail,
                f"مسح التغطية فشل: {exc}",
            )
        old_left = (
            len(old_after.definitions) + len(old_after.references) + len(old_after.import_refs)
        )
        new_count = (
            len(new_after.definitions) + len(new_after.references) + len(new_after.import_refs)
        )
        coverage_detail = {
            "old_left": int(old_left),
            "new_count": int(new_count),
            "new_name": plan.new_name,
            "old_symbol": plan.symbol,
        }
        # العقد: القديم لا يترك أثرًا والجديد حيّ بحسابه المعروف
        coverage_ok = old_left == 0 and new_count > 0
        if old_left:
            coverage_detail["leftover"] = [
                [p, ln] for p, ln in (old_after.definitions + old_after.references)[:8]
            ]
        if new_count == 0:
            coverage_detail["empty_new"] = True
        if not coverage_ok:
            return _rollback(
                contract,
                snapshot,
                applied_paths,
                steps_results,
                _fail,
                f"التغطية ناقصة: بقي {old_left} مرجعًا للرمز القديم — الخطة التي تركت مرجعًا تُرجع",
                coverage_ok=False,
                coverage_detail=coverage_detail,
            )

    return MultiFileReceipt(
        goal_ar=plan.goal_ar,
        kind=plan.kind,
        applied=True,
        ok=True,
        rolled_back=False,
        steps_results=tuple(steps_results),
        syntax_verified=verify_syntax and not syntax_failures,
        coverage_ok=coverage_ok,
        coverage_detail=coverage_detail,
        files_touched=len(applied_paths),
        reason_ar=(
            f"صفقة مكتملة — {len(applied_paths)} ملفات، صياغة موثقة، تغطية كاملة"
            if coverage_ok
            else f"صفقة مكتملة — {len(applied_paths)} ملفات (بلا تحقق تغطية)"
        ),
    )


def _rollback(
    contract: PermissionContract,
    snapshot: dict[str, str],
    applied_paths: list[str],
    steps_results: list[dict[str, Any]],
    fail_factory,
    reason: str,
    **extra: Any,
) -> MultiFileReceipt:
    """أرجع كل ما طُبّق من لقطة الذاكرة — والفشل في الإرجاع نفسه يُعلن."""
    from zyko.sandbox.patcher import patch_file

    restored: list[str] = []
    restore_failures: list[str] = []
    for rel in applied_paths:
        target, _ = contract.check_path(rel)
        if target is None:
            restore_failures.append(f"{rel}: المسار خرج عن العقد وقت الإرجاع")
            continue
        result = patch_file(contract, path=rel, content=snapshot.get(rel, ""))
        if result.ok:
            restored.append(rel)
        else:
            restore_failures.append(f"{rel}: {result.reason_ar}")
    return fail_factory(
        reason + (f" — أُرجع {len(restored)} ملفات" if restored else ""),
        steps_results=tuple(steps_results),
        applied=True,
        rolled_back=True,
        restored=tuple(restored),
        restore_failures=tuple(restore_failures),
        **extra,
    )


def _common_root(a: Path, b: Path) -> Path | None:
    """أقرب جذر مشترك بين مسارين — None إن لم يجتمع."""
    try:
        a.relative_to(b)
        return b
    except ValueError:
        pass
    try:
        b.relative_to(a)
        return a
    except ValueError:
        pass
    try:
        return Path(os.path.commonpath([str(a), str(b)]))
    except ValueError:
        return None


def _cli_main(argv: list[str] | None = None) -> int:
    """سطر الأوامر: ``scan`` يطبع جدول المسح، و``rename --check`` يجرب الخطة.

    التنفيذ الفعلي (``--apply``) API فقط لا سطر أوامر — الكتابة عبر
    الحدود تمر بعقد صريح من الكود المستدعي لا من علم سطر الأوامر.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m zyko.coder.multiplan",
        description="محرك الترقيع متعدد الملفات — المسح والخطة بلا كتابة",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_scan = sub.add_parser("scan", help="امسح رمزًا عبر الجذر — تعريفات ومراجع")
    p_scan.add_argument("--root", required=True)
    p_scan.add_argument("--symbol", required=True)
    p_plan = sub.add_parser("rename", help="ابنِ خطة إعادة تسمية واعرضها بلا كتابة")
    p_plan.add_argument("--root", required=True)
    p_plan.add_argument("--symbol", required=True)
    p_plan.add_argument("--new-name", required=True)
    args = parser.parse_args(argv)
    root = str(Path(args.root).resolve())
    # بناء الخطة يقرأ فقط ولا يكتب بايتًا — لكن عقدَه يطلب allow_patch
    # لإعلان النية؛ التنفيذ عبر apply_plan لا يُستدعى من هنا أبدًا
    contract = PermissionContract.for_roots(root, allow_patch=True)
    if args.command == "scan":
        try:
            scan = find_symbol_references(root, args.symbol)
        except MultiFilePlanError as exc:
            print(f"رفض المسح: {exc.problems[0]}")
            return 1
        print(scan.table_ar())
        return 0
    try:
        plan, scan = build_rename_plan(root, contract, symbol=args.symbol, new_name=args.new_name)
    except MultiFilePlanError as exc:
        print(f"رُفضت الخطة ({len(exc.problems)} مشكلة):")
        for problem in exc.problems:
            print(f"  - {problem}")
        return 1
    print(scan.table_ar())
    print(f"\nالخطة ({len(plan.steps)} خطوات، بلا كتابة — --apply عبر API فقط):")
    for step in plan.steps:
        print(f"  {step.path} — {step.purpose_ar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli_main())
