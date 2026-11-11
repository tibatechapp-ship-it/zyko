"""zyko.mind.autodetect — الاكتشاف التلقائي للقلب الحقيقي من البيئة.

الفجوة التي تغلقها هذه الوحدة: الحلقة الإدراكية كانت تعمل على
``DeterministicCore`` دائمًا، وتفعيل دماغ حقيقي يتطلب علمًا صريحًا
(بناء الأنوية يدويًا). هنا يصير القرار **ذاتيًا وموثقًا**: عند وجود
مفتاح مزود سحابي متوافق مع OpenAI في البيئة، أو نقطة Ollama محلية
قابلة للوصول، تُختبر المرشحات بالترتيب الموثق ويُبنى القلب الحقيقي
تلقائيًا — والرجوع إلى القلب الحتمي فقط عند غياب كل شيء. القرار كاملًا
(المرشحات وأسبابها) يعود في ``CoreDecision`` ليدخل الإيصال فيصير
جزءًا من سلسلة الأدلة لا حدسًا صامتًا.

الترتيب الموثق للمرشحات (الأول المتاح يفوز):

  1. التجاوز الصريح أولاً بأول: ``--brain`` على سطر الأوامر، ثم
     ``ZYKO_MIND_CORE`` في البيئة — النية الصريحة لا تُستبدل بالكشف.
  2. المزودات السحابية المتوافقة مع OpenAI بالترتيب الثابت في
     ``CLOUD_CANDIDATES`` (المفتاح في البيئة = المرشح متاح؛ لا فحص
     شبكي للمزودات السحابية — المفتاح نفسه هو نية المستخدم، وكل فشل
     لاحق يوثّقه الاقتراح المرفوض عند بوابة الخطة).
  3. نقطة Ollama المحلية: فحص وصول قصير المهلة (قابل للحقن) — تُختار
     إذا كانت تعمل ولها نموذج مثبت.
  4. الرجوع الحتمي: ``DeterministicCore`` — نفس سلوك ما قبل هذه
     الوحدة، فيبقى الاختبار بلا شبكة والمحرك بلا مفاتيح افتراضيًا.

الأمان قبل كل شيء: القرار يسجّل **أسماء** متغيرات البيئة ووجودها فقط —
قيم المفاتيح لا تدخل ``to_dict`` ولا الإيصال ولا الطباعة إطلاقًا.

أزرار الضبط (كلها اختيارية):

  - ``ZYKO_MIND_MODEL``    نموذج المزود السحابي المختار (ي override الافتراضي).
  - ``ZYKO_MIND_<LABEL>_HOST`` عنوان المزود (مثل ``ZYKO_MIND_OPENAI_HOST``)؛
    وعقل Qwen يحافظ على بيئته الأصلية ``ZYKO_QWEN_HOST``.
  - ``ZYKO_MIND_CORE``     التجاوز الصريح عبر البيئة (نفس قيم ``--brain``).
  - ``ZYKO_OLLAMA_MODEL``  نموذج Ollama بدل أول نموذج مكتشف.

    from zyko.mind.autodetect import select_core
    decision = select_core()                 # auto: بيئة ⇒ قلب
    loop = MindLoop(decision.core, core_decision=decision)
    print(decision.selected, decision.reason_ar)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

from zyko.ai.brains import GatedBrain
from zyko.ai.ollama_brain import DEFAULT_HOST as OLLAMA_DEFAULT_HOST
from zyko.ai.ollama_brain import OllamaBrain
from zyko.ai.qwen_brain import QwenBrain
from zyko.mind.core import BrainCore, DeterministicCore, ModelCore

GetEnv = Callable[[str], str | None]
#: فحص النماذج: عنوان الخادم ⇒ أسماء النماذج — يرفع استثناءً إن لم يُتاح
Probe = Callable[[str], tuple[str, ...]]

#: التجاوز الصريح عبر البيئة (أولوية بينه وبين الكشف للنية الصريحة)
CORE_ENV = "ZYKO_MIND_CORE"
#: نموذج المزود السحابي المختار — يغلب الافتراضي الموثق
MODEL_ENV = "ZYKO_MIND_MODEL"
#: نموذج Ollama بدل أول نموذج مكتشف من الخادم
OLLAMA_MODEL_ENV = "ZYKO_OLLAMA_MODEL"
#: بيئة عنوان Ollama الأصلية (تبقى كما هي في عقل ollama_brain)
OLLAMA_HOST_ENV = "ZYKO_OLLAMA_HOST"

#: قلب Qwen يقرأ عنوانه الأصلي من ``ZYKO_QWEN_HOST`` — فارغ هنا يعني «حلّه بنفسك»
QWEN_HOST_ENV = "ZYKO_QWEN_HOST"

#: المزودات السحابية المتوافقة مع OpenAI — (التسمية، بيئة المفتاح،
#: العنوان الافتراضي، النموذج الافتراضي). الترتيب ثابت وموثق: الأول
#: المتاح يفوز، والعناوين والنماذج مرآة لطبقة ``zyko.providers`` نفسها
#: (مصدر الحقيقة داخل المستودع) — لا مضيفات مُختلقة هنا. Google
#: مستبعدة لأن نقطة v1beta الخاصة بها ليست متوافقة مع OpenAI.
CLOUD_CANDIDATES: tuple[tuple[str, str, str, str], ...] = (
    ("qwen", "ZYKO_QWEN_API_KEY", "", "qwen-plus"),
    ("openai", "OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("anthropic", "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1", "claude-sonnet-4-20250514"),
    ("deepseek", "DEEPSEEK_API_KEY", "https://api.deepseek.com/v1", "deepseek-chat"),
    ("groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    ("mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1", "mistral-small-latest"),
    ("together", "TOGETHER_API_KEY", "https://api.together.ai/v1", "zai-org/GLM-5.3-Flash"),
    ("openrouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
)

#: القيم المسموحة للتجاوز الصريح — مشتقة من الجدول + المحلي + الحتمي
EXPLICIT_CHOICES: tuple[str, ...] = (
    "deterministic",
    *(label for label, _env, _host, _model in CLOUD_CANDIDATES),
    "ollama",
)


def default_probe(host: str) -> tuple[str, ...]:
    """الفحص الحقيقي: نماذج Ollama المثبتة عبر ``GET /api/tags``.

    يرفع استثناءً إن لم يتاح الخادم — المتصل يقرر (في الكشف التلقائي
    الاستثناء يعني «مرشح غير متاح»، وفي التجاوز الصريح يعني خطأ استخدام).
    """
    from zyko.ai.ollama_brain import list_models

    return list_models(host, timeout=2.0)


# ----------------------------------------------------------------- القرار
@dataclass(frozen=True)
class CandidateRecord:
    """مرشح واحد من مرشحات الكشف: متاح أم لا، ولماذا — بلا قيم مفاتيح."""

    label: str
    env: str  # اسم متغير البيئة، أو "ollama:<host>" للمحلي
    available: bool
    detail_ar: str

    def to_dict(self) -> dict[str, Any]:
        """ممثل JSON بمفاتيح ثابتة الترتيب — آمن للإيصال بلا أسرار."""
        return {
            "label": self.label,
            "env": self.env,
            "available": self.available,
            "detail_ar": self.detail_ar,
        }


@dataclass
class CoreDecision:
    """قرار اختيار القلب كاملًا: المختار وسببه وكل المرشحات المدروسة.

    ``core`` خارج ``to_dict`` دائمًا — الممثل JSON للقرار يوثّق
    **ماذا اختير ولماذا** فحسب، فيدخل الإيصال بلا أي قيمة حساسة.
    """

    mode: str  # "auto" | "explicit"
    selected: str  # "deterministic" أو تسمية المزود أو "ollama"
    reason_ar: str
    core: ModelCore
    candidates: tuple[CandidateRecord, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """ممثل القرار للإيصال — أسماء بيئات وأسباب عربية، بلا أسرار."""
        return {
            "mode": self.mode,
            "selected": self.selected,
            "reason_ar": self.reason_ar,
            "candidates": [c.to_dict() for c in self.candidates],
        }


# ----------------------------------------------------------------- البناء
def _host_override(label: str, getenv: GetEnv) -> str:
    """عنوان المزود: ``ZYKO_MIND_<LABEL>_HOST`` أو العنوان الافتراضي الموثق."""
    return (getenv(f"ZYKO_MIND_{label.upper()}_HOST") or "").strip()


def _build_cloud_core(
    label: str,
    model: str,
    host: str,
    key_env: str,
    getenv: GetEnv,
) -> ModelCore:
    """قلب سحابي خلف بوابات المصنع نفسها — مفتاحه من البيئة المُحقنة.

    المفتاح الغائب لا يرفع استثناء عند البناء (عقد ``QwenBrain``):
    الاقتراح المرفوض بدليل عربي يوثّقه الإيصال عند بوابة الخطة.
    """
    brain = QwenBrain(
        model=model,
        host=host or None,  # فارغ ⇒ عقل Qwen يحل عنوانه الأصلي (ZYKO_QWEN_HOST/DashScope)
        api_key=getenv(key_env) or "",
    )
    return BrainCore(GatedBrain(brain))


def _build_ollama_core(model: str, host: str) -> ModelCore:
    """قلب Ollama المحلي خلف البوابات — النقل urllib القياسي."""
    return BrainCore(GatedBrain(OllamaBrain(model=model, host=host or None)))


# ----------------------------------------------------------------- الكشف
def _scan_cloud(
    getenv: GetEnv, model_override: str
) -> tuple[tuple[CandidateRecord, ...], int | None]:
    """مرّ على مرشحات السحاب بالترتيب الموثق وأعد السجل ومؤشر الأول المتاح.

    فحص توافر مرشح سحابي = وجود مفتاحه في البيئة — **لا فحص شبكي**:
    المفتاح المُصدَّر نية صريحة من المستخدم، وأي فشل لاحق (مفتاح مرفوض،
    عنوان خاطئ) يعود رفضًا عربيًا موثقًا عند بوابة الخطة لا استثناءً هنا.
    """
    records: list[CandidateRecord] = []
    first_hit: int | None = None
    for label, key_env, default_host, default_model in CLOUD_CANDIDATES:
        model = model_override or default_model
        if getenv(key_env):
            host = _host_override(label, getenv)
            detail = f"المفتاح موجود — النموذج {model}"
            if host:
                detail += f" على عنوان مخصص ({label})"
            records.append(CandidateRecord(label, key_env, True, detail))
            if first_hit is None:
                first_hit = len(records) - 1
        else:
            records.append(
                CandidateRecord(label, key_env, False, f"المفتاح غير موجود في البيئة ({key_env})")
            )
    return tuple(records), first_hit


def _ollama_candidate(
    getenv: GetEnv,
    probe: Probe,
    scanned_clouds: bool,
) -> tuple[CandidateRecord, tuple[str, ...]]:
    """سجل مرشح Ollama المحلي ونماذجه المكتشفة — فحص واحد لا يُكرر.

    الفحص يقام مرة واحدة هنا؛ النماذج المعادة تُستعمل مباشرة عند الفوز
    بدل إعادة استجواب الخادم. ``scanned_clouds`` صحيح يعني أن مفتاحًا
    سحابيًا فاز فلا فحص شبكي إطلاقًا.
    """
    host = (getenv(OLLAMA_HOST_ENV) or OLLAMA_DEFAULT_HOST).rstrip("/")
    env_label = f"ollama:{host}"
    if scanned_clouds:
        return CandidateRecord("ollama", env_label, False, "لم يُفحص — مفتاح سحابي موجود"), ()
    try:
        models = probe(host)
    except Exception as exc:  # noqa: BLE001 — تعذر الوصول = مرشح غير متاح لا انهيار
        reason = type(getattr(exc, "reason", exc)).__name__
        return (
            CandidateRecord("ollama", env_label, False, f"غير قابل للوصول على {host} ({reason})"),
            (),
        )
    if not models:
        return (
            CandidateRecord(
                "ollama",
                env_label,
                False,
                f"الخادم يعمل على {host} بلا نماذج مثبتة — اسحب نموذجًا أولًا",
            ),
            (),
        )
    return (
        CandidateRecord(
            "ollama", env_label, True, f"متاح — {len(models)} نموذجًا، الأول {models[0]}"
        ),
        tuple(models),
    )


def _deterministic_decision(
    mode: str,
    reason_ar: str,
    candidates: tuple[CandidateRecord, ...],
) -> CoreDecision:
    """الرجوع الحتمي — نفس سلوك ما قبل الكشف، موثقًا لا صامتًا."""
    return CoreDecision(mode, "deterministic", reason_ar, DeterministicCore(), candidates)


def select_core(
    *,
    explicit: str | None = None,
    model: str | None = None,
    getenv: GetEnv = os.environ.get,
    probe: Probe | None = None,
) -> CoreDecision:
    """اختر القلب من البيئة: تجاوز صريح ⇒ كشف تلقائي ⇒ رجوع حتمي.

    - ``explicit``: ``--brain`` من سطر الأوامر (``auto`` تعني «انظر
      للبيئة ثم افحص»). ``ZYKO_MIND_CORE`` يُقرأ عندما لا يُمرَّر صريح.
    - ``model``: ``--model`` من سطر الأوامر — يغلب ``ZYKO_MIND_MODEL``
      والافتراضي الموثق معًا.
    - ``getenv``/``probe``: نقاط الحقن للاختبارات — بلا بيئة حقيقية
      وبلا شبكة إطلاقًا.

    لا يرفع استثناءً في وضع auto أبدًا (الرجوع حتمي). في الوضع الصريح
    يرفع ``ValueError`` برسالة عربية عند طلب قلب غير معروف، أو طلب
    Ollama بلا نموذج محدد وبلا خادم يسمح باكتشافه — النية الصريحة
    تفشل بصوت مسموع، لا برجوع صامت.
    """
    real_probe: Probe = probe or default_probe
    model_override = (model or getenv(MODEL_ENV) or "").strip()

    # ---- 1) التجاوز الصريح: سطر الأوامر ثم بيئة ZYKO_MIND_CORE
    explicit_name = (explicit or "").strip().lower() or (getenv(CORE_ENV) or "").strip().lower()
    if explicit_name and explicit_name != "auto":
        if explicit_name not in EXPLICIT_CHOICES:
            raise ValueError(
                f"قلب غير معروف: «{explicit_name}» — القيم المسموحة: "
                + "، ".join(("auto",) + EXPLICIT_CHOICES)
            )
        if explicit_name == "deterministic":
            return CoreDecision(
                "explicit",
                "deterministic",
                "تجاوز صريح — القلب الحتمي مطلوب حتى لو توفرت مفاتيح",
                DeterministicCore(),
            )
        if explicit_name == "ollama":
            host = (getenv(OLLAMA_HOST_ENV) or OLLAMA_DEFAULT_HOST).rstrip("/")
            ollama_model = model_override or (getenv(OLLAMA_MODEL_ENV) or "").strip()
            if not ollama_model:
                try:
                    models = real_probe(host)
                except Exception as exc:  # noqa: BLE001 — فشل الاكتشاف خطأ استخدام مسموع
                    raise ValueError(
                        f"قلب ollama يتطلب نموذجًا: حدد --model أو {OLLAMA_MODEL_ENV} "
                        f"— وتعذر الاكتشاف من الخادم على {host} ({type(getattr(exc, 'reason', exc)).__name__})"
                    ) from None
                if not models:
                    raise ValueError(
                        f"قلب ollama يتطلب نموذجًا: حدد --model أو {OLLAMA_MODEL_ENV} "
                        f"— الخادم على {host} يعمل بلا نماذج مثبتة"
                    )
                ollama_model = models[0]
            return CoreDecision(
                "explicit",
                "ollama",
                f"تجاوز صريح — القلب المحلي {ollama_model} على {host}",
                _build_ollama_core(ollama_model, host),
            )
        # مزود سحابي صريح — المفتاح الغيب لا يمنع البناء: الاقتراح
        # المرفوض بدليل عربي يوثّق نفسه عند بوابة الخطة (عقد QwenBrain)
        label, key_env, default_host, default_model = next(
            c for c in CLOUD_CANDIDATES if c[0] == explicit_name
        )
        chosen_model = model_override or default_model
        host = _host_override(label, getenv) or (default_host if label != "qwen" else "")
        return CoreDecision(
            "explicit",
            label,
            f"تجاوز صريح — القلب السحابي {label} بالنموذج {chosen_model}",
            _build_cloud_core(label, chosen_model, host, key_env, getenv),
        )

    # ---- 2) الكشف التلقائي: سحاب بالترتيب الموثق ثم Ollama ثم الحتمي
    cloud_records, first_hit = _scan_cloud(getenv, model_override)
    if first_hit is not None:
        label, key_env, default_host, default_model = CLOUD_CANDIDATES[first_hit]
        chosen_model = model_override or default_model
        host = _host_override(label, getenv) or (default_host if label != "qwen" else "")
        ollama_record, _ollama_models = _ollama_candidate(getenv, real_probe, scanned_clouds=True)
        candidates = cloud_records + (ollama_record,)
        return CoreDecision(
            "auto",
            label,
            f"كشف تلقائي — مفتاح {key_env} موجود في البيئة ففاز {label} "
            f"(الترتيب الموثق: أول مفتاح متاح)",
            _build_cloud_core(label, chosen_model, host, key_env, getenv),
            candidates,
        )

    ollama_record, ollama_models = _ollama_candidate(getenv, real_probe, scanned_clouds=False)
    candidates = cloud_records + (ollama_record,)
    if ollama_record.available:
        host = (getenv(OLLAMA_HOST_ENV) or OLLAMA_DEFAULT_HOST).rstrip("/")
        ollama_model = (
            model_override
            or (getenv(OLLAMA_MODEL_ENV) or "").strip()
            or (ollama_models[0] if ollama_models else "")
        )
        return CoreDecision(
            "auto",
            "ollama",
            f"كشف تلقائي — لا مفاتيح سحابية، وخادم Ollama على {host} متاح بالنموذج {ollama_model}",
            _build_ollama_core(ollama_model, host),
            candidates,
        )

    return _deterministic_decision(
        "auto",
        "كشف تلقائي — لا مفاتيح سحابية في البيئة ولا خادم Ollama متاح؛ "
        "القلب الحتمي هو الافتراضي الآمن بلا شبكة",
        candidates,
    )


__all__ = [
    "CLOUD_CANDIDATES",
    "CORE_ENV",
    "CandidateRecord",
    "CoreDecision",
    "EXPLICIT_CHOICES",
    "MODEL_ENV",
    "OLLAMA_MODEL_ENV",
    "default_probe",
    "select_core",
]
