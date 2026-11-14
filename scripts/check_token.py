#!/usr/bin/env python3
"""فحص حيوية توكن النشر — بروتوكول البيئة فقط (لا قرص، لا argv، لا git config).

ثلاث خطوات إلزامية قبل أي دفع:
  1. /user          ⇒ التوكن حي أصلاً (401 = ميت، لا يُحاول الدفع)
  2. /repos/{repo}  ⇒ صلاحية الدفع على المستودع الهدف تحديداً
  3. /repos/{repo}/releases ⇒ صلاحية إنشاء الإصدارات (دورة النشر كاملة)

الاستعمال:
    GH_PUSH_TOKEN='<token>' python3 scripts/check_token.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

REPO = "tibatechapp-ship-it/zyko"
API = "https://api.github.com"


def _get(path: str, token: str) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{API}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "zyko-release-check",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def main() -> int:
    token = os.environ.get("GH_PUSH_TOKEN", "")
    if not token:
        print("FATAL: GH_PUSH_TOKEN غير مضبوط في بيئة هذا الصدفة فقط", file=sys.stderr)
        return 2
    prefix = token[:8]
    try:
        status, user = _get("/user", token)
    except urllib.error.HTTPError as exc:
        print(f"حزمة 1 فشلت: /user ⇒ HTTP {exc.code} — التوكن {prefix}… ميت أو ملغى")
        return 1
    print(f"حزمة 1 نجحت: /user ⇒ {user.get('login', '?')} (توكن {prefix}… حي)")

    try:
        status, repo = _get(f"/repos/{REPO}", token)
    except urllib.error.HTTPError as exc:
        print(f"حزمة 2 فشلت: /repos/{REPO} ⇒ HTTP {exc.code}")
        return 1
    perms = repo.get("permissions", {})
    if not perms.get("push"):
        print(f"حزمة 2 فشلت: لا صلاحية دفع على {REPO}")
        return 1
    print(f"حزمة 2 نجحت: دفع مسموح على {REPO}")

    try:
        status, rels = _get(f"/repos/{REPO}/releases?per_page=5", token)
    except urllib.error.HTTPError as exc:
        print(f"حزمة 3 فشلت: /releases ⇒ HTTP {exc.code}")
        return 1
    names = [r.get("name") for r in rels[:3]]
    print(f"حزمة 3 نجحت: قراءة الإصدارات ممكنة — آخرها {names}")
    print(f"النتيجة: التوكن {prefix}… جاهز لدورة النشر الكاملة (دفع + وسوم + إصدارات)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
