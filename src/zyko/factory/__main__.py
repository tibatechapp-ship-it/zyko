"""تشغيل مباشر: python -m zyko.factory — نفس بوابة ``zyko factory``."""

from __future__ import annotations

import sys

from zyko.factory.cli import main

if __name__ == "__main__":
    sys.exit(main())
