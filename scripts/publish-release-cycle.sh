#!/usr/bin/env bash
# دورة النشر الكاملة بضغطة واحدة — البروتوكول نفسه بلا استثناءات:
#   1. فحص التوكن (ثلاث حزم: حيوية، دفع، إصدارات)
#   2. دفع main مع كل الوسوم الموقّعة (--follow-tags يمنع انفصال الإصدار عن شهده)
#   3. إنشاء أي إصدارات ناقصة من CHANGELOG (tag بـ v، اسم رقم مجرد)
#
# الاستعمال:
#   GH_PUSH_TOKEN='<token>' bash scripts/publish-release-cycle.sh

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -z "${GH_PUSH_TOKEN:-}" ]]; then
  echo "FATAL: GH_PUSH_TOKEN not set (env-only protocol)" >&2
  exit 2
fi

echo "== الحزمة 0: فحص التوكن =="
python3 "$REPO/scripts/check_token.py"

echo "== الحزمة 0.5: بوابة الأسرار على الفرق الصادر =="
if git -C "$REPO" rev-parse -q --verify origin/main >/dev/null 2>&1; then
  python3 "$REPO/scripts/secret_scan.py" --diff origin/main..HEAD
else
  echo "تحذير: لا origin/main بعد — الفحص على الشجرة الكاملة"
  python3 "$REPO/scripts/secret_scan.py" --tree "$REPO/src"
fi

echo "== الحزمة 1: دفع main + الوسوم الموقّعة =="
GH_PUSH_TOKEN="$GH_PUSH_TOKEN" bash "$REPO/scripts/push-after-rotation.sh"

echo "== الحزمة 2: إنشاء الإصدارات الناقصة =="
GH_PUSH_TOKEN="$GH_PUSH_TOKEN" python3 "$REPO/scripts/create_missing_releases.py" --create

echo "== دورة النشر اكتملت =="
