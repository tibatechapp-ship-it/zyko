"""اختبارات عقل Qwen: نموذج حقيقي عبر واجهة متوافقة مع OpenAI، والبوابات تقرّر.

طبقتان بلا شبكة إطلاقًا:
  1) نقل مزيف يُحقن في العقل — وحدات القرار والأخطاء العربية؛
  2) خادم HTTP وهمي على منفذ محلي يحاكي نقطة نهاية متوافقة مع OpenAI —
     مسار urllib الحقيقي بترويسة Bearer.

والقاعدة الذهبية تُختبر من طرف إلى طرف: نص النموذج (نظيفًا كان أم
مشبوهًا أم عدائيًا) لا يُقبل إلا عبر بوابة PII ثم بوابة RTL.
"""

from __future__ import annotations

import io
import json
import socket
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from zyko.ai.brains import Brain, GatedBrain
from zyko.ai.cli import main as ai_main
from zyko.ai.qwen_brain import (
    API_KEY_ENV,
    HOST_ENV,
    QwenBrain,
    build_chat_payload,
    extract_choice_content,
    list_qwen_models,
)
from zyko.ai.session import AISession
from zyko.mock_llm import get_scenario

CLEAN_GOAL = "قائمة مهام بسيطة مع واجهة سطر أوامر ووحدة tasks"
PII_GOAL = "قائمة مهام — للتنسيق اتصل على 0501234567"

# خطة عربية نظيفة تمامًا: لا PII ولا أخطاء اتجاه — تعود من «النموذج» في الاختبارات
PLAN_CLEAN = "\n".join(
    [
        "- وحدة tasks لإدارة المهام والذاكرة",
        "- واجهة سطر أوامر للإضافة والإتمام والإدراج",
        "- اختبارات وحدة أساسية للمسارات الثلاثة",
    ]
)


def _openai_response(content: object) -> dict[str, Any]:
    """استجابة متوافقة مع OpenAI: ``choices[0].message.content``."""
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _fake_transport(content: object) -> Any:
    """نقل مزيف يعيد استجابة جاهزة — يلتقط الحمولة في ``payloads``."""

    def call(payload: dict[str, Any]) -> Any:
        _fake_transport.payloads.append(payload)  # type: ignore[attr-defined]
        return _openai_response(content)

    return call


_fake_transport.payloads = []  # type: ignore[attr-defined]


# ============================================================ الحمولة والموجّه
def test_chat_payload_shape_deterministic_openai_style() -> None:
    a = build_chat_payload("qwen-plus", CLEAN_GOAL)
    b = build_chat_payload("qwen-plus", CLEAN_GOAL)
    assert a == b
    assert list(a) == ["model", "messages", "stream", "max_tokens"]
    assert a["model"] == "qwen-plus"
    assert a["stream"] is False
    assert a["max_tokens"] == 1024
    assert a["messages"][0]["role"] == "system"
    assert a["messages"][1]["role"] == "user"
    assert a["messages"][1]["content"].endswith("الخطة:")
    assert CLEAN_GOAL in a["messages"][1]["content"]
    assert "بلا بيانات شخصية" in a["messages"][1]["content"]  # قاعدة PII مكتوبة في الموجّه


def test_thinking_toggle_adds_enable_thinking_only_when_true() -> None:
    off = build_chat_payload("m", CLEAN_GOAL)
    assert "enable_thinking" not in off  # الإيقاف حذفًا لل حقل — خوادم صارمة لا ترفضه
    on = build_chat_payload("m", CLEAN_GOAL, thinking=True)
    assert on["enable_thinking"] is True
    custom = build_chat_payload("m", CLEAN_GOAL, max_tokens=256)
    assert custom["max_tokens"] == 256


# ============================================================ استخراج النص
def test_extract_choice_content_reads_choices_message_content() -> None:
    assert extract_choice_content(_openai_response("  نص  ")) == "نص"
    with pytest.raises(KeyError):
        extract_choice_content({})
    with pytest.raises(KeyError):
        extract_choice_content({"choices": []})
    with pytest.raises(TypeError):
        extract_choice_content(_openai_response(None))
    with pytest.raises(ValueError):
        extract_choice_content([1, 2])


def test_extract_choice_content_ignores_reasoning_content() -> None:
    resp = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": PLAN_CLEAN,
                    "reasoning_content": "سلسلة استدلال طويلة لا نهتم بها",
                }
            }
        ]
    }
    assert extract_choice_content(resp) == PLAN_CLEAN


# ============================================================ وحدات العقل
def test_happy_path_clean_output_accepted_through_gates() -> None:
    brain = QwenBrain(model="qwen-plus", api_key="k", transport=_fake_transport(PLAN_CLEAN))
    assert brain.name == "qwen:qwen-plus"
    assert brain.deterministic is False
    gated = GatedBrain(brain)
    proposal = gated.propose(CLEAN_GOAL)
    assert proposal.accepted
    assert proposal.text == PLAN_CLEAN
    assert proposal.brain == "gated:qwen:qwen-plus"
    # الترتيب الثابت: حكم العقل ← PII ← RTL
    assert [v.gate for v in proposal.verdicts] == ["qwen", "pii", "rtl"]


def test_brain_is_runtime_checkable_and_records_payload() -> None:
    _fake_transport.payloads.clear()
    brain = QwenBrain(model="m1", api_key="k", transport=_fake_transport(PLAN_CLEAN))
    assert isinstance(brain, Brain)  # type: ignore[arg-type]
    brain.propose(CLEAN_GOAL)
    payload = _fake_transport.payloads[0]
    assert payload["model"] == "m1"
    assert CLEAN_GOAL in payload["messages"][1]["content"]
    assert payload["max_tokens"] == 1024


def test_pii_output_rejected_by_pii_gate_not_by_luck() -> None:
    dirty = get_scenario("suspicious").render(CLEAN_GOAL)
    brain = QwenBrain(model="m", api_key="k", transport=_fake_transport(dirty))
    proposal = GatedBrain(brain).propose(CLEAN_GOAL)
    assert not proposal.accepted  # نص النموذج لا يتجاوز البوابة أبدًا
    pii = next(v for v in proposal.verdicts if v.gate == "pii")
    assert not pii.passed
    assert "phone" in pii.details_ar


def test_hostile_output_rejected_defense_in_depth() -> None:
    dirty = get_scenario("hostile").render(CLEAN_GOAL)
    brain = QwenBrain(model="m", api_key="k", transport=_fake_transport(dirty))
    proposal = GatedBrain(brain).propose(PII_GOAL)
    assert not proposal.accepted
    assert any(not v.passed for v in proposal.verdicts)


@pytest.mark.parametrize(
    ("content", "needle"),
    [
        ("   ", "فارغًا"),
        (42, "غير مفهومة"),
        (None, "غير مفهومة"),
    ],
)
def test_bad_responses_become_arabic_rejections(content: object, needle: str) -> None:
    brain = QwenBrain(model="m", api_key="k", transport=_fake_transport(content))
    proposal = GatedBrain(brain).propose(CLEAN_GOAL)
    assert not proposal.accepted
    qwen = next(v for v in proposal.verdicts if v.gate == "qwen")
    assert not qwen.passed
    assert needle in qwen.details_ar


@pytest.mark.parametrize(
    ("exc", "needle"),
    [
        (
            urllib.error.HTTPError("u", 401, "no", None, io.BytesIO(b"")),
            "المفتاح",
        ),
        (
            urllib.error.HTTPError("u", 403, "no", None, io.BytesIO(b"")),
            "المفتاح",
        ),
        (
            urllib.error.HTTPError("u", 404, "no", None, io.BytesIO(b"")),
            "المسار",
        ),
        (
            urllib.error.HTTPError("u", 429, "no", None, io.BytesIO(b"")),
            "429",
        ),
        (
            urllib.error.HTTPError("u", 500, "boom", None, io.BytesIO(b"")),
            "HTTP 500",
        ),
        (urllib.error.URLError("refused"), "تعذّر الوصول إلى Qwen"),
        (TimeoutError(), "مهلة"),
        (ValueError("x"), "غير مفهومة"),
    ],
)
def test_transport_failures_never_escape_as_exceptions(exc: Exception, needle: str) -> None:
    def call(payload: dict[str, Any]) -> dict[str, Any]:
        raise exc

    brain = QwenBrain(model="m", api_key="k", host="http://127.0.0.1:1", transport=call)
    proposal = GatedBrain(brain).propose(CLEAN_GOAL)
    assert not proposal.accepted
    qwen = next(v for v in proposal.verdicts if v.gate == "qwen")
    assert not qwen.passed
    assert needle in qwen.details_ar


def test_empty_model_name_rejected_at_construction() -> None:
    with pytest.raises(ValueError):
        QwenBrain(model="   ")


def test_empty_goal_rejected_without_network() -> None:
    _fake_transport.payloads.clear()
    brain = QwenBrain(model="m", api_key="k", transport=_fake_transport(PLAN_CLEAN))
    proposal = GatedBrain(brain).propose("   ")
    assert not proposal.accepted
    assert not _fake_transport.payloads  # لا طلب أُرسل أصلًا


def test_missing_key_is_an_arabic_rejection_not_an_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    _fake_transport.payloads.clear()
    brain = QwenBrain(model="m", transport=_fake_transport(PLAN_CLEAN))
    proposal = GatedBrain(brain).propose(CLEAN_GOAL)
    assert not proposal.accepted
    qwen = next(v for v in proposal.verdicts if v.gate == "qwen")
    assert "ZYKO_QWEN_API_KEY" in qwen.details_ar
    assert not _fake_transport.payloads  # بلا مفتاح لا يُرسل طلب


def test_host_and_key_resolution_env_then_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HOST_ENV, "http://10.1.2.3:8000/v1/")
    assert QwenBrain(model="m", api_key="k").host == "http://10.1.2.3:8000/v1"
    assert (
        QwenBrain(model="m", api_key="k", host="http://127.0.0.1:9/v1").host
        == "http://127.0.0.1:9/v1"
    )
    monkeypatch.setenv(API_KEY_ENV, "from-env")
    assert QwenBrain(model="m").api_key == "from-env"
    assert QwenBrain(model="m", api_key="explicit").api_key == "explicit"


# ============================================================ خادم متوافق وهمي
class _FakeOpenAIHandler(BaseHTTPRequestHandler):
    """محاكي نقطة نهاية متوافقة مع OpenAI: ‎/models للفهرسة و‎/chat/completions للمحادثة."""

    def log_message(self, *args: object) -> None:  # صمت تام
        pass

    def _send(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/v1/models":
            body = json.dumps({"data": [{"id": "qwen-plus"}, {"id": "qwen3.5"}]}).encode("utf-8")
            self._send(200, body)
        else:
            self._send(404, b"{}")

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        if self.path != "/v1/chat/completions":
            self._send(404, b"{}")
            return
        payload = json.loads(raw.decode("utf-8"))
        model = payload.get("model", "")
        if model == "boom-model":
            self._send(500, json.dumps({"error": "انفجار نموذج"}).encode("utf-8"))
            return
        if model == "badjson-model":
            self._send(200, "ليس JSON أصلًا".encode("utf-8"))
            return
        if not self.headers.get("Authorization", "").startswith("Bearer "):
            self._send(401, json.dumps({"error": "no key"}).encode("utf-8"))
            return
        self._send(
            200,
            json.dumps(_openai_response(PLAN_CLEAN + "\n\n"), ensure_ascii=False).encode("utf-8"),
        )


@pytest.fixture()
def openai_server() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_real_http_roundtrip_clean_plan_accepted(openai_server: str) -> None:
    brain = QwenBrain(model="qwen-plus", host=openai_server + "/v1", api_key="k", timeout=5.0)
    proposal = GatedBrain(brain).propose(CLEAN_GOAL)
    assert proposal.accepted
    assert proposal.text == PLAN_CLEAN


def test_real_http_roundtrip_http500_rejected(openai_server: str) -> None:
    brain = QwenBrain(model="boom-model", host=openai_server + "/v1", api_key="k", timeout=5.0)
    proposal = GatedBrain(brain).propose(CLEAN_GOAL)
    assert not proposal.accepted
    qwen = next(v for v in proposal.verdicts if v.gate == "qwen")
    assert "HTTP 500" in qwen.details_ar


def test_real_http_roundtrip_malformed_body_rejected(openai_server: str) -> None:
    brain = QwenBrain(model="badjson-model", host=openai_server + "/v1", api_key="k", timeout=5.0)
    proposal = GatedBrain(brain).propose(CLEAN_GOAL)
    assert not proposal.accepted


def test_list_qwen_models_via_mock_server(openai_server: str) -> None:
    assert list_qwen_models(openai_server + "/v1", api_key="k") == (
        "qwen-plus",
        "qwen3.5",
    )


def _closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_connection_refused_becomes_arabic_verdict() -> None:
    port = _closed_port()
    brain = QwenBrain(model="m", host=f"http://127.0.0.1:{port}/v1", api_key="k", timeout=2.0)
    proposal = GatedBrain(brain).propose(CLEAN_GOAL)
    assert not proposal.accepted
    qwen = next(v for v in proposal.verdicts if v.gate == "qwen")
    assert f"127.0.0.1:{port}" in qwen.details_ar
    assert "تعذّر الوصول" in qwen.details_ar


# ============================================================ الجلسة الكاملة
def test_session_with_qwen_brain_clean_accepted(tmp_path: Path) -> None:
    brain = GatedBrain(QwenBrain(model="m2", api_key="k", transport=_fake_transport(PLAN_CLEAN)))
    receipt = AISession(brain=brain).run(CLEAN_GOAL, tmp_path / "proj")
    assert receipt.ok
    assert receipt.brain == "gated:qwen:m2"
    assert receipt.brain_deterministic is False
    assert receipt.plan is not None and receipt.plan["text"] == PLAN_CLEAN
    assert receipt.steps[0].step == "plan" and receipt.steps[0].ok


def test_session_with_qwen_brain_suspicious_rejected_before_any_write(tmp_path: Path) -> None:
    dirty = get_scenario("suspicious").render(CLEAN_GOAL)
    brain = GatedBrain(QwenBrain(model="m", api_key="k", transport=_fake_transport(dirty)))
    receipt = AISession(brain=brain).run(CLEAN_GOAL, tmp_path / "proj")
    assert not receipt.ok
    assert receipt.failed_step == "plan"
    assert "phone" in receipt.steps[0].details_ar
    assert not (tmp_path / "proj").exists()  # الرفض قبل كتابة بايت واحد


def test_session_qwen_receipt_is_byte_deterministic(tmp_path: Path) -> None:
    brain = GatedBrain(QwenBrain(model="m3", api_key="k", transport=_fake_transport(PLAN_CLEAN)))
    r1 = AISession(brain=brain).run(CLEAN_GOAL, tmp_path / "a" / "proj")
    r2 = AISession(brain=brain).run(CLEAN_GOAL, tmp_path / "b" / "proj")
    assert r1.to_json() == r2.to_json()


# ============================================================ سطر الأوامر
def test_cli_run_brain_qwen_requires_model(capsys: pytest.CaptureFixture[str]) -> None:
    rc = ai_main(["run", "--brain", "qwen", "--goal", CLEAN_GOAL, "--out", "/tmp/x"])
    assert rc == 2
    assert "--model" in capsys.readouterr().err


def test_cli_run_brain_qwen_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from zyko.ai import qwen_brain as qb

    monkeypatch.setenv(API_KEY_ENV, "test-key")  # المفتاح من البيئة — بلا شبكة فعلية
    monkeypatch.setattr(
        qb,
        "_http_transport",
        lambda host, api_key, timeout: _fake_transport(PLAN_CLEAN),
    )
    rc = ai_main(
        [
            "run",
            "--brain",
            "qwen",
            "--model",
            "fake-model",
            "--goal",
            CLEAN_GOAL,
            "--out",
            str(tmp_path / "proj"),
            "--dry-run",
            "--format",
            "json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["brain"] == "gated:qwen:fake-model"
    assert payload["brain_deterministic"] is False
    assert payload["plan"]["text"] == PLAN_CLEAN


def test_map_documents_the_qwen_brain(capsys: pytest.CaptureFixture[str]) -> None:
    assert ai_main(["map"]) == 0
    out = capsys.readouterr().out
    assert "--brain qwen" in out
    assert "qwen:" in out or "qwen " in out
