"""Offline receipt verification: `zyko verify` and its reusable core."""

from __future__ import annotations

import copy
import json

import pytest

from tests.fakes import FakeProvider
from zyko.cli import main
from zyko.core.messages import Message
from zyko.core.response import ChatRequest
from zyko.exceptions import ConfigError
from zyko.router.engine import Router
from zyko.router.quality import QualityLedger
from zyko.router.verify import load_receipt, verify_receipt


def _receipt(**router_kw) -> dict:
    router = Router({"fake": FakeProvider()}, **router_kw)
    result = router.route(ChatRequest(messages=[Message.user("hello")]))
    assert result.receipt
    return result.receipt


def _codes(report) -> set[str]:
    return {issue.code for issue in report.issues}


# ------------------------------------------------------------------ happy path
def test_fresh_receipt_verifies_without_a_ledger():
    report = verify_receipt(_receipt())
    assert report.ok, [i.message for i in report.issues]
    assert report.checks >= 6
    assert report.strategy == "balanced"
    assert report.chosen in {row["candidate"] for row in _receipt()["ranking"]}
    assert report.total is not None and 0.0 <= report.total <= 1.0


def test_receipt_verifies_against_the_ledger_that_produced_it():
    ledger = QualityLedger.empty()
    ledger.update("fake", "fake-small", quality=0.8, samples=10)
    ledger.update("fake", "fake-large", quality=0.6, samples=10)
    receipt = _receipt(ledger=ledger, strategy="quality")
    report = verify_receipt(receipt, ledger=ledger)
    assert report.ok, [i.message for i in report.issues]


# ------------------------------------------------------------- tampering cases
def test_tampered_total_is_caught():
    receipt = _receipt()
    receipt["ranking"][0]["total"] = receipt["ranking"][0]["total"] + 0.25
    report = verify_receipt(receipt)
    assert not report.ok
    assert "total-mismatch" in _codes(report)


def test_invented_weights_are_caught():
    receipt = _receipt()
    receipt["score_components"]["weights"] = {"quality": 0.9, "cost": 0.05, "latency": 0.05}
    report = verify_receipt(receipt)
    assert not report.ok
    assert "weights-mismatch" in _codes(report)


def test_quality_drift_against_supplied_ledger_is_caught():
    receipt = _receipt()
    inflated = QualityLedger({"scores": {"fake/fake-small": {"quality": 0.99}}, "updated": None})
    report = verify_receipt(receipt, ledger=inflated)
    assert not report.ok
    assert "quality-drift" in _codes(report)


def test_consistent_forgery_is_caught_by_the_ledger_check():
    """Raising quality and total together keeps the arithmetic valid.

    Only the ledger cross-check can catch that — which is exactly why
    `--ledger` exists.
    """
    ledger = QualityLedger.empty()
    ledger.update("fake", "fake-small", quality=0.5, samples=5)
    receipt = _receipt(ledger=ledger)
    row = receipt["ranking"][0]
    row["quality"] = 0.99
    row["total"] = round(
        row["weights"]["quality"] * 0.99
        + row["weights"]["cost"] * row["cost_score"]
        + row["weights"]["latency"] * row["latency_score"],
        4,
    )
    assert verify_receipt(receipt).ok  # self-consistent...
    report = verify_receipt(receipt, ledger=ledger)
    assert not report.ok and "quality-drift" in _codes(report)


def test_ledger_stamp_mismatch_is_caught():
    ledger = QualityLedger.empty()
    receipt = _receipt(ledger=ledger)
    receipt["ledger_updated"] = 123.0  # claims a different ledger generation
    other = QualityLedger({"scores": {}, "updated": 456.0})
    report = verify_receipt(receipt, ledger=other)
    assert "ledger-mismatch" in _codes(report)


def test_out_of_range_component_is_caught():
    receipt = _receipt()
    receipt["score_components"]["quality"] = 1.4
    receipt["score_components"]["total"] = (
        receipt["score_components"]["weights"]["quality"] * 1.4
        + receipt["score_components"]["weights"]["cost"] * receipt["score_components"]["cost_score"]
        + receipt["score_components"]["weights"]["latency"]
        * receipt["score_components"]["latency_score"]
    )
    report = verify_receipt(receipt)
    assert "component-out-of-range" in _codes(report)


def test_unsorted_ranking_is_caught():
    receipt = _receipt()
    receipt["ranking"] = list(reversed(receipt["ranking"]))
    report = verify_receipt(receipt)
    assert "ranking-order" in _codes(report)


def test_unknown_version_and_strategy_are_rejected():
    receipt = _receipt()
    receipt["receipt_version"] = 99
    assert "unsupported-version" in _codes(verify_receipt(receipt))

    receipt = _receipt()
    receipt["strategy"] = "vibes"
    assert "unknown-strategy" in _codes(verify_receipt(receipt))


def test_malformed_receipts_never_raise():
    assert not verify_receipt({}).ok
    assert not verify_receipt({"receipt_version": 1, "strategy": "balanced"}).ok
    assert not verify_receipt(
        {"receipt_version": 1, "strategy": "balanced", "score_components": {}}
    ).ok


# ------------------------------------------------------------------------ CLI
def test_cli_verify_exit_codes_and_json(tmp_path, capsys):
    receipt = _receipt()
    good = tmp_path / "receipt.json"
    good.write_text(json.dumps(receipt), encoding="utf-8")

    assert main(["verify", str(good)]) == 0
    assert "verified" in capsys.readouterr().out

    assert main(["verify", str(good), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True and payload["checks"] >= 6

    bad = copy.deepcopy(receipt)
    bad["score_components"]["total"] = 0.999
    bad_file = tmp_path / "bad.json"
    bad_file.write_text(json.dumps(bad), encoding="utf-8")
    assert main(["verify", str(bad_file)]) == 1
    assert "INVALID" in capsys.readouterr().out
    assert main(["verify", str(bad_file), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_load_receipt_reports_missing_file_with_a_hint(tmp_path):
    with pytest.raises(ConfigError) as excinfo:
        load_receipt(tmp_path / "nope.json")
    assert "receipt" in str(excinfo.value)

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_receipt(broken)

    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_receipt(array)
