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

zk = Zyko()  # keys straight from the environment
answer = zk.ask("Explain routing in one line", system="You are terse.")
print(answer.response.text)
print(answer.receipt["chosen"])  # e.g. "groq/llama-3.3-70b-versatile"
print(answer.receipt["attempts"])  # full candidate ordering with score parts
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
    candidate: str | None  # "provider/model"
    attempts: list[RouteAttempt]  # every try: chosen | failed | skipped-breaker | skipped-policy
    receipt: dict[str, Any]  # verifiable routing decision (see ARCHITECTURE.md)
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
ChatRequest(
    messages,
    model=None,
    temperature=None,
    max_tokens=None,
    tools=None,
    tool_choice=None,
    response_format=None,
    metadata={},
)
```

`model=None` or `"auto"` → the router picks. Pin a model with
`"provider/model"` (e.g. `"ollama/llama3.2"`) to skip ranking entirely.
`response_format` is an OpenAI-shaped dict (see section 13) passed through
verbatim by OpenAI-compatible adapters and mapped to Gemini's
`generationConfig` by the Google adapter.

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
| `TogetherProvider` | `TOGETHER_API_KEY` | `https://api.together.ai/v1` |
| `XAIProvider` | `XAI_API_KEY` | `https://api.x.ai/v1` |
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
An optional **`cache:` section** (`{enabled: true, ttl_s: 300, max_entries:
512}`) builds a policy-owned `ResponseCache` the router consults before any
vendor call — exact-match keys over the post-policy outbound payload,
`"cached": true` receipts on hits, no budget charge, `tool_calls` responses
never stored, per-call overrides via `metadata={"cache": "bypass" or "refresh"}`.
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

settings = Settings.load(path=None)  # YAML + env layering, per-call deep copy
settings.get("router.strategy", "balanced")
settings.provider_settings  # per-provider dicts (base_url, key, api…)
```

Defaults (`router.strategy/max_fallbacks/request_timeout_s/retries/
breaker_threshold/breaker_cooldown_s`, `gateway.*`, `tracing.enabled/file`,
`default_policy`, `prices_file`) — override via YAML or `ZYKO_ROUTER_STRATEGY`,
`ZYKO_REQUEST_TIMEOUT`, `ZYKO_DEFAULT_POLICY`, `ZYKO_GATEWAY_HOST/PORT/API_KEY`,
`ZYKO_TRACING`.

Paths (`zyko.platform.paths`): `config_dir() data_dir() cache_dir()
policies_dir() agents_dir() ledger_file() audit_log() trace_log()
budget_file() sessions_db()` — env-first (`ZYKO_CONFIG_DIR` / `ZYKO_DATA_DIR` /
`ZYKO_CACHE_DIR`), then platform conventions (XDG on Linux,
`~/Library` on macOS, `%APPDATA%` on Windows, Termux-aware).

Kernel (`zyko.kernel`, pure Python; optional Rust accelerator with graceful
fallback): `estimate_tokens`, `estimate_messages_tokens`, `cosine_similarity`,
`top_k`, `moving_average`.

---

## 10. Observability — `zyko.observability`

```python
from zyko import Zyko, Tracer, JsonlSink, InMemorySink, TraceSpan

zk = Zyko()  # self.tracer built from tracing.* settings
with zk.tracer.span("my-rag", corpus="docs") as sp:
    out = zk.ask("...")  # -> child span router.route (provider, tokens, attempts, cached)
sp.status, sp.duration_ms  # "ok", 12.4
```

- `Tracer.span(name, **attrs)` — context manager; exceptions mark the span
  `error` (or `cancelled` for `GeneratorExit`/`KeyboardInterrupt`) and
  re-raise. Manual `start_span`/`end_span` for streams; `emit()` for
  one-shot records. Nesting stays LIFO via contextvars tokens.
- `JsonlSink(path, max_bytes=5_000_000)` — one JSON object per span,
  thread-safe, creates parent dirs, bounded shift rotation (`traces.jsonl`
  → `.1` → `.2`; disk ≤ ~3×`max_bytes` forever). I/O failures log once and
  never propagate.
- `OtlpSink(endpoint, *, headers=None, timeout_s=5.0, service_name="zyko",
  batch_size=64, queue_size=4096)` (0.4.2) — export the same spans to any
  OTLP/HTTP-JSON backend (OTel Collector, Langfuse, Grafana Tempo, Jaeger,
  Honeycomb, New Relic, Datadog) over the already-required `httpx` — zero
  new dependencies. One daemon worker batches up to `batch_size` spans per
  POST; `write()` only enqueues (network latency never touches the request
  path); queue overflow drops and counts (`.dropped`); outages log one
  warning (debug afterwards, re-warn on recovery); `close()` drains then
  stops and is safe to call twice. Spec-exact mapping: 16-byte trace /
  8-byte span ids derived deterministically (sha256) from ZYKO's shorter
  ids, originals preserved as `zyko.trace_id`/`zyko.span_id`/
  `zyko.parent_id` attributes; `ok` → `STATUS_CODE_OK`,
  `error`/`cancelled` → `STATUS_CODE_ERROR` + reason.
- `load_tracer(settings)` — honors `tracing.enabled`/`tracing.file` +
  `ZYKO_TRACING=0`; when `tracing.otlp.endpoint` (or `ZYKO_OTLP_ENDPOINT`,
  which wins) is set, an `OtlpSink` fans the same spans to that backend in
  addition to the local JSONL log. `tracing.otlp.headers` carries backend
  auth (config files interpolate `${ENV_VARS}` — secrets stay off disk).
  Disabled keeps the identical no-write API.

OTLP recipes:

```yaml
# config.yaml — Langfuse cloud (v3 speaks OTLP natively)
tracing:
  otlp:
    endpoint: https://cloud.langfuse.com/api/public/otel/v1/traces
    headers:
      authorization: "Basic ${LANGFUSE_BASIC}"   # base64(pk:secret)
```

```console
# self-hosted: OTel Collector / Grafana Tempo / Jaeger — all listen on :4318
ZYKO_OTLP_ENDPOINT=http://localhost:4318/v1/traces zyko ask "hello"
```

- Router spans: `router.route` (attributes: `strategy`, `provider`,
  `cached`, `input_tokens`, `output_tokens`, `attempts[]`) and
  `router.stream` (closed in `finally`, even on client disconnect).
- Inspect: `zyko traces --last 20` / `--trace <id>` / `--json` / `--clear`;
  `zyko doctor` shows the tracing state and the OTLP target.

---

## 11. Exceptions

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
├── CrewError                  # crew: empty pipeline, duplicate key, bad template
├── MCPError                   # MCP transport / protocol failures
├── ZykoTimeoutError
├── EmbedderError              # RAG embeddings: bad request, dim mismatch, …
├── SchemaSpecError            # structured output: malformed schema (caller bug)
└── StructuredOutputError      # structured output: model answer failed validation
```

Catch `ZykoError` for anything ZYKO-related; `PolicyViolation` for governance
rejections (the audit log records them automatically).

---

## 12. CLI map

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
| `zyko crew crew.yaml --input "…"` | run a sequential multi-agent crew (`--json` = receipt only, `--trace` = step table) |
| `zyko sessions list\|show\|rm\|clear` | inspect SQLite session memory |
| `zyko cost [--days N] [--json]` | spend & governance report from the audit log |
| `zyko cache [--json] [--clear]` | inspect or clear the policy-gated response cache |
| `zyko traces [--last N] [--trace ID] [--json] [--clear]` | inspect the built-in span log (observability) |
| `zyko bench [suite] [--demo]` | reproducible routing benchmark (fixed seeds) |

Environment: `ZYKO_DEMO=1` → keyless offline mock mode (great for CI).

---

## 13. Minimal end-to-end

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

# 4. structured answer (validated, auto-repaired)
out = zk.structured(
    "order 42 details?",
    schema={
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    },
)
print(out.data, out.repaired)
```

---

## 14. Structured output

Schema-constrained answers — ZYKO's answer to LangChain's
`with_structured_output`, CrewAI's Pydantic task outputs, AutoGen's
`response_format` and LiteLLM's passthrough. Validated data or a typed
error, never a raw string to `json.loads` by hand.

```python
from zyko import Zyko, StructuredOutputError, SchemaSpecError

zk = Zyko()

# 1. guided mode (default): schema rides the prompt, output is extracted,
#    validated, and repaired once with the exact validation errors.
out = zk.structured(
    "extract the order as JSON",
    schema={
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "status": {"type": "string", "enum": ["open", "shipped", "cancelled"]},
        },
        "required": ["id", "status"],
        "additionalProperties": False,
    },
    system="you are a precise data extractor",
)
out.data  # validated value (dict)
out.rounds  # validation errors per round — [[]] means clean first shot
out.repaired  # True if a repair round ran
out.route.receipt  # full routing receipt, same as ask()

# 2. Pydantic interop (pip install 'zyko[structured]'):
from pydantic import BaseModel


class Order(BaseModel):
    id: int
    status: str


out = zk.structured("order 42 details?", schema=Order)

# 3. native vendor mode: response_format goes on the wire; vendors that
#    reject it fall through routing automatically.
out = zk.structured("order 42 details?", schema=Order, native=True)

# 4. typed failures after the repair budget:
try:
    zk.structured(
        "…", schema={"type": "object", "properties": {"x": {"type": "integer"}}}, max_repairs=0
    )
except StructuredOutputError as exc:
    print(exc.errors)  # e.g. ["$.x: expected type integer, got str"]
    print(exc.text)  # last raw model output
```

Conversation form: `zk.structured_messages(messages, schema, **kw)` (and
`astructured*` async variants).

Building blocks (public, tested independently):

- `zyko.structured.validate_against_schema(value, schema)` → list of error
  strings (empty = valid). JSON-Schema subset: types, `enum`, `const`,
  numeric bounds, `multipleOf`, string bounds/`pattern`/formats (`email`,
  `date`, `date-time`, `uri`, `uuid`, `ipv4`, `hostname`), array
  bounds/`items`/`uniqueItems`, object `properties`/`required`/
  `additionalProperties`, `allOf`/`anyOf`/`oneOf`, local `$ref`/`$defs` with
  cycle guards. Unknown keywords ignored. Malformed schema →
  `SchemaSpecError` (fail fast — a schema bug is a caller bug). Note the
  Python trap handled: `True` is not an `integer` and not a `number` here.
- `zyko.structured.extract_json(text)` → first JSON value found (whole
  text, fenced blocks, then first balanced `{…}`/`[…]` span, string-aware;
  `<think>` blocks stripped) or `None`.
- `zyko.structured.json_schema_of(spec)` → plain schema dict from a dict or
  a Pydantic model class/instance.
- `StructuredEngine(router)` — the loop `Zyko.structured` uses; reuse it
  for custom pipelines.

---

## 15. RAG — `zyko.rag` (embeddings + local vector store, 0.5.0)

The LlamaIndex-minimum: chunk → embed → cosine search over **files you own**
(JSON persistence, no server, no daemon), with a deterministic zero-dependency
default embedder. Feed the hits into `zk.ask(..., context=[...])`.

```python
from zyko import Zyko
from zyko.rag import HashingEmbedder, OpenAIEmbedder, OllamaEmbedder, VectorStore

# pick one embedder — same contract for all three:
emb = HashingEmbedder(dim=256)  # zero deps, offline, deterministic
# emb = OllamaEmbedder(model="nomic-embed-text")   # real semantics, local, no keys
# emb = OpenAIEmbedder(model="text-embedding-3-small")  # needs OPENAI_API_KEY

store = VectorStore(emb, path="kb.json")  # auto-loads / atomic auto-save
store.add(open("handbook.md").read(), meta={"source": "handbook"})
hits = store.search("refund policy", k=4)  # -> [Hit(text, score, index, meta)]

zk = Zyko()
answer = zk.ask("what is the refund policy?", context=[h.text for h in hits])
```

- `chunk_text(text, max_chars=800, overlap=120)` — paragraph-first chunking,
  hard-split with overlap so nothing straddling two chunks is lost; empty
  input → `[]`; never returns empty chunks.
- **Embedders** (one contract: `embed(texts)` / `await aembed(texts)` →
  `list[list[float]]`, plus `name` and `dim`):
  - `HashingEmbedder(dim=256)` — blake2b feature hashing, sign-weighted,
    L2-normalized. Deterministic across machines; not semantic — shared
    vocabulary ranks together. Perfect for tests, demos and Termux.
  - `OllamaEmbedder(model="nomic-embed-text", base_url=...)` — local real
    semantics, no keys (`/api/embed`).
  - `OpenAIEmbedder(model="text-embedding-3-small", api_key=..., base_url=...)`
    — OpenAI `/v1/embeddings` or any vendor speaking it.
  - All failures raise the typed `EmbedderError` (exported from `zyko`
    root alongside the other errors) — never a raw `httpx` exception.
- `VectorStore(embedder, path=None)` — in-memory cosine index;
  `path="kb.json"` auto-loads and atomic-saves (tmp + replace) after each
  `add`. `add(text, meta=...)` returns the chunk count; `search(query, k=4,
  min_score=0.0)` returns `Hit`s sorted by score (default gate keeps only
  positively-correlated chunks — pass `min_score=-1.0` to see everything);
  `len(store)`, `clear()`, `aadd`/`asearch` async mirrors. A store built
  with a different embedder than it was saved with loads with a loud
  warning (scores would be meaningless). Dimension mismatches raise
  `EmbedderError` instead of corrupting the index.
- `zk.ask(prompt, context=[...])` (0.5.0) — non-empty context becomes its
  own system message ("answer from the context; say so if insufficient")
  placed after any explicit `system` and before the user prompt. Works with
  plain strings too — the store is optional.

---

## 16. Crews — `zyko.crew` (sequential multi-agent pipeline, 0.6.0)

Roadmap step 4: an ordered list of steps; each step is one configured
`Agent` plus a task template. Templates may reference `{task}` (the crew
input), `{output}` (previous step's output) or any earlier step's
`{output_key}`. Safe by construction: unknown placeholders stay literal,
substituted values are never re-formatted (JSON/braces survive), and
malformed templates (`{}`, `{0}`, `{a!}`) raise the typed `CrewError`
when the step is added — fail fast, never mid-run. No hidden prompts:
every agent keeps its own system prompt, tools and policy.

```python
from zyko import Zyko
from zyko.crew import Crew

zk = Zyko()
crew = Crew(router=zk.router, tracer=zk.tracer, name="triage")
crew.add(classifier, "Classify: {task}", output_key="class")
crew.add(replier, "Reply. Ticket: {task}\nClass: {class}")
res = crew.run("my invoice is late")  # or await crew.arun(...)
res.output  # final agent's answer
res.outputs  # {"class": …, "replier": …}
res.steps[1]["task"]  # the filled template (auditable)
res.usage_input_tokens  # aggregated across every step
res.trace_id  # crew.run span — zyko traces / OTLP
```

- `Crew.add(agent, task, *, output_key=None)` — chainable, validated
  immediately: task must be a non-empty template; `output_key` defaults to
  the agent's name (deduped `name_2`, `name_3`, …); duplicate explicit
  keys raise `CrewError`. `Crew.steps` is a read-only copy.
- `CrewResult` — `output`, `outputs` (insertion ordered), `steps` records
  (agent, key, filled task, output, agent_steps, truncated, elapsed_s),
  `usage_input_tokens`/`usage_output_tokens`, `truncated` (any step hit
  its `max_steps`), `elapsed_s`, `trace_id`.
- Declarative YAML (`zk.crew("file.yaml")` or `load_crew(path, router,
  policy=…, tracer=…)`):

```yaml
name: triage
steps:
  - agent: classifier.yaml     # an agent file (searched like zyko run)
    task: "Classify: {task}"
    output_key: class
  - agent:                     # or an inline agent mapping
      name: replier
      system: You draft replies.
      model: auto
    task: "Reply. Ticket: {task}\nClass: {class}"
```

- CLI: `zyko crew crew.yaml --input "…" [--json] [--trace]` — `--json`
  prints ONLY the `CrewResult` JSON on stdout (machine contract);
  `--trace` adds the per-step table.
- Errors: crew bugs raise `CrewError`; provider outages propagate as their
  real typed error (`ProviderError`, …) once the router's retry budget is
  exhausted; a failing run marks the `crew.run` span `error`.
