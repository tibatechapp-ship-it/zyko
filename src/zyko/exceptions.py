"""Exception hierarchy for ZYKO.

Every error raised intentionally by ZYKO derives from :class:`ZykoError`, so
callers can catch a single base class. Errors carry an optional ``hint`` with
actionable advice — printed by the CLI, preserved in receipts.
"""

from __future__ import annotations


class ZykoError(Exception):
    """Base class for every ZYKO error."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base}\nhint: {self.hint}" if self.hint else base


class ConfigError(ZykoError):
    """Invalid or missing configuration (config file, env vars, provider keys)."""


class ProviderError(ZykoError):
    """Error reported by (or while contacting) a model provider."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        status: int | None = None,
        retryable: bool = False,
        hint: str | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.provider = provider
        self.status = status
        self.retryable = retryable


class RateLimitError(ProviderError):
    """Provider-side rate limit (HTTP 429). Always retryable.

    Carries ``retry_after`` (seconds) parsed from the vendor's ``Retry-After``
    header, so the retry loop can honor the vendor's own backoff instruction
    instead of guessing (the LiteLLM/OpenAI-SDK pattern).
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        retry_after: float | None = None,
        **kw,
    ) -> None:
        kw.setdefault("retryable", True)
        super().__init__(message, provider=provider, **kw)
        self.retry_after = retry_after


class AuthError(ProviderError):
    """Missing or invalid API key (HTTP 401/403). Not retried."""


class ModelNotFoundError(ZykoError):
    """Requested model does not exist in any configured provider catalog."""


class PolicyViolation(ZykoError):
    """A request was denied by the Policy-as-Code engine."""

    def __init__(self, message: str, *, rule: str | None = None, hint: str | None = None) -> None:
        super().__init__(message, hint=hint)
        self.rule = rule


class BudgetExceededError(PolicyViolation):
    """Daily spending budget defined in the policy has been exhausted."""


class LocalRateLimitError(PolicyViolation):
    """Local token-bucket rate limit defined in the policy was hit."""


class ToolError(ZykoError):
    """A tool executed by an agent failed."""


class AgentLimitError(ZykoError):
    """Agent loop stopped because it reached its step/token limit."""


class CrewError(ZykoError):
    """Multi-agent crew failure: empty pipeline, duplicate output key, bad template."""


class MCPError(ZykoError):
    """Model Context Protocol client/server failure."""


class GatewayAuthError(ConfigError):
    """Gateway users-file failure: bad YAML, duplicate names, unknown roles.

    A subclass of :class:`ConfigError` — a broken users file is a deployment
    bug and must surface before the gateway binds, never at request time.
    """


class ZykoTimeoutError(ZykoError):
    """Operation exceeded its deadline."""


class EmbedderError(ZykoError):
    """Embeddings failure (RAG): bad request, unreachable embedder, dim mismatch."""


class SchemaSpecError(ZykoError):
    """Invalid structured-output schema (a caller bug, not a model failure).

    Raised when the schema itself is malformed — a non-mapping root, an
    unknown ``type``, a broken ``$ref`` — as opposed to
    :class:`StructuredOutputError`, which fires when a *model's* output fails
    validation against a well-formed schema.
    """


class StructuredOutputError(ZykoError):
    """A model's output failed structured-output validation after all repairs.

    Carries ``errors`` (the failing round's validation problems) and ``text``
    (the last raw model output) so callers can log or retry with their own
    strategy. This is the typed failure ZYKO raises instead of leaking a raw
    ``ValueError`` from the validator.
    """

    def __init__(
        self,
        message: str,
        *,
        errors: list[str] | None = None,
        text: str | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.errors = errors or []
        self.text = text
