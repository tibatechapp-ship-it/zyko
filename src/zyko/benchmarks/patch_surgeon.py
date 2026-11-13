"""zyko.benchmarks.patch_surgeon — الجرّاح الصياغي: تشخيص محلي وتطبيق متسامح (الموجة 20).

درس العينة الواسعة الموثق بالبايت (``docs/SWEBENCH_FULL_2026-11-13.md`` §5):
**19 حالة من 44 بلا رقعة مطبقة** — `git apply` رفض ولم يعرف العقل لماذا
بالتفصيل، والدرس الصياغي للجولتين 9 و11 لم يكتمل على العينة الواسعة.
هذه الوحدة تعالجه بثلاثة عقود معلنة:

1. **فحص صياغي محلي قبل ``git apply``**: ترويسات الملفات وعدّادات
   الأجزاء (``@@ -a,b +c,d @@``) وبادئات الأسطر تُحكَم هنا — الخطأ
   يوصف بالعربية بموضعه الدقيق (مسار، فهرس الجزء، العدد المعلن مقابل
   الفعلي) فيصل للعقل رجعيةً قبل أن يرفض git شيئاً بصمت.
2. **سلّم تطبيق متسامح معلن**: كاملة ← بالملفات ← بالأجزاء (مع
   ``--recount`` الذي يعيد حساب العدّادات). الرقعة متعددة الملفات
   التي يرفضها git بسبب ملف واحد قد تُنقذ بالكامل بتطبيق أجزائها
   الصالحة — والوضع الجزئي **معلن في الإيصال** لا مطموس: كل جزء
   طُبِّق وكل جزء رُفض وسببه موثقان.
3. **إرجاع بالبايت لحرس التراجع**: ما طُبِّق يُرجَع عكسياً جزءاً جزءاً
   — حارس التراجع في الحلقة (درس multiplan: «الصفقة تُرجع بالبايت»
   وصل للحلقة العامة) يعيد الشجرة إلى الأساس بدل أن تبقى رقعة كسّارة
   عقداً على الأجزاء في المحاولة التالية.

السلسلة كلها حتمية: ترتيب الأجزاء ترتيب الظهور في النص، وترتيب
الأخطاء ترتيب المواضع، والأسباب العربية من آخر أسطر git لا أولها.

    from zyko.benchmarks.patch_surgeon import apply_tolerant, validate_syntax

    ok, errors = validate_syntax(patch)
    tol = apply_tolerant(workdir, patch, runner)
    tol.mode_ar        # "كاملة" أو "بالملفات" أو "بالأجزاء"
    tol.applied_subpatches  # نصوص الأجزاء المطبقة — غذاء الإرجاع العكسي
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "MODE_FULL",
    "MODE_FILES",
    "MODE_HUNKS",
    "TolerantApply",
    "apply_tolerant",
    "revert_candidate",
    "split_file_patches",
    "split_hunk_patches",
    "validate_syntax",
]

Runner = Callable[..., Any]

# أوضاع التطبيق المعلنة — تظهر في الإيصال كما هي، لا مواضع خفية
MODE_FULL = "كاملة"
MODE_FILES = "بالملفات"
MODE_HUNKS = "بالأجزاء"

_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")


# --------------------------------------------------------------- التفكيك
def split_file_patches(patch: str) -> tuple[tuple[str, str], ...]:
    """فصّل الرقعة إلى رقع لكل ملف — بالترتيب الأصلي حتماً.

    كل قطعة تحمل ترويسة الملف وكل أجزائه. الملف الواحد لا يُفصَّل
    (طوله الأصلي هو نفسه) فتعيد الدالة قطعة واحدة عنده.
    """
    if not patch.endswith("\n"):
        patch = patch + "\n"
    lines = patch.splitlines(keepends=True)
    sections: list[tuple[str, str]] = []
    current_header: list[str] = []
    current_path: str | None = None
    current_body: list[str] = []
    for line in lines:
        if line.startswith("--- "):
            if current_path is not None:
                sections.append((current_path, "".join(current_header + current_body)))
                current_header, current_body = [], []
            current_header.append(line)
            target = line[4:].strip().split("\t")[0]
            current_path = target[2:] if target.startswith(("a/", "b/")) else target
        elif line.startswith("+++ ") and current_path is not None:
            current_header.append(line)
        elif current_path is not None:
            current_body.append(line)
    if current_path is not None:
        sections.append((current_path, "".join(current_header + current_body)))
    return tuple(sections)


def split_hunk_patches(patch: str) -> tuple[tuple[str, int, str], ...]:
    """فصّل الرقعة إلى رقع لكل جزء — كل جزء رقعة مستقلة بترويسة ملفه.

    الترتيب (المسار، فهرس الجزء صاعد) ترتيب الظهور الأصلي لا ترتيباً
    أبجدياً — الحتمية بالبايت تعني نفس النص يعطي نفس التقسيم.
    """
    subpatches: list[tuple[str, int, str]] = []
    for path, file_patch in split_file_patches(patch):
        lines = file_patch.splitlines(keepends=True)
        header_lines: list[str] = []
        hunks: list[list[str]] = []
        for line in lines:
            if line.startswith("@@ "):
                hunks.append([line])
            elif not hunks:
                header_lines.append(line)
            else:
                hunks[-1].append(line)
        for index, hunk in enumerate(hunks, start=1):
            subpatches.append((path, index, "".join(header_lines + hunk)))
    return tuple(subpatches)


# --------------------------------------------------------------- الحكم الصياغي
def _hunk_counts(header: str) -> tuple[int, int]:
    """العدّان المعلنان في ترويسة الجزء: (أسطر الطرف القديم، الجديد)."""
    m = re.match(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", header)
    if not m:
        return -1, -1
    old = int(m.group(1)) if m.group(1) is not None else 1
    new = int(m.group(2)) if m.group(3) is None else int(m.group(3))
    return old, new


def validate_syntax(patch: str) -> tuple[bool, tuple[str, ...]]:
    """حكم صياغي محلي قبل git — الأخطاء عربية بموضعها، مرتبة بالظهور.

    ما يفحصه: ترويسة ملف ناقصة، ترويسة جزء مشوهة، عدّاد جزء مخالف
    لأسطره الفعلية، سطر بلا بادئة موحدة معلومة. الصمت هنا يعني سليماً
    صياغياً — لا يضمن تطبيق git (المحتوى قد لا يطابق الملف) لكنه يضمن
    أن الرفض القادم إن حصل فسببه المحتوى لا الصيغة.
    """
    if not patch.endswith("\n"):
        patch = patch + "\n"
    lines = patch.splitlines(keepends=True)
    errors: list[str] = []
    path = ""
    seen_header_for_this_file = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- "):
            path = line[4:].strip().split("\t")[0]
            seen_header_for_this_file = False
            if i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                seen_header_for_this_file = True
                i += 2
                continue
            errors.append(f"ترويسة ناقصة: «{path}» بلا سطر «+++» بعده — رقعة موحدة ناقصة")
            # لا خطأ مزدوج: سطر «+++» القادم يُستهلك صامتاً — العلة واحدة
            if i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                i += 2
            else:
                i += 1
            continue
        if line.startswith("@@ "):
            if not seen_header_for_this_file:
                errors.append(
                    f"جزء بلا ترويسة ملف: «{line.rstrip()}» وصل قبل «---/+++» — أعد الترويسة كاملة"
                )
            old, new = _hunk_counts(line.rstrip("\n"))
            if old < 0:
                errors.append(
                    f"ترويسة جزء مشوهة: «{line.rstrip()}» — الصيغة المعتمدة «@@ -أ،ب +ج،د @@»"
                )
                i += 1
                continue
            old_actual = 0
            new_actual = 0
            j = i + 1
            while j < len(lines):
                body = lines[j]
                if body.startswith("@@ ") or body.startswith("--- "):
                    break
                if body.startswith("+"):
                    new_actual += 1
                elif body.startswith("-"):
                    old_actual += 1
                elif body.startswith(" ") or body.strip() == "":
                    old_actual += 1
                    new_actual += 1
                else:
                    errors.append(
                        f"سطر بلا بادئة معلومة في «{path}» بعد ترويسة «{lines[i].rstrip()}»: "
                        f"«{body.rstrip()[:60]}» — كل أسطر الجزء تبدأ بمسافة أو + أو -"
                    )
                j += 1
            if old_actual != old or new_actual != new:
                errors.append(
                    f"عدّاد جزء مخالف في «{path}»: ترويسة «{lines[i].rstrip()}» تعلن "
                    f"{old} قديماً و{new} جديداً، والأسطر الفعلية {old_actual} قديماً و{new_actual} جديداً — "
                    "صحّح الترويسة أو الأسطر (أعِد حساب العدّادات)"
                )
            i = j
            continue
        if line.startswith("+++ "):
            errors.append("سطر «+++» بلا «---» قبله — ترويسة ملف ناقصة")
            i += 1
            continue
        if line.strip() == "":
            i += 1
            continue
        errors.append(f"سطر خارج أي جزء أو ترويسة: «{line.rstrip()[:60]}» — ليس نص رقعة موحدة")
        i += 1
    return (not errors), tuple(errors)


# --------------------------------------------------------------- التطبيق المتسامح
@dataclass(frozen=True)
class TolerantApply:
    """نتيجة السلم — الوضع المعلن والأجزاء المطبقة والمرفوضة بالبايت."""

    applied: bool
    mode_ar: str  # كاملة / بالملفات / بالأجزاء — أو الوضع الأخير عند الفشل الكلي
    parts_applied: tuple[str, ...] = ()  # مسارات أو (مسار:فهرس) بحسب الوضع
    parts_failed: tuple[tuple[str, str], ...] = ()  # (جزء، سبب عربي)
    reason_ar: str = ""
    syntax_errors: tuple[str, ...] = ()
    applied_subpatches: tuple[str, ...] = field(default_factory=tuple)  # غذاء الإرجاع
    flags: tuple[str, ...] = ()  # أعلام التسامح التي أنقذت التطبيق — معلنة لا خفية

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "mode_ar": self.mode_ar,
            "parts_applied": list(self.parts_applied),
            "parts_failed": [[p, r] for p, r in self.parts_failed],
            "reason_ar": self.reason_ar,
            "syntax_errors": list(self.syntax_errors),
            "flags": list(self.flags),
        }


def _git_apply(
    workdir: Path, sub: str, runner: Runner, extra: tuple[str, ...] = ()
) -> tuple[bool, str]:
    """تطبيق رقعة جزئية — فحص ثم تطبيق، وسبب الرفض من آخر أسطر git."""
    if not sub.endswith("\n"):
        sub = sub + "\n"
    check = runner(
        ["git", "apply", "--check", "--whitespace=nowarn", *extra, "-"],
        cwd=str(workdir),
        input=sub,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if getattr(check, "returncode", 1) != 0:
        detail = (getattr(check, "stderr", "") or "").strip().splitlines()
        reason = detail[-1][:200] if detail else "فحص التطبيق رفض الجزء"
        return False, f"فشل فحص التطبيق: {reason}"
    run = runner(
        ["git", "apply", "--whitespace=nowarn", *extra, "-"],
        cwd=str(workdir),
        input=sub,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if getattr(run, "returncode", 1) != 0:
        detail = (getattr(run, "stderr", "") or "").strip().splitlines()
        reason = detail[-1][:200] if detail else "التطبيق فشل بعد الفحص"
        return False, f"فشل التطبيق: {reason}"
    return True, "طُبِّق"


# سلّم أعلام التسامح المعلن — اكتشاف الموجة 20 الموثق بالاختبار:
# git يُلزم الجزء عديم السياق اللاحق أن يمتد إلى نهاية الملف (match_end)،
# فالجزء «@@ -1 +1 @@» على ملف متعدد الأسطر يرفض بلا --unidiff-zero —
# وهذا من أعراض الحالات الـ19 بلا رقعة مطبقة في العينة الواسعة.
_APPLY_FLAG_LADDER: tuple[tuple[str, ...], ...] = (
    (),
    ("--recount",),
    ("--unidiff-zero",),
    ("--recount", "--unidiff-zero"),
)


def _flags_label(flags: tuple[str, ...]) -> str:
    return " + ".join(flags) if flags else "بلا أعلام"


def apply_tolerant(workdir: Path, patch: str, runner: Runner) -> TolerantApply:
    """سلّم التطبيق المعلن: كاملة ← بالملفات ← بالأجزاء، ولكل جزء سلّم
    أعلام (لا شيء ← ‎--recount‎ ← ‎--unidiff-zero‎ ← كلاهما).

    الوضع الجزئي نجاح موثق لا ادعاء كامل: ``parts_failed`` يحمل كل جزء
    رُفض وسببه، ``flags`` يعلن أعلام التسامح التي أنقذت التطبيق، و
    ``applied_subpatches`` يحمل نصوص ما طُبِّق فتُرجَع عكسياً بالبايت
    عند حرس التراجع. الفشل الكلي يحمل سبب git والفحص الصياغي معاً —
    رجعية واحدة كافية للعقل لا رجعيتين متنافرتين.
    """
    syntax_ok, errors = validate_syntax(patch)
    # الوضع الكلي أولاً — بأعلام التسامح نفسها المعلنة
    for flags in _APPLY_FLAG_LADDER:
        ok, reason = _git_apply(workdir, patch, runner, flags)
        if ok:
            suffix = f" بأعلام {_flags_label(flags)}" if flags else ""
            return TolerantApply(
                applied=True,
                mode_ar=MODE_FULL,
                reason_ar="طُبِّقت كاملة" + suffix,
                syntax_errors=errors,
                applied_subpatches=(patch,),
                flags=flags,
            )

    # سلم الملفات — الرقعة متعددة الملفات يرفضها git بسبب ملف واحد أحياناً
    files = split_file_patches(patch)
    if len(files) > 1:
        applied_parts: list[str] = []
        applied_subs: list[str] = []
        applied_flags: list[tuple[str, ...]] = []
        failed_parts: list[tuple[str, str]] = []
        for path, sub in files:
            ok2 = False
            reason2 = ""
            flags2: tuple[str, ...] = ()
            for flags2 in _APPLY_FLAG_LADDER:
                ok2, reason2 = _git_apply(workdir, sub, runner, flags2)
                if ok2:
                    break
            if ok2:
                applied_parts.append(path)
                applied_subs.append(sub)
                applied_flags.append(flags2)
            else:
                failed_parts.append((path, reason2))
        if applied_parts:
            return TolerantApply(
                applied=True,
                mode_ar=MODE_FILES,
                parts_applied=tuple(applied_parts),
                parts_failed=tuple(failed_parts),
                reason_ar="طُبِّقت بالملفات" + (" — تطبيق جزئي معلن" if failed_parts else ""),
                syntax_errors=errors,
                applied_subpatches=tuple(applied_subs),
                flags=applied_flags[0],
            )

    # سلم الأجزاء — كل جزء رقعة مستقلة، بأعلام التسامح نفسها المعلنة
    hunks = split_hunk_patches(patch)
    if len(hunks) > 1:
        applied_parts = []
        applied_subs = []
        applied_flags = []
        failed_parts = []
        for path, index, sub in hunks:
            ok3 = False
            reason3 = ""
            flags3: tuple[str, ...] = ()
            for flags3 in _APPLY_FLAG_LADDER:
                ok3, reason3 = _git_apply(workdir, sub, runner, flags3)
                if ok3:
                    break
            if ok3:
                applied_parts.append(f"{path}:{index}")
                applied_subs.append(sub)
                applied_flags.append(flags3)
            else:
                failed_parts.append((f"{path}:{index}", reason3))
        if applied_parts:
            return TolerantApply(
                applied=True,
                mode_ar=MODE_HUNKS,
                parts_applied=tuple(applied_parts),
                parts_failed=tuple(failed_parts),
                reason_ar="طُبِّقت بالأجزاء" + (" — تطبيق جزئي معلن" if failed_parts else ""),
                syntax_errors=errors,
                applied_subpatches=tuple(applied_subs),
                flags=applied_flags[0],
            )

    # فشل كلي — سبب git (آخر محاولة بأعلام كاملة) والفحص الصياغي معاً بالترتيب الحتمي
    details = [reason]
    if not syntax_ok:
        details.extend(f"الصياغي: {e}" for e in errors)
    return TolerantApply(
        applied=False,
        mode_ar=MODE_FILES if len(files) > 1 else MODE_FULL,
        parts_failed=tuple((p, r) for p, r in files)
        if len(files) > 1
        else ((path_label(patch), reason),),
        reason_ar=" | ".join(details)[:600],
        syntax_errors=errors,
    )


def path_label(patch: str) -> str:
    """تسمية الرقعة الفاشلة بالمسار الأول — للإيصال لا للعقل."""
    files = split_file_patches(patch)
    return files[0][0] if files else "رقعة"


# --------------------------------------------------------------- الإرجاع العكسي
def revert_candidate(
    workdir: Path,
    patch: str,
    runner: Runner,
    applied_subpatches: tuple[str, ...] = (),
) -> tuple[bool, str]:
    """أرجع ما طُبِّق — عكسياً جزءاً جزءاً على الوضع المعلن نفسه.

    التطبيق الكلي يُرجَع بالرقعة كلها، والتطبيق الجزئي يُرجَع بأجزائه
    المطبقة حصراً (عكس رقعة كاملة على شجرة ناقصة التطبيق يرفض ظلماً).
    السبب العربي من آخر أسطر git — فشل الإرجاع موثق لا مطموس.
    """
    subs = applied_subpatches or (patch,)
    for sub in subs:
        ok, reason = False, ""
        for flags in _APPLY_FLAG_LADDER:
            ok, reason = _git_apply(workdir, sub, runner, ("-R", *flags))
            if ok:
                break
        if not ok:
            return False, f"فشل الإرجاع العكسي: {reason}"
    return True, "أُرجعت الشجرة إلى الأساس"
