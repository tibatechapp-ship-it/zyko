<div dir="rtl">

<div align="center">

<img src="docs/assets/social-card.png" alt="ZYKO — منصة تنسيق الذكاء الاصطناعي الشاملة" width="800"/>

[![CI](https://github.com/tibatechapp-ship-it/zyko/actions/workflows/ci.yml/badge.svg)](https://github.com/tibatechapp-ship-it/zyko/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.21.0-6366f1)](CHANGELOG.md)
[![Tests](https://img.shields.io/badge/tests-1581%20passing-22c55e)](.github/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-3776ab?logo=python&logoColor=white)](pyproject.toml)
[![Platforms](https://img.shields.io/badge/platforms-Linux%20%7C%20Windows%20%7C%20macOS%20%7C%20Termux-10b981)](.github/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-3b82f6)](LICENSE)

[الابتكارات](docs/INNOVATION.md) · [سجل الإصدارات](docs/HISTORY.md) · [الموقع التعريفي](https://tibatechapp-ship-it.github.io/zyko/) · [المناقشات](https://github.com/tibatechapp-ship-it/zyko/discussions)

</div>

# ZYKO — محرك البرمجة العربي الحتمي

> توليد ← مراجعة ← إصلاح ← حارس — من بوابة واحدة، بإيصالات توجيه قابلة للتحقق، وعلى أي منصة.

النسخة **0.21.0** · اعتماديتان فقط (`httpx` و`PyYAML`) · بايثون 3.11 – 3.14

---

## ما يميز ZYKO

| الركيزة | ماذا تعني عمليًا |
|:---|:---|
| **حتمية بالبايت** | نفس المدخل = نفس المخرج (SHA-256). لا طوابع زمنية ولا عشوائية — حتى تقارير HTML وخط الأساس مُختبران بمساواة بايتات. |
| **إيصالات قابلة للتحقق** | `zyko verify` يعيد حساب أي قرار توجيه (جودة/تكلفة/زمن) **دون اتصال** — وقد اكتشف فعلًا خطأً حقيقيًا في الموجِّه الذي وُجد ليحميه. |
| **محرك برمجة عربي** | توليد حتمي من وصف عربي واحد، مراجعة بـ38 قاعدة AST + تحليل تلوث بيانات، وإصلاح مُتحقَّق بإعادة التحليل قبل القبول. |
| **حارس ما قبل الكتابة** | المحرّس: أي اقتراح من أي نموذج يمر PII ← RTL ← بنية قبل كتابة بايت واحد، والقرار (ALLOW/DENY/REVIEW) موقَّع ببصمة sha256. |
| **عقول خلف البوابات نفسها** | عقل مخطط حتمي، أو نموذج محلي عبر Ollama، أو منافسة عقول (`BestOfBrain`) — الإيصال يروي القصة كاملة. |
| **محمي قانونيًا** | كل ابتكارات ZYKO منشورة كإثبات مسبق (Prior Art) مؤرَّخ في [docs/INNOVATION.md](docs/INNOVATION.md). |

---

## التثبيت

```bash
pip install git+https://github.com/tibatechapp-ship-it/zyko.git
```

أو من المصدر:

```bash
git clone https://github.com/tibatechapp-ship-it/zyko.git && cd zyko
pip install -e .
```

---

## جرّبه في دقيقة

```bash
# 1) توجيه قابل للتحقق — بلا شبكة وبلا مفاتيح
zyko ask 'مرحبا' --demo --receipt r.json && zyko verify r.json

# 2) الحلقة كاملة: توليد ← مراجعة ← إصلاح من وصف عربي واحد
zyko factory pipeline --description "قائمة مهام للفريق" --out ./مشروعي

# 3) بوابات المراحل الأربع (24 بوابة كمية) ولوحة تحكم HTML حتمية
zyko factory gates --html /tmp/لوحة.html

# 4) حارس الجودة عبر الزمن — بلا طوابع زمنية
zyko factory baseline update --src ./مشروعي
zyko factory baseline check --src ./مشروعي

# 5) ذكاء محلي خلف البوابات نفسها
zyko ai run --brain ollama --model <model> --goal "وصف عربي"

# 6) بايثون عربية: لغة ضاد المستقلة عبر حدود عملية منفصلة
zyko py hello.daad --run
```

---

## شاهدها يعمل — على كود حقيقي

تشغيل موثّق على ملف واقعي من مكتبة [psf/requests](https://github.com/psf/requests): `src/requests/models.py` — **1184 سطراً** (التجربة الكاملة والمنهجية في [docs/REAL_WORLD_TEST.md](docs/REAL_WORLD_TEST.md)):

```text
$ zyko do "راجع src/requests/models.py" --dry-run
[INFO] المهمة: REVIEW — ثقة 0.70
الخطة (1 خطوة):
  1. [review] مراجعة حتمية بقواعد AST — بلا نموذج وبلا شبكة — args: {"path": "src/requests/models.py"}
[WARN] الوضع: تجريبي — لن يُكتب أي ملف (استخدم --write للتطبيق)
التنفيذ:
  ✓ [review] الدرجة 10 — مرفوض (guardian: ALLOW)
  chain_hash             d0e52368…f42485

real    0m0.828s
```

ما جرى في 0.83 ثانية بلا شبكة وبلا مفاتيح: تصنيف الهدف (REVIEW) ← استخراج المسار الحقيقي من النص العربي ← مراجعة AST وجدت **24 ملاحظة حقيقية** (1 عالية، 18 متوسطة، 5 منخفضة) ← درجة حتمية 10/100 وحكم «مرفوض» بمزايدة موثقة ← Guardian يسمح ← إيصال موقّع بـ `chain_hash` قابل للتحقق. ودماغ سحابي (Qwen/OpenAI-compatible) يعمل خلف البوابات نفسها: `zyko ai run --brain qwen --model <model> --goal "راجع وأصلح <ملف>"`.

---

## الأوامر الأساسية

| الأمر | الوظيفة |
|:---|:---|
| `zyko factory pipeline` | الحلقة كاملة بأمر واحد (`--description` + `--out`) |
| `zyko factory workspace` | المحرك على مشروع قائم (تجربة جافة افتراضيًا) |
| `zyko factory fix --path <p>` | إصلاح ملف أو مجلد مع تحقق AST |
| `zyko factory baseline update/check` | حارس الجودة عبر الزمن |
| `zyko factory gates --html <p>` | بوابات المراحل 3+4+5+6 ولوحة HTML حتمية |
| `zyko factory dashboard` | لوحة تحكم عربية (HTML + Markdown) موقعة ببصمة |
| `zyko factory map` | خريطة المصنع: الوحدات والعقود وأكواد الخروج |
| `zyko verify <receipt>` | تحقق دون اتصال من أي إيصال توجيه |
| `zyko gauntlet` | الفحص الكبير: 1000 برنامج حقيقي — ومع `--repeats`/`--review-sample` طبقة الشدّ (حتمية متكررة × سرعة × مراجعة ذاتية) |
| `zyko compare <ملف>` | المقارنة الحتمية: دقة التصنيف + سرعة + حتمية على هدفك، ومنافس اختياري بأمر تمرره أنت |
| `zyko do --brain ollama --model m` | العقل كاملاً مع تخطيط دماغ حقيقي خلف البوابات — والرجوع آمن للمخطط الحتمي عند أي فشل |
| `zyko py <file.daad>` | ترجمة/تنفيذ بايثون عربية (ضاد) |
| `zyko ai run` | جلسة ذكاء موثقة عبر البوابات (`planner` / `ollama` / `bestof`) |
| `zyko ask / chat / route / serve` | البوابة والتوجيه متعدد المزوّدين |

القائمة الكاملة: [docs/API.md](docs/API.md).

---

## المنصات والاختبارات

Linux · Windows · macOS · Android/Termux — مصفوفة CI خضراء على الأنظمة الثلاثة، وPython 3.11 / 3.12 / 3.13 / 3.14.

```bash
pytest -q
# 2004 passed, 13 skipped
```

---

## التوثيق

- [الابتكارات — الإثبات المسبق](docs/INNOVATION.md)
- [سجل الإصدارات الكامل](docs/HISTORY.md) · [CHANGELOG](CHANGELOG.md)
- [مرجع API](docs/API.md) · [المعمارية](docs/ARCHITECTURE.md) · [دليل المزوّدين](docs/PROVIDERS.md)
- [العقل](docs/MIND.md) · [الاستراتيجية](docs/STRATEGY.md)

## الحوكمة

- الترخيص: Apache 2.0 — [LICENSE](LICENSE) · [NOTICE](NOTICE)
- الأمن: [SECURITY.md](SECURITY.md) (لا تفتح issue عامًا) · المساهمة: [CONTRIBUTING.md](CONTRIBUTING.md) · [السلوك](CODE_OF_CONDUCT.md)

## الاقتباس

إن استخدمت ZYKO في بحثٍ أو نظام إنتاجي، اقتبس عبر [CITATION.cff](CITATION.cff):

```text
tibatechapp-ship-it (2026). ZYKO: Deterministic Arabic Coding Engine
and AI Orchestration Platform. https://github.com/tibatechapp-ship-it/zyko
```

</div>
