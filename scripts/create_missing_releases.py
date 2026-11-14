#!/usr/bin/env python3
"""إنشاء الإصدارات الناقصة على GitHub من CHANGELOG — بروتوكول البيئة فقط.

الاصطلاح المعمول به في هذا المستودع:
  * tag_name  = بـ v (مثل ``v0.46.0``، وسم موقّع مرفوع مع --follow-tags)
  * name      = رقم مجرد (مثل ``0.46.0``)
  * body      = الوصف بعد « — » من سطر H2 + قسم ``## What's changed``
    يحمل بنود الموجة (الأسطر التقريرية تحت H2 حتى الـ H2 التالي)

الاستعمال:
    GH_PUSH_TOKEN='<token>' python3 scripts/create_missing_releases.py          # جرد
    GH_PUSH_TOKEN='<token>' python3 scripts/create_missing_releases.py --create # إنشاء الناقص
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

REPO = "tibatechapp-ship-it/zyko"
API = "https://api.github.com"
H2_RE = re.compile(r"^## (\d+\.\d+\.\d+) — (.+)$", re.M)


def _api(method: str, path: str, token: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "zyko-release-publish",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def parse_changelog(text: str) -> dict[str, dict]:
    """H2 ⇒ {version, desc, body_bullets} — بالترتيب، بلا تخمين."""
    entries: dict[str, dict] = {}
    versions = list(H2_RE.finditer(text))
    for i, m in enumerate(versions):
        version, desc = m.group(1), m.group(2).strip()
        end = versions[i + 1].start() if i + 1 < len(versions) else len(text)
        section = text[m.end():end]
        bullets = [ln.strip() for ln in section.splitlines() if ln.strip().startswith("- ")]
        entries[version] = {"desc": desc, "bullets": bullets}
    return entries


def build_body(entry: dict) -> str:
    body = "\n".join(entry["bullets"])
    return f"{entry['desc']}\n\n## What's changed\n\n{body}\n"


def main() -> int:
    token = os.environ.get("GH_PUSH_TOKEN", "")
    if not token:
        print("FATAL: GH_PUSH_TOKEN غير مضبوط", file=sys.stderr)
        return 2
    prefix = token[:8]

    root = __file__ and __import__("pathlib").Path(__file__).resolve().parent.parent
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    entries = parse_changelog(changelog)

    # صفحات الإصدارات الموجودة
    existing: dict[str, dict] = {}
    page = 1
    while True:
        _, rels = _api("GET", f"/repos/{REPO}/releases?per_page=100&page={page}", token)
        if not rels:
            break
        for r in rels:
            existing[r.get("tag_name", "")] = r
        page += 1
    print(f"الجرد: {len(entries)} إصداراً في CHANGELOG، {len(existing)} إصداراً على GitHub")

    missing = []
    for version, entry in entries.items():
        tag = f"v{version}"
        if tag in existing:
            continue
        missing.append((version, tag, entry))
        print(f"ناقص: {tag} — {entry['desc'][:60]}")

    if not os.environ.get("CREATE") and "--create" not in sys.argv:
        print(f"الوضع: جرد فقط — الناقص {len(missing)} من أصل {len(entries)}")
        return 0

    created = 0
    for version, tag, entry in missing:
        payload = {
            "tag_name": tag,
            "name": version,
            "body": build_body(entry),
            "target_commitish": "main",
            "draft": False,
            "prerelease": False,
        }
        try:
            _api("POST", f"/repos/{REPO}/releases", token, payload)
            created += 1
            print(f"أُنشئ: {tag} باسم {version}")
        except urllib.error.HTTPError as exc:
            print(f"فشل إنشاء {tag}: HTTP {exc.code} — {exc.read().decode()[:200]}")
            return 1
    print(f"النتيجة: أُنشئ {created} إصداراً (توكن {prefix}…)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
