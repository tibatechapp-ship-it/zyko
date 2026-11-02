"""JSON Schema subset validator — pure Python, zero dependencies.

Every competitor forces a framework on you: LangChain requires Pydantic
models, AutoGen requires ``response_format`` support from the vendor, CrewAI
ties structure to task objects. ZYKO validates a plain JSON Schema dict with
nothing but the standard library — and *additionally* accepts Pydantic v2
models when Pydantic happens to be installed (``zyko[structured]``).

Supported keywords (documented subset, JSON Schema Draft 2020-12 flavour):

- ``type`` (single or list), ``enum``, ``const``
- numeric: ``minimum``, ``maximum``, ``exclusiveMinimum``, ``exclusiveMaximum``,
  ``multipleOf`` (bools are rejected for numeric types — Python's
  ``bool``/``int`` overlap is the classic silent-wrong-validation bug)
- string: ``minLength``, ``maxLength``, ``pattern`` (search semantics),
  ``format`` for ``email``, ``date``, ``date-time``, ``uri``, ``uuid``,
  ``ipv4``, ``hostname``
- array: ``items``, ``minItems``, ``maxItems``, ``uniqueItems``
- object: ``properties``, ``required``, ``additionalProperties`` (bool or
  schema), ``minProperties``, ``maxProperties``
- composition: ``allOf``, ``anyOf``, ``oneOf``
- references: ``$ref`` with local JSON pointers (``#/$defs/...``) resolved
  against the root — required for Pydantic v2 schemas, which always use
  ``$defs``; guarded against cycles

Unknown keywords are ignored (per spec) so vendors' annotation keys
(``title``, ``description``, ``examples`` …) pass through harmlessly.

Malformed schemas raise :class:`~zyko.exceptions.SchemaSpecError` immediately —
a schema bug is a caller bug and must fail fast, never masquerade as a model
failure.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from zyko.exceptions import SchemaSpecError

MAX_DEPTH = 64

_FORMATS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    "date": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "date-time": re.compile(r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}"),
    "uri": re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE),
    "uuid": re.compile(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    ),
    "ipv4": re.compile(r"^(\d{1,3}\.){3}\d{1,3}$"),
    "hostname": re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})?$"),
}


def _spec(message: str, *, hint: str | None = None) -> SchemaSpecError:
    return SchemaSpecError(f"invalid schema: {message}", hint=hint)


def json_schema_of(spec: Any) -> dict[str, Any]:
    """Normalise a structured-output spec to a plain JSON Schema dict.

    Accepts a dict (returned as-is) or a Pydantic v2 model class/instance
    (``model_json_schema()``); Pydantic v1 models (``schema()``) are honoured
    too when present. Anything else is a :class:`SchemaSpecError`.
    """
    if isinstance(spec, dict):
        return spec
    for attr in ("model_json_schema", "schema"):  # pydantic v2, then v1
        method = getattr(spec, attr, None)
        if callable(method):
            result = method()
            if isinstance(result, dict):
                return result
    raise _spec(
        f"unsupported schema spec of type {type(spec).__name__!r}",
        hint="pass a JSON Schema dict, or a Pydantic model (zyko[structured])",
    )


def _type_ok(value: Any, type_name: str) -> bool:
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "null":
        return value is None
    raise _spec(
        f"unknown type {type_name!r}",
        hint="use object|array|string|boolean|integer|number|null",
    )


def _enum_matches(value: Any, options: list[Any]) -> bool:
    """Type-aware membership: JSON distinguishes ``1`` from ``True``/``1.0``."""
    for option in options:
        if type(value) is type(option) and value == option:
            return True
    return False


def _resolve_ref(ref: str, root: dict[str, Any]) -> Any:
    if not isinstance(ref, str) or not ref.startswith("#"):
        raise _spec(
            f"unsupported $ref {ref!r}",
            hint="only local JSON pointers ('#/$defs/Name') are supported",
        )
    target: Any = root
    for part in ref.lstrip("#/").split("/"):
        if part == "":
            continue
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(target, dict):
            if part not in target:
                raise _spec(f"$ref target {ref!r} does not resolve")
            target = target[part]
        elif isinstance(target, list):
            try:
                target = target[int(part)]
            except (ValueError, IndexError):
                raise _spec(f"$ref target {ref!r} does not resolve") from None
        else:
            raise _spec(f"$ref target {ref!r} does not resolve")
    return target


def _validate(value: Any, schema: Any, path: str, root: dict[str, Any], depth: int) -> list[str]:
    if depth > MAX_DEPTH:
        return [f"{path}: schema nesting exceeds MAX_DEPTH ({MAX_DEPTH})"]
    if schema is True or schema == {}:
        return []
    if schema is False:
        return [f"{path}: schema forbids any value"]
    if not isinstance(schema, dict):
        raise _spec(
            f"schema at {path} must be an object, got {type(schema).__name__}",
            hint="schemas are JSON Schema dicts (or True/False)",
        )

    if "$ref" in schema:
        return _validate(value, _resolve_ref(schema["$ref"], root), path, root, depth + 1)

    errors: list[str] = []

    if "enum" in schema:
        options = schema["enum"]
        if not isinstance(options, list):
            raise _spec(f"'enum' at {path} must be a list")
        if not _enum_matches(value, options):
            errors.append(f"{path}: value {value!r} is not one of {options!r}")

    if "const" in schema:
        const = schema["const"]
        if not (type(value) is type(const) and value == const):
            errors.append(f"{path}: value {value!r} != const {const!r}")

    if "anyOf" in schema:
        branches = schema["anyOf"]
        if not isinstance(branches, list) or not branches:
            raise _spec(f"'anyOf' at {path} must be a non-empty list")
        for branch in branches:
            if not _validate(value, branch, path, root, depth + 1):
                return errors  # anyOf passed; report only enum/const failures above
        errors.append(f"{path}: does not match any anyOf branch")

    if "oneOf" in schema:
        branches = schema["oneOf"]
        if not isinstance(branches, list) or not branches:
            raise _spec(f"'oneOf' at {path} must be a non-empty list")
        matches = sum(1 for b in branches if not _validate(value, b, path, root, depth + 1))
        if matches != 1:
            errors.append(f"{path}: matches {matches} oneOf branches (exactly 1 required)")

    if "allOf" in schema:
        branches = schema["allOf"]
        if not isinstance(branches, list) or not branches:
            raise _spec(f"'allOf' at {path} must be a non-empty list")
        for branch in branches:
            errors.extend(_validate(value, branch, path, root, depth + 1))

    type_spec = schema.get("type")
    if type_spec is not None:
        names = type_spec if isinstance(type_spec, list) else [type_spec]
        for name in names:
            if not isinstance(name, str):
                raise _spec(f"'type' at {path} must be a string or list of strings")
        if not any(_type_ok(value, name) for name in names):
            errors.append(
                f"{path}: expected type {' | '.join(str(t) for t in names)}, "
                f"got {type(value).__name__}"
            )
            return errors  # a type mismatch makes the keyword checks below noise

    numeric = schema.get("type") in ("number", "integer") or (
        isinstance(schema.get("type"), list) and "number" in schema["type"]
    )
    if numeric and isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            errors.append(f"{path}: number must be finite, got {value!r}")
            return errors
        for key, ok in (
            ("minimum", lambda v, b: v >= b),
            ("maximum", lambda v, b: v <= b),
            ("exclusiveMinimum", lambda v, b: v > b),
            ("exclusiveMaximum", lambda v, b: v < b),
        ):
            if key in schema:
                bound = schema[key]
                if not isinstance(bound, (int, float)) or isinstance(bound, bool):
                    raise _spec(f"'{key}' at {path} must be a number")
                if not ok(value, bound):
                    errors.append(f"{path}: {value!r} violates {key}={bound!r}")
        multiple = schema.get("multipleOf")
        if multiple is not None:
            if (
                not isinstance(multiple, (int, float))
                or isinstance(multiple, bool)
                or multiple <= 0
            ):
                raise _spec(f"'multipleOf' at {path} must be a positive number")
            quotient = value / multiple
            if abs(quotient - round(quotient)) > 1e-9:
                errors.append(f"{path}: {value!r} is not a multiple of {multiple!r}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: length {len(value)} < minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: length {len(value)} > maxLength {schema['maxLength']}")
        pattern = schema.get("pattern")
        if pattern is not None:
            if not isinstance(pattern, str):
                raise _spec(f"'pattern' at {path} must be a string")
            try:
                if not re.search(pattern, value):
                    errors.append(f"{path}: {value!r} does not match pattern {pattern!r}")
            except re.error as exc:
                raise _spec(f"'pattern' at {path} is not a valid regex: {exc}") from None
        fmt = schema.get("format")
        if isinstance(fmt, str) and fmt in _FORMATS:
            if not _FORMATS[fmt].match(value):
                errors.append(f"{path}: {value!r} is not a valid {fmt}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: {len(value)} items < minItems {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: {len(value)} items > maxItems {schema['maxItems']}")
        if schema.get("uniqueItems"):
            seen: set[str] = set()
            for item in value:
                marker = json.dumps(item, sort_keys=True, default=str)
                if marker in seen:
                    errors.append(f"{path}: duplicate item {marker[:60]!r}")
                    break
                seen.add(marker)
        items = schema.get("items")
        if items is not None:
            for index, item in enumerate(value):
                errors.extend(_validate(item, items, f"{path}[{index}]", root, depth + 1))

    if isinstance(value, dict):
        props = schema.get("properties")
        if props is not None:
            if not isinstance(props, dict):
                raise _spec(f"'properties' at {path} must be an object")
            for name, sub in props.items():
                if name in value:
                    errors.extend(_validate(value[name], sub, f"{path}.{name}", root, depth + 1))
        for required in schema.get("required", []):
            if not isinstance(required, str):
                raise _spec(f"'required' at {path} must list property names")
            if required not in value:
                errors.append(f"{path}: missing required property {required!r}")
        additional = schema.get("additionalProperties", True)
        if additional is not True:
            extras = sorted(set(value) - set(props or {}))
            if additional is False:
                if extras:
                    errors.append(f"{path}: unexpected properties {extras}")
            elif isinstance(additional, dict):
                for name in extras:
                    errors.extend(
                        _validate(value[name], additional, f"{path}.{name}", root, depth + 1)
                    )
            else:
                raise _spec(f"'additionalProperties' at {path} must be a boolean or a schema")
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            errors.append(
                f"{path}: {len(value)} properties < minProperties {schema['minProperties']}"
            )
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            errors.append(
                f"{path}: {len(value)} properties > maxProperties {schema['maxProperties']}"
            )

    return errors


def validate_against_schema(value: Any, schema: Any) -> list[str]:
    """Validate ``value`` against a JSON Schema subset; return a list of problems.

    An empty list means valid. Paths use dotted notation
    (``$.order.items[0].sku``) so repairs can quote problems back to the
    model. Structural malformations of the schema itself raise
    :class:`~zyko.exceptions.SchemaSpecError` — see module docstring for the
    supported keyword subset.
    """
    if not isinstance(schema, (dict, bool)):
        raise _spec(
            f"root schema must be an object or boolean, got {type(schema).__name__}",
            hint="pass a JSON Schema dict — see zyko.structured",
        )
    root: dict[str, Any] = schema if isinstance(schema, dict) else {}
    return _validate(value, schema, "$", root, 0)


__all__ = ["json_schema_of", "validate_against_schema"]
