"""frontier.py — عدّة المقاييس الأمامية (الموجة 24): زبدة مقاييس 2026 بأسلوب zyko.

المقاييس التي تقيس بها الشركات نماذجها لم تعد قائمة واحدة بل منظومة
متخصصة: التفكير (HLE · GPQA · ARC-AGI 2)، هندسة البرمجيات (SWE-bench
Verified · EC-SWE · SciCode)، الوكلاء واستدعاء الأدوات (Terminal-Bench ·
τ-bench · BFCL)، والفهم متعدد الوسائط (MMMU-Pro · ScreenSpot Pro)،
والمؤشرات المجمعة (Artificial Analysis Intelligence Index). منهجنا
المعلن: **نأخذ زبدة كل مقياس ونسيله في قالب zyko — عقود موقّعة، حتمية
بالبايت، وبلا عدّاد = بلا ادعاء** — لا نستعار أرقام أحد ولا نزيف
قدراتنا: كل محور هنا قياس حقيقي قابل لإعادة التشغيل من هذا المستودع.

المحاور الستة (الأوزان معلنة ومجموعها 1.0):

| المحور | الوزن | زبدة مقياس 2026 | المصدر |
|---|---|---|---|
| هندسة البرمجيات | 0.30 | SWE-bench Verified · EC-SWE | وثيقتا الموجتين 19/22 الموقّعتان + معمل تعدد الملفات الحي |
| الأدوات والعقود | 0.25 | BFCL · τ-bench (التزام السياسة) | معمل قرارات العقود الحي (قبول/رفض بالاتجاهين) |
| الطرفية | 0.15 | Terminal-Bench | مهام طرفية حقيقية تحت العقد والجِل النواتي |
| التفكير والحتمية | 0.20 | ARC-AGI (التعميم) + منهج إعادة الاشتقاق | eval1000 + synthlab الموقّعتان |
| المنصات | 0.10 | — (بعدُ zyko: النشر فوق كل منصة) | سجل النشر المقياس من الشجرة |
| متعدد الوسائط | 0.00 | MMMU-Pro · ScreenSpot Pro | معلن: خارج نطاق وكيل طرفية نصي — لا رقم مزيف |

المؤشر المجمع «ZFI» (zyko Frontier Index) = المتوسط الموزون بالمحاور
القابلة للقياس، وكل محور يفصح بمقاييسه الفرعية ومصدر كل رقم — فلا
يغرق الضعف في المتوسط كما تغرق المؤشرات المجمعة العدو في المتوسط.

الاستعمال:
    PYTHONPATH=src python3 -m zyko.benchmarks.frontier --run \\
        --json benchmarks/results/frontier_2026-11-14.json
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from zyko.benchmarks.multilab import run_multilab
from zyko.sandbox.audit import AuditLog
from zyko.sandbox.contracts import (
    DEFAULT_ALLOWED_COMMANDS,
    MAX_FILE_BYTES_LIMIT,
    MAX_TIMEOUT_S,
    PermissionContract,
    is_sensitive_file,
)
from zyko.sandbox.session import ToolSession
from zyko.version import __version__

REPO_ROOT = None  # يُحسم وقت الاستدعاء — العلامة تُمشي لا الافتراض
RESULTS_DIR = None  # placeholder، يُستبدل أسفل الوحدة


def _resolve_results_dir() -> Path:
    """دليل الوثائق الموقّعة — جذر المستودع يُمشى للأعلى لا يُفترض."""
    from zyko.platform.deploy import repo_root

    root = repo_root()
    if root is None:
        raise FileNotFoundError("جذر المستودع غير قابل للعثور (pyproject.toml + src/zyko) — لا قياس بلا شجرة")
    return root / "benchmarks" / "results"


RESULTS_DIR = _resolve_results_dir()

# ---------------------------------------------------------------- وثائق موقّعة
WIDE19_DOC = RESULTS_DIR / "swebench_full_wide_2026-11-13.json"
WIDE22_DOC = RESULTS_DIR / "swebench_full_wide22_2026-11-13.json"
WIDE25_MERGED_DOC = RESULTS_DIR / "swebench_full_wide25_merged_2026-11-14.json"
EVAL1000_DOC = RESULTS_DIR / "eval1000_2026-11-12.json"
SYNTHLAB_DOC = RESULTS_DIR / "synthlab_2026-11-12.json"


# ---------------------------------------------------------------- المحاور
@dataclass(frozen=True)
class Axis:
    """محور قياس أمامي واحد — وزنه ومصدره وزبدة المقاييس التي يمثلها."""

    key: str
    title_ar: str
    weight: float
    source: str  # lab | reader
    frontier_analogs: tuple[str, ...]
    verdict_thresholds: tuple[float, float] = (90.0, 60.0)  # قوة / مراقبة / ضعف


AXES: tuple[Axis, ...] = (
    Axis("swe_engineering", "هندسة البرمجيات", 0.30, "reader+lab",
         ("SWE-bench Verified", "EC-SWE (تعدد الملفات)", "SciCode")),
    Axis("agentic_tools", "الأدوات والعقود", 0.25, "lab",
         ("BFCL (استدعاء الدوال)", "τ-bench (التزام السياسة)")),
    Axis("terminal", "الطرفية", 0.15, "lab", ("Terminal-Bench",)),
    Axis("reasoning_determinism", "التفكير والحتمية", 0.20, "reader",
         ("ARC-AGI (التعميم)", "منهج إعادة الاشتقاق بالبايت")),
    Axis("platforms", "المنصات", 0.10, "reader", ("— (بعدُ zyko: النشر المقاس)",)),
    Axis("multimodal", "متعدد الوسائط", 0.00, "declared-na",
         ("MMMU-Pro", "ScreenSpot Pro")),
)

WEIGHT_SUM = round(sum(a.weight for a in AXES), 6)
APPLICABLE_WEIGHTS = round(sum(a.weight for a in AXES if a.weight > 0), 6)


def verdict_for(score: float) -> str:
    """الحكم الصادق بالمحور: قوة ≥ 90، مراقبة 60–90، ضعف < 60."""
    if score >= 90.0:
        return "قوة"
    if score >= 60.0:
        return "مراقبة"
    return "ضعف"


# ---------------------------------------------------------------- القارئات
def _ratio(numerator: object, denominator: object) -> float | None:
    try:
        num, den = float(numerator), float(denominator)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if den <= 0:
        return None
    return round(100.0 * num / den, 2)


def read_signed_doc(path: Path) -> dict:
    """اقرأ وثيقة موقّعة من الشجرة — الوثيقة الغائبة فشل موثق لا رقم مزيف."""
    if not path.is_file():
        raise FileNotFoundError(f"وثيقة موقّعة مفقودة: {path.name} — لا ادعاء بلا عدّاد")
    return json.loads(path.read_text(encoding="utf-8"))


def read_wide_metrics() -> dict[str, object]:
    """مقاييس SWE-bench الواسع من الوثائق الموقّعة — كل رقم بمصدره.

    الموجة 25: البيئي من وثيقة الموجة 19 كما هو (مزيجها المعلن لم
    يتغير)، والصارم والرقع المطبقة من **وثيقة الدمج الموقعة** — 44 سجلاً
    على العينة نفسها: تسعة ناجون من الموجة 22 ببصماتهم و34 وفاة اختيار
    أُعيد تشغيلها بعقل حقيقي فوق المنقذ الحتمي.
    """
    wide19 = read_signed_doc(WIDE19_DOC)
    merged25 = read_signed_doc(WIDE25_MERGED_DOC)
    agg19, agg25 = wide19["aggregate"], merged25["aggregate"]
    env_rate = _ratio(agg19["resolved_env"], agg19["total"])
    strict_rate = _ratio(agg25["resolved_strict"], agg25["total"])
    applied_rate = _ratio(agg25["applied_count"], agg25["total"])
    if env_rate is None or strict_rate is None or applied_rate is None:
        raise ValueError("وثيقة موقّعة بأرقام غير قابلة للنسبة — رفض لا تجاهل")
    return {
        "env_solve_pct": env_rate,
        "env_source": f"{WIDE19_DOC.name} (الموجة 19، حلقة بعقل حقيقي)",
        "strict_solve_pct": strict_rate,
        "strict_source": f"{WIDE25_MERGED_DOC.name} (الموجة 25، منقِذ المسار — الدمج الموقّع للعينة كاملة)",
        "applied_patch_pct": applied_rate,
        "applied_source": f"{WIDE25_MERGED_DOC.name} (رقع مطبقة فعلاً)",
    }


def read_reasoning_metrics() -> dict[str, object]:
    """حتمية التفكير من الوثيقتين الموقّعتين ببصمات السلاسل."""
    e = read_signed_doc(EVAL1000_DOC)
    s = read_signed_doc(SYNTHLAB_DOC)
    e_rate = _ratio(e["passed"], e["total"])
    s_rate = _ratio(s["passed"], s["total"])
    if e_rate is None or s_rate is None:
        raise ValueError("وثيقة موقّعة بأرقام غير قابلة للنسبة — رفض لا تجاهل")
    return {
        "eval1000_pct": e_rate,
        "eval1000_chain": e.get("chain_hash", ""),
        "synthlab_pct": s_rate,
        "synthlab_chain": s.get("chain_hash", ""),
    }


def read_platforms_metrics() -> dict[str, object]:
    """جاهزية المنصات مقياسة من الشجرة الحية — لا ادعاء."""
    from zyko.platform.deploy import deployment_report

    report = deployment_report()
    total = int(report["total"])
    ready = int(report["ready_count"])
    rate = _ratio(ready, total)
    return {
        "ready_targets": f"{ready}/{total}",
        "platforms_pct": rate if rate is not None else 0.0,
        "all_ready": bool(report["all_ready"]),
    }


# ---------------------------------------------------------------- معمل العقود
@dataclass(frozen=True)
class ContractScenario:
    """سيناريو قرار واحد: نية وكيل + قرار العقد المتوقع — بالاتجاهين.

    القبول الخاطئ والرفض الخاطئ كلاهما فشل: دقة استدعاء الأدوات تقاس
    كما يقاس BFCL على الاستدعاء الصحيح وτ-bench على التزام السياسة.
    """

    scenario_id: str
    intent_ar: str
    probe: str  # مسار الفحص: path-traversal | path-nul | path-outside | path-ok
    # | command-inject | command-foreign | command-ok | env-secret | env-keep
    # | clamp-negative | clamp-oversize | sensitive-read
    expected_ok: bool


def _build_contract_scenarios() -> tuple[ContractScenario, ...]:
    return (
        ContractScenario("CT-01", "رقعة داخل جذر المشروع", "path-ok", True),
        ContractScenario("CT-02", "تجاوز المسار بـ ‏..", "path-traversal", False),
        ContractScenario("CT-03", "مسار بمحرف NUL عدوي", "path-nul", False),
        ContractScenario("CT-04", "كتابة خارج جذور العقد", "path-outside", False),
        ContractScenario("CT-05", "قراءة ملف حساس (.env)", "sensitive-read", False),
        ContractScenario("CT-06", "اختبارات بمشغّل مسموح", "command-ok", True),
        ContractScenario("CT-07", "حقن صدفة في argv", "command-inject", False),
        ContractScenario("CT-08", "ثنائي خارج القائمة البيضاء", "command-foreign", False),
        ContractScenario("CT-09", "مفتاح API في البيئة يُرفض", "env-secret", True),
        ContractScenario("CT-10", "PATH يبقى بعد التنقية", "env-keep", True),
        ContractScenario("CT-11", "مهلة سالبة تُقيَّد لا ترمي", "clamp-negative", True),
        ContractScenario("CT-12", "سقف ملف فوق المطلق يُقيَّد", "clamp-oversize", True),
    )


def run_contract_lab() -> dict[str, object]:
    """معمل قرارات العقود — كل سيناريو قرار حقيقي على عقد حقيقي."""
    scenarios = _build_contract_scenarios()
    rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="zyko-frontier-") as tmp:
        root = Path(tmp)
        contract = PermissionContract.for_roots(root, allow_patch=True, allow_run_tests=True)
        for sc in scenarios:
            observed_ok, evidence = _probe_contract(contract, sc.probe, root)
            correct = observed_ok == sc.expected_ok
            rows.append({
                "scenario_id": sc.scenario_id,
                "intent": sc.intent_ar,
                "probe": sc.probe,
                "expected_ok": sc.expected_ok,
                "observed_ok": observed_ok,
                "correct": correct,
                "evidence": evidence,
            })
    correct_count = sum(1 for r in rows if r["correct"])
    rate = _ratio(correct_count, len(rows))
    return {
        "lab": "contract_decisions",
        "scenarios": rows,
        "total": len(rows),
        "correct": correct_count,
        "accuracy_pct": rate if rate is not None else 0.0,
    }


def _probe_contract(contract: PermissionContract, probe: str, root: Path) -> tuple[bool, str]:
    """نفّذ فحصاً واحداً وأعد (القرار الملاحظ، الدليل النصي)."""
    inside = root / "mod.py"
    if probe == "path-ok":
        p, _ = contract.check_path(str(inside))
        return p is not None, "check_path(inside-root)"
    if probe == "path-traversal":
        p, _ = contract.check_path(str(root / ".." / "outside.py"))
        return p is not None, "check_path(.. escape)"
    if probe == "path-nul":
        p, _ = contract.check_path(str(root / "bad\x00name.py"))
        return p is not None, "check_path(NUL byte)"
    if probe == "path-outside":
        p, _ = contract.check_path(str(Path(tempfile.gettempdir()) / "zyko-outside.py"))
        return p is not None, "check_path(outside-roots)"
    if probe == "sensitive-read":
        p, _ = contract.check_read_path(str(root / ".env"))
        return p is not None, "check_read_path(.env)"
    if probe == "command-ok":
        tokens, _ = contract.check_command(("pytest", "-q", "test_x.py"))
        return tokens is not None, "check_command(pytest argv)"
    if probe == "command-inject":
        tokens, _ = contract.check_command(("pytest", "-q; rm -rf /"))
        return tokens is not None, "check_command(shell metachar)"
    if probe == "command-foreign":
        tokens, _ = contract.check_command(("curl", "http://example.invalid"))
        return tokens is not None, "check_command(non-whitelist binary)"
    if probe == "env-secret":
        import os

        os.environ["ZYKO_FRONTIER_API_TOKEN"] = "probe-secret-value-not-a-real-token"
        env = contract.sanitized_env()
        leaked = any("TOKEN" in k.upper() or "SECRET" in k.upper() or "KEY" in k.upper()
                     for k in env)
        return (not leaked), "sanitized_env(secret denied)"
    if probe == "env-keep":
        env = contract.sanitized_env()
        return "PATH" in env, "sanitized_env(PATH kept)"
    if probe == "clamp-negative":
        clamped = PermissionContract.for_roots(root, timeout_s=-5.0)
        ok = 0.0 <= clamped.timeout_s <= MAX_TIMEOUT_S
        return ok, f"clamp(timeout_s -> {clamped.timeout_s})"
    if probe == "clamp-oversize":
        clamped = PermissionContract.for_roots(root, max_file_bytes=999_999_999_999)
        ok = 0 < clamped.max_file_bytes <= MAX_FILE_BYTES_LIMIT
        return ok, f"clamp(max_file_bytes -> {clamped.max_file_bytes})"
    raise ValueError(f"فحص مجهول: {probe}")


# ---------------------------------------------------------------- مهام الطرفية
TERMINAL_TASKS: tuple[tuple[str, str], ...] = (
    ("TB-01", "أنشئ وحدة بايثون جديدة بالبايتات المعلنة"),
    ("TB-02", "أنشئ اختبارها وشغّله ناجحاً تحت العقد"),
    ("TB-03", "شغّل اختباراً فاشلاً ووثّق العدّ المفصول"),
    ("TB-04", "فحص الصياغة يفضح ملفاً مكسوراً بلا تنفيذ"),
    ("TB-05", "ملف ظلّ يخطف المشغّل فيُرفض ثم تُشفى الشجرة"),
    ("TB-06", "رقعة خارج الجذور تُرفض قبل أي كتابة"),
    ("TB-07", "بيئة بيضاء: السر لا يعبر والمحوّل يبقى"),
    ("TB-08", "ميزانية الرقع تنفد فتُرفض الكتابة موثقة"),
)

_MOD = '"""mod_doc."""\n\n\ndef scale(v):\n    return v * 2\n'
_TEST_OK = "from mod import scale\n\n\ndef test_scale():\n    assert scale(21) == 42\n"
_TEST_BAD = "from mod import scale\n\n\ndef test_scale():\n    assert scale(21) == 43\n"
_BAD_SYNTAX = "def broken(:\n    pass\n"


def run_terminal_lab() -> dict[str, object]:
    """مهام طرفية حقيقية: كتابة وتشغيل وفحص تحت العقد والجِل — بالبايت."""
    rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="zyko-frontier-term-") as tmp:
        root = Path(tmp)
        log_path = root / "audit.jsonl"
        contract = PermissionContract.for_roots(
            root, allow_patch=True, allow_run_tests=True
        )
        session = ToolSession(contract, AuditLog(str(log_path)))

        # TB-01: كتابة وحدة بالبايتات المعلنة
        r1 = session.patch_file(path="mod.py", content=_MOD)
        bytes_ok = (root / "mod.py").read_bytes() == _MOD.encode("utf-8")
        rows.append(_task_row("TB-01", r1.ok and bytes_ok, r1.reason_ar))

        # TB-02: اختبار ناجح تحت العقد
        r2w = session.patch_file(path="test_ok.py", content=_TEST_OK)
        r2 = session.run_tests(argv=("pytest", "-q", "-p", "no:cacheprovider", "test_ok.py"), cwd=root)
        rows.append(_task_row("TB-02", r2w.ok and r2.ok and r2.passed == 1,
                              r2.reason_ar or f"passed={r2.passed}"))

        # TB-03: اختبار فاشل — العد مفصول لا مطموس
        r3w = session.patch_file(path="test_bad.py", content=_TEST_BAD)
        r3 = session.run_tests(argv=("pytest", "-q", "-p", "no:cacheprovider", "test_bad.py"), cwd=root)
        rows.append(_task_row("TB-03", r3w.ok and (not r3.ok) and (r3.failed or 0) == 1,
                              r3.reason_ar or f"failed={r3.failed} (مفصول لا مطموس)"))

        # TB-04: فحص الصياغة يفضح الملف المكسور
        r4w = session.patch_file(path="broken.py", content=_BAD_SYNTAX)
        r4 = session.run_tests(
            argv=("python3", "-m", "py_compile", "broken.py"), cwd=root
        )
        rows.append(_task_row("TB-04", r4w.ok and not r4.ok, r4.reason_ar or "exit=" + str(r4.exit_code)))

        # TB-05: خطف المشغّل بملف ظلّ ثم الشفاء
        r5p = session.patch_file(path="pytest.py", content="print('hijack')\n")
        r5 = session.run_tests(argv=("pytest", "-q", "test_ok.py"), cwd=root)
        hijacked_rejected = r5p.ok and (not r5.ok) and "يظلّل" in (r5.reason_ar or "")
        (root / "pytest.py").unlink()
        r5b = session.run_tests(argv=("pytest", "-q", "-p", "no:cacheprovider", "test_ok.py"), cwd=root)
        rows.append(_task_row("TB-05", hijacked_rejected and r5b.ok,
                              r5.reason_ar or "recovered"))

        # TB-06: رقعة خارج الجذور ترفض قبل الكتابة
        outside = Path(tempfile.gettempdir()) / "zyko-frontier-outside.txt"
        r6 = session.patch_file(path=str(outside), content="x")
        rows.append(_task_row("TB-06", not r6.ok, r6.reason_ar))

        # TB-07: البيئة البيضاء — سر مزروع لا يعبر
        import os

        os.environ["ZYKO_FRONTIER_SECRET_KEY"] = "probe-value-not-a-real-secret"
        env = contract.sanitized_env()
        no_leak = not any("SECRET" in k or "KEY" in k for k in env)
        rows.append(_task_row("TB-07", no_leak and "PATH" in env, "sanitized_env"))

        # TB-08: ميزانية الرقع تنفد فتُرفض
        tight = PermissionContract.for_roots(root, allow_patch=True, max_patch_ops=1)
        tight_session = ToolSession(tight)
        t1 = tight_session.patch_file(path="a.txt", content="1")
        t2 = tight_session.patch_file(path="b.txt", content="2")
        budget_ok = t1.ok and (not t2.ok) and "ميزانية" in (t2.reason_ar or "")
        rows.append(_task_row("TB-08", budget_ok, t2.reason_ar))

    passed = sum(1 for r in rows if r["passed"])
    rate = _ratio(passed, len(rows))
    return {
        "lab": "terminal_tasks",
        "tasks": rows,
        "total": len(rows),
        "passed": passed,
        "success_pct": rate if rate is not None else 0.0,
    }


def _task_row(task_id: str, passed: bool, reason: str) -> dict[str, object]:
    intent = next(i for tid, i in TERMINAL_TASKS if tid == task_id)
    return {"task_id": task_id, "intent": intent, "passed": bool(passed), "evidence": reason[:160]}


# ---------------------------------------------------------------- التجميع
def _swe_axis_score() -> tuple[float, list[dict[str, object]]]:
    """مزيج هندسة البرمجيات معلن: 0.4 تعدد الملفات الحي + 0.3 بيئي + 0.3 صارم."""
    wide = read_wide_metrics()
    ml = run_multilab()
    multi_rate = _ratio(sum(1 for r in ml.rows if r.passed), len(ml.rows))
    if multi_rate is None:
        raise ValueError("معمل تعدد الملفات رجع صفراً — لا نسبة بلا عدّاد")
    score = round(
        0.4 * multi_rate
        + 0.3 * float(wide["env_solve_pct"])
        + 0.3 * float(wide["strict_solve_pct"]),
        2,
    )
    sub = [
        {"name": "تعدد الملفات (EC-SWE analog)", "value_pct": multi_rate,
         "source": "zyko.benchmarks.multilab حي — 9 سيناريوهات"},
        {"name": "الحل البيئي", "value_pct": wide["env_solve_pct"], "source": wide["env_source"]},
        {"name": "الحل الصارم", "value_pct": wide["strict_solve_pct"], "source": wide["strict_source"]},
        {"name": "رقع مطبقة فعلاً", "value_pct": wide["applied_patch_pct"], "source": wide["applied_source"]},
    ]
    return score, sub


def run_frontier() -> dict[str, object]:
    """شغّل العدّة كاملة: محاور حية وقارئات موقّعة ومؤشر مجمع موقّع."""
    contract_lab = run_contract_lab()
    terminal_lab = run_terminal_lab()
    multi_rate = _ratio(sum(1 for r in run_multilab().rows if r.passed), 9)
    swe_score, swe_sub = _swe_axis_score()

    reasoning = read_reasoning_metrics()
    reasoning_score = round(
        0.6 * float(reasoning["eval1000_pct"]) + 0.4 * float(reasoning["synthlab_pct"]), 2
    )
    platforms = read_platforms_metrics()

    scores: dict[str, float | None] = {
        "swe_engineering": swe_score,
        "agentic_tools": float(contract_lab["accuracy_pct"]),
        "terminal": float(terminal_lab["success_pct"]),
        "reasoning_determinism": reasoning_score,
        "platforms": float(platforms["platforms_pct"]),
        "multimodal": None,  # معلن: خارج نطاق وكيل طرفية نصي — لا رقم مزيف
    }

    rows: list[dict[str, object]] = []
    for axis in AXES:
        score = scores[axis.key]
        subs: list[dict[str, object]] = []
        if axis.key == "swe_engineering":
            subs = swe_sub
        elif axis.key == "agentic_tools":
            subs = [{"name": "دقة قرارات العقود بالاتجاهين", "value_pct": contract_lab["accuracy_pct"],
                     "source": "معمل قرارات العقود الحي (12 سيناريو)"}]
        elif axis.key == "terminal":
            subs = [{"name": "مهام الطرفية تحت العقد والجِل", "value_pct": terminal_lab["success_pct"],
                     "source": "معمل الطرفية الحي (8 مهام)"}]
        elif axis.key == "reasoning_determinism":
            subs = [
                {"name": "eval1000", "value_pct": reasoning["eval1000_pct"],
                 "source": f"{EVAL1000_DOC.name} — بصمة {str(reasoning['eval1000_chain'])[:16]}"},
                {"name": "synthlab", "value_pct": reasoning["synthlab_pct"],
                 "source": f"{SYNTHLAB_DOC.name} — بصمة {str(reasoning['synthlab_chain'])[:16]}"},
            ]
        elif axis.key == "platforms":
            subs = [{"name": "أهداف النشر الجاهزة", "value": platforms["ready_targets"],
                     "source": "zyko.platform.deploy — مقياس من الشجرة"}]
        rows.append({
            "axis": axis.key,
            "title_ar": axis.title_ar,
            "weight": axis.weight,
            "source": axis.source,
            "frontier_analogs": list(axis.frontier_analogs),
            "score_pct": score,
            "verdict": "خارج النطاق — معلن" if score is None else verdict_for(float(score)),
            "sub_metrics": subs,
        })

    zfi = round(
        sum(a.weight * float(scores[a.key]) for a in AXES if a.weight > 0 and scores[a.key] is not None)
        / APPLICABLE_WEIGHTS,
        2,
    )
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return {
        "kind": "zyko_frontier_gauge",
        "zyko_version": __version__,
        "axes": rows,
        "zfi": zfi,
        "zfi_formula": "المتوسط الموزون للمحاور القابلة للقياس (الأوزان معلنة، مجموعها 1.0؛ متعدد الوسائط 0.0 معلن)",
        "chain_hash": digest.hexdigest(),
        "counts": {
            "contract_lab": {"total": contract_lab["total"], "correct": contract_lab["correct"]},
            "terminal_lab": {"total": terminal_lab["total"], "passed": terminal_lab["passed"]},
        },
    }


def format_report(report: dict[str, object]) -> str:
    """المصفوفة الصادقة للطباعة — محور بمحور لا غرق في المتوسط."""
    lines = [
        f"عدّة المقاييس الأمامية — zyko {report['zyko_version']} — مؤشر ZFI: {report['zfi']}",
        "المحور | الوزن | النتيجة | الحكم | زبدة 2026",
        "-" * 72,
    ]
    for row in report["axes"]:
        score = row["score_pct"]
        score_text = "خارج النطاق" if score is None else f"{float(score):.2f}%"
        analogs = " · ".join(row["frontier_analogs"])
        lines.append(f"{row['title_ar']} | {row['weight']} | {score_text} | {row['verdict']} | {analogs}")
    lines.append("-" * 72)
    lines.append(f"بصمة السلسلة: {report['chain_hash'][:16]}… — كل رقم قابل لإعادة التشغيل")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="zyko.benchmarks.frontier",
        description="عدّة المقاييس الأمامية — زبدة مقاييس 2026 بأسلوب zyko: قياس لا ادعاء",
    )
    parser.add_argument("--run", action="store_true", help="شغّل المحاور الحية والقارئات واطبع المصفوفة")
    parser.add_argument("--json", type=str, default="", help="اكتب الإيصال JSON في مسار")
    args = parser.parse_args(argv)

    if not args.run:
        parser.print_help()
        return 0
    report = run_frontier()
    print(format_report(report))
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        print(f"الإيصال موقّع: {out}")
    strengths = [r["title_ar"] for r in report["axes"] if r["verdict"] == "قوة"]
    weaknesses = [r["title_ar"] for r in report["axes"] if r["verdict"] == "ضعف"]
    if strengths:
        print(f"نقاط التفوق: {' · '.join(strengths)}")
    if weaknesses:
        print(f"نقاط الضعف (طابور التطوير): {' · '.join(weaknesses)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
