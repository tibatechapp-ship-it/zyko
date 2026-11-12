"""zyko.sandbox.patcher — أداة patch_file: رقعة دقيقة بكتابة ذرية.

الرقعة هي أخطر عملية في الطبقة — هي التي تكتب — فعقدها صارم بالترتيب:
صلاحية العقد، ثم حصر المسار في الجذور، ثم قراءة سليمة UTF-8 تحت سقف
الحجم، ثم **تطابق وحيد** للنص القديم (صفر تطابق رفض صادق، واكثر من
واحد رفض غموض — الرقعة المضللة أسوأ من الرقعة الفاشلة)، ثم كتابة
ذرية بملف مؤقت في المجلد نفسه ثم ``os.replace`` — فلا يُرى الملف
نصف مكتوب ولا يبقى مؤقت يتيم على فشل.

وضع «الكتابة الكاملة» (``content``) موجود لمولّد الملفات الجديدة،
وقاصره سقف العقد نفسه، وخلط الوضعين (old_text مع content) رفض موثق
لا أولهما يفوز صامتًا.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from zyko.sandbox.contracts import PermissionContract, is_sensitive_file

_TMP_SUFFIX = ".zyko-rq3.tmp"


@dataclass(frozen=True)
class PatchResult:
    """نتيجة رقعة واحدة: قرار + دليل عربي + بصمتا sha256 قبل/بعد."""

    ok: bool
    path: str
    mode: str  # "replace" أو "write" أو "" عند الرفض المبكر
    changed: bool
    matches: int
    sha_before: str
    sha_after: str
    bytes_written: int
    reason_ar: str

    def to_dict(self) -> dict:
        """ممثل JSON حتمي — مفاتيح مفرزة بلا أي زمن."""
        return {
            "bytes_written": int(self.bytes_written),
            "changed": bool(self.changed),
            "matches": int(self.matches),
            "mode": self.mode,
            "ok": bool(self.ok),
            "path": self.path,
            "reason_ar": self.reason_ar,
            "sha_after": self.sha_after,
            "sha_before": self.sha_before,
        }


def _sha256_text(text: str) -> str:
    """بصمة النص المكتوب — sha256 بايتات UTF-8 لا الزمن."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _deny(
    path: str,
    reason_ar: str,
    *,
    mode: str = "",
    matches: int = 0,
    sha_before: str = "",
    sha_after: str = "",
    bytes_written: int = 0,
) -> PatchResult:
    """بناء رفض موحد — كل الرفوض تمر هنا فلا شكل مزدوج للفشل."""
    return PatchResult(
        ok=False,
        path=path,
        mode=mode,
        changed=False,
        matches=matches,
        sha_before=sha_before,
        sha_after=sha_after,
        bytes_written=bytes_written,
        reason_ar=reason_ar,
    )


def patch_file(
    contract: PermissionContract,
    *,
    path: object,
    old_text: object = None,
    new_text: object = None,
    content: object = None,
) -> PatchResult:
    """طبّق رقعة تحت العقد — بلا استثناء خارج: كل فشل رفض موثق عربي.

    وضعا العمل: ``old_text``/``new_text`` (استبدال تطابق وحيد) أو
    ``content`` (كتابة كاملة). أي خلط بينهما رفض صريح قبل أي قراءة.
    """
    path_text = str(path or "").strip()
    # 1) الصلاحية المعلنة
    if not contract.allow_patch:
        return _deny(path_text, "العقد لا يفعّل الكتابة (patch) — عقد قراءة فقط")
    # 2) العقد الوضعي: خلط الوضعين رفض لا أولوية صامتة
    has_replace = old_text is not None or new_text is not None
    has_content = content is not None
    if has_replace and has_content:
        return _deny(path_text, "خلط وضعي الرقعة مرفوض — إما old_text/new_text أو content")
    if not has_replace and not has_content:
        return _deny(path_text, "الرقعة بلا محتوى — حدد old_text/new_text أو content")
    mode = "replace" if has_replace else "write"
    # 3) حصر المسار في الجذور
    target, reason = contract.check_path(path_text)
    if target is None:
        return _deny(path_text, f"حارس المسار رفض — {reason}")
    # 3.5) حرس الاعتماد الحساس — الرقعة تقرأ الهدف قبل أن تكتبه، فلا
    # قراءة ولا رقعة على مخازن الأسرار حتى داخل الجذور (المستعار من
    # nexus-core: حصر الجذر لا يكفي لأن ``.env`` مخزن أسرار لا كود).
    if is_sensitive_file(target):
        return _deny(
            str(target),
            f"الهدف مخزن اعتماد حساس ({target.name}) — لا قراءة ولا رقعة على الأسرار حتى داخل الجذور",
            mode=mode,
        )
    # 4) وضع الاستبدال يحتاج ملفًا قائمًا مقروءًا تحت السقف
    sha_before = ""
    if mode == "replace":
        if not target.is_file():
            return _deny(str(target), "الملف القديم غير موجود — استبدال بلا أصل مرفوض", mode=mode)
        try:
            if target.stat().st_size > contract.max_file_bytes:
                return _deny(
                    str(target),
                    f"الملف فوق سقف العقد ({target.stat().st_size} > "
                    f"{contract.max_file_bytes} بايتًا) — رفض قراءة وتعديل",
                    mode=mode,
                )
            source = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return _deny(
                str(target),
                f"قراءة الملف فشلت ({type(exc).__name__}) — ثنائي أو مقفل أو غير UTF-8",
                mode=mode,
            )
        old_value = str(old_text or "")
        if not old_value:
            return _deny(str(target), "old_text فارغ — رقعة بلا أصل مرفوضة", mode=mode)
        matches = source.count(old_value)
        if matches == 0:
            return _deny(
                str(target),
                "old_text غير موجود في الملف — رقعة صفرية التطابق مرفوضة",
                mode=mode,
                matches=matches,
                sha_before=_sha256_text(source),
            )
        if matches > 1:
            return _deny(
                str(target),
                f"old_text متكرر {matches} مرات — تطابق غامض مرفوض، حدّد نصًا وحيدًا",
                mode=mode,
                matches=matches,
                sha_before=_sha256_text(source),
            )
        sha_before = _sha256_text(source)
        updated = source.replace(old_value, str(new_text or ""), 1)
    else:
        # 5) وضع الكتابة الكاملة — مجلد جديد يُنشأ داخل الجذور فقط
        new_value = str(content or "")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _deny(str(target), f"إنشاء المجلد فشل — {type(exc).__name__}", mode=mode)
        updated = new_value
        if target.is_file():
            try:
                sha_before = _sha256_text(target.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                sha_before = ""
    # 6) سقف الناتج — الحجم بعد الرقعة يعود تحت العقد
    if len(updated.encode("utf-8")) > contract.max_file_bytes:
        return _deny(
            str(target),
            f"ناتج الرقعة فوق سقف العقد ({len(updated.encode('utf-8'))} > "
            f"{contract.max_file_bytes} بايتًا) — رفض كتابة",
            mode=mode,
            sha_before=sha_before,
        )
    if "\x00" in updated:
        return _deny(
            str(target),
            "محتوى يحوي NUL — ثنائي مرفوض في نص الرقعة",
            mode=mode,
            sha_before=sha_before,
        )
    # 7) الكتابة الذرية: مؤقت في المجلد نفسه ثم استبدال — لا نصف ملف
    sha_after = _sha256_text(updated)
    unchanged = (mode == "replace" and updated == source) or (
        mode == "write" and sha_before != "" and sha_before == sha_after
    )
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=target.name,
            suffix=_TMP_SUFFIX,
            delete=False,
        ) as tmp:
            tmp.write(updated)
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, target)
    except OSError as exc:
        try:
            tmp_path.unlink()  # لا مؤقت يتيم يبقى بعد الفشل
        except (OSError, UnboundLocalError, NameError):
            pass
        return _deny(
            str(target),
            f"الكتابة الذرية فشلت — {type(exc).__name__}",
            mode=mode,
            sha_before=sha_before,
        )
    bytes_written = len(updated.encode("utf-8"))
    return PatchResult(
        ok=True,
        path=str(target),
        mode=mode,
        changed=not unchanged,
        matches=1 if mode == "replace" else 0,
        sha_before=sha_before,
        sha_after=sha_after,
        bytes_written=bytes_written,
        reason_ar=(
            f"رقعة مطبقة ({mode}) — {bytes_written} بايتًا"
            if not unchanged
            else "الرقعة مطابقة للأصل — بلا تغيير موثق"
        ),
    )


__all__ = ["PatchResult", "patch_file"]
