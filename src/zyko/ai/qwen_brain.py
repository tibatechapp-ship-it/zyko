"""zyko.ai.qwen_brain — عقل Qwen عبر واجهة متوافقة مع OpenAI، خلف بوابات المصنع نفسها.

القاعدة الذهبية بلا أي تغيير: **العقل يضيف، والبوابات تقرر**.
``QwenBrain`` يطلب خطة عربية من نموذج Qwen عبر أي نقطة نهاية متوافقة مع
OpenAI (DashScope، OpenRouter، Together، أو خادم vLLM/Ollama محلي في
الوضع المتوافق)، ويعيد نصّ النموذج **اقتراحًا خامًا** — لا يُقبل إلا عبر
``GatedBrain`` (بوابة PII ثم بوابة RTL، بالترتيب الثابت)، ولا يلمس
المشروع مباشرة أبدًا، وحتميته ``False`` فيوثّقها الإيصال كما هي.

بلا اعتماديات جديدة: النقل عبر ``urllib`` من المكتبة القياسية، ودالة
النقل **قابلة للحقن** فتبقى الاختبارات بلا شبكة إطلاقًا — خادم وهمي أو
دالة مزيفة بدل الخادم الحقيقي. وكل فشل (مفتاح مرفوض، خادم غير متاح،
خطأ HTTP، مهلة، استجابة مشوّهة) يعود **حكم رفض عربيًا** داخل الاقتراح —
لا استثناء يخرج من طبقة الذكاء أبدًا.

أما ميزة Qwen الثمينة من ``docs/MIND.md`` فموجودة: **وضعا
التفكير/عدم التفكير** — ``thinking=False`` (الافتراضي) لخطة سريعة
موجزة، و``thinking=True`` لهدف يتعمّق؛ يُرسل ``enable_thinking`` كما
يفهمه DashScope وخوادم Qwen المتوافقة، ويُترك حقلًا محذوفًا عند
الإيقاف حتى لا يرفضه خادم صارم.

    from zyko.ai.qwen_brain import QwenBrain
    from zyko.ai.brains import GatedBrain
    from zyko.ai.session import AISession

    brain = QwenBrain(model="qwen-plus")   # المفتاح من ZYKO_QWEN_API_KEY
    receipt = AISession(brain=GatedBrain(brain)).run("قائمة مهام", "./جديد")
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable

from zyko.ai.brains import GateVerdict, Proposal
from zyko.ai.ollama_brain import build_plan_prompt

DEFAULT_HOST = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
HOST_ENV = "ZYKO_QWEN_HOST"
API_KEY_ENV = "ZYKO_QWEN_API_KEY"

# دالة النقل: حمولة المحادثة ⇒ استجابة JSON — نقطة الحقن للاختبارات
Transport = Callable[[dict[str, Any]], dict[str, Any]]

# ---------------------------------------------------------------- الموجه الثابت
SYSTEM_PROMPT = (
    "أنت مخطط مشاريع داخل ZYKO، محرك البرمجة العربي الحتمي. "
    "مهمتك كتابة خطة عربية موجزة لمشروع برمجي من وصف المستخدم."
)


def build_chat_payload(
    model: str,
    goal: str,
    *,
    thinking: bool = False,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    """حمولة ``POST {host}/chat/completions`` بمفاتيح ثابتة الترتيب — حتمية.

    ``thinking=True`` يضيف ``enable_thinking`` فقط حين يُطلب — الحقل
    المحذوف يعني «بلا تفكير» عند DashScope وخوادم Qwen، ولا يرفضه
    خادم متوافق صارم كما قد ترفض الحقول غير المعروفة القيم الصريحة.
    """
    payload: dict[str, Any] = {
        "model": str(model),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_plan_prompt(goal)},
        ],
        "stream": False,
        "max_tokens": int(max_tokens),
    }
    if thinking:
        payload["enable_thinking"] = True
    return payload


# --------------------------------------------------------------- النقل القياسي
def _http_transport(host: str, api_key: str, timeout: float) -> Transport:
    """نقل ``urllib`` القياسي إلى ``{host}/chat/completions`` — بلا اعتماديات."""

    def call(payload: dict[str, Any]) -> dict[str, Any]:
        url = host.rstrip("/") + "/chat/completions"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 — المخطط http(s) مقيد بالبناء
            body = resp.read()
        parsed = json.loads(body.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("الاستجابة ليست كائن JSON")
        return parsed

    return call


def list_qwen_models(
    host: str | None = None,
    api_key: str | None = None,
    timeout: float = 10.0,
) -> tuple[str, ...]:
    """معرّفات النماذج المتاحة من ``GET {host}/models`` — فارغة أو استثناء إن لم تتاح."""
    url = (host or os.environ.get(HOST_ENV) or DEFAULT_HOST).rstrip("/") + "/models"
    key = api_key if api_key is not None else os.environ.get(API_KEY_ENV, "")
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {key}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 — المخطط http(s) مقيد بالبناء
        data = json.loads(resp.read().decode("utf-8"))
    items = data.get("data", []) if isinstance(data, dict) else []
    return tuple(m.get("id", "") for m in items if isinstance(m, dict) and m.get("id"))


# --------------------------------------------------------------- استخراج النص
def extract_choice_content(response: object) -> str:
    """نص النموذج من استجابة ``/chat/completions`` — يرفع استثناءً إن بُنيت الاستجابة خطأ.

    ملاحظة: نماذج التفكير تضع السلسلة الاستدلالية في ``reasoning_content``
    والإجابة النهائية في ``content`` — نأخذ ``content`` وحده دائمًا.
    """
    if not isinstance(response, dict):
        raise ValueError("الاستجابة ليست كائن JSON")
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise KeyError("choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise TypeError("choices[0] ليس كائنًا")
    message = first.get("message")
    if not isinstance(message, dict):
        raise KeyError("message")
    content = message.get("content")
    if not isinstance(content, str):
        raise TypeError("content ليس نصًا")
    return content.strip()


def _classify_error(exc: Exception, host: str, timeout: float) -> str:
    """ترجمة أي فشل نقل إلى دليل عربي قصير — الترتيب مهم (الأدق أولًا)."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return f"رفض خادم Qwen المفتاح (HTTP {exc.code}) — تحقق من ZYKO_QWEN_API_KEY"
        if exc.code == 404:
            return f"لم يُعثر على المسار أو النموذج على {host} (HTTP 404) — تحقق من HOST والنموذج"
        if exc.code == 429:
            return "تجاوزت حد الطلبات (HTTP 429) — انتظر قليلًا ثم أعد المحاولة"
        return f"رفض خادم Qwen الطلب (HTTP {exc.code})"
    if isinstance(exc, TimeoutError):
        return f"انتهت مهلة الانتظار ({timeout:g} ثانية) — النموذج بطيء أو الخادم مشغول"
    if isinstance(exc, (urllib.error.URLError, ConnectionError, OSError)):
        reason = getattr(exc, "reason", exc)
        return f"تعذّر الوصول إلى Qwen على {host} — هل العنوان والمفتاح صحيحان؟ ({type(reason).__name__})"
    if isinstance(exc, (KeyError, TypeError, ValueError)):
        return "استجابة غير مفهومة من Qwen — بنية غير متوقعة"
    return f"خطأ غير متوقع — {type(exc).__name__}"


# --------------------------------------------------------------- عقل Qwen
class QwenBrain:
    """عقل Qwen السحابي/المحلي: نموذج حقيقي، حتميته لا، وقراره عبر البوابات.

    - ``name = "qwen:<model>"`` — يظهر في الإيصال بعد الغلاف:
      ``gated:qwen:<model>``.
    - ``deterministic = False`` — نموذج لغوي، والإيصال يسجّل ذلك صريحًا.
    - لا يرفع استثناءً أبدًا: كل فشل يعود اقتراحًا مرفوضًا بدليل عربي،
      فيوثّقه الإيصال عند بوابة الخطة تمامًا كرفض PII.
    - المفتاح: ``api_key=`` أو ``ZYKO_QWEN_API_KEY`` — غيابه يعود رفضًا
      عربيًا عند أول ``propose`` لا استثناءً عند البناء.
    """

    def __init__(
        self,
        model: str,
        *,
        host: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
        thinking: bool = False,
        max_tokens: int = 1024,
        transport: Transport | None = None,
    ) -> None:
        self.model = str(model).strip()
        if not self.model:
            raise ValueError("اسم النموذج مطلوب — مثال: QwenBrain(model='qwen-plus')")
        self.host = (host or os.environ.get(HOST_ENV) or DEFAULT_HOST).rstrip("/")
        self.api_key = str(api_key) if api_key is not None else os.environ.get(API_KEY_ENV, "")
        self.timeout = float(timeout)
        self.thinking = bool(thinking)
        self.max_tokens = int(max_tokens)
        self._transport: Transport = (
            transport
            if transport is not None
            else _http_transport(self.host, self.api_key, self.timeout)
        )
        self.name = f"qwen:{self.model}"
        self.deterministic = False

    # ------------------------------------------------------------ العقد
    def propose(self, request: str) -> Proposal:
        """اطلب خطة من Qwen وأعد اقتراحًا خامًا — البوابات تقرر لاحقًا."""
        goal = str(request).strip() if request is not None else ""
        if not goal:
            return self._reject("الهدف فارغ — لا شيء ليطلبه العقل من النموذج")
        if not self.api_key:
            return self._reject("مفتاح Qwen مطلوب — مرّره بـ api_key= أو اضبط ZYKO_QWEN_API_KEY")
        payload = build_chat_payload(
            self.model,
            goal,
            thinking=self.thinking,
            max_tokens=self.max_tokens,
        )
        try:
            content = extract_choice_content(self._transport(payload))
        except Exception as exc:  # لا استثناء خارج طبقة الذكاء أبدًا
            return self._reject(_classify_error(exc, self.host, self.timeout))
        if not content:
            return self._reject("أعاد النموذج نصًا فارغًا")
        return Proposal(
            text=content,
            brain=self.name,
            deterministic=self.deterministic,
            verdicts=(
                GateVerdict(
                    gate="qwen",
                    passed=True,
                    details_ar=f"استجابة Qwen: {len(content)} محرفًا — تُفحص الآن ببوابات المصنع",
                ),
            ),
        )

    # ------------------------------------------------------------ داخلي
    def _reject(self, details_ar: str) -> Proposal:
        return Proposal(
            text="",
            brain=self.name,
            deterministic=self.deterministic,
            verdicts=(GateVerdict(gate="qwen", passed=False, details_ar=details_ar),),
        )
