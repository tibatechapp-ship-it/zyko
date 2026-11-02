"""Structured output — schema-constrained answers with automatic repair.

The competitor-parity surface: ``Zyko().structured("…", schema)``, the
zero-dependency JSON Schema validator (:func:`validate_against_schema`), the
robust JSON extractor (:func:`extract_json`) and the typed failures.

    from zyko import Zyko

    zk = Zyko()
    out = zk.structured("order 42 details?", schema={
        "type": "object",
        "properties": {"id": {"type": "integer"}, "status": {"type": "string"}},
        "required": ["id", "status"],
    })
    out.data  # {"id": 42, "status": "shipped"} — validated, or a typed error
"""

from __future__ import annotations

from zyko.structured.engine import StructuredEngine, StructuredResult
from zyko.structured.extract import extract_json
from zyko.structured.schema import json_schema_of, validate_against_schema

__all__ = [
    "StructuredEngine",
    "StructuredResult",
    "extract_json",
    "json_schema_of",
    "validate_against_schema",
]
