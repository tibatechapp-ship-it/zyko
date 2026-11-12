"""zyko.sandbox.runner — أداة run_tests: اختبارات حقيقية بلا صدفة ولا سر.

هذه هي الجبهة التي وثّقتها الفجوة الصادقة: إعادة المحاولة تشغّل **اختبارات
حقيقية** لا مُصلِحًا حتميًا فقط. العقد الأربعة:

  1. **argv قائمة** — ``check_command`` في العقد يبيّح أول token من قائمة
     بيضاء ويرفض محارف الصدفة من كل token، والتنفيذ نفسه بلا shell
     إطلاقًا (``shell=False`` افتراضي ``subprocess``) — فما يُكتب نصًا
     واحدًا لا يُفتّل أمرًا.
  2. **بيئة بيضاء** — ``contract.sanitized_env()``: قائمة بيضاء دنيا،
     فلا مفتاح API ولا توكن يعبر إلى العملية الفرعية مهما كان في
     البيئة الأصل.
  3. **مهلة ومخرجات مسقوفة** — المهلة من العقد بحد مطلق 120 ثانية،
     والمخرجات tails مقطوعة عند سقف العقد حتميًا؛ تجاوز المهلة قرار
     موثق (exit_code=124) لا استثناء يهرب.
  4. **نتيجة حتمية قابلة للتوقيع** — ``to_dict`` بلا زمن ولا بيئة:
     نفس العملية تعطي نفس التمثيل، والعدّادات تُستخلص نصيًا من
     مخرجات pytest/unittest بأمانة (بلا عدّاد = بلا ادعاء).

  5. **حصر النواة** — ``jail``: على Linux ≥ 5.13 تُقيَّد كتابة الابن
     بـ Landlock في ``preexec_fn`` قبل ``exec`` — كود الاختبارات يُولد
     مقيداً لا يُولد حرًا ثم يُقيَّد؛ محاولته الكتابة خارج جذور العقد
     ومجلد الحرارة تفشل بـ ``EPERM`` من النواة نفسها، وفشل تقييد
     النواة إغلاق موثق (exit 126) لا تشغيل بلا عزل. المستوى الفعلي
     (landlock/bwrap/none) يُعلن في سجل التدقيق كما يُعلن — الصدق
     قبل التفاؤل.

حد الصدقة: تشغيل اختبارات مجلد ينفّذ كود ذلك المجلد (conftest.py مثلاً)
بعقده هو — العقد يقيّد ما يعبر من zyko إليه، وحصر النواة يقيّد ما يفعله
*داخله* كتابةً؛ القراءة مفتوحة عمدًا (تشغيل اختبارات مشروع يتطلب قراءته)
والشبكة لا تُمس تحت ABI v1–v3 — فجوتان موثقتان لا ثغرتان مخفيتان؛
وملف ``pytest.py`` في جذر المجلد يظلل المشغّل نفسه فيُرفض قبل
التشغيل — خطف المشغّل ليس اختبارًا.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from zyko.sandbox.contracts import PermissionContract
from zyko.sandbox.jail import JAIL_LEVEL_BWRAP, jail_level, jail_preexec, wrap_argv, write_roots

# ملفات ظلّ المشغّل — وجودها في جذر الجذر يجعل «python -m pytest» ينفّذ
# كود المخطف لا مشغّل الاختبارات الحقيقي — رفض قبل التشغيل لا ثقة
_RUNNER_SHADOW_FILES = ("pytest.py", "unittest.py", "_pytest.py")

# استخلاص العدادات من مخرجات pytest — أنماط السطر الخلاصي القياسية
_PYTEST_PASSED = re.compile(r"(\d+)\s+passed")
_PYTEST_FAILED = re.compile(r"(\d+)\s+failed")
_PYTEST_ERRORS = re.compile(r"(\d+)\s+errors?")
_PYTEST_SKIPPED = re.compile(r"(\d+)\s+skipped")
# unittest: "Ran N tests in 0.001s" + سطر الحالة
_UNTEST_RAN = re.compile(r"^Ran\s+(\d+)\s+tests?\b", re.MULTILINE)
_UNTEST_FAILURES = re.compile(r"failures=(\d+)")
_UNTEST_ERRORS = re.compile(r"errors=(\d+)")

_TIMEOUT_EXIT = 124  # اصطلاح GNU timeout — تجاوز المهلة قرار موثق


@dataclass(frozen=True)
class TestRunResult:
    """نتيجة تشغيل اختبارات موثقة: قرار، عدّادات مستخلصة، tails مسقوفة.

    ``ok`` حكم صادق: خروج صفر **فقط** — الخروج غير الصفر فشل حتى لو
    لم يُستخلص أي عدّاد، والأمانة قبل التفاؤل.
    """

    ok: bool
    exit_code: int
    timed_out: bool
    passed: int | None
    failed: int | None
    errors: int | None
    skipped: int | None
    command: str
    stdout_tail: str
    stderr_tail: str
    reason_ar: str

    def to_dict(self) -> dict:
        """ممثل JSON حتمي — بلا زمن ولا بيئة ولا مسارات مطلقة."""
        return {
            "command": self.command,
            "errors": self.errors,
            "exit_code": int(self.exit_code),
            "failed": self.failed,
            "ok": bool(self.ok),
            "passed": self.passed,
            "reason_ar": self.reason_ar,
            "skipped": self.skipped,
            "stderr_tail": self.stderr_tail,
            "stdout_tail": self.stdout_tail,
            "timed_out": bool(self.timed_out),
        }


def _tails(text: str, cap: int) -> str:
    """ذيل المخرجات المسقوف حتميًا — آخر المحارف (الخلاصة في النهاية)."""
    if cap <= 0:
        return ""
    return text[-cap:] if len(text) > cap else text


def _parse_counts(output: str) -> tuple[int | None, int | None, int | None, int | None]:
    """عدّادات pytest/unittest من النص — بلا نمط مطابق = بلا ادعاء."""
    passed = failed = errors = skipped = None
    m = _PYTEST_PASSED.search(output)
    if m:
        passed = int(m.group(1))
    m = _PYTEST_FAILED.search(output)
    if m:
        failed = int(m.group(1))
    m = _PYTEST_ERRORS.search(output)
    if m:
        errors = int(m.group(1))
    m = _PYTEST_SKIPPED.search(output)
    if m:
        skipped = int(m.group(1))
    m = _UNTEST_RAN.search(output)
    if m and passed is None:
        total = int(m.group(1))
        fm, em = _UNTEST_FAILURES.search(output), _UNTEST_ERRORS.search(output)
        failed = int(fm.group(1)) if fm else 0
        errors = int(em.group(1)) if em else 0
        passed = max(0, total - failed - errors)
    return passed, failed, errors, skipped


def run_tests(
    contract: PermissionContract,
    *,
    argv: object,
    cwd: object = None,
) -> TestRunResult:
    """شغّل اختبارات تحت العقد — بلا استثناء خارج: كل فشل نتيجة موثقة.

    ``cwd`` يُدقَّق ضد الجذور قبل التشغيل (افتراضيًا أول جذر)؛ والملف
    المختطف (``pytest.py`` في الجذر) يُرفض قبل أي عملية — خطف
    المشغّل رفض لا تشغيل.
    """
    # 1) العقد على الأمر
    tokens, reason = contract.check_command(argv)
    if tokens is None:
        return TestRunResult(
            ok=False,
            exit_code=2,
            timed_out=False,
            passed=None,
            failed=None,
            errors=None,
            skipped=None,
            command="",
            stdout_tail="",
            stderr_tail="",
            reason_ar=f"حارس الأمر رفض — {reason}",
        )
    # 2) دليل العمل داخل الجذور + حارس ملف الظل
    cwd_path, cwd_reason = contract.check_path(str(cwd) if cwd is not None else contract.roots[0])
    if cwd_path is None:
        return TestRunResult(
            ok=False,
            exit_code=2,
            timed_out=False,
            passed=None,
            failed=None,
            errors=None,
            skipped=None,
            command=" ".join(tokens),
            stdout_tail="",
            stderr_tail="",
            reason_ar=f"حارس الدليل رفض — {cwd_reason}",
        )
    for shadow in _RUNNER_SHADOW_FILES:
        if (cwd_path / shadow).is_file():
            return TestRunResult(
                ok=False,
                exit_code=2,
                timed_out=False,
                passed=None,
                failed=None,
                errors=None,
                skipped=None,
                command=" ".join(tokens),
                stdout_tail="",
                stderr_tail="",
                reason_ar=f"«{shadow}» في جذر التشغيل يظلّل المشغّل الحقيقي — رفض قبل التنفيذ",
            )
    # 3) التنفيذ: argv قائمة، بيئة بيضاء، مهلة من العقد، وحصر الكتابة بالنواة
    timeout = contract.timeout_s if contract.timeout_s > 0 else 1.0
    env = contract.sanitized_env()
    command_text = " ".join(tokens)
    timed_out = False
    # العزل النواتي: جذور العقد + مجلد الحرارة — الكتابة خارجها EPERM من النواة
    roots_for_jail = write_roots(contract.roots)
    preexec = jail_preexec(roots_for_jail)
    exec_argv = (
        wrap_argv(list(tokens), roots_for_jail) or list(tokens)
        if jail_level() == JAIL_LEVEL_BWRAP
        else list(tokens)
    )
    try:
        proc = subprocess.run(  # noqa: S603 — argv قائمة مفحوصة، بلا shell  # nosec B603
            exec_argv,
            cwd=str(cwd_path),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            preexec_fn=preexec,
        )
        exit_code = proc.returncode
        stdout, stderr = proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = _TIMEOUT_EXIT
        stdout = (
            (exc.stdout or b"").decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            (exc.stderr or b"").decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        stderr += f"\n[zyko] تجاوز المهلة {timeout} ثانية — أُنهي بالقوة"
    except OSError as exc:
        return TestRunResult(
            ok=False,
            exit_code=2,
            timed_out=False,
            passed=None,
            failed=None,
            errors=None,
            skipped=None,
            command=command_text,
            stdout_tail="",
            stderr_tail="",
            reason_ar=f"التشغيل فشل قبل البدء — {type(exc).__name__}",
        )
    passed, failed, errors, skipped = _parse_counts(stdout + "\n" + stderr)
    cap = contract.max_output_chars
    ok = exit_code == 0 and not timed_out
    if timed_out:
        reason_ar = f"تجاوز المهلة ({timeout} ثانية) — أُنهي بالقوة، لا حكم على الاختبارات"
    elif ok:
        counts = (
            "، ".join(
                f"{label} {value}"
                for label, value in (("نجح", passed), ("فشل", failed), ("أخطاء", errors))
                if value is not None
            )
            or "بلا عدّادات مستخلصة"
        )
        reason_ar = f"الاختبارات خضراء (خروج 0) — {counts}"
    else:
        counts = (
            "، ".join(
                f"{label} {value}"
                for label, value in (("فشل", failed), ("أخطاء", errors), ("نجح", passed))
                if value is not None
            )
            or "بلا عدّادات مستخلصة"
        )
        reason_ar = f"الاختبارات حمراء (خروج {exit_code}) — {counts}"
    return TestRunResult(
        ok=ok,
        exit_code=int(exit_code),
        timed_out=timed_out,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        command=command_text,
        stdout_tail=_tails(stdout, cap),
        stderr_tail=_tails(stderr, cap),
        reason_ar=reason_ar,
    )


__all__ = ["TestRunResult", "run_tests"]
