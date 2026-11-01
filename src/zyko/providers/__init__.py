"""Provider registry — discovery, construction and key resolution."""

from __future__ import annotations

import os
from typing import Any, TypeVar

from zyko.exceptions import ConfigError
from zyko.log import get_logger
from zyko.providers.anthropic import AnthropicProvider
from zyko.providers.base import BaseProvider
from zyko.providers.google import GoogleProvider
from zyko.providers.mock import MockProvider
from zyko.providers.ollama import OllamaProvider
from zyko.providers.openai_compat import (
    DeepSeekProvider,
    GroqProvider,
    MistralProvider,
    OpenAICompatProvider,
    OpenRouterProvider,
    TogetherProvider,
    XAIProvider,
)

log = get_logger("providers")

P = TypeVar("P", bound=BaseProvider)

_REGISTRY: dict[str, type[BaseProvider]] = {}


def register(cls: type[P]) -> type[P]:
    _REGISTRY[cls.name] = cls
    return cls


for _cls in (
    OpenAICompatProvider,
    AnthropicProvider,
    GoogleProvider,
    GroqProvider,
    MistralProvider,
    DeepSeekProvider,
    OpenRouterProvider,
    TogetherProvider,
    XAIProvider,
    OllamaProvider,
):
    register(_cls)


def provider_names() -> list[str]:
    return sorted(_REGISTRY)


def get_provider_class(name: str) -> type[BaseProvider]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ConfigError(
            f"unknown provider '{name}'",
            hint=f"available providers: {', '.join(provider_names())}",
        ) from None


def _resolve_key(cls: type[BaseProvider], settings: dict[str, Any]) -> str | None:
    key = settings.get("api_key")
    if key:
        return str(key)
    env_names = cls.KEY_ENV
    if env_names is None:
        return None
    if isinstance(env_names, str):
        env_names = (env_names,)
    for env in env_names:
        value = os.environ.get(env)
        if value:
            return value
    return None


def is_configured(name: str, settings: dict[str, Any] | None = None) -> bool:
    cls = get_provider_class(name)
    settings = settings or {}
    if cls.local:
        return True
    return _resolve_key(cls, settings) is not None


def build_provider(
    name: str, settings: dict[str, Any] | None = None, **kwargs: Any
) -> BaseProvider:
    """Instantiate a provider from its name + optional config section."""
    cls = get_provider_class(name)
    settings = settings or {}
    api_key = kwargs.pop("api_key", None) or _resolve_key(cls, settings)
    base_url = kwargs.pop("base_url", None) or settings.get("base_url")
    if not api_key and not cls.local:
        env_hint = (
            cls.KEY_ENV
            if isinstance(cls.KEY_ENV, str)
            else (cls.KEY_ENV[0] if cls.KEY_ENV else "<KEY>")
        )
        raise ConfigError(
            f"provider '{name}' has no API key",
            hint=f"export {env_hint}=<your-key> or set providers.{name}.api_key in the config",
        )
    timeout = kwargs.pop("timeout", None) or settings.get("timeout") or 120.0
    provider = cls(
        api_key=api_key,
        base_url=base_url,
        timeout=float(timeout),
        default_headers=settings.get("default_headers"),
        **kwargs,
    )
    log.debug("built provider %s (base_url=%s)", name, provider.base_url)
    return provider


def configured_providers(settings: dict[str, Any] | None = None) -> dict[str, BaseProvider]:
    """Build every provider that is usable right now (key present or local+up).

    Local providers (Ollama) are probed for reachability — with a short cache —
    so the router never ranks a backend that is not running.
    """
    settings = settings or {}
    out: dict[str, BaseProvider] = {}
    for name in provider_names():
        section = settings.get(name) or {}
        try:
            if not is_configured(name, section):
                continue
            provider = build_provider(name, section)
        except ConfigError as exc:
            log.debug("skip provider %s: %s", name, exc)
            continue
        if provider.local and hasattr(provider, "probe") and not _probe_cached(name, provider):
            log.debug("skip local provider %s: not reachable", name)
            continue
        out[name] = provider
    return out


_PROBE_CACHE: dict[str, tuple[float, bool]] = {}
_PROBE_TTL_S = 30.0


def _probe_cached(name: str, provider: BaseProvider) -> bool:
    import time

    cached = _PROBE_CACHE.get(name)
    now = time.time()
    if cached and now - cached[0] < _PROBE_TTL_S:
        return cached[1]
    reachable = bool(provider.probe())
    _PROBE_CACHE[name] = (now, reachable)
    return reachable


__all__ = [
    "BaseProvider",
    "OpenAICompatProvider",
    "AnthropicProvider",
    "GoogleProvider",
    "GroqProvider",
    "MistralProvider",
    "DeepSeekProvider",
    "OpenRouterProvider",
    "TogetherProvider",
    "XAIProvider",
    "OllamaProvider",
    "MockProvider",
    "register",
    "provider_names",
    "get_provider_class",
    "build_provider",
    "is_configured",
    "configured_providers",
]
