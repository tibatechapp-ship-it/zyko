"""اختبارات العقل المحلي OllamaBrain: نموذج حقيقي، والبوابات تقرّر.

طبقتان بلا شبكة إطلاقًا:
  1) نقل مزيف يُحقن في العقل — وحدات القرار والأخطاء العربية؛
  2) خادم HTTP وهمي على منفذ محلي يحاكي Ollama — مسار urllib الحقيقي.

والقاعدة الذهبية تُختبر من طرف إلى طرف: نص النموذج (نظيفًا كان أم
مشبوهًا أم عدائيًا) لا يُقبل إلا عبر بوابة PII ثم بوابة RTL.
"""

from __future__ import annotations

import io
import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from zyko.ai.brains import Brain, GatedBrain
from zyko.ai.cli import main as ai_main
from zyko.ai.ollama_brain import (
    OllamaBrain,
    build_chat_payload,
    build_plan_prompt,
    extract_content,
    list_models,
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


def _fake_transport(content: object) -> Any:
    """نقل مزيف يعيد استجابة جاهزة — يلتقط الحمولة في ``payloads``."""

    def call(payload: dict[str, Any]) -> Any:
        _fake_transport.payloads.append(payload)  # type: ignore[attr-defined]
        return content

    return call


_fake_transport.payloads = []  # type: ignore[attr-defined]


# ============================================================ الموجّه والحمولة
def test_plan_prompt_is_deterministic_and_carries_rules() -> None:
    a = build_plan_prompt(CLEAN_GOAL)
    b = build_plan_prompt(CLEAN_GOAL)
    assert a == b
    assert CLEAN_GOAL in a
    assert "بلا بيانات شخصية" in a  # القاعدة مكتوبة في الموجّه نفسه


def test_chat_payload_shape_non_streaming() -> None:
    payload = build_chat_payload("qwen2.5:7b", CLEAN_GOAL)
    assert payload["model"] == "qwen2.5:7b"
    assert payload["stream"] is False
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["role"] == "user"
    assert payload["messages"][1]["content"].endswith("الخطة:")


# ============================================================ وحدات العقل
def test_happy_path_clean_output_accepted_through_gates() -> None:
    brain = OllamaBrain(model="qwen2.5:7b", transport=_fake_transport(
        {"message": {"role": "assistant", "content": PLAN_CLEAN}}
    ))
    assert brain.name == "ollama:qwen2.5:7b"
    assert brain.deterministic is False
    gated = GatedBrain(brain)
    proposal = gated.propose(CLEAN_GOAL)
    assert proposal.accepted
    assert proposal.text == PLAN_CLEAN
    assert proposal.brain == "gated:ollama:qwen2.5:7b"
    # الترتيب الثابت: حكم العقل ← PII ← RTL
    assert [v.gate for v in proposal.verdicts] == ["ollama", "pii", "rtl"]


def test_brain_is_runtime_checkable_and_records_payload() -> None:
    _fake_transport.payloads.clear()
    brain = OllamaBrain(model="m1", transport=_fake_transport(
        {"message": {"content": PLAN_CLEAN}}
    ))
    assert isinstance(brain, Brain)  # type: ignore[arg-type]
    brain.propose(CLEAN_GOAL)
    payload = _fake_transport.payloads[0]
    assert payload["model"] == "m1"
    assert CLEAN_GOAL in payload["messages"][1]["content"]


def test_pii_output_rejected_by_pii_gate_not_by_luck() -> None:
    dirty = get_scenario("suspicious").render(CLEAN_GOAL)
    brain = OllamaBrain(model="m", transport=_fake_transport({"message": {"content": dirty}}))
    proposal = GatedBrain(brain).propose(CLEAN_GOAL)
    assert not proposal.accepted  # نص النموذج لا يتجاوز البوابة أبدًا
    pii = next(v for v in proposal.verdicts if v.gate == "pii")
    assert not pii.passed
    assert "phone" in pii.details_ar


def test_hostile_output_rejected_defense_in_depth() -> None:
    dirty = get_scenario("hostile").render(CLEAN_GOAL)
    brain = OllamaBrain(model="m", transport=_fake_transport({"message": {"content": dirty}}))
    proposal = GatedBrain(brain).propose(PII_GOAL)
    assert not proposal.accepted
    assert any(not v.passed for v in proposal.verdicts)


@pytest.mark.parametrize(
    ("response", "needle"),
    [
        ({"message": {"content": "   "}}, "فارغًا"),
        ({}, "غير مفهومة"),
        ({"message": {"content": 42}}, "غير مفهومة"),
        ([1, 2], "غير مفهومة"),
    ],
)
def test_bad_responses_become_arabic_rejections(response: object, needle: str) -> None:
    brain = OllamaBrain(model="m", transport=_fake_transport(response))
    proposal = GatedBrain(brain).propose(CLEAN_GOAL)
    assert not proposal.accepted
    ollama = next(v for v in proposal.verdicts if v.gate == "ollama")
    assert not ollama.passed
    assert needle in ollama.details_ar


@pytest.mark.parametrize(
    ("exc", "needle"),
    [
        (urllib.error.URLError("refused"), "تعذّر الوصول إلى Ollama"),
        (
            urllib.error.HTTPError("http://127.0.0.1:1/api/chat", 500, "boom", None, io.BytesIO(b"")),
            "HTTP 500",
        ),
        (TimeoutError(), "مهلة"),
    ],
)
def test_transport_failures_never_escape_as_exceptions(exc: Exception, needle: str) -> None:
    def call(payload: dict[str, Any]) -> dict[str, Any]:
        raise exc

    brain = OllamaBrain(model="m", host="http://127.0.0.1:1", transport=call)
    proposal = GatedBrain(brain).propose(CLEAN_GOAL)
    assert not proposal.accepted
    ollama = next(v for v in proposal.verdicts if v.gate == "ollama")
    assert not ollama.passed
    assert needle in ollama.details_ar


def test_empty_model_name_rejected_at_construction() -> None:
    with pytest.raises(ValueError):
        OllamaBrain(model="   ")


def test_host_resolution_env_then_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZYKO_OLLAMA_HOST", "http://10.1.2.3:11434/")
    assert OllamaBrain(model="m").host == "http://10.1.2.3:11434"
    assert OllamaBrain(model="m", host="http://127.0.0.1:9").host == "http://127.0.0.1:9"


def test_extract_content_strips_and_requires_text() -> None:
    assert extract_content({"message": {"content": "  نص  "}}) == "نص"
    with pytest.raises(KeyError):
        extract_content({})
    with pytest.raises(TypeError):
        extract_content({"message": {"content": None}})


# ============================================================ خادم Ollama وهمي
class _FakeOllamaHandler(BaseHTTPRequestHandler):
    """محاكي Ollama: ‎/api/tags للفهرسة و‎/api/chat للمحادثة."""

    def log_message(self, *args: object) -> None:  # صمت تام
        pass

    def _send(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/tags":
            body = json.dumps(
                {"models": [{"name": "qwen2.5:7b"}, {"name": "phi3:mini"}]}
            ).encode("utf-8")
            self._send(200, body)
        else:
            self._send(404, b"{}")

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        if self.path != "/api/chat":
            self._send(404, b"{}")
            return
        model = json.loads(raw.decode("utf-8")).get("model", "")
        if model == "boom-model":
            self._send(500, json.dumps({"error": "انفجار نموذج"}).encode("utf-8"))
            return
        self._send(200, json.dumps({"message": {"content": PLAN_CLEAN + "\n\n"}}).encode("utf-8"))


@pytest.fixture()
def ollama_server() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllamaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_real_http_roundtrip_clean_plan_accepted(ollama_server: str) -> None:
    brain = OllamaBrain(model="qwen2.5:7b", host=ollama_server, timeout=5.0)
    proposal = GatedBrain(brain).propose(CLEAN_GOAL)
    assert proposal.accepted
    assert proposal.text == PLAN_CLEAN


def test_real_http_roundtrip_http500_rejected(ollama_server: str) -> None:
    brain = OllamaBrain(model="boom-model", host=ollama_server, timeout=5.0)
    proposal = GatedBrain(brain).propose(CLEAN_GOAL)
    assert not proposal.accepted
    ollama = next(v for v in proposal.verdicts if v.gate == "ollama")
    assert "HTTP 500" in ollama.details_ar


def test_list_models_via_mock_server(ollama_server: str) -> None:
    assert list_models(ollama_server) == ("qwen2.5:7b", "phi3:mini")


def _closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_connection_refused_becomes_arabic_verdict() -> None:
    port = _closed_port()
    brain = OllamaBrain(model="m", host=f"http://127.0.0.1:{port}", timeout=2.0)
    proposal = GatedBrain(brain).propose(CLEAN_GOAL)
    assert not proposal.accepted
    ollama = next(v for v in proposal.verdicts if v.gate == "ollama")
    assert f"127.0.0.1:{port}" in ollama.details_ar
    assert "تعذّر الوصول" in ollama.details_ar


# ============================================================ الجلسة الكاملة
def test_session_with_ollama_brain_clean_accepted(tmp_path: Path) -> None:
    brain = GatedBrain(OllamaBrain(model="m2", transport=_fake_transport(
        {"message": {"content": PLAN_CLEAN}}
    )))
    receipt = AISession(brain=brain).run(CLEAN_GOAL, tmp_path / "proj")
    assert receipt.ok
    assert receipt.brain == "gated:ollama:m2"
    assert receipt.brain_deterministic is False
    assert receipt.plan is not None and receipt.plan["text"] == PLAN_CLEAN
    assert receipt.steps[0].step == "plan" and receipt.steps[0].ok


def test_session_with_ollama_brain_suspicious_rejected_before_any_write(tmp_path: Path) -> None:
    dirty = get_scenario("suspicious").render(CLEAN_GOAL)
    brain = GatedBrain(OllamaBrain(model="m", transport=_fake_transport(
        {"message": {"content": dirty}}
    )))
    receipt = AISession(brain=brain).run(CLEAN_GOAL, tmp_path / "proj")
    assert not receipt.ok
    assert receipt.failed_step == "plan"
    assert "phone" in receipt.steps[0].details_ar
    assert not (tmp_path / "proj").exists()  # الرفض قبل كتابة بايت واحد


def test_session_ollama_receipt_is_byte_deterministic(tmp_path: Path) -> None:
    brain = GatedBrain(OllamaBrain(model="m3", transport=_fake_transport(
        {"message": {"content": PLAN_CLEAN}}
    )))
    r1 = AISession(brain=brain).run(CLEAN_GOAL, tmp_path / "a" / "proj")
    r2 = AISession(brain=brain).run(CLEAN_GOAL, tmp_path / "b" / "proj")
    assert r1.to_json() == r2.to_json()


# ============================================================ سطر الأوامر
def test_cli_run_brain_ollama_requires_model(capsys: pytest.CaptureFixture[str]) -> None:
    rc = ai_main(["run", "--brain", "ollama", "--goal", CLEAN_GOAL, "--out", "/tmp/x"])
    assert rc == 2
    assert "--model" in capsys.readouterr().err


def test_cli_run_brain_ollama_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from zyko.ai import ollama_brain as ob

    monkeypatch.setattr(ob, "_http_transport", lambda host, timeout: _fake_transport(
        {"message": {"content": PLAN_CLEAN}}
    ))
    rc = ai_main(
        [
            "run",
            "--brain",
            "ollama",
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
    assert payload["brain"] == "gated:ollama:fake-model"
    assert payload["brain_deterministic"] is False
    assert payload["plan"]["text"] == PLAN_CLEAN


def test_cli_ollama_status_available(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from zyko.ai import ollama_brain as ob

    monkeypatch.setattr(ob, "list_models", lambda host: ("qwen2.5:7b", "phi3:mini"))
    rc = ai_main(["ollama", "--ollama-host", "http://127.0.0.1:11434"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "متاح" in out
    assert "qwen2.5:7b" in out


def test_cli_ollama_status_unavailable(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from zyko.ai import ollama_brain as ob

    def boom(host: str) -> tuple[str, ...]:
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(ob, "list_models", boom)
    rc = ai_main(["ollama"])
    assert rc == 1
    assert "غير متاح" in capsys.readouterr().out


def test_map_documents_the_ollama_brain(capsys: pytest.CaptureFixture[str]) -> None:
    assert ai_main(["map"]) == 0
    out = capsys.readouterr().out
    assert "--brain ollama" in out
    assert "ollama:" in out or "ollama " in out
