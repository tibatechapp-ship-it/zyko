# النشر الموثوق إلى PyPI — عقد التشغيل من الوسم إلى الحزمة

هذه الوثيقة هي الإجابة على درس `invalid-publisher` الموثق في المراجعة
الخارجية: فشل النشر لم يكن كودًا سيئًا بل **مطابقة ناقصة** بين هوية
التشغيل على GitHub وسجل الناشر الموثوق على PyPI. المطابقة أربعة حقول،
أي حرف مخالف يُسقط النشر صامتًا. القيم أدناه هي العقد — ويحرسها
اختبار `tests/test_publishing_contract.py` فلا تعفّت.

## 1. سجل الناشر الموثوق على PyPI (المرة الوحيدة، يدويًا من مالك الحساب)

على <https://pypi.org> — الحساب `tibatechapp-ship-it` → مشروع
`zyko` → *Settings* → *Publishing* → *Add pending trusted publisher*:

| الحقل في نموذج PyPI | القيمة العقدية (لا تغيير) |
|---|---|
| **PyPI project name** | `zyko` |
| **Owner** | `tibatechapp-ship-it` |
| **Repository** | `zyko` |
| **Workflow filename** | `publish.yml` |
| **Environment** | `release` |

> المشروع غير موجود على PyPI بعد؟ أنشئ *pending trusted publisher*
> أولًا (النموذج نفسه ينشئ المشروع عند أول نشر ناجح) — أو ارفع أول
> إصدار بـ API token ثم سجّل الناشر.

مطابقة التشغيل في `.github/workflows/publish.yml`:

- `environment: release` — الحقل الرابع فوق حرفيًا.
- `permissions: id-token: write` — OIDC بلا توكن PyPI مخزَّن.
- اسم الملف `publish.yml` هو هوية الـ workflow — إعادة تسميته تكسر
  العقد فيتطلب تحديث نموذج PyPI.

## 2. حراسة داخلية قبل الرفع (آلية، في الـ workflow نفسه)

خطوة **«Tag must certify its own version»** ترفض النشر عند تعارض
الوسم مع `src/zyko/version.py` — الوسم يشهّد نسخته لا يزعمها.

## 3. حماية الفروع (من المراجعة: «أضف حماية تمنع الدمج أو الوسم عند فشل الحواجز»)

على GitHub → `tibatechapp-ship-it/zyko` → *Settings* → *Branches* →
*Add branch protection rule* لـ `main`:

- **Require a pull request before merging** — أو استثناء المشرف الوحيد
  مع إبقاء بقية الشروط.
- **Require status checks to pass**: `test (ubuntu-latest, 3.12)`،
  `lint`، `metrics truth (README badge == this exact run)`،
  `security (bandit + pip-audit)`، `phase-2 reviewer…`.
- **Include administrators** ✓.
- *Tags* (v2 rule): **Restrict tag creation** — الوسم يُنشأ من محلي
  موقّع فقط، وCI الأحمر يمنع رفعه عمليًا لأن `publish` لا يبدأ عندها.

## 4. التحقق بعد أول نشر (معيار الإنجاز من المراجعة)

```bash
pip download zyko==<الإصدار> --no-deps -d /tmp/zyko-pkg   # متاح فعلاً؟
pip install /tmp/zyko-pkg/zyko-*.whl && zyko --version    # يُثبّت ويعمل؟
```

الاختبار الحقيقي: بناء من وسِم → رفع OIDC → **تثبيت من PyPI نفسها** —
الثلاثة معًا وليس أول اثنين فقط.

## 5. مسار كامل للإصدار (من الوسم إلى الحزمة)

```bash
# بعد الخضر الكامل محليًا:
# 1) مزامنة الأرقام من التشغيل الفعلي (مصدر الحقيقة الوحيد)
pytest -q --junitxml=/tmp/junit.xml
PYTHONPATH=src python scripts/make_metrics.py --junit /tmp/junit.xml
# 2) الالتزام + الوسم الموقّع
git add -A && git commit -m "..." && git tag -a vX.Y.Z -m "..."
# 3) الدفع بـ --follow-tags (بروتوكول التوكن في scripts/push-after-rotation.sh)
bash scripts/push-after-rotation.sh
# 4) GitHub Actions → Publish to PyPI → أخضر؟ ثم pip download أعلاه
```

## 6. الأخطاء المعروفة وحكمها

| رسالة | السبب | العلاج |
|---|---|---|
| `invalid-publisher` | أحد حقول الناشر الأربعة لا يطابق | قارن جدول §1 مع نموذج PyPI حرفًا حرفًا |
| `impersonation` أو 403 | المشروع باسم آخر/مطالبة خارجية | تحقق من ملكية اسم `zyko` على PyPI |
| الوسم يرفض في خطوة coherence | `version.py` ≠ الوسم | أصلح الوسم أو الترقية ثم أعِد الوسم |
