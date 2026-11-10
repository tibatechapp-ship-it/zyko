"""zyko.ai.ollama_brain — العقل المحلي الحقيقي: نموذج Ollama خلف بوابات المصنع.

القاعدة الذهبية بلا أي تغيير: **العقل يضيف، والبوابات تقرر**.
``OllamaBrain`` يطلب خطة عربية من نموذج محلي يعمل عبر Ollama، ويعيد
نصّ النموذج **اقتراحًا خامًا** — لا يُقبل إلا عبر ``GatedBrain``
(بوابة PII ثم بوابة RTL، بالترتيب الثابت)، ولا يلمس المشروع مباشرة
أبدًا، وحتميته ``False`` فيوثّقها الإيصال كما هي.

بلا اعتماديات جديدة: النقل عبر ``urllib`` من المكتبة القياسية،
ودالة النقل **قابلة للحقن** فتبقى الاختبارات بلا شبكة إطلاقًا —
خادم وهمي أو دالة مزيفة بدل الخادم الحقيقي. وكل فشل (خادم غير
متاح، خطأ HTTP، مهلة، استجابة مشوّهة) يعود **حكم رفض عربيًا**
داخل الاقتراح — لا استثناء يخرج من طبقة الذكاء أبدًا.

    from zyko.ai.ollama_brain import OllamaBrain
    from zyko.ai.brains import GatedBrain
    from zyko.ai.session import AISession

    brain = OllamaBrain(model="qwen2.5:7b")           # http://127.0.0.1:11434
    receipt = AISession(brain=GatedBrain(brain)).run("قائمة مهام", "./جديد")
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable

from zyko.ai.brains import GateVerdict, Proposal

DEFAULT_HOST = "http://127.0.0.1:11434"
HOST_ENV = "ZYKO_OLLAMA_HOST"

# دالة النقل: حمولة المحادثة ⇒ استجابة JSON — نقطة الحقن للاختبارات
Transport = Callable[[dict[str, Any]], dict[str, Any]]

# --------------------------------------------------------------- الموجه الثابت
_SYSTEM_PROMPT = (
    "أنت مخطط مشاريع داخل ZYKO، محرك البرمجة العربي الحتمي. "
    "مهمتك كتابة خطة عربية موجزة لمشروع برمجي من وصف المستخدم."
)

PROMPT_TEMPLATE = (
    "اكتب خطة مشروع عربية موجزة للهدف التالي، وفق القواعد الحرفية:\n"
    "- من ٣ إلى ٦ بنود، كل بند سطرًا واحدًا يبدأ بـ «- »\n"
    "- بلا بيانات شخصية إطلاقًا: لا هواتف ولا بريد ولا هويات ولا أسماء أشخاص\n"
    "- بلا محارف تحكم اتجاه، وبلا أسطر كود طويلة\n"
    "- عربية سليمة الاتجاه، بصيغة الأمر\n\n"
    "الهدف: {goal}\n\n"
    "الخطة:"
)


def build_plan_prompt(goal: str) -> str:
    """الموجّه العربي الثابت للهدف — دالة حتمية بحتة."""
    return PROMPT_TEMPLATE.format(goal=str(goal).strip())


def build_chat_payload(model: str, goal: str) -> dict[str, Any]:
    """حمولة ``POST /api/chat`` غير المتدفق — مفاتيح ثابتة الترتيب."""
    return {
        "model": str(model),
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": build_plan_prompt(goal)},
        ],
        "stream": False,
    }


# --------------------------------------------------------------- النقل القياسي
def _http_transport(host: str, timeout: float) -> Transport:
    """نقل ``urllib`` القياسي إلى ``{host}/api/chat`` — بلا اعتماديات."""

    def call(payload: dict[str, Any]) -> dict[str, Any]:
        url = host.rstrip("/") + "/api/chat"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 — المخطط http(s) مقيد بالبناء والعنوان محلي افتراضيًا
            body = resp.read()
        parsed = json.loads(body.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("الاستجابة ليست كائن JSON")
        return parsed

    return call


def list_models(host: str | None = None, timeout: float = 3.0) -> tuple[str, ...]:
    """أسماء النماذج المثبتة من ``GET /api/tags`` — فارغة أو استثناء إن لم يتاح."""
    url = (host or os.environ.get(HOST_ENV) or DEFAULT_HOST).rstrip("/") + "/api/tags"
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310 — المخطط http(s) مقيد بالبناء والعنوان محلي افتراضيًا
        data = json.loads(resp.read().decode("utf-8"))
    models = data.get("models", []) if isinstance(data, dict) else []
    return tuple(m.get("name", "") for m in models if isinstance(m, dict) and m.get("name"))


# --------------------------------------------------------------- استخراج النص
def extract_content(response: object) -> str:
    """نص النموذج من استجابة ``/api/chat`` — يرفع استثناءً إن بُنيت الاستجابة خطأ."""
    if not isinstance(response, dict):
        raise ValueError("الاستجابة ليست كائن JSON")
    message = response.get("message")
    if not isinstance(message, dict):
        raise KeyError("message")
    content = message.get("content")
    if not isinstance(content, str):
        raise TypeError("content ليس نصًا")
    return content.strip()


def _classify_error(exc: Exception, host: str, timeout: float) -> str:
    """ترجمة أي فشل نقل إلى دليل عربي قصير — الترتيب مهم (الأدق أولًا)."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"رفض خادم Ollama الطلب (HTTP {exc.code})"
    if isinstance(exc, TimeoutError):
        return f"انتهت مهلة الانتظار ({timeout:g} ثانية) — النموذج بطيء أو الخادم مشغول"
    if isinstance(exc, (urllib.error.URLError, ConnectionError, OSError)):
        reason = getattr(exc, "reason", exc)
        return f"تعذّر الوصول إلى Ollama على {host} — هل الخادم يعمل؟ ({type(reason).__name__})"
    if isinstance(exc, (KeyError, TypeError, ValueError)):
        return "استجابة غير مفهومة من Ollama — بنية غير متوقعة"
    return f"خطأ غير متوقع — {type(exc).__name__}"


# --------------------------------------------------------------- العقل المحلي
class OllamaBrain:
    """عقل Ollama المحلي: نموذج حقيقي، حتميته لا، وقراره عبر البوابات.

    - ``name = "ollama:<model>"`` — يظهر في الإيصال بعد الغلاف:
      ``gated:ollama:<model>``.
    - ``deterministic = False`` — نموذج لغوي، والإيصال يسجّل ذلك صريحًا.
    - لا يرفع استثناءً أبدًا: كل فشل يعود اقتراحًا مرفوضًا بدليل عربي،
      فيوثّقه الإيصال عند بوابة الخطة تمامًا كرفض PII.
    """

    def __init__(
        self,
        model: str,
        *,
        host: str | None = None,
        timeout: float = 120.0,
        transport: Transport | None = None,
    ) -> None:
        self.model = str(model).strip()
        if not self.model:
            raise ValueError("اسم النموذج مطلوب — مثال: OllamaBrain(model='qwen2.5:7b')")
        self.host = (host or os.environ.get(HOST_ENV) or DEFAULT_HOST).rstrip("/")
        self.timeout = float(timeout)
        self._transport: Transport = (
            transport if transport is not None else _http_transport(self.host, self.timeout)
        )
        self.name = f"ollama:{self.model}"
        self.deterministic = False

    # ------------------------------------------------------------ العقد
    def propose(self, request: str) -> Proposal:
        """اطلب خطة من النموذج المحلي وأعد اقتراحًا خامًا — البوابات تقرر لاحقًا."""
        goal = str(request).strip() if request is not None else ""
        if not goal:
            return self._reject("الهدف فارغ — لا شيء ليطلبه العقل من النموذج")
        payload = build_chat_payload(self.model, goal)
        try:
            content = extract_content(self._transport(payload))
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
                    gate="ollama",
                    passed=True,
                    details_ar=f"استجابة النموذج: {len(content)} محرفًا — تُفحص الآن ببوابات المصنع",
                ),
            ),
        )

    # ------------------------------------------------------------ داخلي
    def _reject(self, details_ar: str) -> Proposal:
        return Proposal(
            text="",
            brain=self.name,
            deterministic=self.deterministic,
            verdicts=(GateVerdict(gate="ollama", passed=False, details_ar=details_ar),),
        )
