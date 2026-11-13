# ZYKO مع LobeChat — تكامل مزوّد + إضافة

LobeChat يستهلك zyko من مستويين، كلاهما فوق بوابة zyko المتوافقة مع OpenAI:

## 1) مزوّد OpenAI مخصص (المحادثة عبر zyko)

بوابة zyko نقطة نهاية OpenAI قياسية، فيتصلها LobeChat كمزوّد مخصص:

1. شغّل بوابة zyko أينما تريد (محلياً، على HF Space، أو خلف Vercel):
   ```bash
   zyko serve --host 127.0.0.1 --port 8787 --api-key <مفتاحك>
   # أو عبر النشر: docs/PLATFORMS.md — Space يعمل بلا مفاتيح
   ```
2. في LobeChat: **الإعدادات ← مزوّد اللغة ← OpenAI**، اضبط:
   - **API Proxy Address**: `https://<بوابة-zyko>/v1`
   - **API Key**: مفتاح البوابة نفسه (`--api-key`)
3. اختر اسم نموذج أي شيء (مثل `zyko-routed`) — التوجيه الحقيقي يجري داخل
   zyko بالسياسة، والاستجابة تحمل `zyko.chosen` (المزوّد المختار).

## 2) إضافة الوكيل (manifest.json)

`manifest.json` في هذا المجلد يعرّف إضافة `zyko-agent` لنقطة الإضافات في
LobeChat: أداة واحدة `zykoAsk` تستدعي بوابتك.

**خطوة إلزامية قبل الاستيراد**: عدّل حقل `api[0].url` من العنوان المعلَّن
`https://REPLACE-WITH-YOUR-ZYKO-GATEWAY/v1/chat/completions` إلى عنوان
بوابتك الفعلي — عنوان بوابتك لا يمكن لأحد أن يعرفه عنك.

## التحقق

```bash
curl -s https://<بوابتك>/healthz
curl -s https://<بوابتك>/v1/chat/completions \
  -H "Authorization: Bearer <مفتاح البوابة>" \
  -H "Content-Type: application/json" \
  -d '{"model":"zyko-routed","messages":[{"role":"user","content":"اكتب دالة فيبوناتشي"}]}'
```
