"""تشغيل مباشر: python -m zyko.mind — الحلقة الإدراكية الكاملة."""

from __future__ import annotations

import sys as _sys

if _sys.platform == "win32":
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")


import sys

from zyko.mind.cli import main

if __name__ == "__main__":
    sys.exit(main())
