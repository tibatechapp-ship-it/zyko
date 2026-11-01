"""Logging helpers.

ZYKO is a library first: by default it attaches a ``NullHandler`` so importers
stay quiet. The CLI calls :func:`setup_logging` to activate output.
"""

from __future__ import annotations

import logging

_CONFIGURED = False


def setup_logging(level: str = "INFO", *, quiet: bool = False) -> None:
    """Configure the ``zyko`` logger tree for CLI usage."""
    global _CONFIGURED
    root = logging.getLogger("zyko")
    if _CONFIGURED:
        root.setLevel(logging.DEBUG if level == "DEBUG" else logging.INFO)
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    )
    root.addHandler(handler)
    root.setLevel(logging.CRITICAL if quiet else getattr(logging, level.upper(), logging.INFO))
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"zyko.{name}")


# Library default: stay silent unless the host application opts in.
logging.getLogger("zyko").addHandler(logging.NullHandler())
