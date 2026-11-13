#!/usr/bin/env python3
"""run_swebench_lite.py — الغلاف الموصى به في docs/PROTOCOL.md (الموجة 19).

قبل الالموجة 19 كانت الوثيقة العامة تذكر هذا الأمر وتنفذه خارج المستودع —
ثغرة قابلية إعادة التشغيل أقرّتها الجولة وسدّتها: الغلاف الآن ملف حقيقي
متعقّب يستدعي ``zyko.benchmarks.runner`` (المتسابق المتجمّع نفسه) بأمر
معلن واحد، وبصمة الوثيقة الناتجة تحكم التطابق بايت-ببايت.

    ZYKO_QWEN_HOST=<نقطة> ZYKO_QWEN_API_KEY=<مفتاح> \\
    python3 scripts/run_swebench_lite.py --out benchmarks/results/swebench_full_wide.json
"""

from __future__ import annotations

import sys

from zyko.benchmarks.runner import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
