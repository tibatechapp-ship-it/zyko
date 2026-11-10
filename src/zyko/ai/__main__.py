"""تشغيل مباشر: python -m zyko.ai — طبقة الذكاء فوق المصنع الحتمي."""

from __future__ import annotations

import sys as _sys
if _sys.platform == "win32":
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")



import sys

from zyko.ai.cli import main

if __name__ == "__main__":
    sys.exit(main())
