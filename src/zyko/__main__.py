"""``python -m zyko`` → the ZYKO CLI (same as the ``zyko`` entrypoint)."""

from zyko.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
