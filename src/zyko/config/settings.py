"""Settings loading with layered precedence.

Precedence (lowest → highest):
    1. built-in defaults
    2. ``config.yaml`` in the platform config dir
    3. ``ZYKO_*`` environment variables
    4. explicit keyword overrides in code

YAML files support ``${ENV_VAR}`` interpolation, so secrets can stay out of
the file entirely — important on shared machines and mobile devices.
"""

from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any

from zyko.exceptions import ConfigError
from zyko.log import get_logger
from zyko.platform.paths import config_file

log = get_logger("config")

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

DEFAULTS: dict[str, Any] = {
    "default_policy": None,
    "router": {
        "strategy": "balanced",
        "max_fallbacks": 3,
        "request_timeout_s": 120.0,
        "retries": 2,
        "breaker_threshold": 3,
        "breaker_cooldown_s": 30.0,
    },
    "providers": {},
    "gateway": {
        "host": "127.0.0.1",
        "port": 8787,
        "api_key": None,
    },
    "prices_file": None,
}

_ENV_OVERRIDES: dict[str, str] = {
    "ZYKO_ROUTER_STRATEGY": "router.strategy",
    "ZYKO_REQUEST_TIMEOUT": "router.request_timeout_s",
    "ZYKO_DEFAULT_POLICY": "default_policy",
    "ZYKO_GATEWAY_HOST": "gateway.host",
    "ZYKO_GATEWAY_PORT": "gateway.port",
    "ZYKO_GATEWAY_API_KEY": "gateway.api_key",
}


def _interpolate(raw: str) -> str:
    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        return os.environ.get(name, match.group(0))

    return _ENV_RE.sub(repl, raw)


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _coerce(value: str, key: str) -> Any:
    if key.endswith(("_s", "port")) or key in {"max_fallbacks", "retries", "breaker_threshold"}:
        try:
            return float(value) if "." in value or key.endswith("_s") else int(value)
        except ValueError:
            pass
    return value


class Settings:
    """Typed accessor over the merged configuration mapping."""

    def __init__(self, data: dict[str, Any], *, source: Path | None = None) -> None:
        self._data = data
        self.source = source

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Settings":
        # Deep-copy the module-level DEFAULTS first: _deep_merge shares nested
        # dicts, and env/YAML overrides used to mutate DEFAULTS permanently —
        # every later Settings.load() in the same process inherited the first
        # call's environment (a global-state leak that also cross-contaminated
        # tests and long-lived gateway processes).
        data = _deep_merge(copy.deepcopy(DEFAULTS), {})
        source: Path | None = None
        candidates = [Path(path)] if path else [config_file()]
        for cand in candidates:
            if not cand.exists():
                continue
            try:
                import yaml

                raw = cand.read_text(encoding="utf-8")
                loaded = yaml.safe_load(_interpolate(raw)) or {}
            except ImportError as exc:  # pragma: no cover - guarded by deps
                raise ConfigError("PyYAML is required to read config files") from exc
            except Exception as exc:
                raise ConfigError(f"invalid config file {cand}: {exc}") from exc
            if not isinstance(loaded, dict):
                raise ConfigError(f"config file {cand} must contain a YAML mapping")
            data = _deep_merge(data, loaded)
            source = cand
            break
        for env_key, dotted in _ENV_OVERRIDES.items():
            value = os.environ.get(env_key)
            if value is None:
                continue
            node = data
            parts = dotted.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = _coerce(value, parts[-1])
        return cls(data, source=source)

    # -- accessors ---------------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> dict[str, Any]:
        value = self.get(name, {})
        return value if isinstance(value, dict) else {}

    @property
    def provider_settings(self) -> dict[str, dict[str, Any]]:
        return {k: v for k, v in self.section("providers").items() if isinstance(v, dict)}

    def provider_setting(self, name: str) -> dict[str, Any]:
        return self.provider_settings.get(name, {})

    def write_template(self, path: str | Path | None = None) -> Path:
        """Write a commented starter config; returns the path written."""
        target = Path(path) if path else config_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise ConfigError(f"refusing to overwrite existing config: {target}")
        target.write_text(_TEMPLATE, encoding="utf-8")
        log.info("config template written to %s", target)
        return target


_TEMPLATE = """\
# ZYKO configuration (https://github.com/tibatechapp-ship-it/zyko)
# API keys are read from the environment by default; use ${ENV_VAR} to wire them here.

router:
  strategy: balanced        # quality | cost | latency | balanced
  max_fallbacks: 3
  request_timeout_s: 120
  retries: 2

providers:
  openai: {}                # key: OPENAI_API_KEY
  anthropic: {}             # key: ANTHROPIC_API_KEY
  google: {}                # key: GEMINI_API_KEY
  groq: {}                  # key: GROQ_API_KEY
  ollama:
    base_url: http://127.0.0.1:11434

gateway:
  host: 127.0.0.1
  port: 8787
  api_key: null             # set to require a bearer token on /v1/*

# default_policy: default   # name resolved from ~/.config/zyko/policies/
"""
