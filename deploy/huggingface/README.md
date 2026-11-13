---
title: ZYKO Gateway
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
short_description: بوابة الوكيل الحتمي zyko — متوافقة مع OpenAI وتعمل بلا مفاتيح
---

# ZYKO Gateway على Hugging Face Spaces

Space هذه تشغّل بوابة zyko (المتوافقة مع OpenAI: `/v1/chat/completions`،
`/v1/models`، `/healthz`) فوق المزوّج الحتمي المدمج — تعمل **بلا أي مفاتيح**
من أول لحظة، وهذا عقد zyko على كل منصة.

## النشر

1. أنشئ Space بنمط **Docker**.
2. ارفع `Dockerfile` و`README.md` (هذا الملف بالترويسة أعلاه) إلى جذر الـSpace.
3. انتظر البناء — ثم:

```bash
curl -s https://<your-space>.hf.space/healthz
curl -s https://<your-space>.hf.space/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"mock","messages":[{"role":"user","content":"hello"}]}'
```

## مزوّد حقيقي بدل العرض

أضف Secret واحداً على الأقل في إعدادات الـSpace:

| Secret | المزوّد |
|---|---|
| `ZYKO_OPENAI_API_KEY` | OpenAI |
| `ZYKO_ANTHROPIC_API_KEY` | Anthropic |
| `ZYKO_GOOGLE_API_KEY` | Google |
| `ZYKO_GROQ_API_KEY` | Groq |

ثم في `Dockerfile` احذف `--demo` من سطر CMD — الموجّه يختار تلقائياً بالسياسة
(الجودة/الكلفة/الزمن) بين المزوّدات المهيأة، ومع قواطع الدوائر والسقوط التلقائي.

## تثبيت الإصدار

افتراضياً يُبنى من `main`. للتكرار الصارم ثبّت وسم إصدار:

```dockerfile
ARG ZYKO_REF=v0.46.0
```

المرجع الكامل للمنصات الأخرى: `docs/PLATFORMS.md` في المستودع الأم.
