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
        from zyko.platform.paths import ledger_file

        self.ledger = QualityLedger.load(ledger_path or ledger_file())
        self.router = Router(
            self.providers,
            ledger=self.ledger,
            policy=self.policy,
            strategy=strategy or self.settings.get("router.strategy", "balanced"),
            max_fallbacks=int(self.settings.get("router.max_fallbacks", 3)),
        )

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

    # ------------------------------------------------------------------- misc
    def explain(self) -> dict[str, Any]:
        """Current routing outlook (no API call): ranked candidates + reasons."""
        return self.router.explain()

    @property
    def receipt_schema_note(self) -> str:
        return "Every RouteResult carries a receipt; verify decisions offline via `zyko route --explain`."


__all__ = ["Zyko", "RouteResult"]
