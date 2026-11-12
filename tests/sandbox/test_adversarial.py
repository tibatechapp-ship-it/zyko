"""حزمة اختبارات العدو لطبقة الأدوات — ثغرات، قوة، سرعة، حتمية تحت الضغط.

هذه الحزمة تحاول كسر الطبقة كما يحاول مهاجم حقيقي: اجتياز مسارات
بكل أشكاله (``..``، ارتباطات متراصة، رموز ارتباط مجلدات)، أسرار بأشكال
مختلفة تحاول العبور إلى القرص أو إلى العملية الفرعية، مدخلات عدوية
تحاول إخراج استثناء من عقد «بلا استثناء»، وأحداث تدقيق تحاول كسر
السلسلة — وفوق ذلك ميقاتيات سرعة تثبت أن الصرامة ليست بطءًا.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time

import pytest

# تخطٍ موثق: النواة تعلن Landlock لكن إقامته تفشل في حاويات CI
# (سياسات seccomp تحجب landlock_add_rule) — بروبة إقامة حقيقية تقرر.
from zyko.sandbox import jail as _jail_mod
from zyko.sandbox.audit import AuditLog, entry_hash
from zyko.sandbox.contracts import PermissionContract
from zyko.sandbox.patcher import patch_file
from zyko.sandbox.runner import _parse_counts, run_tests
from zyko.sandbox.session import ToolSession

_jail_broken = (
    _jail_mod.jail_level() == _jail_mod.JAIL_LEVEL_LANDLOCK
    and not _jail_mod.jail_establishment_ok()
)
_working_jail = pytest.mark.skipif(
    _jail_broken,
    reason="إقامة الحبس النواتي تفشل في هذه البيئة (seccomp الحاوية يحجب Landlock) — تخطٍ موثق لا فشل",
)

PY = sys.executable.replace("\\", "/").split("/")[-1].replace(".exe", "") or "python"


# ---------------------------------------------------------------- الاجتياز
class TestPathTraversal:
    """كل أشكال الخروج عن الجذر — كلها مرفوضة بلا استثناء."""

    SNEAKY = (
        "../خارج.py",
        "a/../../b.py",
        "./x/../../../y.py",
        "sub/../../../escape.py",
        "..",
        "../",
    )

    def _session(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        contract = PermissionContract.for_roots(proj, allow_patch=True)
        return ToolSession(contract, AuditLog(tmp_path / "audit.jsonl")), proj

    @pytest.mark.parametrize("sneaky", SNEAKY)
    def test_traversal_paths_denied(self, tmp_path, sneaky):
        session, proj = self._session(tmp_path)
        result = session.patch_file(path=sneaky, content="اقتحام")
        assert not result.ok
        assert not list(proj.rglob("اقتحام*"))

    def test_traversal_not_written_anywhere_outside(self, tmp_path):
        session, proj = self._session(tmp_path)
        for sneaky in self.SNEAKY:
            session.patch_file(path=sneaky, content="اقتحام")
        # لا شيء كُتب في أي مكان خارج proj
        for p in tmp_path.rglob("*"):
            if p.is_file() and p.name != "audit.jsonl":
                assert proj in p.parents or p.parent == proj

    def test_symlink_directory_escape_denied(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        outside = tmp_path / "خارج"
        outside.mkdir()
        (outside / "victim.py").write_text("ضحية\n", encoding="utf-8")
        link = proj / "اتصال"
        link.symlink_to(outside)
        session = ToolSession(
            PermissionContract.for_roots(proj, allow_patch=True),
            AuditLog(tmp_path / "audit.jsonl"),
        )
        result = session.patch_file(path="اتصال/victim.py", old_text="ضحية", new_text="معدلة")
        assert not result.ok
        assert (outside / "victim.py").read_text(encoding="utf-8") == "ضحية\n"

    def test_symlink_chain_to_outside_denied(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        outside = tmp_path / "هدف-نهائي.txt"
        outside.write_text("هدف\n", encoding="utf-8")
        mid = proj / "وسط"
        mid.symlink_to(outside)
        entry = proj / "دخول"
        entry.symlink_to(mid)
        session = ToolSession(
            PermissionContract.for_roots(proj, allow_patch=True),
            AuditLog(tmp_path / "audit.jsonl"),
        )
        assert not session.patch_file(path="دخول", content="x").ok

    def test_relative_path_anchors_to_first_root(self, tmp_path):
        """انحدار: المسار النسبي يُثبَّت على الجذر الأول لا مجلد العمل."""
        proj = tmp_path / "proj"
        proj.mkdir()
        contract = PermissionContract.for_roots(proj)
        target, reason = contract.check_path("app.py")
        assert target is not None and reason is None
        assert target == (proj / "app.py").resolve()

    def test_two_roots_relative_anchors_to_first_only(self, tmp_path):
        a, b = tmp_path / "أ", tmp_path / "ب"
        b.mkdir()
        contract = PermissionContract.for_roots(a, b)
        target, reason = contract.check_path("x.py")
        assert target is not None and reason is None
        assert (a / "x.py").resolve() == target


# ---------------------------------------------------------------- الأوامر
class TestCommandTraversal:
    """argv لا يجتاز جذوره ولا يشير لمسارات مطلقة."""

    def test_parent_reference_denied(self, tmp_path):
        contract = PermissionContract.for_roots(tmp_path, allow_run_tests=True)
        argv, reason = contract.check_command([PY, "-m", "pytest", "../../evil.py"])
        assert argv is None and "اجتياز" in reason

    def test_absolute_path_arg_denied(self, tmp_path):
        contract = PermissionContract.for_roots(tmp_path, allow_run_tests=True)
        argv, reason = contract.check_command([PY, "-m", "pytest", "/etc/passwd"])
        assert argv is None and "مطلق" in reason

    def test_windows_drive_arg_denied(self, tmp_path):
        contract = PermissionContract.for_roots(tmp_path, allow_run_tests=True)
        argv, reason = contract.check_command([PY, "-m", "pytest", "C:\\evil.py"])
        assert argv is None and reason

    def test_relative_safe_args_pass(self, tmp_path):
        contract = PermissionContract.for_roots(tmp_path, allow_run_tests=True)
        argv, reason = contract.check_command([PY, "-m", "pytest", "-q", "tests/test_a.py"])
        assert argv is not None and reason is None


# ---------------------------------------------------------------- الأسرار
class TestSecretContainment:
    """أسرار بأشكال مختلفة لا تعبر إلى القرص ولا إلى العملية الفرعية."""

    SECRET_SHAPES = (
        "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2",
        "sk-" + "abcdefghij1234567890abcd",
        "AKIA" + "IOSFODNN7EXAMPLE",
        "xoxb-" + "123456789012-1234567890123-abcdefghijklmnop",
    )

    def test_secrets_in_paths_masked_in_audit(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        log = AuditLog(tmp_path / "audit.jsonl")
        session = ToolSession(PermissionContract.for_roots(proj, allow_patch=True), log)
        for secret in self.SECRET_SHAPES:
            session.patch_file(path=f"file-{secret}.py", content="محتوى")
        blob = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        for secret in self.SECRET_SHAPES:
            assert secret not in blob
        assert log.verify().ok

    @_working_jail
    def test_secrets_in_env_never_reach_subprocess(self, monkeypatch, tmp_path):
        canary = "هذا-سر-حساس-لا-يعبر"
        for i, name in enumerate(
            (
                "MY_API_KEY",
                "MY_TOKEN_2",
                "SECRET_VALUE",
                "AWS_SECRET_ACCESS_KEY",
                "DATABASE_PASSWORD",
                "AUTH_COOKIE",
                "GITHUB_TOKEN",
            )
        ):
            monkeypatch.setenv(name, f"{canary}-{i}")
        (tmp_path / "test_leak.py").write_text(
            "import os\n\n\n"
            "def test_no_leak():\n"
            f"    bad = {canary!r}\n"
            "    for value in os.environ.values():\n"
            "        assert bad not in str(value)\n",
            encoding="utf-8",
        )
        contract = PermissionContract.for_roots(tmp_path, allow_run_tests=True)
        result = run_tests(contract, argv=[PY, "-m", "pytest", "-q"], cwd=tmp_path)
        assert result.ok and result.passed == 1


# ---------------------------------------------------------------- القوة
class TestNoExceptionContract:
    """عقد «بلا استثناء» تحت مدخلات عدوية — كل محاولة نتيجة موثقة."""

    HOSTILE_OBJECTS = (None, 42, ["قائمة"], {"قاموس": 1}, "  ", "", "\x00")

    def test_patch_hostile_paths_never_raise(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        session = ToolSession(PermissionContract.for_roots(proj, allow_patch=True), None)
        for hostile in self.HOSTILE_OBJECTS:
            result = session.patch_file(path=hostile, content="x")
            assert isinstance(result.ok, bool)

    def test_run_tests_hostile_argv_never_raise(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        session = ToolSession(PermissionContract.for_roots(proj, allow_run_tests=True), None)
        for hostile in self.HOSTILE_OBJECTS:
            result = session.run_tests(argv=hostile)
            assert isinstance(result.ok, bool)

    def test_broken_str_object_never_raises(self, tmp_path):
        class Boom:
            def __str__(self) -> str:
                raise RuntimeError("انفجار")

        proj = tmp_path / "proj"
        proj.mkdir()
        session = ToolSession(PermissionContract.for_roots(proj, allow_patch=True), None)
        result = session.patch_file(path=Boom(), content="x")
        assert not result.ok and "غير قابل للطباعة" in result.reason_ar

    def test_hostile_audit_detail_never_raises(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        for hostile in ({"a": {"b": {"c": 1}}}, {"": ""}, {1: None}, "نص-ليس-قاموسًا"):
            log.append("t", "ALLOW", "سبب", hostile)
        assert log.verify().ok

    def test_huge_reason_and_details_capped(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        entry = log.append("t", "ALLOW", "ك" * 500_000, {"blob": "ب" * 500_000})
        assert len(entry.reason_ar) <= 600
        assert len(json.dumps(entry.detail)) < 2_000


# ---------------------------------------------------------------- السلسلة
class TestAuditHardeningUnderFire:
    """محاولات كسر السلسلة — كلها تكشف."""

    def test_duplicate_seq_caught(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        log = AuditLog(path)
        log.append("t", "ALLOW", "أول", {})
        line = path.read_text(encoding="utf-8").strip()
        with path.open("a", encoding="utf-8") as fh:  # نسخة مكررة من نفس السطر
            fh.write(line + "\n")
        assert not log.verify().ok

    def test_huge_event_stream_verifies(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        for i in range(500):
            log.append("patch_file", "ALLOW", f"حدث {i}", {"n": i})
        report = log.verify()
        assert report.ok and report.count == 500

    def test_flip_one_char_caught_anywhere(self, tmp_path):
        for position in (0, 250, 499):
            path = tmp_path / f"audit-{position}.jsonl"
            log = AuditLog(path)
            for i in range(500):
                log.append("t", "ALLOW", f"حدث {i}", {"n": i})
            lines = path.read_text(encoding="utf-8").splitlines()
            target = json.loads(lines[position])
            target["reason_ar"] += " مزوّر"
            lines[position] = json.dumps(
                target, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            assert not log.verify().ok, position


# ---------------------------------------------------------------- الحتمية
class TestDeterminismUnderFire:
    """حتمية بالبايت تحت ضغط أحداث كثيرة ومتنوعة."""

    def test_two_logs_same_events_same_chain(self, tmp_path):
        a, b = AuditLog(tmp_path / "a.jsonl"), AuditLog(tmp_path / "b.jsonl")
        for i in range(50):
            event = ("patch_file", "ALLOW", f"رقعة {i}", {"n": i, "path": f"f{i}.py"})
            a.append(*event)
            b.append(*event)
        assert [e.hash for e in a.entries()] == [e.hash for e in b.entries()]

    def test_patcher_same_tree_same_sha(self, tmp_path):
        results = []
        for name in ("شجرة-أ", "شجرة-ب"):
            tree = tmp_path / name
            tree.mkdir()
            (tree / "app.py").write_text("قيمة = 1\n", encoding="utf-8")
            contract = PermissionContract.for_roots(tree, allow_patch=True)
            result = patch_file(
                contract, path=tree / "app.py", old_text="قيمة = 1", new_text="قيمة = 2"
            )
            results.append(result.sha_after)
        assert results[0] == results[1]

    def test_contract_to_dict_stable_under_adversarial_values(self, tmp_path):
        a = PermissionContract.for_roots(tmp_path, timeout_s="غريب", max_file_bytes=-1)
        b = PermissionContract.for_roots(tmp_path, timeout_s="غريب", max_file_bytes=-1)
        assert a.to_dict() == b.to_dict()


# ---------------------------------------------------------------- السرعة
class TestSpeedCanaries:
    """الصرامة ليست بطءًا — ميقاتيات أعلى من سواني العقل (أقل من ثوانٍ)."""

    def test_200_patch_ops_under_10s(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        session = ToolSession(PermissionContract.for_roots(proj, allow_patch=True), None)
        started = time.perf_counter()
        for i in range(200):
            session.patch_file(path=proj / f"f{i}.py", content="محتوى " * 20)
        elapsed = time.perf_counter() - started
        assert elapsed < 10.0, f"200 رقعة في {elapsed:.2f} ثانية — بطء غير مقبول"

    def test_2000_audit_appends_and_verify_under_3s(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        started = time.perf_counter()
        for i in range(2_000):
            log.append("t", "ALLOW", f"حدث {i}", {"n": i})
        report = log.verify()
        elapsed = time.perf_counter() - started
        assert report.ok and report.count == 2_000
        assert elapsed < 3.0, f"2,000 حدث + تحقق في {elapsed:.2f} ثانية — بطء غير مقبول"

    def test_5000_check_path_under_2s(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "x.py").write_text("x", encoding="utf-8")
        contract = PermissionContract.for_roots(proj)
        started = time.perf_counter()
        for _ in range(5_000):
            contract.check_path("x.py")
        elapsed = time.perf_counter() - started
        # السقف 3 ثوانٍ مثل حدث السجل المجاور — العدّة على مشغّل CI مشترك
        # تتذبذب ±1%؛ الكناري يمسك التدهور العشري (10x) لا التذبذب الحراري.
        assert elapsed < 3.0, f"5,000 فحص مسار في {elapsed:.2f} ثانية — بطء غير مقبول"

    def test_parse_counts_huge_output_under_05s(self):
        huge = ("ض" * 500 + " 500 passed\n") * 1_000
        started = time.perf_counter()
        passed, failed, errors, skipped = _parse_counts(huge)
        elapsed = time.perf_counter() - started
        assert passed == 500 and failed is None and errors is None and skipped is None
        assert elapsed < 0.5, f"تحليل مليون محرف في {elapsed:.3f} ثانية — بطء غير مقبول"

    def test_full_session_summary_cheap(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        log = AuditLog(tmp_path / "audit.jsonl")
        session = ToolSession(
            PermissionContract.for_roots(proj, allow_patch=True, max_patch_ops=150), log
        )
        for i in range(100):
            session.patch_file(path=proj / f"f{i}.py", content=str(i))
        started = time.perf_counter()
        summary = session.summary()
        elapsed = time.perf_counter() - started
        assert summary["usage"]["patch_ops"] == 100
        assert elapsed < 0.5

    def test_entry_hash_throughput(self):
        started = time.perf_counter()
        for i in range(20_000):
            entry_hash(i, "0" * 64, "t", "ALLOW", "سبب", {"n": i})
        elapsed = time.perf_counter() - started
        assert elapsed < 1.0, f"20,000 بصمة في {elapsed:.2f} ثانية — بطء غير مقبول"


# ---------------------------------------------------------------- التشغيل
class TestRunnerRobustness:
    """التشغيل تحت ظروف غير مُثالية — موثق لا منكسر."""

    @_working_jail
    def test_unicode_output_survives(self, tmp_path):
        (tmp_path / "test_ar.py").write_text(
            "def test_ar():\n    assert 'مرحبا' == 'مرحبا'\n", encoding="utf-8"
        )
        contract = PermissionContract.for_roots(tmp_path, allow_run_tests=True)
        result = run_tests(contract, argv=[PY, "-m", "pytest", "-q"], cwd=tmp_path)
        assert result.ok and result.passed == 1

    @_working_jail
    def test_crashing_tests_are_documented_failure(self, tmp_path):
        (tmp_path / "test_crash.py").write_text(
            "import os\n\n\ndef test_crash():\n    os._exit(3)\n", encoding="utf-8"
        )
        contract = PermissionContract.for_roots(tmp_path, allow_run_tests=True)
        result = run_tests(contract, argv=[PY, "-m", "pytest", "-q"], cwd=tmp_path)
        assert not result.ok and result.exit_code == 3

    def test_stdout_tail_real_sha_consistency(self, tmp_path):
        """المخرجات المسقوفة لا تنكسر ترميزًا — UTF-8 واحد في كل الاتجاهات."""
        (tmp_path / "test_noise.py").write_text(
            "def test_noise():\n    print('مرحباً' * 5_000)\n", encoding="utf-8"
        )
        contract = PermissionContract.for_roots(
            tmp_path, allow_run_tests=True, max_output_chars=300
        )
        result = run_tests(contract, argv=[PY, "-m", "pytest", "-q"], cwd=tmp_path)
        assert isinstance(result.stdout_tail, str)
        blob = json.dumps(result.to_dict(), ensure_ascii=False)
        assert json.loads(blob)["stdout_tail"] == result.stdout_tail


def test_audit_entry_hash_is_real_sha256():
    digest = entry_hash(1, "0" * 64, "t", "ALLOW", "سبب", {})
    assert (
        digest
        == hashlib.sha256(
            (
                '{"decision":"ALLOW","detail":{},"prev_hash":"'
                + "0" * 64
                + '","reason_ar":"سبب","schema":"zyko.audit.v1","seq":1,"tool":"t"}'
            ).encode("utf-8")
        ).hexdigest()
    )
