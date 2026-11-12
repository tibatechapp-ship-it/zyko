"""zyko.benchmarks.swebench — الدليل العام: بروتوكول SWE-bench-Lite بنسخته الصادقة (جولة 8).

المبدأ نفسه الذي بُني عليه معمل الإصلاح في جولة 7، وقدّم إلى الحلبة العامة:
**مستوى البرمجة يُقاس لا يُفترض** — لكن هذه المرة على حالات حقيقية من
مقياس SWE-bench-Lite العام (مجموعة ``psf/requests`` الموثقة في
``benchmarks/data/swe_bench_lite_requests.json`` — مستخرَجة من
``princeton-nlp/SWE-bench_Lite`` يوم 2026-11-12، والرقعة الذهبية مستبعدة
عمداً: المقياس هو zyko لا الوحش).

البروتوكول الصادق لكل حالة:
1. **تحضير** البيئة على الإيثاق الأساس مع رقعة الاختبارات (``test_patch``)
   — بند التحضير في ``scripts/run_swebench_lite.py`` (شبكة + uv venv).
2. **قياس أساس**: تشغيل ``FAIL_TO_PASS`` + ``PASS_TO_PASS`` قبل أي إصلاح —
   ما يفشل هنا يوثَّق كما هو (بعض الفحوص تمرّ أصلاً عندنا بسبب بيئة
   أحدث من 2014 — الصدق فوق الاستهزاء بالأرقام).
3. **محاولة الإصلاح بعقل حقيقي** داخل البوابات نفسها: عقل أحادي الملف
   بجولة واحدة — نداءان متتاليان: اختيار الملف من شجرة المستودع ثم توليد
   رقعة موحدة من محتوى الملف. الرقعة تمرّ حرس الرقعة (مسارات نسبية، لا
   أسماء حساسة، لا حذف اختبارات) ثم ``git apply`` في صندوق العمل.
4. **قياس بعد**: ``FAIL_TO_PASS`` كلها ناجحة + ``PASS_TO_PASS`` لا يخرج
   عن فشل الأساس (قاعدة بيئية موثقة تحمي من تقلب الشبكة) ⇒ ``resolved``.
   ويُحسب حكم صارم إضافي على بروتوكول SWE-bench الرسمي حرفياً.

كل شيء **حتمي بالبايت**: لا أزمنة في الإيصال، الأشجار مرتبة، والأخطاء
عربية صريحة — والشبكة والقرص حقنا (``Runner`` و``Transport``) فتبقى
الاختبارات بلا شبكة إطلاقاً.

    from zyko.benchmarks.swebench import load_instances, evaluate_instance

    instances = load_instances(Path("benchmarks/data/swe_bench_lite_requests.json"))
    verdict = evaluate_instance(
        instances[0], workdir, python_bin, candidate_patch=patch,
    )
    verdict.resolved_env   # الحكم البيئي الموثق
    verdict.chain_hash     # بصمة السلسلة — حتمية بالبايت
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from zyko.ai.brains import GateVerdict, Proposal
from zyko.sandbox.contracts import is_sensitive_file

__all__ = [
    "DIFF_LANGUAGE_AR",
    "P2P_ENV_RULE_AR",
    "SWEInstance",
    "SWEVerdict",
    "TestRun",
    "check_patch_contract",
    "diff_paths",
    "extract_diff",
    "evaluate_instance",
    "load_instances",
    "run_ids",
]

# دالة الأثر الجانبي: أمر ⇒ نتيجة مكتملة — نقطة الحقن للاختبارات (بلا شبكة)
Runner = Callable[..., Any]

DEFAULT_TIMEOUT_S = 600.0

# القاعدة البيئية الموثقة: فشل P2P بعد الإصلاح يُغتفر فقط إن كان فشلاً في
# الأساس نفسه (تقلب httpbin الحي مثلاً) — وثيقة فوق خدعة رقم.
P2P_ENV_RULE_AR = (
    "قاعدة البيئة الموثقة: PASS_TO_PASS بعد الإصلاح يجب ألا يخرج عن فشل الأساس —"
    " الفشل البيئي الحي يوثَّق لا يُخفى"
)

DIFF_LANGUAGE_AR = "الرقعة تُستخرج من كتلة ```diff أو من ترويسة diff --git"


# --------------------------------------------------------------- الحالة
@dataclass(frozen=True)
class SWEInstance:
    """حالة SWE-bench-Lite حقيقية — حقائقها المرجعية كما نشرها المقياس.

    ``fail_to_pass`` و``pass_to_pass`` قوائم عُقد pytest مرتبة — الحقيقة
    المرجعية التي يحكم بها الإيصال، لا تقدير ولا رأي.
    """

    instance_id: str
    repo: str
    base_commit: str
    version: str
    problem_statement: str
    test_patch: str
    fail_to_pass: tuple[str, ...]
    pass_to_pass: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "repo": self.repo,
            "base_commit": self.base_commit,
            "version": self.version,
            "problem_sha16": _sha16(self.problem_statement),
            "test_patch_sha16": _sha16(self.test_patch),
            "fail_to_pass": list(self.fail_to_pass),
            "pass_to_pass": list(self.pass_to_pass),
        }


def load_instances(path: Path) -> tuple[SWEInstance, ...]:
    """حمّل حالات SWE-bench-Lite من ملف البيانات الموثق — مرتبة بالمعرّف.

    الحقول ``FAIL_TO_PASS``/``PASS_TO_PASS`` في المصدر سلاسل JSON داخل
    سلسلة (صيغة المقياس الرسمية) — تُفكّ هنا وتُرتّب حتمياً.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw["instances"] if isinstance(raw, dict) else raw
    instances = []
    for item in items:
        instances.append(
            SWEInstance(
                instance_id=str(item["instance_id"]),
                repo=str(item["repo"]),
                base_commit=str(item["base_commit"]),
                version=str(item.get("version") or ""),
                problem_statement=str(item.get("problem_statement") or ""),
                test_patch=str(item.get("test_patch") or ""),
                fail_to_pass=tuple(sorted(_parse_ids(item["FAIL_TO_PASS"]))),
                pass_to_pass=tuple(sorted(_parse_ids(item["PASS_TO_PASS"]))),
            )
        )
    return tuple(sorted(instances, key=lambda i: i.instance_id))


def _parse_ids(value: Any) -> list[str]:
    """فك قائمة العقد: قائمة جاهزة، أو سلسلة JSON داخل سلسلة، أو سلسلة سطرية."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            decoded = json.loads(text)
            if isinstance(decoded, list):
                return [str(v).strip() for v in decoded if str(v).strip()]
        except json.JSONDecodeError:
            pass
    return [line.strip() for line in text.splitlines() if line.strip()]


def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


# --------------------------------------------------------------- الرقعة
_DIFF_BLOCK = re.compile(r"```(?:diff|patch)\s*\n(.*?)```", re.DOTALL)
_DIFF_HEAD = re.compile(r"(?:^|\n)(?:diff --git |--- (?:a/|\w))")

DIFF_FORBIDDEN_SUFFIXES = (".rej", ".orig")
TEST_PATH_MARKER = "test"


_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", re.MULTILINE)


def extract_diff(text: str, *, fallback_path: str | None = None) -> str | None:
    """استخرج رقعة موحدة من نص العقل — كتلة مسوّرة أولى وإلا ترويسة خام.

    ``fallback_path``: إن أعاد العقل أجزاء ``@@`` عارية بلا ترويسات
    ``---/+++`` (عادة شائعة لدى النماذج) وتعرفنا على ملف الهدف حتماً من
    طلبنا نفسه، نبني الترويسة حوله — مسار من طلبنا الحتمي لا من تخمين
    العقل. تعيد ``None`` الصادقة حين لا رقعة في الرد.
    """
    blocks = _DIFF_BLOCK.findall(text)
    for block in blocks:
        if _DIFF_HEAD.search(block):
            return block.strip() or None
    match = _DIFF_HEAD.search(text)
    if match:
        return text[match.start() :].strip() or None
    if fallback_path:
        hunks = _HUNK_HEADER.findall(text)
        if hunks:
            header = f"--- a/{fallback_path}\n+++ b/{fallback_path}"
            return f"{header}\n{text.strip()}"
    return None


def diff_paths(patch: str) -> tuple[str, ...]:
    """مسارات الرقعة من ترويسات ``+++``/``---`` — مرتبة، بلا تكرار، بلا /dev/null."""
    paths: list[str] = []
    for line in patch.splitlines():
        for marker in ("+++ ", "--- "):
            if line.startswith(marker):
                target = line[len(marker) :].strip().split("\t")[0]
                if target == "/dev/null":
                    continue
                if target.startswith(("a/", "b/")):
                    target = target[2:]
                if target and target not in paths:
                    paths.append(target)
    return tuple(sorted(paths))


def check_patch_contract(patch: str) -> tuple[bool, str]:
    """حرس الرقعة — نفس روح عقد ``patch_file``: مسارات نسبية داخل المستودع،
    لا أسماء حساسة، لا حذف ملفات اختبار، وحد أعلى معلن للحجم.

    يعيد ``(مسموح، سبب_عربي)`` — الرفض بسببه موثق لا مكتوم.
    """
    if not patch or not patch.strip():
        return False, "رقعة فارغة — لا شيء يُطبَّق"
    if len(patch) > 64_000:
        return False, f"الرقعة فوق السقف المعلن ({len(patch)} بايت > 64000)"
    paths = diff_paths(patch)
    if not paths:
        return False, "لا مسارات في الرقعة — ليست رقعة موحدة قابلة للتطبيق"
    for path in paths:
        if path.startswith("/") or ".." in Path(path).parts:
            return False, f"مسار مطلق أو خارجي مرفوض: {path}"
        if is_sensitive_file(path):
            return False, f"مسار حساس مرفوض (حرس الأسرار): {path}"
        if path.endswith(DIFF_FORBIDDEN_SUFFIXES):
            return False, f"ملف بقايا رقع مرفوض: {path}"
        if TEST_PATH_MARKER in Path(path).name.lower() and line_removes_file(patch, path):
            return False, f"حذف ملف اختبار مرفوض: {path}"
    return True, "مسموح"


def line_removes_file(patch: str, path: str) -> bool:
    """هل الرقعة تحذف الملف؟ (ترويسة ``---`` مع ``+++ /dev/null``)."""
    deleting = False
    for line in patch.splitlines():
        if line.startswith("--- ") and line[4:].strip().split("\t")[0].endswith(path):
            deleting = True
        elif line.startswith("+++ "):
            target = line[4:].strip().split("\t")[0]
            if deleting and target == "/dev/null":
                return True
            deleting = False
    return False


def apply_candidate(workdir: Path, patch: str, runner: Runner) -> tuple[bool, str]:
    """طبّق الرقعة في صندوق العمل عبر ``git apply`` — فحص ثم تطبيق.

    سطر النهاية الناقص يُستكمل قبل الفحص (النماذج تعيد رقعاً بلا سطر
    أخير كثيراً) — الفشل بسببه العربي الصريح، الرقعة المرفوضة تُوثَّق.
    """
    if not patch.endswith("\n"):
        patch = patch + "\n"
    check_run = runner(
        ["git", "apply", "--check", "--whitespace=nowarn", "-"],
        cwd=str(workdir), input=patch, capture_output=True, text=True, timeout=30,
    )
    if getattr(check_run, "returncode", 1) != 0:
        detail = (getattr(check_run, "stderr", "") or "").strip().splitlines()
        reason = detail[0][:200] if detail else "فحص التطبيق رفض الرقعة"
        return False, f"فشل فحص التطبيق: {reason}"
    apply_run = runner(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=str(workdir), input=patch, capture_output=True, text=True, timeout=30,
    )
    if getattr(apply_run, "returncode", 1) != 0:
        detail = (getattr(apply_run, "stderr", "") or "").strip().splitlines()
        reason = detail[0][:200] if detail else "التطبيق فشل بعد الفحص"
        return False, f"فشل التطبيق: {reason}"
    return True, "طُبِّقت"


# --------------------------------------------------------------- القياس
@dataclass(frozen=True)
class TestRun:
    """نتيجة تشغيل pytest على عُقد معلومة — حقائق خام موثقة."""

    exit_code: int
    passed_count: int | None
    failed_ids: tuple[str, ...]
    error_ar: str | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.error_ar is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "passed_count": self.passed_count,
            "failed_ids": list(self.failed_ids),
            "error_ar": self.error_ar,
        }


_SUMMARY_PASSED = re.compile(r"(\d+) passed")
_FAILED_LINE = re.compile(r"^FAILED (\S+)")


def run_ids(
    workdir: Path,
    ids: tuple[str, ...],
    python_bin: str,
    *,
    env_extra: dict[str, str] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    runner: Runner = subprocess.run,
    extra_args: tuple[str, ...] = (),
) -> TestRun:
    """شغّل pytest على عُقد محددة — أمر معلن، مخرجات مختزلة، فشل عربي.

    ``extra_args`` يمرر حجج pytest إضافية (مثل مهلة لكل اختبار عبر
    ``pytest-timeout``) — تُعلن في الوثيقة لا تُخمّن.
    """
    if not ids:
        return TestRun(exit_code=0, passed_count=None, failed_ids=(),
                       error_ar="لا عقد لتشغيلها — قائمة فارغة")
    env = dict(os.environ)
    env.update(env_extra or {})
    try:
        proc = runner(
            [python_bin, "-m", "pytest", *ids, "--tb=no", "-q", "-rf",
             "-p", "no:cacheprovider", "--no-header", *extra_args],
            cwd=str(workdir), env=env, capture_output=True, text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return TestRun(exit_code=-1, passed_count=None, failed_ids=(),
                       error_ar=f"تجاوز المهلة ({timeout_s:.0f}s) — أُوقِف")
    except FileNotFoundError:
        return TestRun(exit_code=-1, passed_count=None, failed_ids=(),
                       error_ar=f"المفسّر غير موجود: {python_bin}")
    stdout = proc.stdout or ""
    failed_ids = [
        match.group(1)
        for line in stdout.splitlines()
        if (match := _FAILED_LINE.match(line))
    ]
    passed_match = _SUMMARY_PASSED.search(stdout)
    return TestRun(
        exit_code=proc.returncode,
        passed_count=int(passed_match.group(1)) if passed_match else None,
        failed_ids=tuple(sorted(failed_ids)),
        error_ar=None if proc.returncode in (0, 1) else f"pytest خرج بـ {proc.returncode}",
    )


# --------------------------------------------------------------- الحكم
@dataclass(frozen=True)
class SWEVerdict:
    """حكم حالة واحدة — كامل الحقائق، وحكمان موثقان لا واحد مبهم."""

    instance_id: str
    patch_applied: bool
    apply_error_ar: str | None
    f2p_failed_at_base: tuple[str, ...]
    p2p_failed_at_base: tuple[str, ...]
    f2p_passed_after: tuple[str, ...]
    f2p_failed_after: tuple[str, ...]
    p2p_failed_after: tuple[str, ...]
    runs_error_ar: str | None = None
    patch_sha16: str = ""
    contract_reason_ar: str = ""
    attempts_note_ar: str = ""

    # الحكم الصارم — بروتوكول SWE-bench الرسمي حرفياً
    @property
    def resolved_strict(self) -> bool:
        return (
            self.patch_applied
            and self.runs_error_ar is None
            and not self.f2p_failed_after
            and not self.p2p_failed_after
        )

    # الحكم البيئي الموثق — فشل P2P الحي عند الأساس يُغتفر لا يُخفى
    @property
    def resolved_env(self) -> bool:
        return (
            self.patch_applied
            and self.runs_error_ar is None
            and not self.f2p_failed_after
            and all(f in self.p2p_failed_at_base for f in self.p2p_failed_after)
        )

    @property
    def f2p_repaired_count(self) -> int:
        """عدد عقد FAIL_TO_PASS التي كانت فاشلة عند الأساس ونجحت بعد الإصلاح."""
        return sum(1 for f in self.f2p_failed_at_base if f in self.f2p_passed_after)

    @property
    def chain_hash(self) -> str:
        payload = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "patch_applied": self.patch_applied,
            "apply_error_ar": self.apply_error_ar,
            "patch_sha16": self.patch_sha16,
            "contract_reason_ar": self.contract_reason_ar,
            "f2p_failed_at_base": list(self.f2p_failed_at_base),
            "p2p_failed_at_base": list(self.p2p_failed_at_base),
            "f2p_passed_after": list(self.f2p_passed_after),
            "f2p_failed_after": list(self.f2p_failed_after),
            "p2p_failed_after": list(self.p2p_failed_after),
            "runs_error_ar": self.runs_error_ar,
            "resolved_strict": self.resolved_strict,
            "resolved_env": self.resolved_env,
            "f2p_repaired_count": self.f2p_repaired_count,
            "attempts_note_ar": self.attempts_note_ar,
        }


def evaluate_instance(
    instance: SWEInstance,
    workdir: Path,
    python_bin: str,
    *,
    candidate_patch: str | None = None,
    env_extra: dict[str, str] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    runner: Runner = subprocess.run,
    contract_check: Callable[[str], tuple[bool, str]] | None = None,
    extra_args: tuple[str, ...] = (),
) -> SWEVerdict:
    """قياس كامل لحالة واحدة: أساس ثم (رقعة ثم) بعد — حقائق لا ادعاء.

    ``candidate_patch=None`` ⇒ قياس أساس فقط (يستعمله المدقق أن يثبت أن
    البيئة نفسها تعطي الفشل المتوقع قبل أي ذكاء).
    """
    all_ids = tuple(sorted(set(instance.fail_to_pass) | set(instance.pass_to_pass)))
    base = run_ids(workdir, all_ids, python_bin, env_extra=env_extra,
                   timeout_s=timeout_s, runner=runner, extra_args=extra_args)
    if base.error_ar is not None and base.exit_code < 0:
        # مهلة أو مفسّر مفقود — لا أساس فلا حكم
        return SWEVerdict(
            instance_id=instance.instance_id,
            patch_applied=False,
            apply_error_ar=None,
            f2p_failed_at_base=(),
            p2p_failed_at_base=(),
            f2p_passed_after=(),
            f2p_failed_after=(),
            p2p_failed_after=(),
            runs_error_ar=base.error_ar,
        )

    f2p_base_failed = frozenset(f for f in base.failed_ids if f in set(instance.fail_to_pass))
    p2p_base_failed = frozenset(f for f in base.failed_ids if f in set(instance.pass_to_pass))

    if not candidate_patch:
        return SWEVerdict(
            instance_id=instance.instance_id,
            patch_applied=False,
            apply_error_ar=None,
            f2p_failed_at_base=tuple(sorted(f2p_base_failed)),
            p2p_failed_at_base=tuple(sorted(p2p_base_failed)),
            f2p_passed_after=(),
            f2p_failed_after=(),
            p2p_failed_after=(),
            runs_error_ar=None,
            attempts_note_ar="قياس أساس فقط — بلا رقعة مرشحة",
        )

    checker = contract_check or check_patch_contract
    allowed, reason = checker(candidate_patch)
    if not allowed:
        return SWEVerdict(
            instance_id=instance.instance_id,
            patch_applied=False,
            apply_error_ar=None,
            f2p_failed_at_base=tuple(sorted(f2p_base_failed)),
            p2p_failed_at_base=tuple(sorted(p2p_base_failed)),
            f2p_passed_after=(),
            f2p_failed_after=tuple(sorted(instance.fail_to_pass)),
            p2p_failed_after=(),
            patch_sha16=_sha16(candidate_patch),
            contract_reason_ar=reason,
            attempts_note_ar="حرس الرقعة رفضها — لم تُطبَّق",
        )

    applied, apply_reason = apply_candidate(workdir, candidate_patch, runner)
    if not applied:
        return SWEVerdict(
            instance_id=instance.instance_id,
            patch_applied=False,
            apply_error_ar=apply_reason,
            f2p_failed_at_base=tuple(sorted(f2p_base_failed)),
            p2p_failed_at_base=tuple(sorted(p2p_base_failed)),
            f2p_passed_after=(),
            f2p_failed_after=tuple(sorted(instance.fail_to_pass)),
            p2p_failed_after=(),
            patch_sha16=_sha16(candidate_patch),
            contract_reason_ar=reason,
            attempts_note_ar="git apply رفض الرقعة — لم تُطبَّق",
        )

    after = run_ids(workdir, all_ids, python_bin, env_extra=env_extra,
                    timeout_s=timeout_s, runner=runner, extra_args=extra_args)
    if after.exit_code < 0:
        return SWEVerdict(
            instance_id=instance.instance_id,
            patch_applied=True,
            apply_error_ar=None,
            f2p_failed_at_base=tuple(sorted(f2p_base_failed)),
            p2p_failed_at_base=tuple(sorted(p2p_base_failed)),
            f2p_passed_after=(),
            f2p_failed_after=(),
            p2p_failed_after=(),
            runs_error_ar=after.error_ar,
            patch_sha16=_sha16(candidate_patch),
            contract_reason_ar=reason,
            attempts_note_ar="التشغيل البعدي أُوقِف — لا حكم بعد المهلة",
        )

    f2p_after_failed = frozenset(f for f in after.failed_ids if f in set(instance.fail_to_pass))
    p2p_after_failed = frozenset(f for f in after.failed_ids if f in set(instance.pass_to_pass))
    f2p_after_passed = tuple(sorted(set(instance.fail_to_pass) - f2p_after_failed))
    return SWEVerdict(
        instance_id=instance.instance_id,
        patch_applied=True,
        apply_error_ar=None,
        f2p_failed_at_base=tuple(sorted(f2p_base_failed)),
        p2p_failed_at_base=tuple(sorted(p2p_base_failed)),
        f2p_passed_after=f2p_after_passed,
        f2p_failed_after=tuple(sorted(f2p_after_failed)),
        p2p_failed_after=tuple(sorted(p2p_after_failed)),
        patch_sha16=_sha16(candidate_patch),
        contract_reason_ar=reason,
        attempts_note_ar="طُبِّقت وقِيست",
    )


# --------------------------------------------------------------- العقل الحقيقي
# عقل الجولة 8: أحادي الملف بجولة واحدة (نداءان متتاليان) داخل البوابات —
# الجولة 9 تمدّه إلى حلقة متعددة الملفات مع تلقيم نتائج الاختبارات.
SWE_SYSTEM_CHOICE_AR = (
    "أنت مهندس إصلاح داخل ZYKO، محرك البرمجة العربي الحتمي. مهمتك اختيار ملف "
    "المصدر الأرجح الذي يضم علة التقرير. أجب بمسار ملف واحد فقط من الشجرة "
    "المعطاة، بلا أي نص آخر."
)
SWE_SYSTEM_DIFF_AR = (
    "أنت مهندس إصلاح داخل ZYKO، محرك البرمجة العربي الحتمي. مهمتك إصلاح علة "
    "التقرير في الملف المعطى بأصغر تعديل صحيح. أجب برقعة موحدة (unified diff) "
    "في كتلة ```diff فقط — بلا أي شرح خارجها. لا تغيّر الاختبارات ولا "
    "التوثيق التاريخي، وابقَ على أسلوب الكود القائم."
)
SWE_HOST_ENV = "ZYKO_QWEN_HOST"
SWE_KEY_ENV = "ZYKO_QWEN_API_KEY"
SWE_DEFAULT_MODEL = "glm-4.7"
Transport = Callable[[dict[str, Any]], dict[str, Any]]


def http_transport(payload: dict[str, Any], *, host: str, api_key: str,
                   model: str, timeout_s: float = 120.0) -> dict[str, Any]:
    """نقل OpenAI-Compatible عبر urllib — نمط ``qwen_brain`` نفسه بلا اعتماديات.

    أي فشل يعود استجابة شكلها ``{"error": {"message": "<عربي>"}}`` — لا
    استثناء يخرج من طبقة الذكاء.
    """
    body = {
        "model": model,
        "messages": payload["messages"],
        "stream": False,
        "max_tokens": int(payload.get("max_tokens", 4096)),
    }
    req = urllib.request.Request(
        host.rstrip("/") + "/chat/completions",
        method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "zyko-swe/0.32",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # nosec B310 — نقطة نهاية المختبر بمخططات مضبوطة من العقد
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"error": {"message": f"HTTP {exc.code} من نقطة النهاية"}}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"error": {"message": f"نقطة النهاية غير متاحة: {exc}"}}
    except json.JSONDecodeError:
        return {"error": {"message": "استجابة غير JSON من نقطة النهاية"}}


@dataclass(frozen=True)
class SWEBrain:
    """عقل إصلاح حقيقي عبر نقطة متوافقة مع OpenAI — النقل حقن، الفشل عربي."""

    model: str = SWE_DEFAULT_MODEL
    host: str | None = None       # الافتراضي من البيئة — لا مفتاح في الكود
    api_key: str | None = None    # الافتراضي من البيئة — لا مفتاح في الكود
    transport: Transport | None = None
    mode: str = "choice"          # "choice" ثم "diff" — نداءان بترتيب ثابت

    @property
    def name(self) -> str:
        return f"swe-brain:{self.mode}:{self.model}"

    @property
    def deterministic(self) -> bool:
        return False

    def propose(self, request: str) -> Proposal:
        host = self.host or os.environ.get(SWE_HOST_ENV, "")
        key = self.api_key or os.environ.get(SWE_KEY_ENV, "")
        # النقل المحقون هو الشبكة نفسها — بيانات البيئة لا تُطلب إلا للمسار الحقيقي
        if self.transport is None and (not host or not key):
            return Proposal(text="", brain=self.name, deterministic=False,
                            verdicts=(GateVerdict(gate="transport", passed=False,
                                                  details_ar="لا مضيف أو مفتاح في البيئة — عقل معطل عمداً"),))
        system = SWE_SYSTEM_CHOICE_AR if self.mode == "choice" else SWE_SYSTEM_DIFF_AR
        payload = {
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": request}],
            "max_tokens": 8192 if self.mode == "diff" else 512,
        }
        if self.transport is not None:
            response = self.transport(payload)
        else:
            response = http_transport(payload, host=host, api_key=key, model=self.model)
        error = response.get("error") or {}
        if error:
            return Proposal(text="", brain=self.name, deterministic=False,
                            verdicts=(GateVerdict(gate="transport", passed=False,
                                                  details_ar=str(error.get("message", "فشل النقل"))),))
        try:
            text = str(response["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError):
            return Proposal(text="", brain=self.name, deterministic=False,
                            verdicts=(GateVerdict(gate="transport", passed=False,
                                                  details_ar="استجابة مشوّهة — بلا اختيارات"),))
        return Proposal(text=text, brain=self.name, deterministic=False,
                        verdicts=(GateVerdict(gate="transport", passed=True,
                                              details_ar="استجابة سليمة"),))


def build_choice_request(
    instance: SWEInstance,
    tree: tuple[str, ...],
    *,
    map_lines: tuple[str, ...] | None = None,
) -> str:
    """طلب اختيار الملف: التقرير + عقد الفشل + شجرة مرتبة + خريطة دلالية اختيارية.

    ``map_lines`` (جولة 11): سطور ``repo_map`` — العقل يرى رموز كل ملف
    لا مسارات عمياء، فيختار صاحب العلة لا الجار الأشهر. الخريطة إثراء
    لا استبدال: الشجرة تبقى المرجع الذي يُحكى عليه ``parse_choice``.
    """
    failing = "\n".join(instance.fail_to_pass[:24]) or "(لا عقد معلومة)"
    request = (
        f"التقرير:\n{instance.problem_statement}\n\n"
        f"عقد الفشل (اختبارات يجب أن تمر):\n{failing}\n\n"
        f"شجرة ملفات المصدر:\n" + "\n".join(tree)
    )
    if map_lines:
        request += "\n\nخريطة المستودع الدلالية (رموز كل ملف):\n" + "\n".join(map_lines)
    return request


def parse_choice(reply: str, tree: tuple[str, ...]) -> str | None:
    """استخرج أول مسار موجود فعلاً في الشجرة من رد العقل — ترتيب الشجرة يحكم."""
    for path in tree:
        if path in reply:
            return path
    return None


def build_diff_request(instance: SWEInstance, path: str, content: str) -> str:
    """طلب الرقعة: التقرير + عقد الفشل + محتوى الملف كاملاً."""
    failing = "\n".join(instance.fail_to_pass[:24]) or "(لا عقد معلومة)"
    return (
        f"التقرير:\n{instance.problem_statement}\n\n"
        f"عقد الفشل (اختبارات يجب أن تمر):\n{failing}\n\n"
        f"الملف {path} كاملاً:\n```python\n{content}\n```\n\n"
        "أعد الرقعة الموحدة التي تصلح العلة."
    )


def repo_py_tree(workdir: Path, runner: Runner) -> tuple[str, ...]:
    """شجرة ملفات بايثون من ``git ls-files`` — مرتبة، بلا اختبارات الجولة."""
    proc = runner(["git", "ls-files", "*.py"], cwd=str(workdir),
                  capture_output=True, text=True, timeout=30)
    if getattr(proc, "returncode", 1) != 0:
        return ()
    paths = []
    for line in (proc.stdout or "").splitlines():
        path = line.strip()
        if not path or path.startswith("test"):
            continue
        paths.append(path)
    return tuple(sorted(paths))


# --------------------------------------------------------------- المحاولة
@dataclass(frozen=True)
class SWEAttempt:
    """سجل محاولة إصلاح واحدة — كل ما جرى بالبايت، بلا أزمنة."""

    instance_id: str
    file_choice: str | None
    choice_reply_sha16: str
    diff_reply_sha16: str
    proposal_accepted: bool
    verdict: SWEVerdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "file_choice": self.file_choice,
            "choice_reply_sha16": self.choice_reply_sha16,
            "diff_reply_sha16": self.diff_reply_sha16,
            "proposal_accepted": self.proposal_accepted,
            "verdict": self.verdict.to_dict(),
        }


def attempt_repair(
    instance: SWEInstance,
    workdir: Path,
    python_bin: str,
    choice_brain: Any,
    diff_brain: Any,
    *,
    env_extra: dict[str, str] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    runner: Runner = subprocess.run,
    extra_args: tuple[str, ...] = (),
) -> SWEAttempt:
    """محاولة كاملة: شجرة ← اختيار ← محتوى ← رقعة ← حرس ← تطبيق ← قياس.

    ``choice_brain`` و``diff_brain`` عقلان مسبقا التغليف بـ ``GatedBrain`` —
    البوابات تقرر قبل أن يلمس النص الشجرة. كل رفض موثق في المحاولة.
    """
    tree = repo_py_tree(workdir, runner)
    empty_verdict = SWEVerdict(
        instance_id=instance.instance_id, patch_applied=False, apply_error_ar=None,
        f2p_failed_at_base=(), p2p_failed_at_base=(), f2p_passed_after=(),
        f2p_failed_after=(), p2p_failed_after=(),
        runs_error_ar="لا شجرة مصدر — المستودع غير مهيأ",
    )
    if not tree:
        return SWEAttempt(instance_id=instance.instance_id, file_choice=None,
                          choice_reply_sha16="", diff_reply_sha16="",
                          proposal_accepted=False, verdict=empty_verdict)

    choice = choice_brain.propose(build_choice_request(instance, tree))
    chosen = parse_choice(choice.text, tree) if choice.accepted else None
    if chosen is None:
        note = "اختيار الملف رُفض ببوابة أو لم يعطِ مساراً موجوداً"
        verdict = SWEVerdict(
            instance_id=instance.instance_id, patch_applied=False, apply_error_ar=None,
            f2p_failed_at_base=(), p2p_failed_at_base=(), f2p_passed_after=(),
            f2p_failed_after=(), p2p_failed_after=(),
            runs_error_ar=None, attempts_note_ar=note,
        )
        return SWEAttempt(instance_id=instance.instance_id, file_choice=None,
                          choice_reply_sha16=_sha16(choice.text),
                          diff_reply_sha16="",
                          proposal_accepted=choice.accepted, verdict=verdict)

    content = (workdir / chosen).read_text(encoding="utf-8", errors="replace")
    diff_reply = diff_brain.propose(build_diff_request(instance, chosen, content))
    if not diff_reply.accepted:
        verdict = SWEVerdict(
            instance_id=instance.instance_id, patch_applied=False, apply_error_ar=None,
            f2p_failed_at_base=(), p2p_failed_at_base=(), f2p_passed_after=(),
            f2p_failed_after=(), p2p_failed_after=(),
            runs_error_ar=None,
            attempts_note_ar="الرقعة رُفضت ببوابة (PII أو RTL) — لا تطبيق",
        )
        return SWEAttempt(instance_id=instance.instance_id, file_choice=chosen,
                          choice_reply_sha16=_sha16(choice.text),
                          diff_reply_sha16=_sha16(diff_reply.text),
                          proposal_accepted=False, verdict=verdict)

    patch = extract_diff(diff_reply.text, fallback_path=chosen)
    if patch is None:
        verdict = SWEVerdict(
            instance_id=instance.instance_id, patch_applied=False, apply_error_ar=None,
            f2p_failed_at_base=(), p2p_failed_at_base=(), f2p_passed_after=(),
            f2p_failed_after=(), p2p_failed_after=(),
            runs_error_ar=None,
            attempts_note_ar="لا رقعة موحدة في رد العقل — " + DIFF_LANGUAGE_AR,
        )
        return SWEAttempt(instance_id=instance.instance_id, file_choice=chosen,
                          choice_reply_sha16=_sha16(choice.text),
                          diff_reply_sha16=_sha16(diff_reply.text),
                          proposal_accepted=True, verdict=verdict)

    verdict = evaluate_instance(
        instance, workdir, python_bin, candidate_patch=patch,
        env_extra=env_extra, timeout_s=timeout_s, runner=runner,
        extra_args=extra_args,
    )
    return SWEAttempt(instance_id=instance.instance_id, file_choice=chosen,
                      choice_reply_sha16=_sha16(choice.text),
                      diff_reply_sha16=_sha16(diff_reply.text),
                      proposal_accepted=True, verdict=verdict)


# --------------------------------------------------------------- الخلاصة
@dataclass(frozen=True)
class SWEAggregate:
    """خلاصة تشغيل كامل — الأرقام العامة الصادقة التي تُنشر."""

    total: int
    resolved_strict: int
    resolved_env: int
    f2p_repaired_total: int
    f2p_total: int
    applied_count: int
    contract_rejections: int
    gate_rejections: int

    @property
    def resolve_rate_env(self) -> float:
        return self.resolved_env / self.total if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "resolved_strict": self.resolved_strict,
            "resolved_env": self.resolved_env,
            "f2p_repaired_total": self.f2p_repaired_total,
            "f2p_total": self.f2p_total,
            "applied_count": self.applied_count,
            "contract_rejections": self.contract_rejections,
            "gate_rejections": self.gate_rejections,
            "resolve_rate_env": round(self.resolve_rate_env, 4),
        }


def aggregate(attempts: tuple[SWEAttempt, ...]) -> SWEAggregate:
    """اجمع المحاولات في خلاصة مرتبة — جمع صريح بلا تقريب أو تجميل.

    ``f2p_total`` يُحسب من اتحاد ما رُئي فعلاً من عقد FAIL_TO_PASS في كل
    محاولة (فشل أساس ∪ فشل بعد ∪ نجح بعد) — الصادق حتى في المحاولات التي
    لم تكتمل.
    """
    f2p_total = sum(
        len(set(a.verdict.f2p_failed_at_base)
            | set(a.verdict.f2p_failed_after)
            | set(a.verdict.f2p_passed_after))
        for a in attempts
    )
    return SWEAggregate(
        total=len(attempts),
        resolved_strict=sum(1 for a in attempts if a.verdict.resolved_strict),
        resolved_env=sum(1 for a in attempts if a.verdict.resolved_env),
        f2p_repaired_total=sum(a.verdict.f2p_repaired_count for a in attempts),
        f2p_total=f2p_total,
        applied_count=sum(1 for a in attempts if a.verdict.patch_applied),
        contract_rejections=sum(
            1 for a in attempts if a.verdict.contract_reason_ar and not a.verdict.patch_applied
        ),
        gate_rejections=sum(1 for a in attempts if not a.proposal_accepted),
    )
