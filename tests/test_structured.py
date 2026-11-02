"""Structured output — the competitor-parity feature set.

Covers: the JSON Schema subset validator (including the bool/number trap,
$defs/$ref resolution and oneOf semantics), the robust JSON extractor, the
repair loop, native response_format passthrough, policy/cache/gateway
integration, and the Pydantic interop path.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.fakes import FakeProvider
from zyko.core.messages import Message
from zyko.core.response import ChatRequest, ChatResponse, Usage
from zyko.exceptions import SchemaSpecError, StructuredOutputError
from zyko.router.engine import RouteAttempt, RouteResult
from zyko.structured import extract_json, json_schema_of, validate_against_schema
from zyko.structured.engine import StructuredEngine

ORDER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "status": {"type": "string", "enum": ["open", "shipped", "cancelled"]},
        "tags": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "total": {"type": "number", "minimum": 0},
    },
    "required": ["id", "status"],
    "additionalProperties": False,
}

GOOD = {"id": 42, "status": "shipped", "tags": ["priority"], "total": 12.5}


# ------------------------------------------------------------------ validator
def test_valid_object_has_no_errors():
    assert validate_against_schema(GOOD, ORDER_SCHEMA) == []


def test_missing_required_reports_path():
    errors = validate_against_schema({"status": "open"}, ORDER_SCHEMA)
    assert any("missing required property 'id'" in e for e in errors)
    assert any(e.startswith("$") for e in errors)


def test_wrong_type_reports_expected_and_got():
    errors = validate_against_schema({"id": "42", "status": "open"}, ORDER_SCHEMA)
    assert any("$.id: expected type integer, got str" in e for e in errors)


def test_bool_is_not_integer():
    assert validate_against_schema({"id": True, "status": "open"}, ORDER_SCHEMA)


def test_bool_is_not_number():
    schema = {"type": "number"}
    assert validate_against_schema(True, schema)


def test_bool_is_valid_boolean():
    assert validate_against_schema(True, {"type": "boolean"}) == []


def test_number_accepts_int_and_float():
    assert validate_against_schema(3, {"type": "number"}) == []
    assert validate_against_schema(3.5, {"type": "number"}) == []


def test_number_rejects_nan_and_infinite():
    assert validate_against_schema(float("nan"), {"type": "number"})
    assert validate_against_schema(float("inf"), {"type": "number"})


def test_numeric_bounds():
    schema = {"type": "integer", "minimum": 1, "maximum": 10}
    assert validate_against_schema(5, schema) == []
    assert validate_against_schema(0, schema)
    assert validate_against_schema(11, schema)


def test_exclusive_bounds():
    schema = {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1}
    assert validate_against_schema(0.5, schema) == []
    assert validate_against_schema(0, schema)
    assert validate_against_schema(1, schema)


def test_multiple_of():
    schema = {"type": "integer", "multipleOf": 5}
    assert validate_against_schema(20, schema) == []
    assert validate_against_schema(21, schema)


def test_enum_type_aware_bool_vs_int():
    schema = {"enum": [1, 2]}
    assert validate_against_schema(True, schema)  # True is not 1 in JSON terms
    assert validate_against_schema(1, schema) == []


def test_enum_invalid_value():
    errors = validate_against_schema("closed", {"enum": ["open", "shipped"]})
    assert any("is not one of" in e for e in errors)


def test_const():
    assert validate_against_schema("v2", {"const": "v2"}) == []
    assert validate_against_schema("v1", {"const": "v2"})


def test_string_length_bounds():
    schema = {"type": "string", "minLength": 2, "maxLength": 4}
    assert validate_against_schema("abc", schema) == []
    assert validate_against_schema("a", schema)
    assert validate_against_schema("abcde", schema)


def test_pattern_uses_search_semantics():
    schema = {"type": "string", "pattern": "[0-9]+"}
    assert validate_against_schema("abc123", schema) == []  # unanchored match
    assert validate_against_schema("abcdef", schema)


def test_format_email_and_uuid():
    assert validate_against_schema("a@b.co", {"type": "string", "format": "email"}) == []
    assert validate_against_schema("not-an-email", {"type": "string", "format": "email"})
    uuid = "123e4567-e89b-12d3-a456-426614174000"
    assert validate_against_schema(uuid, {"type": "string", "format": "uuid"}) == []
    assert validate_against_schema("nope", {"type": "string", "format": "uuid"})


def test_array_items_and_bounds():
    schema = {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 2}
    assert validate_against_schema(["a"], schema) == []
    assert validate_against_schema([], schema)
    assert validate_against_schema(["a", "b", "c"], schema)
    assert validate_against_schema(["a", 1], schema)  # $.items[1] flagged


def test_array_element_paths_are_reported():
    errors = validate_against_schema([1, "x"], {"type": "array", "items": {"type": "integer"}})
    assert any("$[1]" in e for e in errors)
    errors = validate_against_schema(
        {"xs": [1, "x"]},
        {"type": "object", "properties": {"xs": {"type": "array", "items": {"type": "integer"}}}},
    )
    assert any("$.xs[1]" in e for e in errors)


def test_unique_items():
    schema = {"type": "array", "uniqueItems": True}
    assert validate_against_schema([1, 2], schema) == []
    assert validate_against_schema([1, 1], schema)


def test_additional_properties_false_names_extras():
    errors = validate_against_schema(
        {"a": 1, "b": 2}, {"properties": {"a": {}}, "additionalProperties": False}
    )
    assert any("unexpected properties ['b']" in e for e in errors)


def test_additional_properties_schema_validates_extras():
    schema = {"properties": {"a": {}}, "additionalProperties": {"type": "integer"}}
    assert validate_against_schema({"a": 1, "extra": 5}, schema) == []
    assert validate_against_schema({"a": 1, "extra": "no"}, schema)


def test_nested_object_paths():
    schema = {
        "type": "object",
        "properties": {"order": {"type": "object", "properties": {"sku": {"type": "string"}}}},
    }
    errors = validate_against_schema({"order": {"sku": 3}}, schema)
    assert any("$.order.sku" in e for e in errors)


def test_any_of():
    schema = {"anyOf": [{"type": "integer"}, {"type": "string"}]}
    assert validate_against_schema(3, schema) == []
    assert validate_against_schema("x", schema) == []
    assert validate_against_schema(3.5, schema)


def test_one_of_requires_exactly_one():
    schema = {"oneOf": [{"type": "number"}, {"type": "integer"}]}
    assert validate_against_schema(3.5, schema) == []  # only number matches
    assert validate_against_schema(3, schema)  # both match -> error
    assert validate_against_schema("x", schema)  # none match -> error


def test_all_of():
    schema = {"allOf": [{"type": "string"}, {"minLength": 3}]}
    assert validate_against_schema("abcd", schema) == []
    assert validate_against_schema("ab", schema)


def test_ref_and_defs_resolution():
    schema = {
        "$defs": {"positive": {"type": "integer", "minimum": 1}},
        "type": "object",
        "properties": {"qty": {"$ref": "#/$defs/positive"}},
        "required": ["qty"],
    }
    assert validate_against_schema({"qty": 3}, schema) == []
    assert validate_against_schema({"qty": 0}, schema)
    assert validate_against_schema({"qty": True}, schema)


def test_broken_ref_raises_schemasperror():
    with pytest.raises(SchemaSpecError):
        validate_against_schema(1, {"$ref": "#/$defs/missing"})


def test_malformed_schemas_raise_schemasperror():
    with pytest.raises(SchemaSpecError):
        validate_against_schema(1, "not-a-schema")
    with pytest.raises(SchemaSpecError):
        validate_against_schema({"a": 1}, {"properties": "nope"})
    with pytest.raises(SchemaSpecError):
        validate_against_schema(1, {"type": "spaceship"})
    with pytest.raises(SchemaSpecError):
        validate_against_schema(1, {"enum": "nope"})


def test_schema_true_false_forms():
    assert validate_against_schema(1, True) == []
    assert validate_against_schema(1, False)


def test_unknown_keywords_are_ignored():
    schema = {"type": "string", "title": "T", "description": "d", "examples": ["x"]}
    assert validate_against_schema("x", schema) == []


def test_type_mismatch_skips_keyword_noise():
    errors = validate_against_schema("abc", {"type": "integer", "minimum": 5})
    assert errors and all("expected type" in e for e in errors)


# ------------------------------------------------------------------ extractor
def test_extract_plain_object():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_from_fenced_block():
    text = 'Here you go:\n```json\n{"a": 1}\n```\nHope that helps!'
    assert extract_json(text) == {"a": 1}


def test_extract_from_prose_wrapped():
    assert extract_json('The answer is {"a": [1, 2]} as requested.') == {"a": [1, 2]}


def test_extract_from_think_block():
    assert extract_json('<think>{"x": 1} maybe?</think>{"a": 1}') == {"a": 1}


def test_extract_array_root():
    assert extract_json("prefix [1, 2, 3] suffix") == [1, 2, 3]


def test_extract_braces_inside_strings_do_not_confuse_scan():
    text = '{"code": "if (x) { return \\"}\\"; }", "n": 1}'
    assert extract_json(text)["n"] == 1


def test_extract_garbage_returns_none():
    assert extract_json("no json here at all") is None
    assert extract_json("") is None
    assert extract_json(None) is None


# --------------------------------------------------------------- json_schema_of
def test_dict_passthrough():
    schema = {"type": "object"}
    assert json_schema_of(schema) is schema


def test_unsupported_spec_raises():
    class Plain:
        pass

    with pytest.raises(SchemaSpecError):
        json_schema_of(Plain())
    with pytest.raises(SchemaSpecError):
        json_schema_of(42)


def test_pydantic_model_class_and_instance():
    pydantic = pytest.importorskip("pydantic")

    class Order(pydantic.BaseModel):
        id: int
        status: str

    schema = json_schema_of(Order)
    assert isinstance(schema, dict) and schema.get("type") == "object"
    assert json_schema_of(Order(id=1, status="s"))["type"] == "object"
    assert validate_against_schema({"id": 1, "status": "s"}, schema) == []
    assert validate_against_schema({"id": "x", "status": "s"}, schema)


def test_pydantic_nested_model_uses_defs():
    pydantic = pytest.importorskip("pydantic")

    class Item(pydantic.BaseModel):
        sku: str

    class Cart(pydantic.BaseModel):
        items: list[Item]

    schema = json_schema_of(Cart)
    assert "$defs" in schema
    assert validate_against_schema({"items": [{"sku": "a"}]}, schema) == []
    assert validate_against_schema({"items": [{"sku": 1}]}, schema)


# --------------------------------------------------------------------- engine
class StubRouter:
    """Records requests, answers from a script of raw texts."""

    def __init__(self, script: list[str]):
        self.script = script
        self.requests: list[ChatRequest] = []
        self.n = 0

    async def aroute(self, request: ChatRequest) -> RouteResult:
        self.requests.append(request)
        text = self.script[min(self.n, len(self.script) - 1)]
        self.n += 1
        return RouteResult(
            ChatResponse(
                id=f"stub-{self.n}",
                provider="stub",
                model="stub-1",
                content=text,
                usage=Usage(10, 5),
            ),
            "stub/stub-1",
            [RouteAttempt("stub/stub-1", "ok")],
            {"chosen": "stub/stub-1"},
        )


def _messages() -> list[Message]:
    return [Message.user("order info please")]


@pytest.mark.asyncio()
async def test_guided_happy_path():
    router = StubRouter([json.dumps(GOOD)])
    out = await StructuredEngine(router).astructured(_messages(), ORDER_SCHEMA)
    assert out.data == GOOD
    assert out.rounds == [[]]
    assert out.repaired is False
    assert out.route.receipt["chosen"] == "stub/stub-1"


@pytest.mark.asyncio()
async def test_guided_appends_schema_system_message():
    router = StubRouter([json.dumps(GOOD)])
    await StructuredEngine(router).astructured(_messages(), ORDER_SCHEMA)
    sent = router.requests[0].messages
    assert sent[0].role == Message.user("x").role
    guide = sent[-1].content or ""
    assert '"required"' in guide and "ONLY" in guide
    assert json.dumps(ORDER_SCHEMA, sort_keys=True) in guide


@pytest.mark.asyncio()
async def test_repair_round_feeds_errors_back():
    router = StubRouter(['{"id": "not-int"}', json.dumps(GOOD)])
    out = await StructuredEngine(router).astructured(_messages(), ORDER_SCHEMA)
    assert out.data == GOOD
    assert out.repaired is True and len(out.rounds) == 2
    assert router.n == 2
    repair_convo = router.requests[1].messages
    assert repair_convo[-2].role == Message.assistant("x").role
    assert "not-int" in (repair_convo[-2].content or "")
    assert "Problems found" in (repair_convo[-1].content or "")
    assert "$.id" in (repair_convo[-1].content or "")


@pytest.mark.asyncio()
async def test_exhausted_repairs_raise_typed_error():
    router = StubRouter(['{"id": "never-valid"}'])
    with pytest.raises(StructuredOutputError) as exc_info:
        await StructuredEngine(router).astructured(_messages(), ORDER_SCHEMA)
    err = exc_info.value
    assert err.errors and "$.id" in err.errors[0]
    assert "after 2 round(s)" in str(err)
    assert len(router.requests) == 2  # initial + one repair


@pytest.mark.asyncio()
async def test_max_repairs_zero_is_single_round():
    router = StubRouter(["garbage"])
    with pytest.raises(StructuredOutputError):
        await StructuredEngine(router).astructured(_messages(), ORDER_SCHEMA, max_repairs=0)
    assert len(router.requests) == 1


@pytest.mark.asyncio()
async def test_unparseable_then_repaired():
    router = StubRouter(["I cannot answer that.", json.dumps(GOOD)])
    out = await StructuredEngine(router).astructured(_messages(), ORDER_SCHEMA)
    assert out.data == GOOD
    assert out.rounds[0] == ["output is not parseable JSON"]


@pytest.mark.asyncio()
async def test_native_mode_sets_response_format():
    router = StubRouter([json.dumps(GOOD)])
    await StructuredEngine(router).astructured(_messages(), ORDER_SCHEMA, native=True)
    request = router.requests[0]
    assert request.response_format == {
        "type": "json_schema",
        "json_schema": {"name": "response", "strict": True, "schema": ORDER_SCHEMA},
    }
    # native mode must NOT inject the schema-riding system message
    assert all("ONLY" not in (m.content or "") for m in request.messages)


@pytest.mark.asyncio()
async def test_system_and_routing_kwargs_flow_through():
    router = StubRouter([json.dumps(GOOD)])
    await StructuredEngine(router).astructured(
        _messages(),
        ORDER_SCHEMA,
        system="be terse",
        model="stub/stub-1",
        temperature=0.2,
        max_tokens=99,
    )
    request = router.requests[0]
    assert request.messages[0].role == Message.system("x").role
    assert request.model == "stub/stub-1"
    assert request.temperature == 0.2
    assert request.max_tokens == 99


# ------------------------------------------------- passthrough & integrations
def _build_openai_payload(**kw: Any) -> dict[str, Any]:
    from zyko.providers.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider(api_key="k")
    request = ChatRequest(messages=[Message.user("hi")], **kw)
    _, payload, _ = provider._build(request, stream=False)
    return payload


def test_openai_compat_passes_response_format():
    rf = {"type": "json_object"}
    assert _build_openai_payload(response_format=rf)["response_format"] == rf


def test_openai_compat_omits_response_format_when_absent():
    assert "response_format" not in _build_openai_payload()


def test_google_maps_json_object():
    from zyko.providers.google import GoogleProvider

    provider = GoogleProvider(api_key="k")
    request = ChatRequest(messages=[Message.user("hi")], response_format={"type": "json_object"})
    _, payload, _ = provider._build(request, stream=False)
    assert payload["generationConfig"]["responseMimeType"] == "application/json"


def test_google_maps_json_schema_with_response_schema():
    from zyko.providers.google import GoogleProvider

    provider = GoogleProvider(api_key="k")
    request = ChatRequest(
        messages=[Message.user("hi")],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "r", "schema": ORDER_SCHEMA},
        },
    )
    _, payload, _ = provider._build(request, stream=False)
    gen = payload["generationConfig"]
    assert gen["responseMimeType"] == "application/json"
    assert gen["responseSchema"] == ORDER_SCHEMA


def test_policy_rewrites_preserve_response_format():
    from zyko.policy.engine import PolicyEngine
    from zyko.router.engine import RouteCandidate

    engine = PolicyEngine({"version": 1, "name": "t", "defaults": {"max_tokens_per_request": 50}})
    request = ChatRequest(
        messages=[Message.user("hi")],
        max_tokens=500,
        response_format={"type": "json_object"},
    )
    decision = engine.check_request(request, RouteCandidate("fake", "fake-small"))
    assert decision.allowed
    assert decision.request.max_tokens == 50
    assert decision.request.response_format == {"type": "json_object"}


def test_policy_redaction_preserves_response_format():
    from zyko.policy.engine import PolicyEngine
    from zyko.router.engine import RouteCandidate

    engine = PolicyEngine({"version": 1, "name": "t", "privacy": {"redact": ["email"]}})
    request = ChatRequest(
        messages=[Message.user("email me at a@b.co")],
        response_format={"type": "json_object"},
    )
    decision = engine.check_request(request, RouteCandidate("fake", "fake-small"))
    assert decision.allowed
    assert decision.request.response_format == {"type": "json_object"}


def test_cache_key_changes_with_response_format():
    from zyko.cache import ResponseCache

    plain = ChatRequest(messages=[Message.user("hi")])
    structured = ChatRequest(messages=[Message.user("hi")], response_format={"type": "json_object"})
    key_plain = ResponseCache.key_for(plain, provider="fake", model="m")
    key_structured = ResponseCache.key_for(structured, provider="fake", model="m")
    assert key_plain != key_structured
    # unchanged request -> stable key
    assert key_plain == ResponseCache.key_for(plain, provider="fake", model="m")


def test_gateway_end_to_end_response_format():
    from tests.fakes import FakeProvider
    from zyko.gateway.server import serve
    from zyko.router.engine import Router

    router = Router({"fake": FakeProvider(script=["gateway answer"])})
    httpd = serve(router, host="127.0.0.1", port=0)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        import urllib.request

        body = json.dumps(
            {
                "model": "fake/fake-small",
                "messages": [{"role": "user", "content": "hi"}],
                "response_format": {"type": "json_object"},
            }
        ).encode()
        request = urllib.request.Request(
            base + "/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as resp:
            assert resp.status == 200
    finally:
        httpd.shutdown()


def test_gateway_rejects_non_object_response_format():
    from tests.fakes import FakeProvider
    from zyko.gateway.server import serve
    from zyko.router.engine import Router

    router = Router({"fake": FakeProvider(script=["gateway answer"])})
    httpd = serve(router, host="127.0.0.1", port=0)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        import urllib.error
        import urllib.request

        body = json.dumps(
            {
                "model": "fake/fake-small",
                "messages": [{"role": "user", "content": "hi"}],
                "response_format": "json",
            }
        ).encode()
        request = urllib.request.Request(
            base + "/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=10)
            raise AssertionError("expected HTTP 400")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            assert b"response_format" in exc.read()
    finally:
        httpd.shutdown()


# ------------------------------------------------------------ facade (Zyko())
@pytest.fixture()
def scripted_fake(monkeypatch):
    fake = FakeProvider(script=[json.dumps(GOOD)])
    monkeypatch.setattr("zyko.client.configured_providers", lambda *_a, **_k: {"fake": fake})
    return fake


def test_zyko_structured_facade(scripted_fake, tmp_path):
    from zyko import Zyko

    zk = Zyko(ledger_path=tmp_path / "ledger.json")
    out = zk.structured("order info?", ORDER_SCHEMA, system="be terse")
    assert out.data == GOOD
    assert out.repaired is False
    assert out.route.candidate.startswith("fake/")


def test_zyko_structured_messages_facade(scripted_fake, tmp_path):
    from zyko import Zyko

    zk = Zyko(ledger_path=tmp_path / "ledger.json")
    out = zk.structured_messages([Message.user("hi")], ORDER_SCHEMA)
    assert out.data == GOOD


def test_zyko_structured_repairs_via_fake_provider(tmp_path, monkeypatch):
    from zyko import Zyko

    fake = FakeProvider(script=['{"id": "bad"}', json.dumps(GOOD)])
    monkeypatch.setattr("zyko.client.configured_providers", lambda *_a, **_k: {"fake": fake})
    zk = Zyko(ledger_path=tmp_path / "ledger.json")
    out = zk.structured("order info?", ORDER_SCHEMA)
    assert out.data == GOOD
    assert out.repaired is True
    assert fake.calls == 2
