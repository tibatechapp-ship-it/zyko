<div dir="rtl">

<div align="center">

<img src="docs/assets/social-card.png" alt="ZYKO — Universal AI Orchestration Platform" width="800"/>

[![CI](https://github.com/tibatechapp-ship-it/zyko/actions/workflows/ci.yml/badge.svg)](https://github.com/tibatechapp-ship-it/zyko/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-438%20passing-22c55e)](.github/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-98%25-84cc16)](.github/workflows/ci.yml)
[![Security](https://img.shields.io/badge/bandit-0%20findings-22c55e?logo=shield&logoColor=white)](.github/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-3776ab?logo=python&logoColor=white)](pyproject.toml)
[![Platforms](https://img.shields.io/badge/platforms-Linux%20%7C%20Windows%20%7C%20macOS%20%7C%20Android%20%7C%20Termux-10b981)](android/README.md)
[![License](https://img.shields.io/badge/license-Apache--2.0-3b82f6)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-native-8b5cf6)](https://modelcontextprotocol.io)
[![Docs](https://img.shields.io/badge/docs-tibatechapp--ship--it.github.io%2Fzyko-22d3ee)](https://tibatechapp-ship-it.github.io/zyko/)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-ec4899)](CONTRIBUTING.md)

**العربية** · [English](#zyko--universal-ai-orchestration-platform-english) · [الموقع التعريفي](https://tibatechapp-ship-it.github.io/zyko/) · [المناقشات](https://github.com/tibatechapp-ship-it/zyko/discussions)

</div>

# ZYKO — منصة تنسيق الذكاء الاصطناعي الشاملة

**النسخة 0.4.1** · توجيه متعدد المزوّدين بقرارات **قابلة للتحقق** · حوكمة **Policy-as-Code** · وكلاء أصليون بـ **MCP** · تتبّع **مدمج**

تعمل على: **Linux · Windows · macOS · Android · Termux** — بنية Python خالصة، لا شيء يُترجم إلزاميًا على أي منصة.

---

## لماذا ZYKO؟

أربعة ركائز تميّز ZYKO عن كل البوابات الموجودة:

| الركيزة | ماذا تعني عمليًا |
|---|---|
| **توجيه قابل للتحقق** | كل استجابة تحمل «إيصال توجيه»: ترتيب كامل للمرشحين بمكوّنات الدرجات (جودة/تكلفة/زمن) والأوزان المنشورة. أعد التحقق من أي قرار سابق دون اتصال. |
| **جودة صادقة** | درجات الجودة تأتي فقط من مقاييس مرجعية **قابلة لإعادة الإنتاج** (`zyko bench`) ببذور ثابتة ومصحّحات موضوعية — لا من جداول تسويقية. |
| **حوكمة شيفرة-كسياسة** | سقف إنفاق يومي، حجب PII حتمي، قوائم سماح للنماذج والأدوات، حدود معدل، وسجل تدقيق — كل ذلك في ملف YAML واحد مُطبَّق على **كل** نداء. |
| **MCP أولًا** | ZYKO **يستهلك** خوادم MCP كأدوات لوكلائه، **ويعرض نفسه** كخادم MCP (`zyko mcp serve`) لأي مضيف MCP. |

## من أين استلهم ZYKO؟ (أنماط المشاريع الكبيرة)

| النمط المُعتمد | المصدر |
|---|---|
| محوّلات موحّدة بصيغة OpenAI، إعادة محاولة أُسّية، واحترام `Retry-After` من الخادم | [LiteLLM](https://github.com/BerriAI/litellm) |
| مزوّد فوق المزوّدين، تسمية `provider/model`، ورؤوس الإحالة (HTTP-Referer/X-Title) | [OpenRouter](https://openrouter.ai) |
| درجات جودة مشتقّة من مقاييس مرجعية قابلة لإعادة الإنتاج لا من جداول تسويقية | [RouteLLM](https://github.com/lmcache/routellm) |
| الحوكمة كإعدادات مُعلنة: سقوف إنفاق، قوائم سماح، تدقيق | [Portkey Gateway](https://github.com/Portkey-AI/gateway) |
| بروتوكول مفتوح يوحّد أدوات الوكلاء (عميل + خادم) | [Model Context Protocol](https://modelcontextprotocol.io) |

تميّز ZYKO ليس الاختراع من الصفر بل **التحقق**: إيصالات توجيه تُعاد من دون اتصال، دفتر جودة قابل لإعادة الإنتاج، وسياسة مُطبَّقة على كل نداء — على كل منصة.

## ما الجديد في 0.4.1؟ (تتبّع مدمج — ما يبيعه الآخرون خدمة مدفوعة نحن نقدّمه محليًا بلا اعتماديات)

كانت الملاحظة أكبر فجوة ميزات مقابل المنافسين: LangChain يبيعها LangSmith،
وLangfuse/AgentOps تتطلب SDK خارجيًا وخدمة سحابية. ZYKO الآن **تتتبّع كل نداء**
بـ spans على نمط OpenTelemetry (معرّفات trace/parent، مدد، حالات، سمات) —
**صفر اعتماديات جديدة**، ملف JSONL **ملكك على قرصك**، وأمر فحص من نفس الـCLI:

```python
from zyko import Zyko

zk = Zyko()
with zk.tracer.span("my-rag", corpus="support-docs"):  # span أبو لك
    zk.ask("لماذا تأخرت فاتورتي؟")  # span الموجّه يتداخل تلقائيًا
# لاحقًا: zyko traces --last 20   أو   --json   أو   --trace <id>
```

- `zyko traces` — جدول زمني، `--json` دائمًا JSON صالح (عقد `cost`/`cache`)،
  `--trace <id>` لكل spans نداء واحد، `--clear`، و`--file` لمسار مخصص.
- التتبّع **لا يكسر النداء أبدًا**: فشل الكتابة يتحوّل سطر تحذير واحد؛
  التدفق المُهمَل (انقطاع العميل) يُغلق الـspan بحالة `cancelled`.
- سجل دوار بحدّ (حالية + نسختان `.1`/`.2`) فلا يمتلئ القرص مهما طال تشغيل البوابة.
- عطّله بـ`ZYKO_TRACING=0` أو `tracing.enabled: false` — الواجهة نفسها بلا كتابة.

## ما الجديد في 0.4.0؟ (المخرجات المنظمة — الميزة الأكثر تنافسية التي كانت لدى LangChain وCrewAI وAutoGen وينقصنا)

مراجعة قدرات مقابل LangChain (`with_structured_output`) وCrewAI (مخرجات Pydantic) وAutoGen (`response_format`) وLiteLLM (تمرير `response_format`) بيّنت أكبر فجوة متبقية: **إجابات مقيّدة بمخطط (JSON Schema)**. تُرجع ZYKO الآن *بيانات متحققًا منها أو خطأ مُنمّطًا* — لا نصًا خامًا عليك أن تفكّه بنفسك — مع حلقة إصلاح تلقائية تُعيد أخطاء التحقق إلى النموذج. **صفر اعتماديات إلزامية جديدة**؛ Pydantic اختياري (`zyko[structured]`) لا شرط:

```python
from zyko import Zyko

zk = Zyko()
out = zk.structured(
    "ما تفاصيل الطلب 42؟",
    schema={
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "status": {"type": "string", "enum": ["open", "shipped"]},
        },
        "required": ["id", "status"],
    },
)
out.data  # {"id": 42, "status": "shipped"} — متحقق منه، أو خطأ مُنمّط StructuredOutputError
out.repaired  # هل لجأ الإصدار إلى جولة إصلاح؟
```

- **مُصادِق JSON Schema خالص من Python**: أنواع، `enum`/`const`، حدود رقمية ونصية، `pattern`، تنسيقات أساسية، قوائم وكائنات متداخلة، `allOf`/`anyOf`/`oneOf`، وحلّ `$ref`/`$defs` المحلي بحماية من الدوران — ما تحتاجه مخططات Pydantic دائمًا. ولغة Python تلتقط الفخّ الكلاسيكي: `True` **ليس** عددًا صحيحًا هنا.
- **حلقة إصلاح تلقائية**: عند فشل التحقق تُرسَل الأخطاء الفعلية (بمساراتها `$.id`…) إلى النموذج في جولة تصحيح واحدة قابلة للزيادة (`max_repairs`)، وبعدها خطأ مُنمّط يحمل `errors` و`text`.
- **مستخرِج JSON مقاوم للفوضى**: ينجو من النثر المحيط وأسيجة Markdown وكتل `<think>` (نمط DeepSeek).
- **وضع أصلي اختياري**: `native=True` يرسل `response_format: {"type": "json_schema", …}` للمزوّدين الداعمين (OpenAI، Groq، Mistral، DeepSeek، OpenRouter، Together، xAI)، والبائع الذي يرفضها يسقط في التوجيه البديل تلقائيًا.
- **دعم عبر المزوّدين**: Google يُرسَم إلى `generationConfig.responseMimeType` (+ `responseSchema`)؛ والبوابة المتوافقة مع OpenAI تقبل `response_format` في جسم الطلب وترفض غير الكائنات بـ 400.
- **سلامة الطبقات**: مخطط مُعطّب = `SchemaSpecError` فوري (خطأ مُبرمِج)، بينما فشل النموذج = `StructuredOutputError`؛ ومفاتيح الذاكرة المؤقتة (basis v2) تشمل `response_format` فلا تُقدَّم إجابة نصية مخزّنة لطلب منظم.

63 اختبارًا جديدًا (`tests/test_structured.py`) — **438 اختبارًا ناجحًا**.

## ما الجديد في 0.3.9؟ (ذاكرة تخزين مؤقت للاستجابات — أكبر فجوة كانت أمام المنافسين)

مراجعة مقارنة ضد LiteLLM وPortkey أظهرت أن ZYKO يكافئهم في إعادة المحاولة الأُسّية والتحوّل التلقائي وقواطع الدائرة وسقوف الإنفاق وحجب PII — لكنه كان يفتقد **ذاكرة تخزين للاستجابات**. أُضيفت الآن خلف قسم سياسة واحد، مطفأة افتراضيًا:

```yaml
# في ملف السياسة (Policy-as-Code):
cache:
  enabled: true
  ttl_s: 300        # مدة صلاحية الإجابة (ثانية)
  max_entries: 512  # حد LRU
```

- **مفتاح دقيق**: SHA-256 على الحمولة الصادرة الكاملة (المزوّد، النموذج، الرسائل، الحرارة، الأدوات) — الإصابة تعني أن البائع كان سيجيب نفس الإجابة نفسها.
- **لكل مرشّح مفتاحه**: إجابة `openai/*` المخزّنة لا تُقدَّم أبدًا لطلب وجّه إلى `anthropic/*`.
- **إيصال صادق**: الإصابة تظهر كـ `cache-hit` و`"cached": true` — بلا نداء للبائع، بلا خصم من الميزانية، بلا كتابة في متعقّب الصحة.
- **آمنة للوكلاء**: الردود التي تحمل `tool_calls` لا تُخزَّن أبدًا؛ البثّ يتجاوز الذاكرة في هذه النسخة.
- **تحكّم لكل طلب**: `metadata={"cache": "bypass"}` يتجاوز الذاكرة، و`"refresh"` يعيد التحقق من نداء واحد.
- **رؤية كاملة**: `zyko cache` يعرض الإدخالات ونسبة الإصابة (`--json` دائمًا JSON صالح)، و`--clear` يفرّغها.

20 اختبارًا جديدًا — **375 اختبارًا ناجحًا**.

## ما الجديد في 0.3.8؟ (+xAI وTogether AI — عشرة مزوّدين مسجّلين)

مزوّدان جديدان متوافقان مع OpenAI على نفس رافعة الفئة (~30 سطرًا)، كل حقول الكتالوج مأخوذة من التوثيق الرسمي لكل بائع (الـ slugs ونوافذ السياق والأسعار المعلنة):

- **`xai`** (`XAI_API_KEY`) — `grok-4.7` (سياق 500 ألف، $2/$6)، `grok-4.3` (سياق مليون، $1.25/$2.50)، `grok-build-0.1` (سياق 256 ألف، $1/$2).
- **`together`** (`TOGETHER_API_KEY`) — `Kimi-K3`، `GLM-5.3`، `GLM-5.3-Flash`، `DeepSeek-V4.1-Flash`، `gpt-oss-120b`، `Qwen3.5-9B` — باب واحد لنماذج مفتوحة بأسعار منافسة وسياقات تصل مليون رمز.

8 اختبارات جديدة (شكل الطلب، سلامة الكتالوج، حلّ المفاتيح) — **355 اختبارًا ناجحًا**.

## ما الجديد في 0.3.7؟ (سباق موت خادم MCP أصبح مُنمّطًا على كل منصة)

التقطتها ذراع macOS/py3.11 في CI بعد 0.3.6: عندما يموت خادم MCP بين `write()` و`drain()` لدى العميل، كان `drain()` يرمي `ConnectionResetError` خام في بعض المنصات بدلاً من `MCPError` الموثّقة. الآن يسلك المسارَان (`_request` و`_notify`) سلوكًا واحدًا حتميًا على Linux وmacOS وWindows: خطأ مُنمّط واحد `MCPError("closed the stream")`، مع تنظيف الطلب المعلّق فورًا (يزيل تحذير "Future exception was never retrieved"). **347 اختبارًا ناجحًا**.

## ما الجديد في 0.3.6؟ (امتثال التنسيق لأداة ruff 0.17)

جولة نظافة صفرية التأثير: أداة ruff 0.17 غيّرت سلوك التنسيق (وأصبحت تنسّق كتل الكود داخل Markdown أيضًا). أُصلحت أربعة ملفات خارج نطاق CI الحالي (`README.md` و`docs/API.md` و`docs/PROVIDERS.md` و`examples/04_agent_tools.py`) حتى لا ينكسر الـ lint مستقبلًا عند توسيع النطاق أو ترقية الأداة. لا تغيير في أي سطر تحت `src/` أو `tests/` — **347 اختبارًا ناجحًا** كما هي، و`ruff format --check .` نقي الآن على كامل الشجرة (97 ملفًا).

## ما الجديد في 0.3.5؟ (توثيق عميق للمطوّرين)

ثلاثة مستندات مرجعية جديدة، كل توقيع فيها مأخوذ حرفيًا من الكود (لا اختراع):

- **[مرجع API](docs/API.md)** — العميل `Zyko`، محرك التوجيه وإيصاله، المزوّدون العشرة، `PolicyEngine`، البوابة، MCP بالاتجاهين، الوكلاء، الإعدادات والمسارات، شجرة الاستثناءات، خريطة CLI الكاملة.
- **[المعمارية](docs/ARCHITECTURE.md)** — مخططات mermaid لدورة حياة الطلب، لماذا الإيصال قابل للتحقق بالبناء، جودة مُقاسة لا مُدّعاة، الحوكمة على كل نداء، وقابلية النقل بين المنصات.
- **[دليل المزوّدين](docs/PROVIDERS.md)** — الاكتشاف التلقائي، إعداد YAML، أي بائع متوافق مع OpenAI، تسعير يغذّي التوجيه، المرونة (إعادة المحاولة/القاطع/البدائل)، وسير العمل بلا مفاتيح.

## ما الجديد في 0.3.4؟ (إصلاح CI الحقيقي: الأخضر على المنصات الثلاث)

جولة 0.3.3 أصلحت بوابة الأمان محليًا — لكن CI على GitHub كان ما يزال أحمر بثلاث مشاكل حقيقية لم يكشفها Linux وحده:

- **`bandit: unrecognized arguments: --exit-zero-on-skipped`** — العلم أُزيل في bandit الحديث؛ حُذف من أمر CI.
- **اختبار علامة Termux كان يفترض أن `sys.platform == linux`** — الآن إشارة `PREFIX=com.termux` حاسمة بذاتها على كل الأنظمة (إصلاح إنتاجي وليس اختباريًا فقط).
- **اختبار XDG كان يفترض سلوك Linux على macOS/Windows** — يثبّت الآن فرع LINUX صراحةً كما يفعل اختبار macOS.

النتيجة: **الأخضر على Ubuntu + macOS + Windows × Python 3.11/3.12/3.13** + بوابة أمان تعمل فعلًا.

## ما الجديد في 0.3.3؟ (بوابة الأمان التي لم تكن تعمل أبدًا)

جولة 0.3.2 أضافت بوابة أمان في CI — لكنها كانت ستفشل عند أول تشغيل حقيقي: **bandit لا يقرأ `pyproject.toml` أصلًا** (حتى الإصدار 1.9.x)، فتُتجاهل الاستثناءات الموثّقة (B101/B311/B404) بصمت ويظهر 11 نتيجة LOW. الإصلاح: ملف `.bandit.yml` حقيقي بتعليقات التبرير، يستهلكه CI و`make security` معًا، وحُذف قسم `[tool.bandit]` المضلل. إضافة إلى **10 اختبارات حوافّ جديدة** (الإجمالي 347): ربط أخطاء 500 الداخلية في البوابة، رؤوس `Content-Length` الكاذبة، انقطاع العميل أثناء البث (RST) مع بقاء الخادم صحيًا، إظهار MCP للأخطاء غير المتوقعة كـ `isError` دون انهيار الحلقة، جولة `zyko_chat` مع إيصال التوجيه، ربط `default_policy`، نقطة دخول `python -m zyko.mcp.server`، تسوية التكلفة/الزمن Degenerate، وقفزات القاطع/السياسة في `astream_route`. التغطية 98% والأسطر غير المغطاة 84 → 69.

## ما الجديد في 0.3.2؟ (جولة تقييم كاملة: تغطية + lint + أمان)

جولة جودة شاملة على كامل الشيفرة — تحليل تغطية، فحص lint، تدقيق أمني — مع إصلاح كل النتائج واختبارها:

| الخلل الحقيقي المُكتشف | المعالجة |
|---|---|
| **`Settings.load()` كان يلوّث الإعدادات الافتراضية العامّة**: `_deep_merge` يشارك القواميس المتشعبة مع ثابت `DEFAULTS`، فأول استدعاء بمتغيرات `ZYKO_*` كان يُعيد كتابتها **بشكل دائم** — كل الاستدعاءات اللاحقة ترث بيئة أول استدعاء (تلوّث عمليات البوابة طويلة الأمد والاختبارات معًا) | نسخ عميق للافتراضيات عند كل تحميل + اختبار انحدار مخصص |
| **`policies_dir()`/`agents_dir(create=True)` لا ينشئان المجلد المُعاد** — الأب فقط | `create=True` يضمن الآن وجود المجلد الطرفي نفسه |
| **`PolicyEngine` كان ينهار بـ `AttributeError` خام** على أقسام سياسة تالفة (`defaults`/`privacy`/`rate_limit`/`audit` بقيمة غير قاموس) قبل أن تصل آلية التحذيرات | الأقسام التالفة تتحلل إلى التحذيرات الموثّقة بدل الانهيار |

نتائج الجولة: **التغطية 92% → 98%** (3491 عبارة) · الاختبارات 230 → **337** (107 اختبارات جديدة: دورة حياة MCP كاملة، حوكمة البث وأثر التدقيق `estimated: false`، قافز الدائرة والسياسة، اكتشاف المنصات، مصفوفات المزوّدين، رموز خروج POSIX 130/141) · `ruff check` و`ruff format` نظيفان على كامل الشجرة · **بوابة أمان في CI**: `bandit` (0 نتائج) + `pip-audit` على التبعيات المعلنة · **سكربتات التثبيت عادت** لجذر المستودع.

## ما الجديد في 0.3.1؟ (تصلّب الـ CLI + جولة تغطية)

جولة تقييم مستهدفة شغّلت **كل أمر CLI فعليًا** (وضع العرض) وطاردت الأعطال التي لا تراها الاختبارات وحدها:

| العطل المُكتشف | المعالجة |
|---|---|
| **`zyko cost --json` كان يطبع نصًا لا JSON** عند غياب سجل التدقيق → كل الأنابيب اللاحقة (`\| jq`، خطوات CI) تنكسر | فراغ السجل يُصدر **نفس مخطط JSON** للتقرير الحقيقي؛ رسالة `[INFO]` بقت للأمر العادي فقط |
| **`zyko serve` على منفذ مشغول كان ينهار بـ traceback خام** (`OSError: Address already in use`) | ردّ ودّي `[FAIL] cannot start gateway` + تلميح عملي (جرّب `--port 8788`) |
| **`zyko doctor \| head` كان يطبع `BrokenPipeError` traceback** | خروج هادئ بالرمز **141** (128+SIGPIPE) كأداة POSIX محترفة |
| **ويندوز: كونسول cp1252 القديم كان ينهار على `—`/`·`/الحروف العربية** | حارس ترميز عند الإقلاع (`errors="replace"`) — الحرف يُستبدل بدل قتل الأمر |

نتائج الجولة: **التغطية 89% → 92%** (بروتوكول MCP والنواة وأدوات الوكلاء 95–100%) · الاختبارات 203 → **230** (ملف `tests/test_hardening.py`: حواف الحاسبة، هروب مساحة العمل، خرائط أخطاء HTTP الكاملة، توقيتات MCP، تبديل نواة Rust) · تدقيق أمان أكّد أن أدوات الخطر (`shell`) تبقى **مقفلة** ما لم تُسمَّ صراحةً في `tools.allow` — حتى مع `allow: ["*"]`.

## ما الجديد في 0.3.0؟ (جولة تقييم وعلاج)

جولة إعادة تقييم كاملة كشفت وعالجت **أربع** ثغرات وظيفية حقيقية، وأضافت أوامر رؤية جديدة:

| الثغرة المكتشفة | المعالجة |
|---|---|
| **التثبيت الصريح للنموذج كان مُهمَلًا**: `zyko ask --model openai/gpt-4o` كان يتجاهله الموجّه ويختار أفضل مرشّح! | `candidates_for()` تُلزم المسار بالنموذج المطلوب (`provider/model` أو `model` مجرد أو `provider/*`)، وتفشل فورًا برسالة مفيدة إن لم يتوفر، والإيصال يسجّل `requested_model` للتحقق اللاحق |
| **رفض 401 كان يُفسد اتصالات keep-alive في البوابة**: جسم الطلب غير المقروء يُفسَّر كسطر طلب تالٍ → 501 | جسم الطلب يُستهلك قبل أي ردّ خطأ — اختبار HTTP حقيقي بمقبس فعلي يثبت الدورة الكاملة (401 ثم 200 على نفس الاتصال) |
| **إطار JSON-RPC تالف كان يُسقط خادم MCP بالكامل** | الرد بـ `PARSE_ERROR (-32700)` حسب مواصفة JSON-RPC والاستمرار في الخدمة؛ كما صار `zyko_models` يعرض النماذج **المتاحة فعليًا** (مُرشّحة بالسياسة) لا كتالوجًا ثابتًا |
| **ذاكرة الجلسات كانت ميزة «ميتة»**: SQLite كاملة بلا أي رؤية في CLI وتغطية 25% | أمر جديد `zyko sessions list/show/rm/clear` + تغطية 98% |

إضافات: **`zyko cost`** — تقرير إنفاق وحوكمة من سجل التدقيق (حسب اليوم، حسب المرشّح، تقديري مقابل مُبلَّغ من المورّد، قواعد الحجب) · التغطية 81% → **89%** · الاختبارات 133 → **203**.

## التثبيت

**الطريق الأسرع — سكربتات جاهزة في جذر المستودع:**

```bash
# Linux / macOS / Termux — يشغّل ZYKO فورًا (ينشئ بيئة معزولة عند أول استخدام)
./zyko.sh ask "مرحبًا" --demo

# أو تثبيت دائم ببيئة معزولة (~/.zyko/venv)
./install.sh            # أضف --dev لأدوات الاختبار

# Windows (PowerShell أو cmd أو مشغّل فوري)
powershell -ExecutionPolicy Bypass -File install.ps1
install.bat
zyko.cmd ask "hello" --demo

# Docker — بوابة متوافقة مع OpenAI بحاوية واحدة
docker build -t zyko . && docker run --rm -p 8787:8787 zyko
```

**أو عبر pip مباشرة:**

```bash
pip install git+https://github.com/tibatechapp-ship-it/zyko.git

# من المصدر (كل المنصات)
git clone https://github.com/tibatechapp-ship-it/zyko.git && cd zyko
pip install -e .[dev]
```

للمطوّرين: `make test` · `make coverage` · `make lint` · `make security` · `make bench-demo` (راجع [Makefile](Makefile)).

التبعيات الأساسية: `httpx` و`PyYAML` فقط — كلتاهما Python خالص، لذا **لا شيء يُترجم** على أي منصة، بما فيها Termux.

### على أندرويد/Termux

```bash
pkg install -y git && git clone https://github.com/tibatechapp-ship-it/zyko.git
cd zyko/android && bash install-termux.sh
```

راجع [android/README.md](android/README.md) للنموذج المحلي عبر Ollama على الهاتف، وويدجت البوابة الدائمة، وواجهة Kivy.

## ابدأ في 60 ثانية

```bash
# أسرع تجربة — بلا مفاتيح، بلا شبكة، وضع عرض حتمي:
zyko ask "مرحبًا يا زيكو" --demo --explain
zyko route "ملخص هذا الملف" --demo

# ثم بمزوّد حقيقي:
export OPENAI_API_KEY=sk-...        # أو أنشئ ollama محليًا ليعمل بلا مفاتيح

zyko ask "اشرح MCP في سطر واحد" --explain   # إجابة + قرار التوجيه
zyko serve                                   # بوابة متوافقة مع OpenAI
zyko doctor                                  # تشخيص البيئة والمفاتيح
```

وبرمجيًا:

```python
from zyko import Zyko

zk = Zyko()  # المفاتيح من البيئة
outcome = zk.ask("مرحبًا")
print(outcome.response.text)
print(outcome.receipt["chosen"])  # القرار المُوجَّه — قابل للتحقق

# وكيل بأدوات:
agent = zk.agent({"name": "calc", "tools": ["calculator"], "max_steps": 6})
print(agent.run_sync("كم 47 × 16 × 7؟").output)
```

## سطر الأوامر

| أمر | الوظيفة |
|---|---|
| `zyko ask PROMPT` | إكمال لمرة واحدة عبر الموجّه (مع `--receipt` و`--explain`) |
| `zyko chat` | محادثة تفاعلية بذاكرة جلسات (SQLite) |
| `zyko route PROMPT` | **خطة التوجيه فقط** — بلا أي نداء API |
| `zyko models` | كل النماذج المتاحة مع درجاتها وأسعارها |
| `zyko policy check/show/redact` | التحقق من السياسات وعرضها وتجربة الحجب |
| `zyko run AGENT.yaml TASK` | تشغيل وكيل من تعريف YAML (مع `--trace`) |
| `zyko serve` | بوابة `/v1/chat/completions` متوافقة مع OpenAI (بما فيها البث SSE) |
| `zyko mcp serve` | **اعرض ZYKO نفسه كخادم MCP** عبر stdio |
| `zyko mcp tools -- CMD` | فحص أدوات أي خادم MCP |
| `zyko bench` | المقياس المرجعي القابل لإعادة الإنتاج (`--repeats N` لوسائط أثبت، و`--update-ledger` يغذّي الموجّه) |
| `zyko traces` | **سجل التتبّع المدمج**: آخر spans، `--trace <id>` لكل نداء واحد، `--json` دائمًا صالح |
| `--demo` (مع أغلب الأوامر) | **وضع عرض بدون مفاتيح ولا شبكة** عبر مزوّد المحاكاة الحتمي — يمرّ بالمسار الحقيقي كله: توجيه، سياسة، إيصالات، بث |
| `zyko doctor` / `zyko info` / `zyko version` | تشخيص البيئة، المفاتيح، والمسارات |

## المزوّدون

OpenAI · Anthropic · Google Gemini · Groq · Mistral · DeepSeek · OpenRouter · **Together AI** · **xAI (Grok)** · **Ollama (محلي/بلا مفاتيح)** — والمعمارية موحّدة: إضافة مزوّد متوافق مع OpenAI = فئة من ~30 سطرًا.

## التوثيق

| المستند | ماذا يغطي |
|---|---|
| [مرجع API](docs/API.md) | كل التوقيعات من الكود: `Zyko`، `Router`، السياسات، البوابة، MCP، الوكلاء، الاستثناءات، خريطة CLI |
| [المعمارية](docs/ARCHITECTURE.md) | دورة حياة الطلب، إيصال التوجيه القابل للتحقق، الطبقات ونقاط الامتداد (مخططات mermaid) |
| [دليل المزوّدين](docs/PROVIDERS.md) | كل المزوّدين، إعداد YAML، أي بائع متوافق مع OpenAI، التسعير والمرونة وسير العمل بلا مفاتيح |
| [الخطة الاستراتيجية](docs/STRATEGY.md) | قياس حي مقابل LangChain/CrewAI/AutoGen/LangGraph، جاهزية الإنتاج، عيوب المنافسين وخارطة الصدارة |

## السياسات (Policy-as-Code)

```yaml
version: 1
name: strict
defaults:
  budget_usd_per_day: 2.0
  max_tokens_per_request: 2048
models:
  deny: ["*opus*"]
privacy:
  redact: [email, phone, credit_card, iban, ssn]
tools:
  deny: ["shell*"]
rate_limit:
  requests_per_minute: 30
```

```bash
zyko ask "..." --policy strict    # كل نداء يمر عبر السياسة: سقف، حجب، سماح، تدقيق
```

تجربة فورية: `zyko policy redact "card 4111 1111 1111 1111 mail bob@corp.com"`

## النواة الاختيارية (Rust)

النواة النقية Python تُغطي كل الوظائف. لمن يريد سرعة إضافية، `rust/zyko-kernel` (PyO3) تُسرّع الحسابات الساخنة **بنفس الدلالات تمامًا** (مضمونة باختبار تعادل مخصص)، وتُبنى اختياريًا:

```bash
pip install maturin && maturin develop --release -m rust/zyko-kernel/Cargo.toml
zyko info   # kernel backend: rust
```

## الاختبارات والجودة

```bash
pip install -e .[dev]
pytest -q            # 463 اختبارًا: توجيه، سياسات، MCP (بعمليات فرعية حقيقية)، بوابة، وكلاء، مزوّدون (HTTP مُحاكى)، تصلّب CLI، وضع العرض، مخرجات منظمة، تتبّع
pytest --cov=src/zyko   # تغطية 98%
ruff check src tests && ruff format --check src tests
make security        # bandit + pip-audit (نفس بوابة CI)
```

يعمل CI على ubuntu/windows/macos × Python 3.11/3.12/3.13 + فحص Rust + تجربة دخان للـCLI + **وظيفة أمان (bandit + pip-audit)** — ويعمل أول تشغيل **بلا أي مفاتيح** عبر التراجع التلقائي لمزوّد العرض المدمج.

## الأمان

- **حوكمة مدمجة**: أدوات الخطر (`shell`) تبقى مقفلة ما لم تُسمّى صراحةً في `tools.allow` — حتى مع `allow: ["*"]`؛ خادم MCP يُطلق عبر `exec` لا عبر shell؛ `http_get` يرفض المخططات غير HTTP؛ حجب PII حتمي (بفحص Luhn).
- **بوابة أمان في CI**: `bandit` (0 نتائج؛ استثناء `shell=True` المقصود موثّق داخليًا بـ `nosec` مُحكوم) + `pip-audit` على التبعيات المعلنة.

بلّغ ثغرة أمنية خاصًة عبر [SECURITY.md](SECURITY.md) — لا تفتح issue عامًا للثغرات.

## الاقتباس العلمي

إذا استخدمت ZYKO في بحث، اقتبسها عبر [CITATION.cff](CITATION.cff) (يدعمها GitHub في زر «Cite this repository»).

## خارطة الطريق

انظر [الخطة الاستراتيجية](docs/STRATEGY.md) — قياس حي مقابل المنافسين + جاهزية الإنتاج + خطة 18–24 شهرًا. التالي: نشر PyPI، مُصدّر OpenTelemetry اختياري، مصادقة متعددة المستخدمين للبوابة، أساسيات RAG، ووكلاء متعددون بحوكمة.

## الترخيص

Apache-2.0 — راجع [LICENSE](LICENSE).

</div>

---

<div dir="ltr">

# ZYKO — Universal AI Orchestration Platform (English)

**v0.4.1** · Multi-provider routing with **verifiable** decisions · **Policy-as-Code** governance · **MCP-native** agents · **built-in tracing** — running on **Linux, Windows, macOS, Android and Termux** with a pure-Python core (only `httpx` + `PyYAML`).

## What's new in 0.4.1 — built-in tracing: what others sell as a hosted service, ZYKO ships locally with zero dependencies

Observability was the biggest remaining feature gap versus the competition: LangChain sells it as LangSmith; Langfuse/AgentOps require an external SDK and a cloud account. ZYKO now **traces every routed call** with OpenTelemetry-style spans (trace/parent ids, durations, statuses, attributes) — **zero new required dependencies**, a JSONL file **you own on your disk**, and an inspection command in the same CLI:

```python
from zyko import Zyko

zk = Zyko()
with zk.tracer.span("my-rag", corpus="support-docs"):  # your parent span
    zk.ask("why is my invoice late?")  # router span nests automatically
# later: zyko traces --last 20   |   --json   |   --trace <id>
```

- `zyko traces` — a time table, `--json` always valid JSON (the `cost`/`cache` contract), `--trace <id>` for every span of one request, plus `--clear` and `--file`.
- **Tracing can never break a request**: sink write failures degrade to one log line; an abandoned stream (client disconnect) still closes its span as `cancelled`.
- Bounded rotation (live file + two `.1`/`.2` backups) so a long-lived gateway can never fill the disk.
- Disable with `ZYKO_TRACING=0` or `tracing.enabled: false` — the same API, just no writes.

25 new tests (`tests/test_observability.py`) — **463 tests passing**.

## What's new in 0.4.0 — structured output: the most-competitive feature LangChain/CrewAI/AutoGen had and ZYKO didn't

A capability review against LangChain (`with_structured_output`), CrewAI (Pydantic task outputs), AutoGen (`response_format`) and LiteLLM (`response_format` passthrough) found the biggest remaining gap: **schema-constrained answers**. ZYKO now returns *validated data or a typed error* — never a raw string you must `json.loads` by hand — with an automatic repair round that feeds the exact validation errors back to the model. **Zero new required dependencies**; Pydantic is optional (`zyko[structured]`), not a requirement:

```python
from zyko import Zyko

zk = Zyko()
out = zk.structured(
    "order 42 details?",
    schema={
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "status": {"type": "string", "enum": ["open", "shipped"]},
        },
        "required": ["id", "status"],
    },
)
out.data  # {"id": 42, "status": "shipped"} — validated, or a typed StructuredOutputError
out.repaired  # did a repair round kick in?
```

- **Pure-Python JSON Schema validator**: types, `enum`/`const`, numeric/string bounds, `pattern`, basic formats, nested arrays/objects, `allOf`/`anyOf`/`oneOf`, and local `$ref`/`$defs` resolution with cycle guards — what Pydantic schemas always need. Python's classic trap is caught: `True` is **not** an integer here.
- **Automatic repair**: on failure the real errors (with paths like `$.id`) go back to the model for one configurable repair round (`max_repairs`), then a typed error carries `errors` + `text`.
- **Mess-proof extractor**: survives surrounding prose, markdown fences and `<think>` blocks (DeepSeek style).
- **Optional native mode**: `native=True` sends `response_format: {"type": "json_schema", …}` to vendors that support it (OpenAI, Groq, Mistral, DeepSeek, OpenRouter, Together, xAI); a vendor that rejects it just falls through routing.
- **Cross-provider support**: Google maps it to `generationConfig.responseMimeType` (+ `responseSchema`); the OpenAI-compatible gateway accepts `response_format` and 400s non-objects.
- **Layer-safe**: malformed schema → immediate `SchemaSpecError` (caller bug); model failure → `StructuredOutputError`; cache keys (basis v2) include `response_format` so a cached free-text answer is never served for a structured call.

63 new tests (`tests/test_structured.py`) — **438 tests passing**.

## What's new in 0.3.9 — response cache: the #1 gap versus the competition

A competitive-matrix review against LiteLLM and Portkey showed ZYKO already matched their retries, failover, breakers, budgets and PII governance — but shipped **no response cache**. It now ships behind one policy section, off by default:

```yaml
# in your policy file (Policy-as-Code):
cache:
  enabled: true
  ttl_s: 300        # seconds an answer stays valid
  max_entries: 512  # LRU bound
```

- **Exact key**: SHA-256 over the full outbound payload (provider, model, messages, temperature, tools) — a hit means the vendor would have answered the same thing.
- **Per-candidate keys**: a cached `openai/*` answer is never served for a request that routed to `anthropic/*`.
- **Honest receipts**: hits surface as `cache-hit` attempts and `"cached": true` — no vendor call, no budget charge, no health write.
- **Agent-safe**: `tool_calls` responses are never stored; streaming bypasses the cache in v1.
- **Per-call control**: `metadata={"cache": "bypass"}` skips it; `"refresh"` revalidates a single call.
- **Full visibility**: `zyko cache` shows entries and hit rate (`--json` is always valid JSON); `--clear` empties it.

20 new tests — **375 tests passing**.

## What's new in 0.3.8 — +xAI (Grok) and +Together AI: ten registered providers

Two new OpenAI-compatible vendors on the same ~30-line subclass lever. Every catalog fact comes from each vendor's official documentation (slugs, context windows, list prices):

- **`xai`** (`XAI_API_KEY`) — `grok-4.7` (500k ctx, $2/$6), `grok-4.3` (1M ctx, $1.25/$2.50), `grok-build-0.1` (256k ctx, $1/$2).
- **`together`** (`TOGETHER_API_KEY`) — `Kimi-K3`, `GLM-5.3`, `GLM-5.3-Flash`, `DeepSeek-V4.1-Flash`, `gpt-oss-120b`, `Qwen3.5-9B` — one key to a deep open-model catalog with contexts up to 1M tokens.

8 new tests (request shape, catalog integrity, key-env resolution) — **355 tests passing**.

## What's new in 0.3.7 — MCP dead-server race now fails typed, on every OS

Caught by the macOS/py3.11 CI leg after 0.3.6: when an MCP server dies between the client's `write()` and `drain()`, `drain()` used to leak a raw `ConnectionResetError` on some platforms instead of the documented `MCPError`. Both paths (`_request`, `_notify`) now behave identically and deterministically on Linux, macOS and Windows — one typed `MCPError("closed the stream")`, with the pending future cleaned up immediately (also removing the "Future exception was never retrieved" warning). **347 tests passing**.

## What's new in 0.3.6 — ruff 0.17 format compliance

Zero-impact hygiene round: ruff 0.17 changed formatting behaviour (and now formats Python code blocks inside Markdown too). Four files outside CI's current scope were normalized — `README.md`, `docs/API.md`, `docs/PROVIDERS.md`, `examples/04_agent_tools.py` — so a future scope extension or toolchain upgrade cannot break `lint`. Not a single line under `src/` or `tests/` changed — **347 tests passing** as before, and `ruff format --check .` is now clean across the whole tree (97 files).

## What's new in 0.3.5 — deep developer documentation

Three new reference documents, every signature taken verbatim from the code (nothing invented):

- **[API reference](docs/API.md)** — the `Zyko` client, the router and its receipt, all ten providers, `PolicyEngine`, the gateway, MCP in both directions, agents, settings & paths, the exception tree, the full CLI map.
- **[Architecture](docs/ARCHITECTURE.md)** — mermaid diagrams of the request lifecycle, why the receipt is verifiable by construction, measured (not claimed) quality, governance on every call, and cross-platform portability.
- **[Providers guide](docs/PROVIDERS.md)** — auto-discovery, YAML config, any OpenAI-compatible vendor, pricing that feeds routing, resilience (retries/breaker/fallbacks), and keyless workflows.

## What's new in 0.3.4 — the real CI fix: green on all three platforms

The 0.3.3 round fixed the security gate locally — but CI on GitHub was still red with three real issues Linux alone could never catch:

- **`bandit: unrecognized arguments: --exit-zero-on-skipped`** — the flag was removed in modern bandit; dropped from the CI command.
- **the Termux-marker test assumed `sys.platform == linux`** — a `com.termux` PREFIX is now definitive on every OS (a production fix, not just a test patch).
- **the XDG test assumed Linux behaviour on macOS/Windows** — it now pins the LINUX branch explicitly, like the macOS test does.

Result: **green on Ubuntu + macOS + Windows × Python 3.11/3.12/3.13** with a security gate that actually runs.

## What's new in 0.3.3 — the security gate that never worked

The 0.3.2 round added a CI security job — but it would have failed on its first real run: **bandit does not read `pyproject.toml` at all** (through 1.9.x), so the documented suppressions (B101/B311/B404) were silently ignored and 11 LOW findings surfaced. Fixed with a real `.bandit.yml` (justification comments included) consumed by both CI and `make security`; the misleading `[tool.bandit]` section is gone. Plus **10 new edge-path tests** (347 total): gateway 500 mapping for unexpected router exceptions, lying `Content-Length` headers, mid-stream client disconnect (RST) with the worker staying healthy, the MCP server surfacing unexpected exceptions as `isError` without crashing the loop, the `zyko_chat` round-trip with a routing receipt, `default_policy` wiring, the `python -m zyko.mcp.server` entrypoint, degenerate cost/latency normalisation, and breaker/policy skips in `astream_route`. Coverage holds at 98% with uncovered lines down 84 → 69.

## What's new in 0.3.2 — full evaluation round (coverage + lint + security)

A complete quality round across the whole codebase, every finding fixed and regression-tested:

- **`Settings.load()` leaked overrides into module-level defaults.** `_deep_merge` shared nested dicts with the `DEFAULTS` constant, so the first `load()` with `ZYKO_*` env vars (or YAML values) permanently rewrote the defaults for the whole process — later calls inherited the first call's environment, contaminating long-lived gateway processes and unrelated tests. Defaults are now deep-copied per call.
- **`policies_dir()` / `agents_dir(create=True)` did not create the returned directory** — only its parent. `create=True` now guarantees the leaf exists.
- **`PolicyEngine` crashed with a raw `AttributeError` on malformed policy sections** (`defaults`/`privacy`/`rate_limit`/`audit` holding a non-mapping value) before the schema-warnings machinery could report them. Malformed sections now degrade to the documented warnings.

Round results: **coverage 92% → 98%** · tests 230 → **337** (107 new: full MCP client lifecycle, streaming governance with vendor-usage audit `estimated: false`, breaker/policy routing paths, platform detection, provider payload matrices, POSIX exit codes 130/141) · `ruff check` + `ruff format` clean across the tree · a **security gate in CI** (`bandit` 0 findings + `pip-audit` on declared deps) · **install scripts restored** to the repo root (`zyko.sh`, `zyko.cmd`, `install.sh`/`install.bat`/`install.ps1`, `Makefile`, `Dockerfile`).

## What's new in 0.3.1 — CLI robustness + coverage round

A targeted audit ran **every CLI command for real** (demo mode) and hunted the failures tests alone cannot see:

- **`zyko cost --json` printed `[INFO]` text instead of JSON** when no audit log existed — breaking every downstream consumer (`| jq`, CI steps). The empty-log branch now emits the exact report schema; the friendly `[INFO]` stays for human mode.
- **`zyko serve` on a busy port crashed with a raw `OSError` traceback** → now a friendly `[FAIL] cannot start gateway` with an actionable hint.
- **`zyko doctor | head` printed a `BrokenPipeError` traceback** → the CLI now exits quietly with code **141** (128 + SIGPIPE), like every well-behaved POSIX tool.
- **Windows hardening**: legacy cp1252 consoles can no longer crash on em-dashes, `·` separators, or Arabic output (`errors="replace"` guard at startup).

Round results: **coverage 89% → 92%** (MCP protocol, kernel swap and agent tools at 95–100%) · tests 203 → **230** (new `tests/test_hardening.py`: calculator edges, workspace escapes, full HTTP error maps, MCP timings, Rust-kernel swap) · a security audit re-confirmed danger tools (`shell`) stay **locked** unless explicitly named in `tools.allow` — even under `allow: ["*"]`.

## Four differentiators

1. **Verifiable routing** — every response carries a *routing receipt*: the full candidate ranking with score components (quality/cost/latency) and published weights. Replay any past decision offline.
2. **Honest quality scores** — ledger scores come only from the reproducible benchmark (`zyko bench`, fixed seed, objective graders), never vendor marketing tables. No data yet → neutral 0.5 for everyone.
3. **Policy-as-Code** — daily USD budget, deterministic PII redaction (email/phone/card/IBAN/SSN with Luhn), model & tool allowlists, rate limits, JSONL audit trail — one YAML enforced on every call.
4. **MCP-first** — ZYKO consumes MCP servers as agent tools *and* exposes itself as one (`zyko mcp serve`).

## Design lineage — patterns from the big projects

| Adopted pattern | Source |
|---|---|
| Unified OpenAI-format adapters, exponential-backoff retries, `Retry-After` honoring | [LiteLLM](https://github.com/BerriAI/litellm) |
| Meta-provider `provider/model` naming, attribution headers | [OpenRouter](https://openrouter.ai) |
| Routing quality derived from reproducible benchmarks, not marketing tables | [RouteLLM](https://github.com/lmcache/routellm) |
| Config-as-code gateway governance (budgets, allowlists, audit) | [Portkey Gateway](https://github.com/Portkey-AI/gateway) |
| An open protocol unifying agent tooling (client + server) | [Model Context Protocol](https://modelcontextprotocol.io) |

ZYKO's edge is not reinvention but **verifiability**: routing receipts you can replay offline, an honest reproducible quality ledger, and governance enforced on every call — on every platform.

## Quickstart

```bash
# Linux / macOS / Termux — instant runner (isolated venv on first use):
./zyko.sh ask "hello" --demo
# Windows: zyko.cmd ask "hello" --demo   ·   Docker: docker build -t zyko . && docker run -p 8787:8787 zyko

# Or install permanently:
pip install git+https://github.com/tibatechapp-ship-it/zyko.git

# Fastest first run — no keys, no network (deterministic demo mode):
zyko ask "hello zyko" --demo --explain
zyko bench --demo

# Then with a real provider:
export OPENAI_API_KEY=sk-...        # or run Ollama locally for a keyless setup
zyko ask "Explain MCP in one line" --explain
zyko serve                          # OpenAI-compatible gateway on :8787
```

```python
from zyko import Zyko

outcome = Zyko().ask("hello")
print(outcome.response.text, "←", outcome.receipt["chosen"])
```

## Highlights

- **CLI**: `ask` · `chat` · `route` (planning-only) · `models` · `policy` · `run` (agents) · `sessions` (inspect SQLite memory) · `cost` (spend & governance report) · `serve` · `mcp` · `bench` · `doctor` — argparse-only, zero CLI dependencies. `--demo` runs the whole stack offline through a deterministic mock provider (no keys, no network). Explicit `--model provider/name` pins are enforced by the router, not ignored.
- **Gateway**: stdlib HTTP server, streaming SSE included, `zyko.receipt` embedded in responses and chunks.
- **Agents**: ReAct loop, builtin tools (calculator/file/http/shell-guarded), MCP tools namespaced as `server__tool`, SQLite session memory, step/timeout/policy guards.
- **Providers**: OpenAI · Anthropic · Google · Groq · Mistral · DeepSeek · OpenRouter · Together AI · xAI (Grok) · Ollama(local). Retries with backoff, circuit breakers, latency EWMA.
- **Android/Termux**: one-command installer, offline models via Ollama, widget shortcut for the gateway, optional Kivy UI. Nothing compiles.
- **Rust kernel (optional)**: PyO3 accelerator with enforced Python-parity; graceful fallback everywhere.

## Documentation

| Document | Covers |
|---|---|
| [API reference](docs/API.md) | every signature from the code: `Zyko`, `Router`, policies, gateway, MCP, agents, exceptions, CLI map |
| [Architecture](docs/ARCHITECTURE.md) | request lifecycle, the verifiable receipt, layers and extension points (mermaid diagrams) |
| [Providers guide](docs/PROVIDERS.md) | all vendors, YAML config, any OpenAI-compatible endpoint, pricing & resilience, keyless workflows |
| [Strategy](docs/STRATEGY.md) | live benchmark vs LangChain/CrewAI/AutoGen/LangGraph, production-readiness audit, competitor weaknesses, roadmap to the top |

## Tests

`pytest -q` → 463 tests (98% coverage) covering routing (incl. snapshot/parity and explicit model pinning), policy (incl. schema warnings and malformed-document degradation), structured output (validation + repair + native mode), built-in tracing (spans, sinks, rotation, router + CLI integration), MCP over real subprocesses plus in-memory server frames and the full client lifecycle (timeouts, server errors, pagination, closed streams), the gateway over a real HTTP socket (auth + keep-alive integrity + 502 upstream errors), agents, every provider adapter against canned HTTP, session memory, the audit-based cost report, streaming cost accounting, `Retry-After` resilience, CLI robustness (broken pipes, busy ports, JSON-only `--json`), tool-loop failure modes, and the keyless demo mode. CI runs the matrix on Linux/Windows/macOS + Python 3.11/3.12/3.13, plus lint (`ruff check` + `ruff format --check`), a security job (`bandit` + `pip-audit`), and a Rust kernel check.

## Security

- **Built-in governance**: danger tools (`shell`) stay locked unless explicitly named in `tools.allow` — even under `allow: ["*"]`; the MCP client spawns servers via `exec`, never a shell; `http_get` rejects non-HTTP schemes; deterministic PII redaction with Luhn validation.
- **CI security gate**: `bandit -c .bandit.yml -r src/zyko` (0 findings; the intentional, policy-gated `shell=True` is documented inline with a scoped `# nosec`) and `pip-audit --skip-editable` over the declared dependency surface (`httpx`, `PyYAML` — clean at release time).

Report a vulnerability privately via [SECURITY.md](SECURITY.md) — please do not open public issues for security reports.

## License

Apache-2.0 — see [LICENSE](LICENSE).

</div>
