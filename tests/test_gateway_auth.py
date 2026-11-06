"""Gateway multi-user auth (0.7.0): UserStore, scrypt hashing, HTTP governance."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest
import yaml

from tests.fakes import FakeProvider
from zyko.exceptions import ConfigError, GatewayAuthError
from zyko.gateway.auth import UserStore, hash_key, verify_key
from zyko.gateway.server import serve
from zyko.router.engine import Router


# --------------------------------------------------------------------- hashing
def test_hash_key_format_roundtrip_and_fresh_salt():
    record = hash_key("s3cret")
    parts = record.split("$")
    assert parts[0] == "scrypt" and len(parts) == 6
    n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
    assert (n, r, p) == (16384, 8, 1)
    assert verify_key("s3cret", record)
    assert not verify_key("wrong", record)
    # fresh salt per call: same key, different records, both verify
    other = hash_key("s3cret")
    assert other != record
    assert verify_key("s3cret", other)


def test_verify_key_malformed_records_are_false_never_raise():
    assert not verify_key("x", "scrypt$garbage")
    assert not verify_key("x", "scrypt$16384$8$1$zz$51")  # bad hex salt
    assert not verify_key("x", "scrypt$0$8$1$ab$cd")  # invalid scrypt params
    assert not verify_key("x", "")
    assert not verify_key("", "anything")


def test_hash_key_rejects_empty():
    with pytest.raises(GatewayAuthError):
        hash_key("")


def test_gateway_auth_error_is_config_error():
    assert issubclass(GatewayAuthError, ConfigError)


# ------------------------------------------------------------------ UserStore
def _write_users(tmp_path, doc, name="users.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


def _doc():
    return {
        "users": [
            {"name": "alice", "key": "plain-dev", "roles": ["chat"], "rpm": 5},
            {
                "name": "ops",
                "key_hash": hash_key("op-secret"),
                "roles": ["chat", "admin"],
                "daily_budget_usd": 5.0,
            },
            {"name": "intern", "key": "intern-key", "enabled": False},
        ]
    }


def test_userstore_load_from_yaml_and_suffix_search(tmp_path):
    path = _write_users(tmp_path, _doc())
    store = UserStore.load(str(path))
    assert store.get("alice") is not None
    # suffix search: name without extension resolves .yaml
    (tmp_path / "team.yaml").write_text(yaml.safe_dump(_doc()), encoding="utf-8")
    store2 = UserStore.load(str(tmp_path / "team"))
    assert store2.get("ops") is not None


def test_userstore_missing_file_lists_searched_paths(tmp_path):
    with pytest.raises(GatewayAuthError) as exc:
        UserStore.load(str(tmp_path / "nowhere"))
    assert "not found" in str(exc.value)
    assert "searched:" in str(exc.value)


def test_userstore_rejects_duplicate_names():
    doc = {"users": [{"name": "x", "key": "a"}, {"name": "x", "key": "b"}]}
    with pytest.raises(GatewayAuthError) as exc:
        UserStore.from_doc(doc)
    assert "duplicate user name" in str(exc.value)


def test_userstore_rejects_missing_or_ambiguous_key():
    with pytest.raises(GatewayAuthError) as no_key:
        UserStore.from_doc({"users": [{"name": "x"}]})
    assert "exactly one of 'key'" in str(no_key.value)
    both = {"users": [{"name": "x", "key": "a", "key_hash": hash_key("b")}]}
    with pytest.raises(GatewayAuthError):
        UserStore.from_doc(both)


def test_userstore_rejects_bad_key_hash_role_rpm_budget_and_shape():
    with pytest.raises(GatewayAuthError):
        UserStore.from_doc({"users": [{"name": "x", "key_hash": "plaintext-not-scrypt"}]})
    with pytest.raises(GatewayAuthError):
        UserStore.from_doc({"users": [{"name": "x", "key": "k", "roles": ["sudo"]}]})
    with pytest.raises(GatewayAuthError):
        UserStore.from_doc({"users": [{"name": "x", "key": "k", "roles": []}]})
    with pytest.raises(GatewayAuthError):
        UserStore.from_doc({"users": [{"name": "x", "key": "k", "rpm": 0}]})
    with pytest.raises(GatewayAuthError):
        UserStore.from_doc({"users": [{"name": "x", "key": "k", "daily_budget_usd": -1}]})
    with pytest.raises(GatewayAuthError):
        UserStore.from_doc({"users": []})
    with pytest.raises(GatewayAuthError):
        UserStore.from_doc({"users": ["not-a-mapping"]})


def test_authenticate_matches_every_entry_no_early_exit():
    store = UserStore.from_doc(_doc())
    alice = store.authenticate("plain-dev")
    assert alice is not None and alice.name == "alice"
    ops = store.authenticate("op-secret")
    assert ops is not None and ops.is_admin
    intern = store.authenticate("intern-key")
    # disabled users still authenticate — the SERVER turns that into 403
    assert intern is not None and intern.enabled is False
    assert store.authenticate("nothing-matches") is None
    assert store.authenticate("") is None


def test_snapshot_never_leaks_key_material():
    store = UserStore.from_doc(_doc())
    blob = json.dumps(store.snapshot())
    assert "plain-dev" not in blob
    assert "op-secret" not in blob
    assert "scrypt$" not in blob
    assert blob.count('"name"') == 3


def test_rpm_bucket_exhausts_then_refills():
    """Exhaust, refuse, refill — on an injected clock, not the wall clock.

    This test used to sleep 0.12 s and assert the bucket was empty after 6000
    calls. A 6000 rpm bucket refills 100 tokens/s, i.e. one token per 10 ms of
    *test run time*, so on a slow runner (Windows CI) the 6000-call loop alone
    took long enough to refill the bucket and the "capacity reached" assertion
    flipped. It failed on windows-latest · py3.11 in runs 41711705447 and
    41712602606 for exactly that reason. The bucket now takes a clock.
    """

    class Clock:
        def __init__(self) -> None:
            self.now = 1000.0

        def __call__(self) -> float:
            return self.now

    clock = Clock()
    store = UserStore.from_doc({"users": [{"name": "burst", "key": "k", "rpm": 6000}]}, clock=clock)
    user = store.get("burst")
    assert all(store.check_rate(user) for _ in range(6000))
    assert not store.check_rate(user)  # capacity reached, no time has passed
    clock.now += 0.5  # 6000/min = 100/s → 50 tokens refill
    assert all(store.check_rate(user) for _ in range(50))
    assert not store.check_rate(user)  # those 50 were all that refilled
    clock.now += 60.0  # a full minute refills to capacity, never beyond it
    assert all(store.check_rate(user) for _ in range(6000))
    assert not store.check_rate(user)


def test_unlimited_user_has_no_bucket():
    store = UserStore.from_doc({"users": [{"name": "free", "key": "k"}]})
    user = store.get("free")
    assert all(store.check_rate(user) for _ in range(500))


def test_budget_ledger_records_persists_and_resets_daily(tmp_path):
    store = UserStore.from_doc(_doc(), state_dir=tmp_path / "state")
    ops = store.get("ops")
    assert store.budget_left(ops) == 5.0
    store.record_usage(ops, cost_usd=2.0, input_tokens=11, output_tokens=7)
    entry = store.ledger.today("ops")
    assert entry["spend_usd"] == 2.0 and entry["requests"] == 1
    assert entry["input_tokens"] == 11 and entry["output_tokens"] == 7
    # persistence: a fresh store over the same state dir sees the spend
    reloaded = UserStore.from_doc(_doc(), state_dir=tmp_path / "state")
    assert reloaded.budget_left(reloaded.get("ops")) == 3.0
    reloaded.record_usage(reloaded.get("ops"), cost_usd=3.0)
    assert not reloaded.within_budget(reloaded.get("ops"))
    # day rollover: yesterday's state no longer counts
    state_file = tmp_path / "state" / "gateway_users_state.json"
    state = json.loads(state_file.read_text())
    state["ops"]["date"] = "2000-01-01"
    state_file.write_text(json.dumps(state))
    assert reloaded.budget_left(reloaded.get("ops")) == 5.0


def test_users_without_budget_or_rpm_are_unlimited(tmp_path):
    store = UserStore.from_doc(_doc(), state_dir=tmp_path / "s2")
    alice = store.get("alice")
    assert alice.daily_budget_usd is None
    assert store.budget_left(alice) is None
    assert store.within_budget(alice)


# -------------------------------------------------------------- HTTP surfaces
@pytest.fixture()
def multiuser_gateway(tmp_path):
    router = Router({"fake": FakeProvider(script=["multiuser answer"])})
    store = UserStore.from_doc(_doc(), state_dir=tmp_path / "gwstate")
    httpd = serve(router, host="127.0.0.1", port=0, users=store)
    port = httpd.server_address[1]
    yield f"http://127.0.0.1:{port}", store
    httpd.shutdown()


def _post(base, path, payload, headers=None):
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


def _get(base, path, headers=None):
    request = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def test_multiuser_chat_carries_identity_in_receipt(multiuser_gateway):
    base, store = multiuser_gateway
    status, body = _post(
        base,
        "/v1/chat/completions",
        {"messages": [{"role": "user", "content": "hi"}]},
        {"Authorization": "Bearer plain-dev"},
    )
    assert status == 200
    assert body["zyko"]["receipt"]["user"] == "alice"
    entry = store.ledger.today("alice")
    assert entry["requests"] == 1


def test_multiuser_hashed_key_works_end_to_end(multiuser_gateway):
    base, _ = multiuser_gateway
    status, body = _post(
        base,
        "/v1/chat/completions",
        {"messages": [{"role": "user", "content": "hi"}]},
        {"Authorization": "Bearer op-secret"},
    )
    assert status == 200
    assert body["zyko"]["receipt"]["user"] == "ops"


def test_multiuser_bad_and_missing_tokens_401(multiuser_gateway):
    base, _ = multiuser_gateway
    status, body = _post(
        base, "/v1/chat/completions", {"messages": [{"role": "user", "content": "hi"}]}
    )
    assert status == 401 and "bearer" in body["error"]["message"].lower()
    status, _ = _get(base, "/healthz", {"Authorization": "Bearer nope"})
    assert status == 401


def test_multiuser_disabled_user_gets_403(multiuser_gateway):
    base, _ = multiuser_gateway
    status, body = _post(
        base,
        "/v1/chat/completions",
        {"messages": [{"role": "user", "content": "hi"}]},
        {"Authorization": "Bearer intern-key"},
    )
    assert status == 403
    assert "disabled" in body["error"]["message"]


def test_multiuser_rpm_enforced_over_http(multiuser_gateway):
    base, _ = multiuser_gateway
    headers = {"Authorization": "Bearer plain-dev"}
    # alice declares rpm=5; the fixture store starts full, so burn then expect 429
    for _ in range(5):
        status, _b = _post(
            base,
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hi"}]},
            headers,
        )
        assert status == 200
    status, body = _post(
        base,
        "/v1/chat/completions",
        {"messages": [{"role": "user", "content": "hi"}]},
        headers,
    )
    assert status == 429
    assert body["error"]["type"] == "zyko_rate_limit"
    assert "rpm=5" in body["error"]["message"]


def test_multiuser_budget_enforced_over_http(multiuser_gateway):
    base, store = multiuser_gateway
    # pre-seed the ledger so 'ops' (budget 5.0) is already spent out —
    # deterministic: does not depend on provider pricing
    store.record_usage(store.get("ops"), cost_usd=5.0)
    status, body = _post(
        base,
        "/v1/chat/completions",
        {"messages": [{"role": "user", "content": "hi"}]},
        {"Authorization": "Bearer op-secret"},
    )
    assert status == 429
    assert body["error"]["type"] == "zyko_budget_exceeded"
    assert "daily_budget_usd=5.0" in body["error"]["message"]


def test_users_me_reports_identity_and_usage(multiuser_gateway):
    base, store = multiuser_gateway
    status, body = _get(base, "/v1/users/me", {"Authorization": "Bearer op-secret"})
    assert status == 200
    assert body["object"] == "user"
    assert body["user"]["name"] == "ops"
    assert "scrypt" not in json.dumps(body)
    store.record_usage(store.get("ops"), cost_usd=1.5)
    _s, body2 = _get(base, "/v1/users/me", {"Authorization": "Bearer op-secret"})
    assert body2["usage_today"]["requests"] == 1
    assert body2["usage_today"]["spend_usd"] == 1.5
    assert body2["budget_remaining_usd"] == 3.5
    # wrong token still 401 on the same endpoint
    status, _ = _get(base, "/v1/users/me", {"Authorization": "Bearer nope"})
    assert status == 401


def test_users_me_404_without_users_store():
    router = Router({"fake": FakeProvider(script=["secret"])})
    httpd = serve(router, host="127.0.0.1", port=0, api_key="topsecret")
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        status, _body = _get(base, "/v1/users/me", {"Authorization": "Bearer topsecret"})
        assert status == 404
    finally:
        httpd.shutdown()


def test_legacy_single_token_gateway_unchanged():
    router = Router({"fake": FakeProvider(script=["legacy answer"])})
    httpd = serve(router, host="127.0.0.1", port=0, api_key="topsecret")
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        status, body = _post(
            base,
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hi"}]},
            {"Authorization": "Bearer topsecret"},
        )
        assert status == 200
        assert "user" not in body["zyko"]["receipt"]  # legacy receipts stay clean
        status, _ = _post(
            base,
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hi"}]},
            {"Authorization": "Bearer wrong"},
        )
        assert status == 401
    finally:
        httpd.shutdown()


def test_open_gateway_still_works():
    router = Router({"fake": FakeProvider(script=["open answer"])})
    httpd = serve(router, host="127.0.0.1", port=0)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        status, body = _post(
            base, "/v1/chat/completions", {"messages": [{"role": "user", "content": "hi"}]}
        )
        assert status == 200 and body["choices"][0]["message"]["content"] == "open answer"
    finally:
        httpd.shutdown()


def test_streaming_identity_in_meta_receipt(multiuser_gateway):
    base, store = multiuser_gateway
    request = urllib.request.Request(
        base + "/v1/chat/completions",
        data=json.dumps({"stream": True, "messages": [{"role": "user", "content": "hi"}]}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer plain-dev"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as resp:
        raw = resp.read().decode()
    assert "zyko_receipt" in raw
    meta_line = next(line for line in raw.splitlines() if "zyko_receipt" in line)
    receipt = json.loads(meta_line.removeprefix("data: "))["zyko_receipt"]
    assert receipt["user"] == "alice"
    assert store.ledger.today("alice")["requests"] == 1


# ------------------------------------------------------------------------ CLI
def test_hash_key_cli(capsys):
    from zyko.cli import main

    assert main(["hash-key", "--key", "cli-secret"]) == 0
    out = capsys.readouterr().out
    record = out.strip().splitlines()[0]
    assert record.startswith("scrypt$")
    assert verify_key("cli-secret", record)


def test_gatewayautherror_surfaces_from_bad_users_file(tmp_path, capsys):
    from zyko.cli import main

    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"users": [{"name": "x"}]}), encoding="utf-8")
    assert main(["serve", "--users", str(bad)]) == 1
    assert "exactly one of 'key'" in capsys.readouterr().err
