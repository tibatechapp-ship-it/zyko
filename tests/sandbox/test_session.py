"""اختبارات جلسة الأدوات — كل محاولة موثقة، ميزانية رقع، بلا استثناء."""

from __future__ import annotations

import json

from zyko.sandbox.audit import AuditLog
from zyko.sandbox.contracts import PermissionContract
from zyko.sandbox.session import ToolSession


def _session(tmp_path, *, audit=True, **kw):
    contract = PermissionContract.for_roots(tmp_path, **kw)
    log = AuditLog(tmp_path / "audit.jsonl") if audit else None
    return ToolSession(contract, log), contract, log


# ---------------------------------------------------------------- الرقعة
def test_patch_allow_audited_pre_and_post(tmp_path):
    session, _, log = _session(tmp_path, allow_patch=True)
    result = session.patch_file(path=tmp_path / "a.py", content="محتوى")
    assert result.ok
    entries = log.entries()
    # تدقيقان لكل استدعاء: قبل التنفيذ وبعده
    assert [e.decision for e in entries] == ["ALLOW", "ALLOW"]
    assert entries[0].tool == "patch_file"
    assert entries[1].detail["bytes_written"] > 0


def test_patch_denial_audited(tmp_path):
    session, _, log = _session(tmp_path)  # بلا allow_patch
    result = session.patch_file(path=tmp_path / "a.py", content="محتوى")
    assert not result.ok
    decisions = [e.decision for e in log.entries()]
    assert decisions.count("DENY") == 2  # قبل وبعد


def test_patch_ops_budget_enforced_and_audited(tmp_path):
    session, _, log = _session(tmp_path, allow_patch=True, max_patch_ops=2)
    for i in range(2):
        assert session.patch_file(path=tmp_path / f"f{i}.py", content=str(i)).ok
    over = session.patch_file(path=tmp_path / "f3.py", content="3")
    assert not over.ok and "ميزانية" in over.reason_ar
    assert session.usage.patch_ops == 2
    assert session.usage.patch_denied == 1
    denials = [e for e in log.entries() if e.decision == "DENY"]
    assert denials and "ميزانية" in denials[0].reason_ar


def test_patch_exception_becomes_documented_error(tmp_path):
    """أداة تدمّر نفسها بالمدخل — الجلسة تحولها ERROR موثق لا استثناء."""
    session, _, log = _session(tmp_path, allow_patch=True)
    # مسار كائن عدوي يفجّر str()/Path في العمق — المحاولة تُدقَّق ولا يخرج استثناء
    class Boom:
        def __str__(self) -> str:
            raise RuntimeError("انفجار متعمد")

    result = session.patch_file(path=Boom(), content="x")
    assert not result.ok
    decisions = [e.decision for e in log.entries()]
    assert "ERROR" in decisions


# ---------------------------------------------------------------- الاختبارات
def test_run_tests_allow_audited(tmp_path):
    session, _, log = _session(tmp_path, allow_run_tests=True)
    result = session.run_tests(argv=[sys_py(), "-V"], cwd=tmp_path)
    assert result.ok
    assert log.entries()[0].tool == "run_tests"


def test_run_tests_denial_audited(tmp_path):
    session, _, log = _session(tmp_path)
    result = session.run_tests(argv=[sys_py(), "-m", "pytest"])
    assert not result.ok
    decisions = [e.decision for e in log.entries()]
    assert decisions.count("DENY") == 2


def test_run_tests_exception_becomes_error(tmp_path):
    session, _, log = _session(tmp_path, allow_run_tests=True)

    class Boom:
        def __str__(self) -> str:
            raise RuntimeError("انفجار")

    result = session.run_tests(argv=[Boom()], cwd=tmp_path)
    assert not result.ok and not result.ok is None
    assert any(e.decision == "ERROR" for e in log.entries())


# ---------------------------------------------------------------- الملخص
def test_summary_contract_usage_and_audit_chain(tmp_path):
    session, _, log = _session(tmp_path, allow_patch=True)
    session.patch_file(path=tmp_path / "a.py", content="x")
    summary = session.summary()
    assert summary["contract"]["allow_patch"] is True
    assert summary["usage"]["patch_ops"] == 1
    assert summary["audit"]["count"] == 2
    assert len(summary["audit"]["last_hash"]) == 64


def test_summary_without_audit_has_no_audit_key(tmp_path):
    session, _, _ = _session(tmp_path, audit=False)
    summary = session.summary()
    assert "audit" not in summary


def test_session_audit_content_has_no_secrets(tmp_path, monkeypatch):
    canary = "ghp_" + "A" * 20  # يُبنى برمجيًا — توكن-الشكل للفحص لا حرفيًا
    monkeypatch.setenv("ZYKO_SECRET_TOKEN", canary)
    session, _, log = _session(tmp_path, allow_patch=True)
    # سر في اسم الملف — يُدوَّن في detail.path فيُقنَّع قبل القرص
    session.patch_file(path=tmp_path / f"file-{canary}.py", content="محتوى عادي بلا أسرار")
    blob = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert canary not in blob
    assert "[سر-مقنّع]" in blob
    # والسجل يبقى سليمًا بعد القنع
    assert log.verify().ok


def test_session_summary_is_json_serializable(tmp_path):
    session, _, _ = _session(tmp_path, allow_patch=True, allow_run_tests=True)
    session.patch_file(path=tmp_path / "a.py", content="x")
    blob = json.dumps(session.summary(), ensure_ascii=False, sort_keys=True)
    assert json.loads(blob)


def sys_py() -> str:
    """بايثون الحالي باسمه القصير — يمر القائمة البيضاء الافتراضية."""
    import sys

    return sys.executable.split("/")[-1].replace(".exe", "") or "python"
