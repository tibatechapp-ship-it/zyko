"""deploy/vercel/api/zyko.py — دالة Vercel Serverless بواجهة متوافقة مع OpenAI.

تطبيق ASGI مصغّر بلا أي إطار فوق zyko نفسها: اعتماديتا zyko الإلزاميتان
(httpx + PyYAML) تكفيان للبارد — لا FastAPI ولا Flask في مسار النشر هذا.

المسارات (عبر rewrites في vercel.json):
    POST /v1/chat/completions  ← سؤال موجه عبر zyko، بقرار توجيه قابل للتحقق
    GET  /v1/models            ← المزوّدات المهيأة في هذه النسخة
    GET  /healthz              ← حيّة الدالة

بلا مفاتيح تعمل الدالة فوق المزوّج الحتمي المدمج (عقد zyko: أول تشغيل يعمل
بلا مفاتيح على كل منصة). بمفتاح واحد في البيئة تتحول للتوجيه الحقيقي.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

_MAX_BODY = 1_000_000  # 1MB — سقف جسم الطلب المعلن

_state: dict[str, Any] = {}


def _gateway_api_key() -> str | None:
    return os.environ.get("ZYKO_GATEWAY_API_KEY") or None


def _unauthorized() -> tuple[int, dict[str, Any]]:
    return 401, {"error": {"message": "missing or invalid bearer token (ZYKO_GATEWAY_API_KEY)"}}


def _authorized(headers: dict[str, str]) -> bool:
    key = _gateway_api_key()
    if not key:  # بلا مفتاح مضبوط: البوابة مفتوحة (تطوير/عرض) — السياسة نفسها في zyko serve
        return True
    supplied = headers.get("authorization", "") or headers.get("Authorization", "")
    return supplied == f"Bearer {key}"


def _engine() -> Any:
    """محرك zyko مرة واحدة لكل نسخة دالة — مزوّد حقيقي إن وُجد مفتاح، وإلا العرض الحتمي."""
    if "engine" not in _state:
        from zyko.client import Zyko
        from zyko.config.settings import Settings
        from zyko.providers import configured_providers
        from zyko.providers.mock import MockProvider

        settings = Settings.load()
        providers = configured_providers(settings.provider_settings) or {
            "mock": MockProvider()
        }
        _state["engine"] = Zyko(providers=providers)
        _state["demo"] = "mock" in providers and len(providers) == 1
    return _state["engine"]


def _models_payload() -> dict[str, Any]:
    engine = _engine()
    names = sorted(engine.providers.keys())
    return {
        "object": "list",
        "data": [{"id": n, "object": "model", "owned_by": "zyko"} for n in names],
    }


def _chat_payload(body: bytes) -> tuple[int, dict[str, Any]]:
    try:
        payload = json.loads(body.decode("utf-8"))
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            return 400, {"error": {"message": "messages list is required"}}
        prompt_parts = [
            str(m.get("content", ""))
            for m in messages
            if m.get("role") in ("user", "system")
        ]
        prompt = "\n".join(p for p in prompt_parts if p).strip()
        if not prompt:
            return 400, {"error": {"message": "no user/system content in messages"}}
        engine = _engine()
        result = engine.ask(prompt)
        text = result.response.text
        receipt = getattr(result, "receipt", {}) or {}
        return 200, {
            "id": f"chatcmpl-vercel-{receipt.get('chosen', 'route')}",
            "object": "chat.completion",
            "model": payload.get("model") or "zyko-routed",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
            ],
            "zyko": {
                "chosen": receipt.get("chosen"),
                "deterministic": bool(_state.get("demo")),
            },
        }
    except Exception as exc:  # لا استثناء خارج طبقة الذكاء أبدًا
        return 502, {"error": {"message": f"zyko engine failed: {exc}"}}


def _route(method: str, path: str, body: bytes, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    if path.endswith("/healthz"):
        return 200, {"ok": True, "service": "zyko-vercel"}
    if not path.endswith(("/v1/chat/completions", "/v1/models", "/api/zyko")):
        return 404, {"error": {"message": f"unknown path {path}"}}
    if not _authorized(headers):
        return _unauthorized()
    if method == "GET" and path.endswith("/v1/models"):
        return 200, _models_payload()
    if method == "POST" and path.endswith("/v1/chat/completions"):
        return _chat_payload(body)
    return 405, {"error": {"message": f"{method} not allowed on {path}"}}


async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    """ASGI مصغّر — واحد للمسارات كلها، بلا أطر ولا اعتماديات إضافية."""
    if scope["type"] != "http":
        return
    body = b""
    more = True
    while more:
        message = await receive()
        if message["type"] == "http.request":
            body += message.get("body", b"")
            more = message.get("more_body", False)
            if len(body) > _MAX_BODY:
                await _respond(send, 413, {"error": {"message": "body too large"}})
                return
        else:
            more = False
    headers = {
        k.decode("utf-8").lower(): v.decode("utf-8")
        for k, v in scope.get("headers", [])
    }
    path = scope.get("path", "/")
    method = scope.get("method", "GET").upper()
    # الاستدعاء الحتمي للمحرك في خيط عمل — حلقة الأحداث لا تُسد بنداء الشبكة.
    status, payload = await asyncio.to_thread(_route, method, path, body, headers)
    await _respond(send, status, payload)


async def _respond(send: Any, status: int, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json; charset=utf-8")],
        }
    )
    await send({"type": "http.response.body", "body": data})
