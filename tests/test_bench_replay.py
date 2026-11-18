"""اختبارات قاعة إعادة الحكم (الموجة 30).

العقد: أي إيصال يُعاد حكمه بأمر واحد — أربع طبقات تحقق حتمية:
(1) بصمة الوثيقة تُعاد من بايتاتها نفسها، (2) مشتقات الحكم
(resolved_strict/resolved_env/f2p_repaired_count) تُعاد من الحقول
الخام فتُكشف الكذبة داخل ظرف موقَّع، (3) التدقيق الثماني القواعد
يُعاد على نص الرقعة المؤرشف فيُكشف الرقعة المسمومة التي عداها العدّ،
(4) العدّ يُعاد من المحاولات فيُكشف تلاعب الخلاصة. وما لا يمكن
إعادة حكمه (إيصالات ما قبل 0.52.0 بلا نصوص رقع) يُوثَّق بالاسم
لا يُخفى، والشكل القديم يُعاد حكمه بما يملكه لا بما يتمناه.

بلا شبكة وبلا مفتاح: إيصالات مُصنَّعة بالبياناتكلاسات نفسها التي
كتبت الإيصالات الحية، وgit حقيقي على مستودع مصغّر للبوابة الثابتة —
حتمي بالبايت على أي جهاز.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from zyko.benchmarks.replay import replay_file, replay_receipt, run_replay
from zyko.benchmarks.runner import chain_hash_of
from zyko.benchmarks.swebench import (
    SWEAttempt,
    SWEVerdict,
    aggregate,
    audit_patch_text,
)

# ---------------------------------------------------------------- القوالب
CLEAN_SRC = """def add(a, b):
    total = a + b
    return total


def div(a, b):
    if b == 0:
        raise ValueError("قسمة على صفر")
    return a // b
"""

CLEAN_PATCH = """--- a/calc.py
+++ b/calc.py
@@ -1,6 +1,7 @@
 def add(a, b):
     total = a + b
     return total
+    # تعديل مشروع بلا ملاحظات


 def div(a, b):
"""

BROKEN_PATCH = """--- a/calc.py
+++ b/calc.py
@@ -1,6 +1,8 @@
 def add(a, b):
     total = a + b
     return total
+def broken(:
+    pass


 def div(a, b):
"""

POISON_PATCH = """--- a/calc.py
+++ b/calc.py
@@ -1,6 +1,8 @@
 def add(a, b):
     total = a + b
     return total
+token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234"


 def div(a, b):
"""

LEGACY_ATTEMPT_KEYS = (
    "index",
    "feedback_sha16",
    "file_choice",
    "patch_sha16",
    "accepted",
    "contract_reason_ar",
    "applied",
    "apply_error_ar",
    "stop_reason_ar",
    "apply_mode",
    "reverted",
)


# ---------------------------------------------------------------- البناء
def _verdict(**over) -> SWEVerdict:
    """حكم نظيف كامل: رقعة طُبِّقت وأصلحت عقدة F2P الواحدة."""
    base: dict = {
        "instance_id": "psf__requests-0001",
        "patch_applied": True,
        "apply_error_ar": None,
        "f2p_failed_at_base": ("tests/test_calc.py::test_div",),
        "p2p_failed_at_base": (),
        "f2p_passed_after": ("tests/test_calc.py::test_div",),
        "f2p_failed_after": (),
        "p2p_failed_after": (),
        "runs_error_ar": None,
        "patch_sha16": "a" * 16,
        "contract_reason_ar": "أساس نظيف",
        "attempts_note_ar": "طُبِّقت وقِيست",
    }
    base.update(over)
    return SWEVerdict(**base)


def _attempt(v: SWEVerdict, *, text: str = "", audit: dict | None = None) -> SWEAttempt:
    return SWEAttempt(
        instance_id=v.instance_id,
        file_choice="calc.py",
        choice_reply_sha16="b" * 16,
        diff_reply_sha16="c" * 16,
        proposal_accepted=True,
        verdict=v,
        patch_audit=audit if audit is not None else {},
        patch_text=text,
    )


def _legacy_attempt(index: int) -> dict:
    """محاولة الشكل القديم (قبل 0.51.0) — مسطّحة بلا حكم وبلا نص."""
    return {
        "index": index,
        "feedback_sha16": "f" * 16,
        "file_choice": "calc.py",
        "patch_sha16": "a" * 16,
        "accepted": True,
        "contract_reason_ar": None,
        "applied": True,
        "apply_error_ar": None,
        "stop_reason_ar": "نهاية الحلقة",
        "apply_mode": "git apply",
        "reverted": False,
    }


def _result(instance_id: str, attempts: tuple[SWEAttempt, ...], *, legacy: bool = False) -> dict:
    """نتيجة حالة واحدة بالشكلين: الجديد بأحكام لكل محاولة، والقديم بحكم نهائي."""
    if legacy:
        loop: dict = {
            "instance_id": instance_id,
            "attempts": [_legacy_attempt(i) for i in range(len(attempts))],
            "verdict": attempts[-1].verdict.to_dict(),
            "file_choices": ["calc.py" for _ in attempts],
            "note_ar": "",
        }
    else:
        loop = {
            "instance_id": instance_id,
            "attempts": [a.to_dict() for a in attempts],
            "verdict": attempts[-1].verdict.to_dict(),
            "file_choices": [a.file_choice for a in attempts],
            "note_ar": "",
        }
    loop["chain_hash"] = chain_hash_of(loop)
    return {"instance_id": instance_id, "base": "خامة", "prep_error_ar": None, "loop": loop}


def _receipt(results: list[dict], attempts_all: tuple[SWEAttempt, ...]) -> dict:
    """إيصال كامل بالبنية نفسها التي تكتبها تشغيلات 0.51+."""
    agg = aggregate(attempts_all).to_dict()
    agg["planned_total"] = len(results)
    doc: dict = {
        "protocol": "قاعة الاختبار — إيصال مُصنَّع حتمي",
        "data": {"repo": "psf/requests", "sample": 2},
        "aggregate": agg,
        "results": results,
    }
    doc["chain_hash"] = chain_hash_of(doc)
    return doc


def _clean_world() -> tuple[dict, tuple[SWEAttempt, ...]]:
    """إيصال نظيف من حالتين بالشكل الجديد: الأولى تُصلح والثانية تفشل."""
    good = _verdict(instance_id="psf__requests-0001")
    bad = _verdict(
        instance_id="psf__requests-0002",
        patch_sha16="d" * 16,
        f2p_passed_after=(),
        f2p_failed_after=("tests/test_calc.py::test_div",),
        attempts_note_ar="طُبِّقت وفشلت",
    )
    a1 = _attempt(good, text=CLEAN_PATCH, audit=audit_patch_text(CLEAN_PATCH).to_dict())
    a2 = _attempt(bad, text=CLEAN_PATCH, audit=audit_patch_text(CLEAN_PATCH).to_dict())
    attempts = (a1, a2)
    results = [
        _result("psf__requests-0001", (a1,)),
        _result("psf__requests-0002", (a2,)),
    ]
    return _receipt(results, attempts), attempts


def _gate_repo(tmp_path: Path) -> Path:
    """مستودع مصغّر بملف نظيف ملتزم — الأساس الذي تقيس عليه البوابة."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "calc.py").write_text(CLEAN_SRC, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


# ------------------------------------------------------- الطبقة 1: البصمة
def test_clean_receipt_replays_clean_and_deterministic():
    receipt, _ = _clean_world()
    r1 = replay_receipt(receipt, source_label="clean")
    r2 = replay_receipt(receipt, source_label="clean")
    assert r1.doc_hash_ok is True
    assert r1.ok is True
    assert r1.audit_mismatch_total == 0
    assert r1.derivation_mismatch_total == 0
    assert r1.count_mismatches == ()
    assert r1.chain_hash == r2.chain_hash  # الحتمية بالبايت
    assert r1.recomputed_chain_hash == receipt["chain_hash"]


def test_byte_tampering_after_the_event_is_caught():
    receipt, _ = _clean_world()
    poisoned = copy.deepcopy(receipt)
    # تلاعب بعد الحدث: فشل P2P يختفي من الحكم، والبصمة القديمة تبقى كما هي
    v = poisoned["results"][0]["loop"]["attempts"][0]["verdict"]
    v["p2p_failed_after"] = ["tests/test_calc.py::test_new"]
    r = replay_receipt(poisoned, source_label="tampered")
    assert r.doc_hash_ok is False
    assert r.ok is False
    assert r.recomputed_chain_hash != r.source_chain_hash


def test_receipt_without_fingerprint_is_documented_not_guessed():
    receipt, _ = _clean_world()
    receipt.pop("chain_hash")
    r = replay_receipt(receipt, source_label="no-fp")
    assert r.doc_hash_ok is False
    assert r.ok is False
    assert "بصمة الوثيقة غائبة" in r.doc_hash_note_ar


# --------------------------------------- الطبقة 2: مشتقات الحكم تُعاد
def test_lie_inside_signed_envelope_is_caught():
    """البصمة تؤمّن البايتات لا الصدق — حكم يزعم حلًّا وحقوله تقول فشلًا."""
    receipt, _ = _clean_world()
    forged = copy.deepcopy(receipt)
    # المشتق المزوّر يزعم حلًّا صارمًا والحقول الخام تقول: عقدة F2P فاشلة
    v = forged["results"][1]["loop"]["attempts"][0]["verdict"]
    assert v["f2p_failed_after"]  # الحقول الخام: ما زالت فاشلة
    v["resolved_strict"] = True
    v["resolved_env"] = True
    # البصمة تُحسب فوق الوثيقة المزوّرة كاملة — الظرف سليم والكذبة داخله
    forged["chain_hash"] = chain_hash_of({k: x for k, x in forged.items() if k != "chain_hash"})
    r = replay_receipt(forged, source_label="forged")
    assert r.doc_hash_ok is True  # البصمة سليمة — والتلاعب مع ذلك مكتشف
    assert r.derivation_mismatch_total >= 1
    assert r.ok is False


def test_legacy_verdict_derivation_is_replayed():
    receipt, _ = _clean_world()
    legacy_results = [
        _result(
            "psf__requests-0001",
            (_attempt(_verdict(instance_id="psf__requests-0001")),),
            legacy=True,
        ),
        _result(
            "psf__requests-0002",
            (_attempt(_verdict(instance_id="psf__requests-0002")),),
            legacy=True,
        ),
    ]
    legacy_attempts = tuple(
        _attempt(_verdict(instance_id=i)) for i in ("psf__requests-0001", "psf__requests-0002")
    )
    doc = _receipt(legacy_results, legacy_attempts)
    r = replay_receipt(doc, source_label="legacy")
    assert r.rows[0].shape == "legacy"
    assert r.rows[0].derivation_mismatches == 0
    assert r.rows[0].texts_replayed == 0
    assert r.rows[0].text_absent == 1  # موثق لا مخفي
    assert r.ok is True


def test_legacy_derivation_lie_is_caught():
    good = _verdict(instance_id="psf__requests-0001")
    a = _attempt(good)
    res = _result("psf__requests-0001", (a,), legacy=True)
    v = res["loop"]["verdict"]
    v["resolved_env"] = False  # الكذبة: الحقول الخام تقول حلًّا بيئيًّا
    doc = _receipt([res], (a,))
    r = replay_receipt(doc, source_label="legacy-lie")
    assert r.rows[0].shape == "legacy"
    assert r.rows[0].derivation_mismatches == 1
    assert r.ok is False


# --------------------------------- الطبقة 3: التدقيق يُعاد على النص
def test_poisoned_patch_that_passed_counting_is_caught():
    """رقعة تحمل سرًّا دخل العدّ التاريخي بإصابة نظيفة — القاعة تكشفها."""
    receipt, _ = _clean_world()
    poisoned = copy.deepcopy(receipt)
    att = poisoned["results"][0]["loop"]["attempts"][0]
    att["patch_text"] = POISON_PATCH
    att["patch_audit"] = {"schema": "zyko.patch_audit/1", "findings": [], "finding_count": 0}
    # البصمة فوق الإيصال المسموم كله — الظرف سليم والسر داخله
    poisoned["chain_hash"] = chain_hash_of({k: x for k, x in poisoned.items() if k != "chain_hash"})
    r = replay_receipt(poisoned, source_label="poison")
    assert r.rows[0].audit_mismatches == 1
    assert r.audit_rejection_total == 1  # الحرج يُرفض في إعادة العدّ
    # العدّ المُعاد يسقط الحالة المسمومة من الحل البيئي
    assert "resolved_env" in r.count_mismatches or "resolved_strict" in r.count_mismatches
    assert r.ok is False


def test_tampered_archive_vs_text_is_caught():
    """الأرشيف يدّعي إصابة لم تقع على النص — إعادة التدقيق تنفيها."""
    receipt, _ = _clean_world()
    forged = copy.deepcopy(receipt)
    att = forged["results"][0]["loop"]["attempts"][0]
    att["patch_audit"]["findings"] = [
        {
            "rule_id": "QUA-TODO-001",
            "severity": "low",
            "file": "calc.py",
            "line_in_file": 4,
            "evidence": "مصطنع",
            "message_ar": "مصطنع",
        }
    ]
    att["patch_audit"]["finding_count"] = 1
    forged["chain_hash"] = chain_hash_of({k: x for k, x in forged.items() if k != "chain_hash"})
    r = replay_receipt(forged, source_label="ghost-finding")
    assert r.rows[0].audit_mismatches == 1
    assert r.ok is False


def test_text_absent_is_documented_not_failed():
    """إيصال ما قبل 0.52.0: بصمات بلا نصوص — لا إعادة تدقيق ممكنة، والتوثيق هو الصدق."""
    receipt, attempts = _clean_world()
    bare = copy.deepcopy(receipt)
    for res, a in zip(bare["results"], attempts):
        att = res["loop"]["attempts"][0]
        att["patch_text"] = ""
        att["patch_audit"] = {}
    bare["chain_hash"] = chain_hash_of({k: x for k, x in bare.items() if k != "chain_hash"})
    r = replay_receipt(bare, source_label="bare")
    assert r.text_absent_total == 2
    assert r.rows[0].texts_replayed == 0
    assert r.rows[0].audit_mismatches == 0
    assert r.audit_absent_total == 2
    assert r.ok is True  # لا تناقض — الغياب موثق لا مكتوم


# ------------------------------------ الطبقة 4: العدّ يُعاد من الأصل
def test_aggregate_tampering_is_caught():
    receipt, _ = _clean_world()
    forged = copy.deepcopy(receipt)
    forged["aggregate"]["resolved_strict"] = 99
    forged["chain_hash"] = chain_hash_of({k: x for k, x in forged.items() if k != "chain_hash"})
    r = replay_receipt(forged, source_label="count-lie")
    assert "resolved_strict" in r.count_mismatches
    assert r.ok is False


def test_count_replay_matches_archived_on_clean_receipt():
    receipt, _ = _clean_world()
    r = replay_receipt(receipt, source_label="clean-count")
    assert r.recomputed_aggregate["total"] == 2
    assert r.recomputed_aggregate["resolved_strict"] == 1
    assert r.recomputed_aggregate["resolved_env"] == 1
    assert r.recomputed_aggregate["f2p_repaired_total"] == 1
    assert r.recomputed_aggregate["applied_count"] == 2


def test_legacy_count_replay_sums_final_verdicts():
    good = _verdict(instance_id="psf__requests-0001")
    bad = _verdict(
        instance_id="psf__requests-0002",
        f2p_passed_after=(),
        f2p_failed_after=("tests/test_calc.py::test_div",),
    )
    a1, a2 = _attempt(good), _attempt(bad)
    doc = _receipt(
        [
            _result("psf__requests-0001", (a1,), legacy=True),
            _result("psf__requests-0002", (a2,), legacy=True),
        ],
        (a1, a2),
    )
    r = replay_receipt(doc, source_label="legacy-count")
    assert r.recomputed_aggregate["total"] == 2
    assert r.recomputed_aggregate["resolved_strict"] == 1
    assert r.recomputed_aggregate["resolved_env"] == 1


# ------------------------------ الطبقة 5: البوابة الثابتة عند الشجرة
def test_static_gate_replay_verifies_clean_patch(tmp_path):
    repo = _gate_repo(tmp_path)
    from zyko.benchmarks.swebench import apply_candidate, run_static_gate

    applied, _ = apply_candidate(repo, CLEAN_PATCH, subprocess.run)
    assert applied
    gate = run_static_gate(repo, CLEAN_PATCH, subprocess.run)
    assert gate["accepted"] is True
    # أعِد الأساس قبل القاعة — القاعة تُطبّق بنفسها وتُعيد بنفسها
    subprocess.run(["git", "checkout", "--", "calc.py"], cwd=repo, check=True)
    assert (repo / "calc.py").read_text(encoding="utf-8") == CLEAN_SRC

    good = _verdict(instance_id="psf__requests-0001")
    v = good.to_dict()
    v["static_gate"] = gate
    good = SWEVerdict(**{k: x for k, x in v.items() if k in SWEVerdict.__dataclass_fields__})
    a = _attempt(good, text=CLEAN_PATCH, audit=audit_patch_text(CLEAN_PATCH).to_dict())
    doc = _receipt([_result("psf__requests-0001", (a,))], (a,))
    r = replay_receipt(doc, workdirs={"psf__requests-0001": repo}, source_label="gate-ok")
    assert r.rows[0].static_gate_replays == 1
    assert r.rows[0].static_gate_mismatches == 0
    assert r.ok is True
    # الشجرة عادت إلى الأساس بالبايت بعد إعادة الحكم
    assert (repo / "calc.py").read_text(encoding="utf-8") == CLEAN_SRC


def test_static_gate_replay_catches_poison_acceptance(tmp_path):
    """البوابة المزوّرة زعمت قبول رقعة تكسر البنية — إعادة الحكم تنفي الزعم."""
    repo = _gate_repo(tmp_path)
    good = _verdict(instance_id="psf__requests-0001")
    v = good.to_dict()
    v["static_gate"] = {
        "schema": "zyko.static_gate/1",
        "accepted": True,
        "files_checked": ["calc.py"],
        "files_skipped": [],
        "per_file": [{"path": "calc.py", "accepted": True, "score_before": 96, "score_after": 96}],
        "reasons_ar": [],
        "patch_sha16": "a" * 16,
    }
    good = SWEVerdict(**{k: x for k, x in v.items() if k in SWEVerdict.__dataclass_fields__})
    a = _attempt(good, text=BROKEN_PATCH, audit=audit_patch_text(BROKEN_PATCH).to_dict())
    doc = _receipt([_result("psf__requests-0001", (a,))], (a,))
    r = replay_receipt(doc, workdirs={"psf__requests-0001": repo}, source_label="gate-poison")
    assert r.rows[0].static_gate_replays == 1
    assert r.rows[0].static_gate_mismatches == 1
    assert r.ok is False
    assert (repo / "calc.py").read_text(encoding="utf-8") == CLEAN_SRC


def test_static_gate_skipped_without_tree_is_documented():
    receipt, _ = _clean_world()
    r = replay_receipt(receipt, source_label="no-tree")
    assert r.static_gate_skipped_total == 2
    assert r.static_gate_replay_total == 0
    assert r.ok is True


# ------------------------------------------------------- الوثيقة وCLI
def test_report_schema_and_table_are_declared():
    receipt, _ = _clean_world()
    r = replay_receipt(receipt, source_label="schema")
    d = r.to_dict()
    assert d["schema"] == "zyko.bench_replay/1"
    assert d["source_label"] == "schema"
    assert d["doc_hash_ok"] is True
    assert r.rows[0].instance_id == "psf__requests-0001"
    table = r.table_ar()
    assert "قاعة إعادة الحكم" in table
    assert "psf__requests-0001" in table


def test_replay_file_round_trip(tmp_path):
    import hashlib

    receipt, _ = _clean_world()
    # tmp_path لا /tmp: مسار POSIX مطلق ينكسر على ويندوز (\tmp\ لا \USR\tmp)
    path = tmp_path / "replay_test_receipt.json"
    raw = json.dumps(receipt, ensure_ascii=False)
    path.write_text(raw, encoding="utf-8")
    r = replay_file(path, source_label="file")
    assert r.ok is True
    assert r.source_sha16 == hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    # المستوى الحاسم: إعادة التحميل لا تغيّر شيئًا
    r2 = replay_file(path, source_label="file")
    assert r.chain_hash == r2.chain_hash


def test_cli_exit_codes(tmp_path):
    receipt, _ = _clean_world()
    clean_path = tmp_path / "clean.json"
    clean_path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    assert run_replay(SimpleNamespace(receipt=str(clean_path), json_out=None)) == 0

    forged = copy.deepcopy(receipt)
    forged["aggregate"]["resolved_strict"] = 99
    forged["chain_hash"] = chain_hash_of({k: x for k, x in forged.items() if k != "chain_hash"})
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(forged, ensure_ascii=False), encoding="utf-8")
    assert run_replay(SimpleNamespace(receipt=str(bad_path), json_out=None)) == 1

    assert run_replay(SimpleNamespace(receipt=str(tmp_path / "غائب.json"), json_out=None)) == 2


def test_cli_writes_signed_replay_receipt(tmp_path):
    receipt, _ = _clean_world()
    src = tmp_path / "receipt.json"
    src.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "replay_out.json"
    code = run_replay(SimpleNamespace(receipt=str(src), json_out=str(out)))
    assert code == 0
    signed = json.loads(out.read_text(encoding="utf-8"))
    assert signed["schema"] == "zyko.bench_replay/1"
    assert signed["chain_hash"] == chain_hash_of(signed)
