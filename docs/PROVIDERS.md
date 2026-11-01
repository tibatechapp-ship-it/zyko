# ZYKO Providers Guide

How ZYKO discovers providers, how to configure each built-in vendor, how to
add **any** OpenAI-compatible vendor, and how pricing feeds routing.

## Discovery in 30 seconds

`configured_providers()` (used by `Zyko()`, the CLI and the gateway) collects:

1. every built-in provider whose **key env** is set (or whose YAML block exists),
2. **Ollama** when a local server answers at `127.0.0.1:11434` (probed once, cached),
3. **mock** when `ZYKO_DEMO=1` — keyless offline mode for CI and demos.

No key at all? ZYKO still boots in demo mode and tells you so — nothing crashes.

## Built-in providers

| Provider | Key env | Base URL | Notes |
|---|---|---|---|
| OpenAI | `OPENAI_API_KEY` | `https://api.openai.com/v1` | also the template for custom vendors |
| Anthropic | `ANTHROPIC_API_KEY` | `https://api.anthropic.com/v1` | Messages API dialect |
| Google Gemini | `GEMINI_API_KEY` / `GOOGLE_API_KEY` | `https://generativelanguage.googleapis.com/v1beta` | both env names accepted |
| Groq | `GROQ_API_KEY` | `https://api.groq.com/openai/v1` | OpenAI-compatible |
| Mistral | `MISTRAL_API_KEY` | `https://api.mistral.ai/v1` | OpenAI-compatible |
| DeepSeek | `DEEPSEEK_API_KEY` | `https://api.deepseek.com/v1` | OpenAI-compatible |
| OpenRouter | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` | hundreds of models behind one key |
| Ollama | — | `http://127.0.0.1:11434` | keyless, local, offline |
| Mock | — | `mock://local` | deterministic, `ZYKO_DEMO=1` |

```bash
# mix vendors freely — the router balances across all of them
export OPENAI_API_KEY=sk-...
export GROQ_API_KEY=gsk_...
export OPENROUTER_API_KEY=sk-or-...
zyko models        # see every discovered model with scores
zyko route "hi"    # routing plan, no API call
```

## YAML configuration (per-provider)

`~/.zyko/zyko.yaml` (or `$ZYKO_CONFIG_DIR/zyko.yaml`):

```yaml
providers:
  openai:
    api_key: ${OPENAI_API_KEY}        # ${VAR} interpolation supported
  groq:
    base_url: https://api.groq.com/openai/v1   # optional override
  ollama:
    base_url: http://127.0.0.1:11434
  openrouter:
    api_key: ${OPENROUTER_API_KEY}

router:
  strategy: balanced        # quality | cost | latency | balanced
  max_fallbacks: 3
  request_timeout_s: 120
  retries: 2
  breaker_threshold: 3
  breaker_cooldown_s: 30
```

Env shortcuts: `ZYKO_ROUTER_STRATEGY`, `ZYKO_REQUEST_TIMEOUT`,
`ZYKO_GATEWAY_HOST/PORT/API_KEY`, `ZYKO_DEFAULT_POLICY`.

## Any OpenAI-compatible vendor

Together, Fireworks, LM Studio, vLLM, LiteLLM proxies, local llama.cpp
servers — anything speaking the OpenAI protocol:

```python
from zyko.providers.openai_compat import OpenAICompatProvider
from zyko import Zyko

together = OpenAICompatProvider(
    api_key="...", base_url="https://api.together.xyz/v1"
)
zk = Zyko(providers={"together": together})
print(zk.ask("hello").receipt["chosen"])
```

Per-model catalog/price overrides can be declared in the provider YAML block
(the settings key `prices_file` points at a custom pricing table that feeds
the cost normaliser).

## Pricing → routing

The router's cost component normalises each candidate's estimated request
cost against the live board (cheapest → 1.0, priciest → ~0.0). Prices come
from the provider catalogs (override with `prices_file`). Vendor-reported
usage replaces estimates when available and the receipt flags it:

```json
{ "cost_usd": 0.00042, "estimated": false, "input_tokens": 131, "output_tokens": 88 }
```

`estimated: true` rows are clearly marked — estimates are never silently
blended with vendor numbers (`zyko cost` reports both views).

## Resilience per provider

- **Retries**: exponential backoff with jitter (capped 8 s); a vendor
  `Retry-After` header is honoured exactly (clamped 0.05–30 s).
- **Circuit breaker**: `breaker_threshold` consecutive failures open the
  circuit for `breaker_cooldown_s`; open candidates are skipped with an
  auditable `skipped-breaker` attempt row.
- **Fallbacks**: up to `max_fallbacks` candidates per request, always
  best-scored-first, policy-checked each time.
- **Timeouts**: `router.request_timeout_s` per attempt; MCP transport has
  its own `request_timeout` (default 20 s).

## Keyless-first workflows

```bash
ZYKO_DEMO=1 zyko chat            # zero-key demo: mock provider, offline
ollama serve && zyko chat        # fully local, no keys, real models
zyko serve --demo --port 8788    # keyless OpenAI-compatible gateway for testing
```

CI usage (no secrets needed):

```bash
ZYKO_DEMO=1 pytest -q            # the whole 347-test suite runs keyless
ZYKO_DEMO=1 zyko bench --demo    # reproducible benchmark in offline mode
```
