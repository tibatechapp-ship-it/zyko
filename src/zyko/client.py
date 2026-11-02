"""The one-liner client: ``Zyko()`` wires config, providers, policy, router.

from zyko import Zyko

zk = Zyko()                      # keys from the environment
answer = zk.ask("hello")         # routed, policy-checked, receipted
print(answer.response.text)
print(answer.receipt["chosen"])  # verifiable routing decision
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from zyko.agents.agent import Agent
from zyko.agents.loader import build_agent, load_agent_document
from zyko.config.settings import Settings
from zyko.core.messages import Message
from zyko.core.response import ChatRequest
from zyko.policy.engine import PolicyEngine, load_policy
from zyko.providers import configured_providers
from zyko.providers.base import BaseProvider
from zyko.router.engine import Router, RouteResult
from zyko.router.quality import QualityLedger
from zyko.structured.engine import StructuredEngine, StructuredResult
from zyko.utils.loop import run_sync


class Zyko:
    """High-level entrypoint over the whole stack."""

    def __init__(
        self,
        *,
        config_path: str | Path | None = None,
        policy: str | PolicyEngine | None = None,
        strategy: str | None = None,
        providers: dict[str, BaseProvider] | None = None,
        ledger_path: Path | None = None,
    ) -> None:
        self.settings = Settings.load(config_path)
        self.providers = (
            providers
            if providers is not None
            else configured_providers(self.settings.provider_settings)
        )
        resolved = policy if policy is not None else self.settings.get("default_policy")
        if isinstance(resolved, str):
            self.policy = load_policy(resolved)
        elif isinstance(resolved, PolicyEngine):
            self.policy = resolved
        else:
            self.policy = None
        from zyko.observability.tracer import load_tracer
        from zyko.platform.paths import ledger_file

        self.ledger = QualityLedger.load(ledger_path or ledger_file())
        # Public so callers can wrap their own spans around ZYKO calls:
        #   with zk.tracer.span("my-rag"): zk.ask(...)
        self.tracer = load_tracer(self.settings)
        self.router = Router(
            self.providers,
            ledger=self.ledger,
            policy=self.policy,
            strategy=strategy or self.settings.get("router.strategy", "balanced"),
            max_fallbacks=int(self.settings.get("router.max_fallbacks", 3)),
            cache=self.policy.cache if self.policy else None,
            tracer=self.tracer,
        )
        self.__engine: StructuredEngine | None = None

    # ------------------------------------------------------------- completion
    async def aask(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> RouteResult:
        messages: list[Message] = []
        if system:
            messages.append(Message.system(system))
        messages.append(Message.user(prompt))
        request = ChatRequest(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return await self.router.aroute(request)

    def ask(self, prompt: str, **kwargs: Any) -> RouteResult:
        return run_sync(self.aask(prompt, **kwargs))

    async def achat(
        self, messages: list[Message], *, model: str | None = None, **kwargs: Any
    ) -> RouteResult:
        return await self.router.aroute(ChatRequest(messages=messages, model=model, **kwargs))

    def chat(self, messages: list[Message], **kwargs: Any) -> RouteResult:
        return run_sync(self.achat(messages, **kwargs))

    # ----------------------------------------------------------------- agents
    def agent(self, source: str, *, workspace: str = ".") -> Agent:
        doc = load_agent_document(source)
        return build_agent(doc, self.router, policy=self.policy, workspace=workspace)

    # ------------------------------------------------------------- structured
    async def astructured(
        self,
        prompt: str,
        schema: Any,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_repairs: int = 1,
        native: bool = False,
    ) -> StructuredResult:
        """Structured answer: validated against a JSON Schema (or Pydantic model).

        Guided mode (default) rides the prompt and repairs invalid output once
        by feeding the validation errors back; ``native=True`` sends OpenAI
        ``response_format`` for vendors that support it. Raises
        :class:`~zyko.exceptions.StructuredOutputError` after the repair budget
        is exhausted — ``out.data`` is always a validated value.
        """
        messages: list[Message] = []
        if system:
            messages.append(Message.system(system))
        messages.append(Message.user(prompt))
        return await self._structured_engine.astructured(
            messages,
            schema,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            max_repairs=max_repairs,
            native=native,
        )

    async def astructured_messages(
        self, messages: list[Message], schema: Any, **kwargs: Any
    ) -> StructuredResult:
        """Structured answer over an explicit conversation (see astructured)."""
        return await self._structured_engine.astructured(messages, schema, **kwargs)

    def structured(self, prompt: str, schema: Any, **kwargs: Any) -> StructuredResult:
        return run_sync(self.astructured(prompt, schema, **kwargs))

    def structured_messages(
        self, messages: list[Message], schema: Any, **kwargs: Any
    ) -> StructuredResult:
        return run_sync(self.astructured_messages(messages, schema, **kwargs))

    @property
    def _structured_engine(self) -> StructuredEngine:
        if self.__engine is None:
            self.__engine = StructuredEngine(self.router)
        return self.__engine

    # ------------------------------------------------------------------- misc
    def explain(self) -> dict[str, Any]:
        """Current routing outlook (no API call): ranked candidates + reasons."""
        return self.router.explain()

    @property
    def receipt_schema_note(self) -> str:
        return "Every RouteResult carries a receipt; verify decisions offline via `zyko route --explain`."


__all__ = ["Zyko", "RouteResult", "StructuredResult"]
