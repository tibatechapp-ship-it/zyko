<div dir="rtl">

<div align="center">

<img src="docs/assets/social-card.png" alt="ZYKO — Universal AI Orchestration Platform" width="800"/>

[![CI](https://github.com/tibatechapp-ship-it/zyko/actions/workflows/ci.yml/badge.svg)](https://github.com/tibatechapp-ship-it/zyko/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-337%20passing-22c55e)](.github/workflows/ci.yml)
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

**النسخة 0.3.2** · توجيه متعدد المزوّدين بقرارات **قابلة للتحقق** · حوكمة **Policy-as-Code** · وكلاء أصليون بـ **MCP**

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

zk = Zyko()                                  # المفاتيح من البيئة
outcome = zk.ask("مرحبًا")
print(outcome.response.text)
print(outcome.receipt["chosen"])             # القرار المُوجَّه — قابل للتحقق

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
| `--demo` (مع أغلب الأوامر) | **وضع عرض بدون مفاتيح ولا شبكة** عبر مزوّد المحاكاة الحتمي — يمرّ بالمسار الحقيقي كله: توجيه، سياسة، إيصالات، بث |
| `zyko doctor` / `zyko info` / `zyko version` | تشخيص البيئة، المفاتيح، والمسارات |

## المزوّدون

OpenAI · Anthropic · Google Gemini · Groq · Mistral · DeepSeek · OpenRouter · **Ollama (محلي/بلا مفاتيح)** — والمعمارية موحّدة: إضافة مزوّد متوافق مع OpenAI = فئة من ~30 سطرًا.

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
pytest -q            # 337 اختبارًا: توجيه، سياسات، MCP (بعمليات فرعية حقيقية)، بوابة، وكلاء، مزوّدون (HTTP مُحاكى)، تصلّب CLI، وضع العرض
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

انظر ملف الخطة الاستراتيجية في مستودع المشروع (تقييم + خطة 18–24 شهرًا). التالي: لوحة درجات عامة عبر CI، مزامنة Ledger عبر Git، دعم رؤى الصور، والمصادقة المتعددة المستخدمين للبوابة.

## الترخيص

Apache-2.0 — راجع [LICENSE](LICENSE).

</div>

---

<div dir="ltr">

# ZYKO — Universal AI Orchestration Platform (English)

**v0.3.2** · Multi-provider routing with **verifiable** decisions · **Policy-as-Code** governance · **MCP-native** agents — running on **Linux, Windows, macOS, Android and Termux** with a pure-Python core (only `httpx` + `PyYAML`).

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
- **Providers**: OpenAI · Anthropic · Google · Groq · Mistral · DeepSeek · OpenRouter · Ollama(local). Retries with backoff, circuit breakers, latency EWMA.
- **Android/Termux**: one-command installer, offline models via Ollama, widget shortcut for the gateway, optional Kivy UI. Nothing compiles.
- **Rust kernel (optional)**: PyO3 accelerator with enforced Python-parity; graceful fallback everywhere.

## Tests

`pytest -q` → 337 tests (98% coverage) covering routing (incl. snapshot/parity and explicit model pinning), policy (incl. schema warnings and malformed-document degradation), MCP over real subprocesses plus in-memory server frames and the full client lifecycle (timeouts, server errors, pagination, closed streams), the gateway over a real HTTP socket (auth + keep-alive integrity + 502 upstream errors), agents, every provider adapter against canned HTTP, session memory, the audit-based cost report, streaming cost accounting, `Retry-After` resilience, CLI robustness (broken pipes, busy ports, JSON-only `--json`), tool-loop failure modes, and the keyless demo mode. CI runs the matrix on Linux/Windows/macOS + Python 3.11/3.12/3.13, plus lint (`ruff check` + `ruff format --check`), a security job (`bandit` + `pip-audit`), and a Rust kernel check.

## Security

- **Built-in governance**: danger tools (`shell`) stay locked unless explicitly named in `tools.allow` — even under `allow: ["*"]`; the MCP client spawns servers via `exec`, never a shell; `http_get` rejects non-HTTP schemes; deterministic PII redaction with Luhn validation.
- **CI security gate**: `bandit -c pyproject.toml -r src/zyko` (0 findings; the intentional, policy-gated `shell=True` is documented inline with a scoped `# nosec`) and `pip-audit --skip-editable` over the declared dependency surface (`httpx`, `PyYAML` — clean at release time).

Report a vulnerability privately via [SECURITY.md](SECURITY.md) — please do not open public issues for security reports.

## License

Apache-2.0 — see [LICENSE](LICENSE).

</div>
