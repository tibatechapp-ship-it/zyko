#!/usr/bin/env python3
"""أداة القياس المعيارية المرجعية — تولّد سجل مرجعي حقيقي في benchmarks/results/.

ما هذا الملف؟ سجل مرجعي من تشغيل فعلي على هدف حقيقي (ملف من مكتبة
psf/requests) — مُغلَّف بالإثبات: الإصدار، بيئة التشغيل، وبصمة الهدف
sha256 — وبداخله إيصالان حتميان بأوامر المستخدم نفسها:

  * ``zyko compare``           — دقة التصنيف + الحتمية البايتية + دوران الإيصال
  * ``zyko gauntlet --repeats --review-sample`` — طبقة الشدّ الكاملة

لماذا مغلَّف ولا نُعدل الإيصالات؟ عقد الإيصالات بايتي — لا حقول إضافية.
الإثبات يُحكى من الخارج، والاختبار (tests/test_bench_baseline_artifact.py)
يتحقق من تماسك الغلاف مع حزمة zyko المثبتة نفسها.

التشغيل (يحتاج هدفًا حقيقيًا موجودًا):

    git clone --depth 1 https://github.com/psf/requests.git /tmp/requests-test
    python scripts/make_bench_baseline.py /tmp/requests-test/src/requests/models.py \
        benchmarks/results/baseline_<التاريخ>.json

المكتبة القياسية فقط — بلا اعتماديات جديدة (قاعدة R1).
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# مُلصَق الهدف المعتمد في السجل — الوجهة الافتراضية للمستنسخ الضحل المعياري.
REQUESTS_LABEL = "psf/requests — src/requests/models.py (clone --depth 1 @HEAD)"
REQUESTS_SUFFIX = "src/requests/models.py"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build_baseline(
    target: Path, per_intent: int = 8, repeats: int = 2, review_sample: int = 6
) -> dict:
    """شغّل القياسات الفعلية وأعد الغلاف الحتمي (بلا مؤقتات — بلا عشوائية)."""
    from zyko.benchmarks.compare import run_compare
    from zyko.benchmarks.gauntlet_plus import run_stress_gauntlet
    from zyko.version import __version__

    source = target.read_text(encoding="utf-8")
    compare = run_compare(str(target), runs=3)
    gauntlet = run_stress_gauntlet(
        per_intent, repeats=repeats, review_sample=review_sample, execute=0
    )

    label = REQUESTS_LABEL if str(target).endswith(REQUESTS_SUFFIX) else str(target)
    return {
        "$comment": (
            "سجل مرجعي من تشغيل فعلي — أعد توليده على جهازك بـ "
            "scripts/make_bench_baseline.py وقارن الإيصالات الداخلية بايت-ببايت."
        ),
        "recorded": {
            "date": date.today().isoformat(),
            "zyko_version": __version__,
            "python": platform.python_version(),
            "platform": platform.system(),
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "target": {
            "label": label,
            "sha256": _sha256_file(target),
            "bytes": len(source.encode("utf-8")),
            "lines": source.count("\n") + (0 if source.endswith("\n") else 1),
        },
        # إيصالات بأوامر المستخدم نفسها — عقد بايتي، بلا توقيتات
        "compare": compare.to_dict(),
        "gauntlet_stress": json.loads(gauntlet.to_json(include_timing=False)),
    }


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    target = Path(argv[1])
    out = Path(argv[2])
    if not target.is_file():
        print(f"خطأ: الهدف غير موجود: {target}", file=sys.stderr)
        return 2

    baseline = build_baseline(target)

    ok = baseline["compare"]["ok"] and baseline["gauntlet_stress"]["ok"]
    if not ok:
        print("خطأ: إحدى الإيصالات ليست خضراء — لا يُكتب سجل مرجعي فاشل", file=sys.stderr)
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(baseline, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"✅ السجل المرجعي: {out}")
    print(f"   الهدف: {baseline['target']['label']} — {baseline['target']['bytes']} بايت")
    print(
        f"   مقارنة: دقة {baseline['compare']['probes_passed']}/"
        f"{baseline['compare']['probes_total']} — حتمية ✅"
    )
    print(
        f"   شدّ: تكرارات {baseline['gauntlet_stress']['repeats']} — "
        f"أدنى درجة مراجعة {baseline['gauntlet_stress']['review_min_score']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
