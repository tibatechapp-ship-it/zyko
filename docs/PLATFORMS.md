# منصات النشر — zyko فوق كل شيء يعمل

*أُضيفت في الموجة 23 (v0.46.0). عقد المنصات: النسخة تعمل بلا مفاتيح على كل
منصة (المزوّج الحتمي المدمج)، وبمفتاح واحد تتحول توجيهاً حقيقياً بالسياسة.
الجاهزية تُقاس لا تُدَّعى: `zyko doctor` يطبع قسم «أهداف النشر» من سجل
`zyko.platform.deploy` ويقيس الأصول من الشجرة الفعلية.*

---

## العربية

| الهدف | ما يُنشر | الأصول | بلا مفاتيح؟ |
|---|---|---|---|
| GitHub | CI 3 منصات × 3 بايثونات + نشر PyPI (Trusted Publisher) + Pages + Docker | `.github/workflows/*`, `Dockerfile`, `CITATION.cff` | ✅ CI على وضع العرض |
| Hugging Face Spaces | Space Docker: بوابة OpenAI-متوافقة على 7860 | `deploy/huggingface/` | ✅ عرض حتمي |
| Vercel | دالة Serverless ASGI بلا أطر فوق الموجّه | `deploy/vercel/` | ✅ عرض حتمي |
| LobeChat | مزوّد مخصص + إضافة `zykoAsk` | `deploy/lobe/` | ✅ عبر بوابتك |

### GitHub

المستودع نفسه هو النشر: CI أخضر على Linux/macOS/Windows × Python 3.11–3.13،
workflow نشر إلى PyPI عبر Trusted Publisher، موقع Pages ثنائي اللغة، وحاوية
Docker جاهزة (`docker build -t zyko .` ثم `docker run -p 8787:8787 zyko`).
عقدة المجتمع كاملة: قوالب قضايا وPR، Code of Conduct، SECURITY.md، CITATION.cff.

### Hugging Face Spaces

1. أنشئ Space بنمط **Docker**.
2. ارفع `deploy/huggingface/Dockerfile` و`deploy/huggingface/README.md`
   (بالترويسة) إلى جذر الـSpace.
3. البناء يستنسخ هذا المستودع ويثبّته ويشغّل `zyko serve --demo` على 7860.
4. مزوّد حقيقي: أضف Secret مثل `ZYKO_OPENAI_API_KEY` واحذف `--demo` من CMD.

التفصيل الكامل: `deploy/huggingface/README.md`.

### Vercel

```bash
cd deploy/vercel && vercel deploy --prod
```

- `api/zyko.py`: تطبيق ASGI مصغّر بلا أطر — اعتماديتا zyko الإلزاميتان فقط
  تصلحان للبارد، ولا FastAPI في مسار النشر.
- `vercel.json` يعيد كتابة `/v1/chat/completions` و`/v1/models` و`/healthz`
  إلى الدالة، ويضيف CORS لمستخدمي LobeChat من المتصفح.
- `ZYKO_GATEWAY_API_KEY` يفرض Bearer auth — يُنصح به في الإنتاج.

### LobeChat

مسارَان موثّقان في `deploy/lobe/README.md`: بوابة zyko كمزوّد OpenAI مخصص
في LobeChat، وإضافة `zyko-agent` بمانيفست `manifest.json` (عدّل عنوان
بوابتك في الحقل المعلَّن قبل الاستيراد).

### القياس

```bash
zyko doctor
python3 -c "from zyko.platform.deploy import deployment_report; print(deployment_report()['ready_count'], '/', deployment_report()['total'])"
```

الأصول الناقصة تُذكر بالاسم — «بلا عدّاد = بلا ادعاء» يسري على جاهزية النشر
كما يسري على أرقام البنش.

---

## English

Deployment contract: keyless-first on every platform (the built-in
deterministic demo provider); one provider key flips it to real
policy-based routing. Readiness is measured from the actual tree by
`zyko.platform.deploy` — `zyko doctor` prints the deployment-targets
section with missing assets named.

| Target | Ships | Assets | Keyless |
|---|---|---|---|
| GitHub | CI (3 OS × 3 Py), PyPI via Trusted Publisher, Pages, Docker | `.github/workflows/*`, `Dockerfile`, `CITATION.cff` | yes |
| Hugging Face Spaces | Docker Space: OpenAI-compatible gateway on 7860 | `deploy/huggingface/` | yes |
| Vercel | framework-free ASGI serverless function over the router | `deploy/vercel/` | yes |
| LobeChat | custom OpenAI provider + `zykoAsk` plugin | `deploy/lobe/` | via your gateway |

Per-target steps live beside the assets: `deploy/<target>/README.md`
(bilingual). Measure with `zyko doctor` or
`python3 -c "from zyko.platform.deploy import deployment_report; print(deployment_report())"`.
