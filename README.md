<div dir="rtl">

# ZYKO — منصة تنسيق الذكاء الاصطناعي الشاملة

**النسخة 0.1.0** · توجيه متعدد المزوّدين بقرارات **قابلة للتحقق** · حوكمة **Policy-as-Code** · وكلاء أصليون بـ **MCP**

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

## التثبيت

```bash
# Linux / macOS / Termux
pip install git+https://github.com/tibatechapp-ship-it/zyko.git

# Windows
pip install git+https://github.com/tibatechapp-ship-it/zyko.git

# من المصدر (كل المنصات)
git clone https://github.com/tibatechapp-ship-it/zyko.git && cd zyko
pip install -e .[dev]
```

التبعيات الأساسية: `httpx` و`PyYAML` فقط — كلتاهما Python خالص، لذا **لا شيء يُترجم** على أي منصة، بما فيها Termux.

### على أندرويد/Termux

```bash
pkg install -y git && git clone https://github.com/tibatechapp-ship-it/zyko.git
cd zyko/android && bash install-termux.sh
```

راجع [android/README.md](android/README.md) للنموذج المحلي عبر Ollama على الهاتف، وويدجت البوابة الدائمة، وواجهة Kivy.

## ابدأ في 60 ثانية

```bash
export OPENAI_API_KEY=sk-...        # أو أنشئ ollama محليًا ليعمل بلا مفاتيح

zyko ask "اشرح MCP في سطر واحد" --explain   # إجابة + قرار التوجيه
zyko route "ملخص هذا الملف"                 # خطة التوجيه بلا أي تكلفة
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
| `zyko bench` | المقياس المرجعي القابل لإعادة الإنتاج (وبـ`--update-ledger` يغذّي الموجّه) |
| `zyko doctor` / `zyko info` | تشخيص البيئة، المفاتيح، والمسارات |

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
pytest -q            # 93+ اختبارًا: توجيه، سياسات، MCP (بعمليات فرعية حقيقية)، بوابة، وكلاء، مزوّدون (HTTP مُحاكى)
ruff check src tests benchmarks
```

يعمل CI على ubuntu/windows/macos × Python 3.11/3.12 + فحص Rust + تجربة دخان للـCLI.

## خارطة الطريق

انظر ملف الخطة الاستراتيجية في مستودع المشروع (تقييم + خطة 18–24 شهرًا). التالي: لوحة درجات عامة عبر CI، مزامنة Ledger عبر Git، دعم رؤى الصور، والمصادقة المتعددة المستخدمين للبوابة.

## الترخيص

Apache-2.0 — راجع [LICENSE](LICENSE).

</div>

---

<div dir="ltr">

# ZYKO — Universal AI Orchestration Platform (English)

**v0.1.0** · Multi-provider routing with **verifiable** decisions · **Policy-as-Code** governance · **MCP-native** agents — running on **Linux, Windows, macOS, Android and Termux** with a pure-Python core (only `httpx` + `PyYAML`).

## Four differentiators

1. **Verifiable routing** — every response carries a *routing receipt*: the full candidate ranking with score components (quality/cost/latency) and published weights. Replay any past decision offline.
2. **Honest quality scores** — ledger scores come only from the reproducible benchmark (`zyko bench`, fixed seed, objective graders), never vendor marketing tables. No data yet → neutral 0.5 for everyone.
3. **Policy-as-Code** — daily USD budget, deterministic PII redaction (email/phone/card/IBAN/SSN with Luhn), model & tool allowlists, rate limits, JSONL audit trail — one YAML enforced on every call.
4. **MCP-first** — ZYKO consumes MCP servers as agent tools *and* exposes itself as one (`zyko mcp serve`).

## Quickstart

```bash
pip install git+https://github.com/tibatechapp-ship-it/zyko.git
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

- **CLI**: `ask` · `chat` · `route` (planning-only) · `models` · `policy` · `run` (agents) · `serve` · `mcp` · `bench` · `doctor` — argparse-only, zero CLI dependencies.
- **Gateway**: stdlib HTTP server, streaming SSE included, `zyko.receipt` embedded in responses and chunks.
- **Agents**: ReAct loop, builtin tools (calculator/file/http/shell-guarded), MCP tools namespaced as `server__tool`, SQLite session memory, step/timeout/policy guards.
- **Providers**: OpenAI · Anthropic · Google · Groq · Mistral · DeepSeek · OpenRouter · Ollama(local). Retries with backoff, circuit breakers, latency EWMA.
- **Android/Termux**: one-command installer, offline models via Ollama, widget shortcut for the gateway, optional Kivy UI. Nothing compiles.
- **Rust kernel (optional)**: PyO3 accelerator with enforced Python-parity; graceful fallback everywhere.

## Tests

`pytest -q` → 90+ tests covering routing, policy, MCP over real subprocesses, the gateway, agents, and every provider adapter against canned HTTP. CI runs the matrix on Linux/Windows/macOS + Python 3.11/3.12.

## License

Apache-2.0 — see [LICENSE](LICENSE).

</div>
