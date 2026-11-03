# ZYKO Strategic Assessment — أين نقف، وما الذي ينقصنا، وكيف نصدر؟

*Written 2026-11-02 (v0.4.0 baseline, published with v0.4.1). Every number below
was pulled live from the GitHub REST API on the writing date — no memory, no
vendor marketing. Re-measure before quoting.*

---

## العربية

### 1) مقارنة دقيقة بالمشاريع الكبيرة — أين نحن؟

| المشروع | النجوم | الفروع | الدفع الأخير | ملاحظة |
|---|---:|---:|---|---|
| LangChain | 148,848 | 25,018 | 2026-11-02 | الأوسع انتشاراً، الأكثر شكوى من عدم الاستقرار |
| AutoGen | 61,663 | 9,347 | 2026-10-28 | محادثات متعددة الوكلاء، يفلت منه التحكم أحياناً |
| CrewAI | 60,395 | 8,996 | 2026-11-01 | فرق بأدوار، حالة بسيطة لا تكفي التدفقات المتشعبة |
| LlamaIndex | 52,774 | 8,495 | 2026-10-26 | ملك الـRAG، أضيق في التنسيق العام |
| LangGraph | 44,293 | 7,620 | 2026-11-02 | رسوم حالات للإنتاج، منحنى تعلّم حاد |
| OpenAI Agents SDK | 30,443 | 4,970 | 2026-11-01 | انحياز طبيعي لعائلة OpenAI |
| Semantic Kernel | 28,725 | 4,850 | 2026-10-31 | Microsoft/.NET/Azure أولاً |
| PydanticAI | 20,990 | 3,080 | 2026-11-01 | أطر عمل وكلاء فقط — بلا بوابة/توجيه |
| **ZYKO** | **0** | **0** | **2026-11-02** | وُلد في الملعب مع كل الميزات تقريباً وبلا جمهور بعد |

**الحقيقة الصريحة**: فجوتنا ليست في الميزات — الفجوة **في التوزيع**.
صفر نجوم لا يعني منتجاً أصغر؛ يعني منتجاً لم يُخبَر بعد.

**ما لدينا وهو ليس لدى الكثيرين (مقارنة قدرات، إصدار 0.4.x):**

- **11 مزوّداً** (OpenAI, Anthropic, Google, Groq, Mistral, DeepSeek, OpenRouter,
  Together, xAI, Ollama محلي بلا مفاتيح, Mock حتمي) مع قواطع دائرة وصحة ومصدر
  سقوط تلقائي — ما يبنيه الآخرون بـLiteLLM خارجياً نملكه داخلياً.
- **Policy-as-Code** (خصوصية، حدود إنفاق، سجل تدقيق، قفل الأدوات الخطرة) —
  **لا يملكه أي من المنافسين الكبار** بشكل تصريحي موحّد. هذه بصمتنا.
- **MCP أصلي** (عميل + خادم، JSON-RPC 2.0) — نطاق أعمق من CrewAI/SK.
- **Structured output** بمخطط + إصلاح تلقائي (0.4.0) — تعادل مع
  `with_structured_output` في LangChain و`response_format` في AutoGen.
- **Response cache** موقّع بالسياسة (0.3.9) — تعادل مع LiteLLM/Portkey.
- **Observability مدمجة** (0.4.1): spans بمعرّفات trace/parent + ملف JSONL
  ملكك + `zyko traces` — ما يبيعه الآخرون خدمة سحابية مدفوعة (LangSmith/
  Langfuse) نحن نقدمه محلياً وبلا اعتماديات.
- **هندسة نظيفة بالأرقام**: ‏463 اختباراً، تغطية ~98%، bandit صفر، pip-audit،
  ruff، ‏CI 14 وظيفة خضراء على ‏Linux/macOS/Windows ‏× ‏Python ‏3.11–3.13،
  اعتماديتان إلزاميتان فقط (httpx + PyYAML). معظم المنافسين يحملون عشرات
  الاعتماديات الانتقالية.
- **Android/Termux** مواطن من الدرجة الأولى — لا أحد يفعل هذا.

**ما ينقصنا (الفجوات الحقيقية):**

1. **PyPI** — `pip install zyko` لا يعمل بعد. هذه أخطر فجوة منفردة: مستخدم
   بلا تثبيت بسهولة = مستخدم بلا وجود.
2. **الجمهور والتوزيع** — صفر نجوم، لا مشاركات، لا دراسات حالة.
3. **RAG/embeddings** — لا مزوّد embeddings ولا استرجاع أساسي (LlamaIndex
   يملك عالماً كاملاً هنا).
4. **أنماط متعددة الوكلاء** — لدينا وكلاء بأدوات وذاكرة، لكن لا "crew/pipeline"
   على طريقة CrewAI ولا رسوم DAG على طريقة LangGraph.
5. **تكاملات الملاحظة الخارجية** — OTel exporter / Langfuse / Prometheus:
   طبقتنا مدمجة، لكن الاستيراد إلى منصات الفرق غير موجود بعد.
6. **مصادقة متعددة المستخدمين للبوابة** — رمز حامل واحد فقط حتى الآن.

### 2) هل المشروع جاهز للتشغيل؟ (جاهزية الإنتاج)

**نعم — للتشغيل الفردي/الذاتي الآن، وبثلاث تحفظات**:

| البعد | الحالة | الدليل |
|---|---|---|
| التثبيت والتشغيل | ✅ يعمل | سكربتات تشغيل فوري، `zyko doctor`، وضع عرض بلا مفاتيح، Docker |
| الوظائف الأساسية | ✅ مكتملة | ask/chat/route/structured/agents/MCP/gateway(‏SSE)/cache/traces |
| المرونة | ✅ جيدة | قواطع دائرة، صحة، سقوط تلقائي، مهلات، إعادة محاولات |
| الأمان | ✅ جيد فردي | bandit 0، قفل أدوات خطرة، تدقيق، رمز بوابة؛ ⚠️ بلا تعدد مستخدمين |
| المراقبة | ✅ مدمجة الآن | تدقيق + تكلفة + تتبّع JSONL؛ ⚠️ بلا مُصدّر OTel/Prometheus |
| التوثيق | ✅ عميق | API/ARCHITECTURE/PROVIDERS/STRATEGY + موقع ثنائي اللغة |
| التوزيع | ⚠️ ناقص | GitHub فقط — **PyPI لم يُفعل بعد** (يتملك حساب pypi.org + Trusted Publisher) |
| الاستقرار الواجهي | ⚠️ مبكر | بيتا؛ ‏0.x يعني احتمال تغييرات واجهة حتى 1.0 |

**قائمة ما قبل الإنتاج الواسع (بالترتيب)**: نشر PyPI ← مُصدّر OTel ← مصادقة
متعددة مستخدمين للبوابة ← ضمان واجهة 1.0.

### 3) عيوب المنافسين — وكيف نصدّر عن كل عيب

| المنافس | عيبه الموثّق | جواب ZYKO |
|---|---|---|
| LangChain | تغييرات كاسرة متكررة، طبقات تجريد عميقة تصعّب التتبّع، ليست منصة إنتاج بذاتها (بلا تدقيق/حدود/مراقبة مدمجة) | سطح API صغير ثابت، أخطاء مُنمّطة، Policy-as-Code + تدقيق + تتبّع مدمجة |
| LangGraph | منحنى تعلّم حاد؛ تتطلب تفكير "رسوم بيانية" حتى للمهام البسيطة | `Zyko().ask()` سطر واحد يقرّر الموجّه عنك؛ التعقيد اختياري لا إلزامي |
| CrewAI | حالة بسيطة لا تكفي التدفقات المتشعبة، مخرجات غير محكمة بلا مخطط | مخطط + تحقق + إصلاح تلقائي في كل استجابة (0.4.0) + سياسة صريحة |
| AutoGen | محادثات جماعية تنحرف أو تدور بلا نهاية، حالة صعبة التتبّع | توجيه حتمي + مهلات + ميزانية إصلاح محدودة + تتبّع span لكل محاولة |
| Semantic Kernel | انحياز Microsoft/.NET، لا يصلح لمن يعيش بيثون خالصاً | بيثون أولاً، محايد البائعين، يعمل حتى على هاتفك (Termux) |
| LlamaIndex | أضيق نطاقاً في التنسيق العام؛ ثقيل على الأنظمة الصغيرة | نواة 8K سطر واعتماديتان فقط؛ الـRAG في خارطتنا لا في قلبنا |
| OpenAI Agents SDK | انحياز لعائلة OpenAI | 11 مزوّداً + محلي Ollama + سقوط تلقائي بين البائعين |
| PydanticAI | إطار وكلاء فقط — بلا بوابة متوافقة مع OpenAI ولا توجيه بائعين | بوابة + توجيه + سياسة + تتبّع في الحزمة نفسها |

**خطة الصدارة (18–24 شهراً، مرتبة):**

1. **v0.4.x — التوزيع**: نشر PyPI (Trusted Publisher)، أمثلة تشغيل في 60 ثانية
   في كل مقال، بطاقات اجتماعية لكل إصدار.
2. **v0.4.x — جسور الملاحظة**: مُصدّر OTel اختياري (zyko[otel]) + Langfuse.
   *(نُفّذ في 0.4.2 — وأفضل من الوعد: OTLP/HTTP-JSON عبر httpx الموجودة أصلًا، صفر اعتماديات وحتى الـextra غير مطلوب)*
3. **v0.5 — RAG الأساسيات**: مزوّد embeddings + مخزن متجهات محلي بسيط +
   `zk.ask(..., context=docs)` — أقل ما يرضي مستخدم LlamaIndex.
   *(نُفّذ في 0.5.0 — chunker + ثلاثة مُدمجات بعقد واحد + VectorStore بملف JSON ملكك + `ask(context=…)`، والمُدمج الافتراضي بصفر اعتماديات)*
4. **v0.6 — الوكلاء المتعددون**: خط أنابيب crew تسلسلي بسياق مشترك (توازي
   CrewAI في البساطة، أقوى في الحوكمة).
   *(نُفّذ في 0.6.0 — `zyko.crew`: خطوات مرتبة + قوالب `{task}`/`{output}`/`{output_key}` آمنة بنيويًا وتُدقَّق عند البناء، بلا مطالبات خفية، spans لكل خطوة، إيصال `CrewResult` كامل، و`CrewError` مكتوب النوع)*
5. **v1.0 — عقد الاستقرار**: تجميد واجهات، سياسة إصدارات دعم، دليل ترقية.

---

## English

### 1) Precise benchmark against the big projects

The table above carries the live GitHub numbers (2026-11-02). The blunt
truth: **our gap is not features — it is distribution**. Zero stars means an
unmarketed product, not a smaller one. Capability-wise v0.4.x ships 11
providers with circuit breakers + failover, Policy-as-Code (unique — none of
the majors has a declarative governance engine), native MCP client+server,
schema-constrained structured output with auto-repair, policy-gated response
cache, and — from 0.4.1 — built-in OpenTelemetry-style tracing with a JSONL
sink you own and a `zyko traces` CLI. Engineering hygiene is a moat: 463
tests, ~98% coverage, bandit zero, two mandatory dependencies, CI 14/14 on
three OSes. Real gaps: **PyPI presence, audience, RAG/embeddings, multi-agent
patterns, external observability bridges, multi-user gateway auth**.

### 2) Production readiness

Yes for single-user/self-hosted production today (install scripts, keyless
demo mode, doctor, gateway with bearer auth + SSE, cache, structured,
tracing, cross-platform CI). Three reservations: PyPI distribution is the
critical missing gate; auth is single-token; the API is still 0.x-beta.
Pre-broad-production order: **PyPI → OTel exporter → multi-user auth → 1.0
stability contract**.

### 3) Competitor weaknesses → the ZYKO answer

LangChain: breaking churn + abstraction opacity + no built-in governance →
small stable surface + typed errors + Policy-as-Code + built-in tracing.
LangGraph: steep graph-first learning curve → one-liner default with optional
depth. CrewAI: thin state, unvalidated outputs → schema+validation+repair on
every answer. AutoGen: divergent group chats → deterministic routing,
budgets, per-attempt spans. Semantic Kernel: Microsoft-first → Python-first,
vendor-neutral, phone-capable. LlamaIndex: narrow scope, heavier core →
8K-line core, two deps, RAG as an opt-in layer. OpenAI Agents SDK: vendor
bias → 11 providers + local + failover. PydanticAI: agents only → full stack
in one package.

### Roadmap to the top

Distribution (PyPI + 60-second stories) → observability bridges (OTel,
Langfuse — shipped in 0.4.2 as a zero-dependency OTLP/JSON sink) → RAG
essentials (embeddings, local vector store, `context=docs` — shipped in
0.5.0 with a deterministic zero-dep default embedder) → multi-agent crews
with governance → the 1.0 stability contract.
