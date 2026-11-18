"""اختبارات تحصين البوابة (v0.54.0 — المراجعة الخارجية تُغلق).

العقود:
1. **فشل مغلقة**: ربط واجهة خارجية (0.0.0.0) بلا مصادقة يُرفض قبل فتح
   المقبس — والباب المفتوح فعل صريح (allow_open) لا سهو افتراضي.
2. **صمام الحجم**: جسم يتجاوز السقف يُرفض 413 بلا قراءة، والاتصال يُغلق
   (البايتات غير المقروءة لا تسمّم الطلب التالي).
3. **صمام التزامن**: طلبات فوق السقف تُرفض 503 ولا تُطلق خيوطًا بلا حد.
4. **صمت الخمسمئة**: خطأ داخلي لا يسرّب نص الاستثناء — التفاصيل للسجل.
5. القيم الافتراضية معلنة (ثوابت مُصدَّرة لا أرقام مبعثرة).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request

import pytest

from tests.fakes import FakeProvider
from zyko.exceptions import GatewayAuthError
from zyko.gateway import server as gw
from zyko.gateway.server import serve
from zyko.router.engine import Router


def _post(
    base: str,
    path: str,
    payload: dict,
    *,
    headers: dict | None = None,
    raw_data: bytes | None = None,
) -> tuple[int, dict | str]:
    data = raw_data if raw_data is not None else json.dumps(payload).encode()
    request = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


# ---------------------------------------------------------------- فشل مغلقة
def test_external_bind_without_auth_is_refused_before_socket_opens() -> None:
    router = Router({"fake": FakeProvider(script=["x"])})
    with pytest.raises(GatewayAuthError) as excinfo:
        serve(router, host="0.0.0.0", port=0)
    # الرسالة تسمّي الواجهة وتعلن سياسة الفشل المغلق لا تلمّح فقط
    assert "0.0.0.0" in str(excinfo.value)
    assert excinfo.value.hint and "--allow-open" in excinfo.value.hint


def test_external_bind_refusal_holds_for_ipv6_any() -> None:
    router = Router({"fake": FakeProvider(script=["x"])})
    with pytest.raises(GatewayAuthError):
        serve(router, host="::", port=0)


def test_external_bind_with_api_key_is_allowed() -> None:
    router = Router({"fake": FakeProvider(script=["x"])})
    httpd = serve(router, host="0.0.0.0", port=0, api_key="k")
    httpd.shutdown()


def test_external_bind_with_users_store_is_allowed() -> None:
    from zyko.gateway.auth import GatewayUser, UserStore

    router = Router({"fake": FakeProvider(script=["x"])})
    store = UserStore([GatewayUser(name="ops", stored_key="k")])
    httpd = serve(router, host="0.0.0.0", port=0, users=store)
    httpd.shutdown()


def test_explicit_allow_open_is_the_only_open_door_outside_loopback() -> None:
    router = Router({"fake": FakeProvider(script=["x"])})
    httpd = serve(router, host="0.0.0.0", port=0, allow_open=True)
    port = httpd.server_address[1]
    try:
        status, body = _post(
            f"http://127.0.0.1:{port}",
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hi"}]},
        )
        assert status == 200  # الباب المفتوح صراحةً يعمل فعلاً لا اسمًا
    finally:
        httpd.shutdown()


def test_loopback_open_gateway_stays_allowed_for_local_dev() -> None:
    router = Router({"fake": FakeProvider(script=["x"])})
    httpd = serve(router, host="127.0.0.1", port=0)  # الافتراضي لا يتغير
    httpd.shutdown()


# ---------------------------------------------------------------- صمام الحجم
def test_body_cap_returns_413_without_reading() -> None:
    router = Router({"fake": FakeProvider(script=["x"])})
    httpd = serve(router, host="127.0.0.1", port=0, max_body_bytes=128)
    port = httpd.server_address[1]
    try:
        status, body = _post(
            f"http://127.0.0.1:{port}",
            "/v1/chat/completions",
            {},
            raw_data=b"x" * 4096,
        )
        assert status == 413
        assert isinstance(body, dict)
        assert body["error"]["type"] == "zyko_payload_too_large"
    finally:
        httpd.shutdown()


def test_invalid_content_length_is_400_not_a_traceback() -> None:
    router = Router({"fake": FakeProvider(script=["x"])})
    httpd = serve(router, host="127.0.0.1", port=0)
    port = httpd.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "abc"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                status, body = resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            status, body = exc.code, json.loads(exc.read() or b"{}")
        assert status == 400
        assert "Content-Length" in str(body)
    finally:
        httpd.shutdown()


# --------------------------------------------------------------- صمام التزامن
def test_concurrency_cap_returns_503_not_unbounded_threads() -> None:
    router = Router({"fake": FakeProvider(script=["slow"])})

    # عقل بطيء محقون: الطلب الأول يحجز الخانة الوحيدة فالثاني يُرفض 503
    class _SlowRouter:
        def aroute(self, request):
            time.sleep(0.4)
            return router.aroute(request)

        def stream_route(self, request):
            yield from router.stream_route(request)

        def rank(self):  # noqa: D102 — /v1/models غير مستخدمة هنا
            return router.rank()

    httpd = serve(_SlowRouter(), host="127.0.0.1", port=0, max_concurrent=1)
    port = httpd.server_address[1]
    base = f"http://127.0.0.1:{port}"

    results: list[tuple[int, dict]] = []

    def first() -> None:
        results.append(
            _post(base, "/v1/chat/completions", {"messages": [{"role": "user", "content": "a"}]})
        )

    thread = threading.Thread(target=first, daemon=True)
    thread.start()
    time.sleep(0.12)  # الأول حجز الخانة وأصبح داخل aroute البطيء
    status, body = _post(
        base, "/v1/chat/completions", {"messages": [{"role": "user", "content": "b"}]}
    )
    thread.join(timeout=10)
    try:
        assert status == 503
        assert isinstance(body, dict)
        assert body["error"]["type"] == "zyko_overloaded"
        # الأول اكتمل طبيعيًا — الصمام يرفض الزائد ولا يكسر القائم
        assert results and results[0][0] == 200
    finally:
        httpd.shutdown()


# ---------------------------------------------------------------- صمت الأخطاء
def test_internal_error_is_generic_and_does_not_leak_exception_text() -> None:
    class _BrokenRouter:
        def aroute(self, request):
            raise RuntimeError("secret-internal-path /home/z/whatever")

        def stream_route(self, request):
            raise RuntimeError("secret-internal-path")

        def rank(self):
            return []

    httpd = serve(_BrokenRouter(), host="127.0.0.1", port=0)
    port = httpd.server_address[1]
    try:
        status, body = _post(
            f"http://127.0.0.1:{port}",
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hi"}]},
        )
        assert status == 500
        text = json.dumps(body, ensure_ascii=False)
        assert "secret-internal-path" not in text
        assert "internal error" in str(body)
    finally:
        httpd.shutdown()


# ---------------------------------------------------------------- ثوابت معلنة
def test_valve_defaults_are_declared_exportable_constants() -> None:
    assert gw.MAX_BODY_BYTES_DEFAULT == 16 * 1024 * 1024
    assert 1 <= gw.MAX_CONCURRENT_REQUESTS_DEFAULT <= 1024
    assert 1 <= gw.REQUEST_TIMEOUT_S_DEFAULT <= 600
    assert "127.0.0.1" in gw.LOOPBACK_HOSTS and "localhost" in gw.LOOPBACK_HOSTS


def test_timeout_valve_is_applied_to_bound_handler() -> None:
    router = Router({"fake": FakeProvider(script=["x"])})
    httpd = serve(router, host="127.0.0.1", port=0, request_timeout_s=7.5)
    try:
        # الصمام على صنف المعالج المربوط — نقيس الصنف لا مقبسًا حيًا
        assert httpd.RequestHandlerClass.timeout == 7.5
        assert httpd.RequestHandlerClass.max_body_bytes == gw.MAX_BODY_BYTES_DEFAULT
    finally:
        httpd.shutdown()
