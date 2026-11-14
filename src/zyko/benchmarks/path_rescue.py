"""zyko.benchmarks.path_rescue — منقِذ المسار الحتمي (الموجة 25).

درس العينة الواسعة بالبايت (وثيقة الموجة 22): 35 حالة من 44 انتهت بلا
رقعة مطبقة، و34 منها ماتت عند نقطة واحدة — «اختيار الملف رُفض ببوابة أو
لم يعطِ مساراً موجوداً». العقل يفشل مرة في الإعطاء فتنكسر الحلقة كلها:
نقطة فشل أحادية قتلت 77% من العينة قبل أن تلمس رقعةً شيئاً.

الزبدة المستخلصة من منهج التوطين الحتمي في أدوات 2026 (Agentless-style):
لا يُسمح للعقل أن يكون نقطة فشل وحيدة. إذا لم يعطِ العقل مساراً حياً
يتولى **منقِذ بلا نموذج** الاستخراج على درجات معلنة، وكل إنقاذ يُوثق
بالإيصال — لا استبدال صامت:

1. «عقل» — ``parse_choice`` كما هي: العقد الأول لا يتغير. المسار من رد
   رفضته البوابة يُستخرج للتوثيق فقط (المخرج مسار متحقَّق من الشجرة —
   لا نص حر يعبر) ويُسمّى ``brain`` في حقل الإنقاذ.
2. «تطبيع» — مرشّحات من نص الرد نفسه: عبارات الكود والاقتباسات وسوابق
   ‏a/‏ وb/‏ والمستودع، ثم مطابقة الشجرة: تام ← لاحقة فريدة ← اسم ملف
   فريقي — الفريد عقداً: الغموض يُرفض لا يُخمَّن.
3. «معجمي» — ``lexical_chooser.rank_files`` على (التقرير + عقد الفشل +
   الخريطة الدلالية): توطين مطلق بلا نص عقل أصلاً — نفس مسطرة قيمة
   الخريطة (الموجة 21) صارت حلقة إنقاذ.

العقود:
- **حتمي بالبايت**: نفس الرد والشجرة والخريطة ⇒ نفس المسار — ترتيب
  المرشّحات نصي والفرز ``(الدرجة، المسار)`` عقد لا تفضيل.
- **بلا شبكة وبلا نموذج**: الدرجتان 2 و3 معجم و match حصراً — يعيد
  إنتاجهما أي جهاز بأي نواة.
- **لا مسار خارج الشجرة إطلاقاً**: كل مخرجات الدرجات الثلاث مُتحقَّقة
  عضوياً في ``tree`` — المنقذ لا يخترع ولا يُمرِّر نصاً حرماً للشجرة.
- **الإنقاذ يُعلن**: حقل ``rescue_mode`` في محاولة الحلقة يحمل الوضع
  حرفياً، وسلسلة الوثيقة تُغطيه — رفع الأرقام بإعادة قياس موثقة لا
  بتحرير يدوي.

    from zyko.benchmarks.path_rescue import rescue_choice

    resc = rescue_choice(reply_text, tree, instance, map_lines=map_lines)
    resc.path    # مسار حي في الشجرة أو None
    resc.mode    # brain | normalize | lexical | none — يُوثق كما هو
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from zyko.benchmarks.lexical_chooser import rank_files
from zyko.benchmarks.swebench import SWEInstance, parse_choice

__all__ = ["PathRescue", "candidate_paths_from_reply", "resolve_candidate", "rescue_choice"]

#: سوابق السوابق التي تُنزع من المرشّح قبل المطابقة — ‏a/‏ وb/‏ لرقع git
#: وبادئة مستودع العمل ‏psf__requests-NNNN/‎ إن ألحقها العقل
_STRIP_PREFIXES = ("a/", "b/", "i/", "w/")

_REPO_PREFIX_RX = re.compile(r"^psf__requests-\d+/")

#: مرشّح مسار معقول: يحمل لاحقة بايثون أو اسم ملف معرفاً — ما دون ذلك
#: ضجيج لا يُطابق
_PATH_RX = re.compile(r"[\w./-]+\.(?:py|cfg|ini|toml|txt|rst|md)")

#: عبارات الكود المحصورة — أغلب ردود العقل تضع المسار هنا
_INLINE_RX = re.compile(r"`([^`\n]+)`")

#: الوضع الفارغ — لا مسار من أي درجة
_NONE_AR = "لا مسار من الدرجات الثلاث — الفشل موثق لا مُخترع"


@dataclass(frozen=True)
class PathRescue:
    """نتيجة إنقاذ واحدة — المسار ووضعه وسطر الإفصاح العربي."""

    path: str | None
    mode: str  # brain | normalize | lexical | none
    reason_ar: str

    @property
    def rescued(self) -> bool:
        """إنقاذ حقيقي = مسار حي من خارج المسار القياسي (تطبيع أو معجمي)."""
        return self.path is not None and self.mode in ("normalize", "lexical")


def candidate_paths_from_reply(reply: str) -> tuple[str, ...]:
    """مرشّحات مسار من نص الرد — بترتيب نصي حتمي، بلا إعادة ترتيب ذوقي.

    المصادر: عبارات الكود المحصورة أولًا (أغلب الردود تضع المسار فيها)،
    ثم أي قاطعة مسار معقول في الأسطر. المرشّح يُنقّى من اقتباسات
    وسوابق ‏a/‏ وb/‏ وبادئة المستودع ومسافة الاستقطاب العربية.
    """
    if not reply:
        return ()
    seen: list[str] = []
    spans = list(_INLINE_RX.findall(reply))
    spans.extend(_PATH_RX.findall(reply))
    for span in spans:
        cand = span.strip().strip("\"'“”«»")
        cand = _REPO_PREFIX_RX.sub("", cand)
        for prefix in _STRIP_PREFIXES:
            if cand.startswith(prefix):
                cand = cand[len(prefix) :]
        cand = cand.lstrip("/")
        if not cand or "/" not in cand and "." not in cand:
            continue
        if cand not in seen:
            seen.append(cand)
    return tuple(seen)


def resolve_candidate(candidate: str, tree: tuple[str, ...]) -> str | None:
    """طابق مرشّحاً على الشجرة — تام ← لاحقة فريدة ← اسم فريقي.

    الغموض عقد: أكثر من مرشّح لاحق أو اسم ملف مطابق ⇒ رفض لا تخمين —
    المنقذ الذي يخمّن يفسد قياس الدقة الذي يقيسه.
    """
    if not candidate or not tree:
        return None
    tree_set = set(tree)
    if candidate in tree_set:
        return candidate
    suffix_hits = [p for p in tree if p.endswith("/" + candidate)]
    if len(suffix_hits) == 1:
        return suffix_hits[0]
    base = PurePosixPath(candidate).name
    if not base or "." not in base:
        return None  # مرشّح بلا لاحقة يطابق أدلة — الغموض رفض لا تخمين
    name_hits = [p for p in tree if PurePosixPath(p).name == base]
    if len(name_hits) == 1:
        return name_hits[0]
    return None


def rescue_choice(
    reply: str,
    tree: tuple[str, ...],
    instance: SWEInstance,
    map_lines: tuple[str, ...] | list[str] | None = None,
) -> PathRescue:
    """درجات الإنقاذ الثلاث بالترتيب المعلن — أول مسار حي يفوز ووضعه يُوثق.

    الدرجات لا تتدخل إلا في استخراج **مسار**: أي محتوى آخر في الرد لا
    يعبر — والدرجة الأولى «عقل» هي ``parse_choice`` نفسها فلا يتغير
    العقد الأول، والدرجات التالية تنشط حين يخفق.
    """
    # الدرج 1 — العقد الأول كما هو (حتى لرد رُفض ببوابة: المسار فقط
    # يُستخرج للتوثيق والمتابعة، ولا نص حر يعبر إلى الشجرة)
    via_brain = parse_choice(reply or "", tree)
    if via_brain is not None:
        return PathRescue(via_brain, "brain", "المسار من رد العقل بتحقق الشجرة")

    # الدرج 2 — تطبيع المرشّحات من نص الرد نفسه
    for cand in candidate_paths_from_reply(reply or ""):
        hit = resolve_candidate(cand, tree)
        if hit is not None:
            return PathRescue(
                hit,
                "normalize",
                f"المرشّح «{cand}» طابعه المنقذ بالتطبيع على «{hit}»",
            )

    # الدرج 3 — التوطين المعجمي المطلق: التقرير + عقد الفشل + الخريطة
    ranked = rank_files(
        instance.problem_statement,
        tree,
        map_lines=map_lines,
        fail_to_pass=tuple(instance.fail_to_pass),
    )
    if ranked:
        top = ranked[0]
        return PathRescue(
            top,
            "lexical",
            f"التوطين المعجمي الحتمي رتّب «{top}» أولاً من التقرير وعقد الفشل",
        )
    return PathRescue(None, "none", _NONE_AR)
