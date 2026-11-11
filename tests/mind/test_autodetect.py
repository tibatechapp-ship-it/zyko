"""اختبارات الاكتشاف التلقائي للقلب — بلا بيئة حقيقية وبلا شبكة إطلاقًا.

عقد الاختبار: كل قرار ``select_core`` يُبنى من بيئة مُحقنة (``getenv``)
وفحص مُحقن (``probe``) — لا اختبار يقرأ ``os.environ`` الحقيقي ولا
يفتح مقبسًا. والعقد الحاكم نفسه: القرار موثق في الإيصال بلا أي قيمة
مفتاح، والتجاوز الصريح يغلب الكشف، وغياب كل شيء يعيد الحتمي.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from zyko.mind.autodetect import (
    CLOUD_CANDIDATES,
    CORE_ENV,
    MODEL_ENV,
    OLLAMA_MODEL_ENV,
    select_core,
)
from zyko.mind.cli import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, handle_mind, register_to
from zyko.mind.core import BrainCore, DeterministicCore
from zyko.mind.loop import MindLoop


# ------------------------------------------------------------- حقن الاختبار
def _getenv(env: dict[str, str]):
    """بيئة مُحقنة من جدول — لا لمس للبيئة الحقيقية."""
    return env.get


def _probe_models(*models: str):
    """فحص مُحقن ناجح: الخادم «يعمل» بالقائمة المعطاة."""

    def probe(_host: str) -> tuple[str, ...]:
        return tuple(models)

    return probe


def _probe_down():
    """فحص مُحقن فاشل: الخادم «لا يستجيب»."""

    def probe(_host: str) -> tuple[str, ...]:
        raise ConnectionError("connection refused")

    return probe


def _probe_forbidden():
    """فحص يفشل الاختبار إن قُبل — لإثبات عدم فحص Ollama عند فوز سحابي."""

    def probe(_host: str) -> tuple[str, ...]:
        raise AssertionError("لا يُفحص Ollama عندما يفوز مفتاح سحابي")

    return probe


GOAL = "انشئ مشروع قائمة مهام مع واجهة سطر أوامر"


# ------------------------------------------------------------- الترتيب الموثق
class TestDocumentedOrder:
    def test_cloud_table_order_is_the_contract(self):
        """ترتيب الجدول نفسه عقد: أول مفتاح متاح يفوز — تغييره يكسر الاختبار."""
        assert [c[0] for c in CLOUD_CANDIDATES] == [
            "qwen",
            "openai",
            "anthropic",
            "deepseek",
            "groq",
            "mistral",
            "together",
            "openrouter",
        ]

    def test_candidates_cover_all_clouds_plus_ollama(self):
        decision = select_core(getenv=_getenv({}), probe=_probe_down())
        labels = [c.label for c in decision.candidates]
        assert labels == [c[0] for c in CLOUD_CANDIDATES] + ["ollama"]

    def test_precedence_qwen_before_openai(self):
        decision = select_core(
            getenv=_getenv({"ZYKO_QWEN_API_KEY": "k1", "OPENAI_API_KEY": "k2"}),
            probe=_probe_forbidden(),
        )
        assert decision.selected == "qwen"
        assert decision.candidates[0].available is True
        assert decision.candidates[1].label == "openai"

    def test_precedence_deepseek_before_groq(self):
        decision = select_core(
            getenv=_getenv({"GROQ_API_KEY": "g", "DEEPSEEK_API_KEY": "d"}),
            probe=_probe_forbidden(),
        )
        assert decision.selected == "deepseek"


# ------------------------------------------------------------- الرجوع الحتمي
class TestDeterministicFallback:
    def test_no_keys_no_ollama_yields_deterministic(self):
        decision = select_core(getenv=_getenv({}), probe=_probe_down())
        assert decision.mode == "auto"
        assert decision.selected == "deterministic"
        assert isinstance(decision.core, DeterministicCore)
        assert decision.core.deterministic is True
        assert "لا مفاتيح" in decision.reason_ar

    def test_empty_key_value_counts_as_missing(self):
        decision = select_core(getenv=_getenv({"OPENAI_API_KEY": ""}), probe=_probe_down())
        assert decision.selected == "deterministic"

    def test_ollama_without_models_is_skipped(self):
        decision = select_core(getenv=_getenv({}), probe=_probe_models())
        assert decision.selected == "deterministic"
        ollama = decision.candidates[-1]
        assert ollama.available is False
        assert "بلا نماذج" in ollama.detail_ar

    def test_auto_mode_never_raises(self):
        """حتى بيئة عدائية (قيم غريبة) تُنتج قرارًا حتميًا لا استثناء."""
        decision = select_core(
            getenv=_getenv({CORE_ENV: "   ", MODEL_ENV: "  ", "OPENAI_API_KEY": None}),
            probe=_probe_down(),
        )
        assert decision.selected in ("deterministic", "openai")


# ------------------------------------------------------------- فوز السحاب
class TestCloudAutoSelection:
    def test_qwen_key_builds_gated_qwen_core(self):
        decision = select_core(getenv=_getenv({"ZYKO_QWEN_API_KEY": "k"}), probe=_probe_forbidden())
        assert decision.selected == "qwen"
        assert decision.mode == "auto"
        assert isinstance(decision.core, BrainCore)
        assert decision.core.name == "core:gated:qwen:qwen-plus"
        assert decision.core.deterministic is False

    def test_openai_key_uses_documented_host_and_model(self):
        decision = select_core(getenv=_getenv({"OPENAI_API_KEY": "k"}), probe=_probe_forbidden())
        assert decision.selected == "openai"
        assert decision.core.name == "core:gated:qwen:gpt-4o-mini"
        qwen = decision.core._brain._brain
        assert qwen.host == "https://api.openai.com/v1"

    def test_anthropic_key_uses_compat_host(self):
        decision = select_core(getenv=_getenv({"ANTHROPIC_API_KEY": "k"}), probe=_probe_forbidden())
        assert decision.selected == "anthropic"
        qwen = decision.core._brain._brain
        assert qwen.host == "https://api.anthropic.com/v1"
        assert qwen.model == "claude-sonnet-4-20250514"

    def test_model_env_overrides_default(self):
        decision = select_core(
            getenv=_getenv({"OPENAI_API_KEY": "k", MODEL_ENV: "gpt-5-mini"}),
            probe=_probe_forbidden(),
        )
        assert decision.core.name == "core:gated:qwen:gpt-5-mini"

    def test_host_env_overrides_default(self):
        decision = select_core(
            getenv=_getenv(
                {"OPENAI_API_KEY": "k", "ZYKO_MIND_OPENAI_HOST": "https://proxy.example/v1"}
            ),
            probe=_probe_forbidden(),
        )
        assert decision.core._brain._brain.host == "https://proxy.example/v1"

    def test_model_kwarg_beats_model_env(self):
        decision = select_core(
            model="qwen-max",
            getenv=_getenv({"ZYKO_QWEN_API_KEY": "k", MODEL_ENV: "qwen-plus"}),
            probe=_probe_forbidden(),
        )
        assert decision.core.name == "core:gated:qwen:qwen-max"

    def test_ollama_not_probed_when_cloud_key_wins(self):
        decision = select_core(getenv=_getenv({"ZYKO_QWEN_API_KEY": "k"}), probe=_probe_forbidden())
        ollama = decision.candidates[-1]
        assert ollama.available is False
        assert "لم يُفحص" in ollama.detail_ar


# ------------------------------------------------------------- فوز المحلي
class TestOllamaAutoSelection:
    def test_reachable_ollama_wins_without_keys(self):
        decision = select_core(getenv=_getenv({}), probe=_probe_models("qwen2.5:7b", "llama3.2"))
        assert decision.selected == "ollama"
        assert isinstance(decision.core, BrainCore)
        assert decision.core.name == "core:gated:ollama:qwen2.5:7b"
        assert "qwen2.5:7b" in decision.reason_ar

    def test_first_listed_model_is_the_choice(self):
        decision = select_core(getenv=_getenv({}), probe=_probe_models("a:1", "b:2"))
        assert decision.core.name.endswith("gated:ollama:a:1")

    def test_ollama_model_env_overrides_first(self):
        decision = select_core(
            getenv=_getenv({OLLAMA_MODEL_ENV: "qwen3:4b"}), probe=_probe_models("a:1")
        )
        assert decision.core.name.endswith("gated:ollama:qwen3:4b")

    def test_ollama_host_env_is_respected(self):
        decision = select_core(
            getenv=_getenv({"ZYKO_OLLAMA_HOST": "http://192.168.1.7:11434"}),
            probe=_probe_models("m:1"),
        )
        assert decision.candidates[-1].env == "ollama:http://192.168.1.7:11434"
        assert "192.168.1.7" in decision.reason_ar


# ------------------------------------------------------------- التجاوز الصريح
class TestExplicitOverride:
    def test_explicit_deterministic_beats_keys(self):
        decision = select_core(
            explicit="deterministic",
            getenv=_getenv({"OPENAI_API_KEY": "k"}),
            probe=_probe_forbidden(),
        )
        assert decision.mode == "explicit"
        assert decision.selected == "deterministic"
        assert isinstance(decision.core, DeterministicCore)

    def test_explicit_cloud_without_key_still_builds(self):
        """النية الصريحة لا تمنع البناء — الرفض يوثّق نفسه عند بوابة الخطة."""
        decision = select_core(explicit="qwen", getenv=_getenv({}), probe=_probe_down())
        assert decision.mode == "explicit"
        assert decision.selected == "qwen"
        assert isinstance(decision.core, BrainCore)
        assert decision.core.name == "core:gated:qwen:qwen-plus"

    def test_explicit_qwen_without_key_rejects_without_network(self):
        decision = select_core(explicit="qwen", getenv=_getenv({}), probe=_probe_down())
        text = decision.core.respond(GOAL)
        assert text == ""
        assert any(not v.passed for v in decision.core.last_verdicts)

    def test_explicit_ollama_with_model_kwarg(self):
        decision = select_core(
            explicit="ollama", model="qwen3:8b", getenv=_getenv({}), probe=_probe_down()
        )
        assert decision.mode == "explicit"
        assert decision.core.name == "core:gated:ollama:qwen3:8b"

    def test_explicit_ollama_discovers_model_from_probe(self):
        decision = select_core(explicit="ollama", getenv=_getenv({}), probe=_probe_models("m:9"))
        assert decision.core.name.endswith("gated:ollama:m:9")

    def test_explicit_ollama_without_model_and_down_server_raises_arabic(self):
        with pytest.raises(ValueError, match="يتطلب نموذجًا"):
            select_core(explicit="ollama", getenv=_getenv({}), probe=_probe_down())

    def test_explicit_ollama_without_model_and_empty_server_raises(self):
        with pytest.raises(ValueError, match="بلا نماذج"):
            select_core(explicit="ollama", getenv=_getenv({}), probe=_probe_models())

    def test_explicit_unknown_label_raises_listing_choices(self):
        with pytest.raises(ValueError, match="قلب غير معروف"):
            select_core(explicit="hal9k", getenv=_getenv({}), probe=_probe_down())

    def test_explicit_auto_means_scan(self):
        decision = select_core(
            explicit="auto", getenv=_getenv({"OPENAI_API_KEY": "k"}), probe=_probe_forbidden()
        )
        assert decision.mode == "auto" and decision.selected == "openai"

    def test_explicit_is_case_and_space_tolerant(self):
        decision = select_core(explicit="  QWEN  ", getenv=_getenv({}), probe=_probe_down())
        assert decision.selected == "qwen"

    def test_env_override_via_zyko_mind_core(self):
        decision = select_core(
            getenv=_getenv({CORE_ENV: "deterministic", "OPENAI_API_KEY": "k"}),
            probe=_probe_forbidden(),
        )
        assert decision.mode == "explicit"
        assert decision.selected == "deterministic"

    def test_cli_explicit_beats_env_override(self):
        decision = select_core(
            explicit="openai",
            getenv=_getenv({CORE_ENV: "deterministic"}),
            probe=_probe_down(),
        )
        assert decision.selected == "openai"


# ------------------------------------------------------------- الأسرار
class TestNoSecretsInDecision:
    KEY = "sk-super-secret-value-000"

    def test_decision_dict_never_carries_key_values(self):
        decision = select_core(
            getenv=_getenv({"OPENAI_API_KEY": self.KEY}), probe=_probe_forbidden()
        )
        blob = json.dumps(decision.to_dict(), ensure_ascii=False)
        assert self.KEY not in blob
        assert "OPENAI_API_KEY" in blob  # الاسم يوثّق، والقيمة لا تُسجَّل أبدًا

    def test_candidate_env_holds_names_only(self):
        decision = select_core(getenv=_getenv({}), probe=_probe_down())
        for c in decision.candidates:
            assert c.env.startswith(
                (
                    "ZYKO_",
                    "OPENAI_",
                    "ANTHROPIC_",
                    "DEEPSEEK_",
                    "GROQ_",
                    "MISTRAL_",
                    "TOGETHER_",
                    "OPENROUTER_",
                    "ollama:",
                )
            )

    def test_decision_dict_shape_is_stable(self):
        decision = select_core(getenv=_getenv({}), probe=_probe_down())
        blob = decision.to_dict()
        assert set(blob) == {"mode", "selected", "reason_ar", "candidates"}
        assert set(blob["candidates"][0]) == {"label", "env", "available", "detail_ar"}


# ------------------------------------------------------------- الإيصال
class TestReceiptIntegration:
    def test_decision_lands_in_receipt_and_json(self, tmp_path):
        decision = select_core(getenv=_getenv({}), probe=_probe_down())
        receipt = MindLoop(decision.core, core_decision=decision).run(GOAL, tmp_path / "p")
        assert receipt.core_decision == decision.to_dict()
        payload = json.loads(receipt.to_json())
        assert payload["core_decision"]["selected"] == "deterministic"
        assert payload["core_decision"]["mode"] == "auto"

    def test_decision_is_part_of_chain_hash(self, tmp_path):
        base = {"mode": "auto", "selected": "deterministic", "reason_ar": "", "candidates": []}
        r1 = MindLoop(DeterministicCore(), core_decision={**base, "reason_ar": "سبب أ"}).run(
            GOAL, tmp_path / "a"
        )
        r2 = MindLoop(DeterministicCore(), core_decision={**base, "reason_ar": "سبب ب"}).run(
            GOAL, tmp_path / "b"
        )
        assert r1.chain_hash != r2.chain_hash

    def test_default_loop_has_empty_decision(self, tmp_path):
        receipt = MindLoop().run(GOAL, tmp_path / "p")
        assert receipt.core_decision == {}
        assert "قرار القلب" not in receipt.to_md()

    def test_md_receipt_documents_the_decision(self, tmp_path):
        decision = select_core(getenv=_getenv({}), probe=_probe_down())
        receipt = MindLoop(decision.core, core_decision=decision).run(GOAL, tmp_path / "p")
        md = receipt.to_md()
        assert "قرار القلب: deterministic (auto)" in md


# ------------------------------------------------------------- سطر الأوامر
class _Args:
    def __init__(self, **kw: Any) -> None:
        self.mind_cmd = kw.get("mind_cmd", "run")
        self.goal = kw.get("goal", GOAL)
        self.out = kw.get("out", "جديد")
        self.rounds = kw.get("rounds", 2)
        self.fail_under = kw.get("fail_under", 75)
        self.dry_run = kw.get("dry_run", False)
        self.json = kw.get("json", False)
        self.brain = kw.get("brain", "auto")
        self.model = kw.get("model", None)


class TestCli:
    def test_explicit_deterministic_prints_the_choice(self, tmp_path, capsys):
        args = _Args(out=str(tmp_path / "p"), brain="deterministic")
        assert handle_mind(args) == EXIT_OK
        out = capsys.readouterr().out
        assert "القلب المُختار: deterministic (explicit)" in out

    def test_auto_fallback_prints_deterministic_choice(self, tmp_path, capsys, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ZYKO_MIND_CORE", raising=False)
        monkeypatch.setattr("zyko.mind.autodetect.default_probe", _probe_down())
        args = _Args(out=str(tmp_path / "p"))
        assert handle_mind(args) == EXIT_OK
        out = capsys.readouterr().out
        assert "القلب المُختار: deterministic (auto)" in out
        assert "لا مفاتيح" in out

    def test_explicit_qwen_without_key_runs_and_documents_rejection(self, tmp_path, capsys):
        """بلا مفتاح: القلب يُبنى، والاقتراح يُرفض عند بوابة الخطة بلا شبكة."""
        args = _Args(out=str(tmp_path / "p"), brain="qwen")
        assert handle_mind(args) == EXIT_FINDINGS
        out = capsys.readouterr().out
        assert "القلب المُختار: qwen (explicit)" in out
        assert "مفتاح Qwen مطلوب" in out

    def test_explicit_qwen_json_receipt_carries_decision(self, tmp_path, capsys):
        args = _Args(out=str(tmp_path / "p"), brain="qwen", json=True)
        assert handle_mind(args) == EXIT_FINDINGS
        payload = json.loads(capsys.readouterr().out)
        assert payload["core_decision"]["selected"] == "qwen"

    def test_explicit_ollama_without_model_is_usage_error(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr("zyko.mind.autodetect.default_probe", _probe_down())
        args = _Args(out=str(tmp_path / "p"), brain="ollama")
        assert handle_mind(args) == EXIT_USAGE
        assert "يتطلب نموذجًا" in capsys.readouterr().err

    def test_parser_rejects_unknown_brain(self):
        parser = argparse.ArgumentParser(prog="zyko mind")
        register_to(parser.add_subparsers(dest="mind_cmd"))
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["run", GOAL, "-o", "جديد", "--brain", "hal9k"])
        assert exc.value.code == 2

    def test_parser_accepts_all_documented_choices(self):
        parser = argparse.ArgumentParser(prog="zyko mind")
        register_to(parser.add_subparsers(dest="mind_cmd"))
        argv = [
            "run",
            GOAL,
            "-o",
            "جديد",
            "--brain",
            "anthropic",
            "--model",
            "claude-sonnet-4-20250514",
        ]
        args = parser.parse_args(argv)
        assert args.brain == "anthropic" and args.model == "claude-sonnet-4-20250514"
