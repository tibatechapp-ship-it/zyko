# ZYKO API Reference

Everything a developer needs to drive ZYKO from Python. Every signature below
is taken verbatim from the source at the tagged release; nothing is invented.

```python
from zyko import Zyko, RouteResult, Message, ChatRequest, ChatResponse, ZykoError, __version__
```

---

## 1. The one-liner client — `Zyko`

`Zyko()` wires config → providers → policy → ledger → router in one call.

```python
class Zyko:
    def __init__(
        self,
        *,
        config_path: str | Path | None = None,
        policy: str | PolicyEngine | None = None,
        strategy: str | None = None,
        providers: dict[str, BaseProvider] | None = None,
        ledger_path: Path | None = None,
    ) -> None: ...
```

| Parameter | Meaning |
|---|---|
| `config_path` | explicit YAML settings file; otherwise `ZYKO_CONFIG_DIR/zyko.yaml` (or defaults) |
| `policy` | policy **name** (resolved via `load_policy`), a prebuilt `PolicyEngine`, or `None` (uses `default_policy` from settings) |
| `strategy` | routing strategy override: `quality` / `cost` / `latency` / `balanced` |
| `providers` | inject your own provider instances (skip auto-discovery entirely) |
| `ledger_path` | alternative quality-ledger file for reproducible quality scores |

### Completion

```python
async def aask(self, prompt: str, *, model: str | None = None, system: str | None = None,
               temperature: float | None = None, max_tokens: int | None = None) -> RouteResult: ...

def ask(self, prompt: str, **kwargs) -> RouteResult:          # sync wrapper

async def achat(self, messages: list[Message], *, model: str | None = None, **kwargs) -> RouteResult: ...

def chat(self, messages: list[Message], **kwargs) -> RouteResult:   # sync wrapper
```

```python
from zyko import Zyko

zk = Zyko()                          # keys straight from the environment
answer = zk.ask("Explain routing in one line", system="You are terse.")
print(answer.response.text)
print(answer.receipt["chosen"])      # e.g. "groq/llama-3.3-70b-versatile"
print(answer.receipt["attempts"])    # full candidate ordering with score parts
```

### Agents, introspection

```python
def agent(self, source: str, *, workspace: str = ".") -> Agent:   # YAML agent definition
def explain(self) -> dict[str, Any]:   # current routing outlook — NO API call
```

---

## 2. Routing — `Router`

```python
from zyko.router.engine import Router, RouteResult, RouteAttempt, ScoreBreakdown

Router(
    providers: dict[str, BaseProvider],
    *,
    ledger: QualityLedger | None = None,
    policy: PolicyEngine | None = None,
    strategy: str = "balanced",          # quality | cost | latency | balanced
    max_fallbacks: int = 3,
    breaker_threshold: int = 3,          # consecutive failures open the circuit
    breaker_cooldown_s: float = 30.0,
)
```

| Method | Purpose |
|---|---|
| `async aroute(request) -> RouteResult` | full route: rank → policy gate → call (with fallbacks) → receipt |
| `route(request)` | sync wrapper over `aroute` |
| `async astream_route(request) -> AsyncIterator[StreamEvent]` | streaming; falls back **only before the first token** |
| `stream_route(request)` | sync generator wrapper |
| `rank(*, est_input_tokens, est_output_tokens, pool=None)` | scored, ordered candidates — pure computation |
| `explain(*, est_input_tokens=..., est_output_tokens=...)` | strategy + ranking + score breakdowns (no API call) |
| `candidates_for(request)` | candidates allowed for this request (model/policy pre-filter) |

```python
@dataclass
class RouteResult:
    response: ChatResponse | None
    candidate: str | None               # "provider/model"
    attempts: list[RouteAttempt]        # every try: chosen | failed | skipped-breaker | skipped-policy
    receipt: dict[str, Any]             # verifiable routing decision (see ARCHITECTURE.md)
```

The receipt is the contract: candidate ordering, score components
(quality / cost / latency + weights), token accounting and the
`estimated: true|false` flag for cost rows. Re-verify offline with
`zyko route --explain`.

---

## 3. Messages & requests

```python
from zyko.core.messages import Message
from zyko.core.response import ChatRequest, ChatResponse
from zyko.core.models import ModelInfo, Usage

Message.system(text) / Message.user(text) / Message.assistant(text)
ChatRequest(messages, model=None, temperature=None, max_tokens=None,
            tools=None, tool_choice=None, metadata={})
```

`model=None` or `"auto"` → the router picks. Pin a model with
`"provider/model"` (e.g. `"ollama/llama3.2"`) to skip ranking entirely.

---

## 4. Providers

All providers subclass `zyko.providers.base.BaseProvider`
(`async acomplete`, `async astream`, `catalog`, `find_model`). Built-ins:

| Class | Key env | Default base URL |
|---|---|---|
| `OpenAICompatProvider` | `OPENAI_API_KEY` | `https://api.openai.com/v1` |
| `AnthropicProvider` | `ANTHROPIC_API_KEY` | `https://api.anthropic.com/v1` |
| `GoogleProvider` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `https://generativelanguage.googleapis.com/v1beta` |
| `GroqProvider` | `GROQ_API_KEY` | `https://api.groq.com/openai/v1` |
| `MistralProvider` | `MISTRAL_API_KEY` | `https://api.mistral.ai/v1` |
| `DeepSeekProvider` | `DEEPSEEK_API_KEY` | `https://api.deepseek.com/v1` |
| `OpenRouterProvider` | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` |
| `OllamaProvider` | — (keyless, local) | `http://127.0.0.1:11434` |
| `MockProvider` | — (offline demo, `ZYKO_DEMO=1`) | `mock://local` |

Registry helpers (`zyko.providers`):

```python
provider_names() -> list[str]
get_provider_class(name: str) -> type[BaseProvider]
is_configured(name: str, settings=None) -> bool
build_provider(name: str, settings: dict) -> BaseProvider
configured_providers(settings=None) -> dict[str, BaseProvider]   # every key'd + keyless provider found
```

Any OpenAI-compatible vendor (Together, Fireworks, LM Studio, vLLM, …) works
through `OpenAICompatProvider` with a custom `base_url` — see
[PROVIDERS.md](PROVIDERS.md).

---

## 5. Policy-as-Code — `PolicyEngine`

```python
from zyko.policy.engine import PolicyEngine, load_policy

engine = PolicyEngine(doc: dict, *, state_dir: Path | None = None)
engine = load_policy("strict")                  # examples/policies/strict.yaml or ~/.zyko/policies/
engine.check_request(request, candidate) -> PolicyDecision   # .allowed / .reason / .request
engine.record_stream_open(candidate)            # rpm metering for streams
```

Enforced per call: provider/model allow-deny, tool allow-deny, PII redaction
(email/phone/IP/card patterns), local rate limits, daily budget (audited to
`budget_file()`), plus a full audit trail consumed by `zyko cost`.
Malformed sections degrade to documented schema warnings — never a raw
crash. Schema: [examples/policies/strict.yaml](../examples/policies/strict.yaml).

---

## 6. Gateway — OpenAI-compatible HTTP

```python
from zyko.gateway.server import serve

httpd = serve(router, *, host="127.0.0.1", port=8787, api_key=None)  # returns ThreadingHTTPServer
httpd.shutdown()
```

Endpoints: `GET /healthz`, `GET /v1/models`, `POST /v1/chat/completions`
(`"stream": true` → SSE). Auth: `Authorization: Bearer <api_key>` when a key
is configured. CLI: `zyko serve --port 8788`, or `zyko serve --demo` for the
keyless mock mode. Port conflicts raise a friendly `ConfigError`.

---

## 7. MCP — server & client

```python
from zyko.mcp.server import ZykoMCPServer

server = ZykoMCPServer(*, router=None)      # router built lazily from settings when None
asyncio.run(server.serve(stdin=None, stdout=None))   # stdio JSON-RPC; also `python -m zyko.mcp.server`
```

Exposes tools **`zyko_models`**, **`zyko_route`** (plan, no API call) and
**`zyko_chat`** (full router + receipt). Protocol: `2024-11-05`.

```python
from zyko.mcp.client import MCPClient

client = MCPClient(name, command, *, env=None, cwd=None, request_timeout=20.0)
tools = await client.list_tools()           # or client.list_tools_sync()
out   = await client.call_tool("echo", {"text": "hi"})   # or client.call_tool_sync(...)
await client.aclose()
```

ZYKO agents consume MCP servers as tools (YAML `mcp:` block), and ZYKO
exposes itself as an MCP server — both directions, first-class.

---

## 8. Agents

```python
from zyko.agents.agent import Agent, AgentResult

result = await agent.run(task, *, history=None)      # agent.run_sync(task) also available

@dataclass
class AgentResult:
    output: str
    steps: list[dict]                # every router call / tool call, in order
    usage_input_tokens: int
    usage_output_tokens: int
    truncated: bool
    elapsed_s: float
```

Agent YAML: `examples/agents/math-agent.yaml`, `examples/agents/workspace-agent.yaml`.
Builtin tools: calculator, safe shell (policy-gated), plus MCP-provided tools.

---

## 9. Config & paths

```python
from zyko.config.settings import Settings

settings = Settings.load(path=None)        # YAML + env layering, per-call deep copy
settings.get("router.strategy", "balanced")
settings.provider_settings                 # per-provider dicts (base_url, key, api…)
```

Defaults (`router.strategy/max_fallbacks/request_timeout_s/retries/
breaker_threshold/breaker_cooldown_s`, `gateway.*`, `default_policy`,
`prices_file`) — override via YAML or `ZYKO_ROUTER_STRATEGY`,
`ZYKO_REQUEST_TIMEOUT`, `ZYKO_DEFAULT_POLICY`, `ZYKO_GATEWAY_HOST/PORT/API_KEY`.

Paths (`zyko.platform.paths`): `config_dir() data_dir() cache_dir()
policies_dir() agents_dir() ledger_file() audit_log() budget_file()
sessions_db()` — env-first (`ZYKO_CONFIG_DIR` / `ZYKO_DATA_DIR` /
`ZYKO_CACHE_DIR`), then platform conventions (XDG on Linux,
`~/Library` on macOS, `%APPDATA%` on Windows, Termux-aware).

Kernel (`zyko.kernel`, pure Python; optional Rust accelerator with graceful
fallback): `estimate_tokens`, `estimate_messages_tokens`, `cosine_similarity`,
`top_k`, `moving_average`.

---

## 10. Exceptions

```
ZykoError
├── ConfigError                # bad config, busy port, missing files
├── ProviderError              # all upstream failures (all candidates failed …)
│   ├── RateLimitError         # 429 from a vendor (honours Retry-After)
│   └── AuthError              # 401/403 — bad key
├── ModelNotFoundError
├── PolicyViolation
│   ├── BudgetExceededError
│   └── LocalRateLimitError
├── ToolError
├── AgentLimitError            # agent step/tool budget exhausted
├── MCPError                   # MCP transport / protocol failures
└── ZykoTimeoutError
```

Catch `ZykoError` for anything ZYKO-related; `PolicyViolation` for governance
rejections (the audit log records them automatically).

---

## 11. CLI map

| Command | Does |
|---|---|
| `zyko version` `info` `doctor` | version/protocol · platform+config summary · environment diagnosis |
| `zyko models` | models the router can use, with scores |
| `zyko route "prompt"` | routing plan — **no API call** (`--explain` for full receipt) |
| `zyko ask "prompt"` `chat` | one-shot completion · interactive chat with session memory |
| `zyko serve [--port N] [--demo]` | OpenAI-compatible gateway |
| `zyko policy check\|show\|redact` | validate/display policies · redaction demo |
| `zyko mcp serve\|tools -- <cmd>` | ZYKO as MCP server · inspect another MCP server |
| `zyko run agent.yaml "task"` | run a YAML-defined agent |
| `zyko sessions list\|show\|rm\|clear` | inspect SQLite session memory |
| `zyko cost [--days N] [--json]` | spend & governance report from the audit log |
| `zyko bench [suite] [--demo]` | reproducible routing benchmark (fixed seeds) |

Environment: `ZYKO_DEMO=1` → keyless offline mock mode (great for CI).

---

## 12. Minimal end-to-end

```python
import asyncio
from zyko import Zyko, Message

zk = Zyko(strategy="balanced")

# 1. plain ask
print(zk.ask("2+2?").response.text)

# 2. streamed routing plan (no API call)
for entry in zk.explain()["ranking"]:
    print(entry["candidate"], entry["total"])

# 3. agent with tools
agent = zk.agent("examples/agents/math-agent.yaml")
print(agent.run_sync("what is 17 * 23?").output)
```
