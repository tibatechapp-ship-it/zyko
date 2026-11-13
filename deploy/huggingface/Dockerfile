# deploy/huggingface/Dockerfile — Space حاوية Docker تشغّل بوابة zyko كما هي.
#
# الاستعمال (دقيقتان):
#   1. أنشئ Space جديداً بنمط Docker على huggingface.co.
#   2. ارفع هذا الملف و README.md الملاصق إلى جذر الـSpace (أو اجعل الـSpace يعكس هذا المستودع).
#   3. الـSpace يبني الصورة وينصت على 7860 — وضع العرض الحتمي يعمل بلا أي مفاتيح.
#
# لمفاتيح مزوّد حقيقي: أضف Secret باسم ZYKO_OPENAI_API_KEY (أو أي مفتاح مزوّد مدعوم)
# ثم شغّل بلا --demo — انظر README.md الملاصق.
#
# ZYKO_REF يثبّت المرجع — وسوم الإصدارات (v0.46.0 مثلاً) أكثر قابلية للتكرار من main.

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

ARG ZYKO_REF=main
RUN git clone --depth 1 --branch "${ZYKO_REF}" \
      https://github.com/tibatechapp-ship-it/zyko.git /zyko \
    && pip install --no-cache-dir /zyko \
    && zyko doctor

ENV ZYKO_GATEWAY_PORT=7860 \
    PYTHONUNBUFFERED=1

EXPOSE 7860

# وضع العرض بلا مفاتيح: بوابة متوافقة مع OpenAI فوق المزوّج الحتمي المدمج.
CMD ["python", "-m", "zyko", "serve", "--host", "0.0.0.0", "--port", "7860", "--demo"]
