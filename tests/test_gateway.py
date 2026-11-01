"""Gateway: OpenAI-compatible HTTP surface over the router (stdlib server)."""

from __future__ import annotations

import json
import urllib.request

import pytest

from tests.fakes import FakeProvider
from zyko.gateway.server import serve
from zyko.router.engine import Router


@pytest.fixture()
def gateway():
    router = Router({"fake": FakeProvider(script=["gateway answer"])})
    httpd = serve(router, host="127.0.0.1", port=0)
    port = httpd.server_address[1]
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


@pytest.fixture()
def secured_gateway():
    router = Router({"fake": FakeProvider(script=["secret"])})
    httpd = serve(router, host="127.0.0.1", port=0, api_key="topsecret")
    port = httpd.server_address[1]
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


def _post(base: str, path: str, payload: dict, headers: dict | None = None) -> tuple[int, dict | str]:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def _get(base: str, path: str, headers: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(base + path, headers=headers or {})
    with urllib.request.urlopen(request, timeout=10) as resp:
        return resp.status, json.loads(resp.read())


def test_healthz(gateway):
    status, body = _get(gateway, "/healthz")
    assert status == 200 and body["status"] == "ok"


def test_chat_completions_shape_and_receipt(gateway):
    status, body = _post(gateway, "/v1/chat/completions", {
        "model": "auto",
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert status == 200
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "gateway answer"
    assert body["zyko"]["provider"] == "fake"
    assert body["zyko"]["receipt"]["attempts"][0]["outcome"] == "ok"
    assert body["usage"]["prompt_tokens"] == 20


def test_models_endpoint_lists_ranked_candidates(gateway):
    status, body = _get(gateway, "/v1/models")
    assert status == 200
    ids = [m["id"] for m in body["data"]]
    assert "fake/fake-small" in ids and "fake/fake-large" in ids


def test_404_route(gateway):
    status, body = _post(gateway, "/v1/nothing", {})
    assert status == 404


def test_auth_required_without_token(secured_gateway):
    status, body = _post(secured_gateway, "/v1/chat/completions", {"messages": []})
    assert status == 401
    status, _ = _post(secured_gateway, "/v1/chat/completions",
                      {"messages": [{"role": "user", "content": "x"}]},
                      headers={"Authorization": "Bearer topsecret"})
    assert status == 200


def test_streaming_sse(gateway):
    request = urllib.request.Request(
        gateway + "/v1/chat/completions",
        data=json.dumps({"messages": [{"role": "user", "content": "hi"}], "stream": True}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as resp:
        body = resp.read().decode()
    assert "data: [DONE]" in body
    assert "chat.completion.chunk" in body
    assert "gateway answer" in body or "zyko_receipt" in body
