# ZYKO على Vercel — دالة Serverless متوافقة مع OpenAI

الدالة (`api/zyko.py`) هي تطبيق ASGI مصغّر بلا أطر فوق موجّه zyko — يعمل
**بلا مفاتيح** فوق المزوّج الحتمي المدمج، ويستفيد من مفتاح واحد في البيئة
للتوجيه الحقيقي بالسياسة.

## النشر (دقيقتان)

```bash
cd deploy/vercel
vercel deploy --prod
# أو اربط المجلد بمشروع Vercel من اللوحة — الجذر = deploy/vercel
```

## الاختبار بعد النشر

```bash
curl -s https://<your-app>.vercel.app/healthz
curl -s https://<your-app>.vercel.app/v1/models
curl -s https://<your-app>.vercel.app/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"hello"}]}'
```

## البيئة

| متغير | أثره |
|---|---|
| `ZYKO_OPENAI_API_KEY` (أو أي مفتاح مزوّد مدعوم) | توجيه حقيقي بين المزوّدات المهيأة بدل العرض الحتمي |
| `ZYKO_GATEWAY_API_KEY` | يفرض Bearer auth على `/v1/*` — يُنصح به في الإنتاج |

## حدود معلنة

- البارد يجلب zyko من `main` (انظر requirements.txt لتثبيت وسم إصدار).
- الدالة مزوّدة بحالة لكل نسخة: المحرك يُبنى مرة لكل نسخة دالة، والسقف
  المعلن لجسم الطلب 1MB.
- كل استجابة تحمل `zyko.chosen` — قرار التوجيه قابل للتحقق لا مُدَّعى.
