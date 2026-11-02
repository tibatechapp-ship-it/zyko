"""Structured-output engine: schema-constrained answers with an automatic
repair round — the ZYKO answer to LangChain's ``with_structured_output``,
CrewAI's Pydantic task outputs and AutoGen's ``response_format``.

Two strategies, selectable per call:

- **Guided (default)** — the schema rides in the prompt, the reply is
  extracted (fences/prose/``<think>``-proof), validated against the JSON
  Schema subset, and — on failure — repaired in one extra round that feeds
  the exact validation errors back to the model. Works on *every* provider,
  including ones with no native structured-output support.
- **Native** (``native=True``) — the schema is sent as OpenAI
  ``response_format: {"type": "json_schema", …}`` for vendors that support
  it (OpenAI, Groq, Mistral, DeepSeek, OpenRouter, Together, xAI); vendors
  that reject it simply fail the attempt and the router falls back, so
  native mode composes with failover instead of fighting it.

Either way the caller gets a validated :class:`StructuredResult` or a typed
:class:`~zyko.exceptions.StructuredOutputError` — never a raw string to
``json.loads`` by hand.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from zyko.core.messages import Message
from zyko.core.response import ChatRequest, ChatResponse
from zyko.exceptions import StructuredOutputError
from zyko.router.engine import RouteResult
from zyko.structured.extract import extract_json
from zyko.structured.schema import json_schema_of, validate_against_schema

GUIDED_INSTRUCTION = (
    "Respond with ONLY a single JSON value that conforms to the JSON Schema "
    "below. No prose before or after, no markdown fences, no comments.\n"
    "JSON Schema:\n"
)

REPAIR_INSTRUCTION = (
    "Your previous response did not conform to the required JSON Schema.\n"
    "Problems found:\n{problems}\n"
    "Respond again with ONLY corrected JSON that conforms to the schema. "
    "No prose, no markdown fences."
)

MAX_ERRORS_IN_REPAIR = 12


@dataclass
class StructuredResult:
    """A validated structured answer plus its full provenance."""

    data: Any
    schema: dict[str, Any]
    route: RouteResult
    rounds: list[list[str]] = field(default_factory=list)  # errors per round
    native: bool = False

    @property
    def repaired(self) -> bool:
        return len(self.rounds) > 1

    @property
    def response(self) -> ChatResponse | None:
        return self.route.response


def _schema_snippet(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, sort_keys=True)


class StructuredEngine:
    """Runs guided/native structured requests through a :class:`Router`."""

    def __init__(self, router: Any, *, default_max_repairs: int = 1) -> None:
        self.router = router
        self.default_max_repairs = max(0, int(default_max_repairs))

    # ------------------------------------------------------------------ core
    async def astructured(
        self,
        messages: list[Message],
        schema: Any,
        *,
        model: str | None = None,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_repairs: int | None = None,
        native: bool = False,
        instruction: str | None = None,
    ) -> StructuredResult:
        """Return a validated ``data`` for ``messages`` under ``schema``.

        Raises :class:`StructuredOutputError` when every round (initial +
        ``max_repairs`` repair rounds) still fails validation, and
        :class:`SchemaSpecError` when the schema itself is malformed.
        """
        schema_dict = json_schema_of(schema)
        repairs = self.default_max_repairs if max_repairs is None else max(0, int(max_repairs))

        base_messages = list(messages)
        if system:
            base_messages.insert(0, Message.system(system))

        response_format: dict[str, Any] | None = None
        if native:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": schema_dict,
                },
            }
        else:
            guide = instruction or GUIDED_INSTRUCTION
            base_messages.append(Message.system(f"{guide}{_schema_snippet(schema_dict)}"))

        rounds: list[list[str]] = []
        convo = base_messages
        last_text = ""
        attempt = 0
        while True:
            request = ChatRequest(
                messages=convo,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
            route = await self.router.aroute(request)
            last_text = (route.response.text if route.response else "") or ""
            parsed = extract_json(last_text)
            if parsed is None:
                errors = ["output is not parseable JSON"]
            else:
                errors = validate_against_schema(parsed, schema_dict)
            rounds.append(errors)
            if not errors:
                return StructuredResult(
                    data=parsed,
                    schema=schema_dict,
                    route=route,
                    rounds=rounds,
                    native=native,
                )
            if attempt >= repairs:
                raise _exhausted(errors, last_text, attempt + 1)
            convo = [
                *base_messages,
                Message.assistant(last_text),
                Message.user(
                    REPAIR_INSTRUCTION.format(
                        problems="\n".join(f"- {e}" for e in errors[:MAX_ERRORS_IN_REPAIR])
                    )
                ),
            ]
            attempt += 1

    # ------------------------------------------------------------------- sync
    def structured(self, *args: Any, **kwargs: Any) -> StructuredResult:
        from zyko.utils.loop import run_sync

        return run_sync(self.astructured(*args, **kwargs))


def _exhausted(errors: list[str], text: str, rounds: int) -> StructuredOutputError:
    shown = "; ".join(errors[:3])
    more = f" (+{len(errors) - 3} more)" if len(errors) > 3 else ""
    return StructuredOutputError(
        f"structured output failed validation after {rounds} round(s): {shown}{more}",
        errors=errors,
        text=text[:2000],
        hint=(
            "raise max_repairs, simplify the schema, or pass native=True for "
            "vendors that support response_format"
        ),
    )


__all__ = ["StructuredEngine", "StructuredResult"]
