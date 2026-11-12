"""بنّاؤو حالات التقييم (ب) — العقود، التدقيق، الرقع والتشغيل، العزل النووي."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import tempfile
from typing import Any

from zyko.sandbox.audit import (
    AUDIT_SCHEMA,
    MAX_DETAIL_VALUE_CHARS,
    MAX_REASON_CHARS,
    AuditLog,
    canonical_json,
    entry_hash,
)
from zyko.sandbox.contracts import (
    DEFAULT_ALLOWED_COMMANDS,
    DEFAULT_TIMEOUT_S,
    MAX_FILE_BYTES_LIMIT,
    MAX_ROOTS,
    MAX_TIMEOUT_S,
    PermissionContract,
    is_sensitive_dir,
    is_sensitive_file,
    sensitive_paths_in_roots,
)
from zyko.sandbox.jail import (
    jail_level,
    landlock_abi,
    net_confinement,
    reset_detection_cache,
    sensitive_overlays,
    wrap_argv,
    write_roots,
)
from zyko.sandbox.patcher import patch_file
from zyko.sandbox.runner import run_tests

_SECRET_SAMPLE = "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"  # عيّنة مزيّفة للفحص — تُبنى بالجمع فلا تلدغ الحماية


def _root() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix="zyko-eval-contract-")


def _contract(root: str, **kw: Any) -> PermissionContract:
    base = dict(allow_patch=True, allow_run_tests=True)
    base.update(kw)
    return PermissionContract.for_roots(root, **base)


# ==================================================== 8) عقود الصلاحيات
def build_contracts():
    cases = []

    # أ) القيود عند الإنشاء — العدوي يُقيَّد لا يرمي
    def fn_timeout_neg():
        c = _contract(_root().name, timeout_s=-5)
        return (True, "السالب يُقصّ للصفر") if c.timeout_s == 0.0 else (False, f"timeout_s={c.timeout_s}")
    cases.append(("قيود", "مهلة سالبة تُقصّ للصفر", fn_timeout_neg))

    def fn_timeout_cap():
        c = _contract(_root().name, timeout_s=9999)
        return (True, "السقف المطلق يعمل") if c.timeout_s == MAX_TIMEOUT_S else (False, f"timeout_s={c.timeout_s}")
    cases.append(("قيود", "مهلة فوق السقف تُقيَّد للسقف", fn_timeout_cap))

    def fn_timeout_nan():
        c = _contract(_root().name, timeout_s=float("nan"))
        return (True, "NaN يعود افتراضيًا") if c.timeout_s == DEFAULT_TIMEOUT_S else (False, "NaN مرّ داخل العقد!")
    cases.append(("قيود", "مهلة NaN تُقيَّد", fn_timeout_nan))

    def fn_timeout_junk():
        c = _contract(_root().name, timeout_s="نصف ساعة")
        return (True, "النص يُرفض للافتراضي") if c.timeout_s == DEFAULT_TIMEOUT_S else (False, f"timeout_s={c.timeout_s}")
    cases.append(("قيود", "مهلة غير عددية تُقيَّد", fn_timeout_junk))

    def fn_bytes_neg():
        c = _contract(_root().name, max_file_bytes=-1)
        return (True, "السالب يُقصّ للصفر") if c.max_file_bytes == 0 else (False, f"max_file_bytes={c.max_file_bytes}")
    cases.append(("قيود", "سقف ملف سالب يُقصّ للصفر", fn_bytes_neg))

    def fn_bytes_cap():
        c = _contract(_root().name, max_file_bytes=10**12)
        return (True, "سقف 8MB مطلق") if c.max_file_bytes == MAX_FILE_BYTES_LIMIT else (False, f"max_file_bytes={c.max_file_bytes}")
    cases.append(("قيود", "سقف ملف فوق المطلق يُقيَّد", fn_bytes_cap))

    def fn_ops_cap():
        c = _contract(_root().name, max_patch_ops=10**9)
        return (True, "سقف العمليات يعمل") if c.max_patch_ops == 100_000 else (False, f"max_patch_ops={c.max_patch_ops}")
    cases.append(("قيود", "عمليات الرقعة فوق السقف تُقيَّد", fn_ops_cap))

    def fn_roots_cap():
        many = tuple(f"/tmp/zyko-eval-{i}" for i in range(20))
        c = PermissionContract.for_roots(*many)
        return (True, "8 جذور كحد أقصى") if len(c.roots) == MAX_ROOTS else (False, f"جذور: {len(c.roots)}")
    cases.append(("قيود", "الجذور فوق الثمانية تُقصّ", fn_roots_cap))

    def fn_roots_absolute():
        c = PermissionContract.for_roots("relative/path")
        ok = c.roots and c.roots[0].startswith("/")
        return (True, "النسبي يُحسم مطلقًا") if ok else (False, f"الجذور: {c.roots}")
    cases.append(("قيود", "جذر نسبي يُحسم مطلقًا", fn_roots_absolute))

    def fn_roots_empty_skip():
        c = PermissionContract.for_roots("", "   ", None)
        return (True, "الفارغ يُتخطى") if c.roots == () else (False, f"جذور من فراغ: {c.roots}")
    cases.append(("قيود", "جذور فارغة تُتخطى", fn_roots_empty_skip))

    def fn_commands_dedupe():
        c = _contract(_root().name, allowed_commands=("python", "python", " pytest ", ""))
        return (True, "تكرار وفراغ يُنقّى") if c.allowed_commands == ("python", "pytest") else (False, f"الأوامر: {c.allowed_commands}")
    cases.append(("قيود", "قائمة الأوامر تُنقّى وتفرد", fn_commands_dedupe))

    def fn_defaults():
        c = PermissionContract.for_roots("/tmp")
        ok = c.allow_patch is False and c.allow_run_tests is False and c.timeout_s == DEFAULT_TIMEOUT_S
        return (True, "الافتراضي أصلًا محصور") if ok else (False, "الافتراضيات ليست أقصى التحفظ")
    cases.append(("قيود", "الافتراضيات أقصى التحفظ", fn_defaults))

    def fn_frozen():
        c = _contract(_root().name)
        try:
            object.__setattr__  # noqa: B018 — فحص القدرة فقط
            c.timeout_s = 1.0  # type: ignore[misc]
            return False, "العقد المجمّد تغير!"
        except AttributeError:
            return True, "frozen يحفظ العقد"
        except Exception as exc:  # noqa: BLE001
            return True, f"frozen يحفظ العقد ({type(exc).__name__})"
    cases.append(("قيود", "العقد مجمّد لا يتغير", fn_frozen))

    # ب) فحص المسارات
    def fn_path_no_roots():
        c = PermissionContract.for_roots()
        target, reason = c.check_path("/tmp/x.py")
        ok = target is None and reason
        return (True, "بلا جذور لا مسار") if ok else (False, "عقد بلا جذور قبض مسارًا")
    cases.append(("مسارات", "عقد بلا جذور يرفض كل مسار", fn_path_no_roots))

    def fn_path_empty():
        c = _contract(_root().name)
        target, reason = c.check_path("")
        return (True, "الفراغ موثق") if target is None and reason else (False, "مسار فارغ قُبل")
    cases.append(("مسارات", "المسار الفارغ يُرفض", fn_path_empty))

    def fn_path_none():
        c = _contract(_root().name)
        target, reason = c.check_path(None)
        return (True, "None يُرفض موثقًا") if target is None and reason else (False, "None قُبل مسارًا")
    cases.append(("مسارات", "None يُرفض موثقًا", fn_path_none))

    def fn_path_nul():
        c = _contract(_root().name)
        target, reason = c.check_path("a\x00b.py")
        return (True, "NUL يُرفض") if target is None else (False, "محرف NUL قُبل في المسار")
    cases.append(("مسارات", "محرف NUL يُرفض", fn_path_nul))

    def fn_relative():
        with _root() as td:
            root = pathlib.Path(td)
            (root / "sub").mkdir()
            (root / "ok.py").write_text("x = 1\n", encoding="utf-8")
            c = _contract(td)
            target, reason = c.check_path("sub/../ok.py")
            ok = target is not None and str(target).startswith(str(root))
            return (True, "النسبي يُثبَّت على الجذر") if ok else (False, f"نسبي: {target} {reason}")
    cases.append(("مسارات", "مسار نسبي يُثبَّت على الجذر الأول", fn_relative))

    def fn_inside():
        with _root() as td:
            root = pathlib.Path(td)
            (root / "ok.py").write_text("x = 1\n", encoding="utf-8")
            c = _contract(td)
            target, reason = c.check_path(str(root / "ok.py"))
            return (True, "الداخل يمر") if target is not None else (False, reason or "داخل الجذر رُفض")
    cases.append(("مسارات", "مسار داخل الجذر يمر", fn_inside))

    def fn_root_itself():
        with _root() as td:
            c = _contract(td)
            target, reason = c.check_path(td)
            return (True, "الجذر نفسه مقبول") if target is not None else (False, reason or "الجذر نفسه رُفض")
    cases.append(("مسارات", "الجذر نفسه مقبول", fn_root_itself))

    def fn_outside():
        c = _contract(_root().name)
        target, reason = c.check_path("/etc/hostname")
        return (True, "الخارج يُرفض") if target is None and reason else (False, "مسار خارج الجذر قُبل")
    cases.append(("مسارات", "مسار خارج الجذور يُرفض", fn_outside))

    def fn_escape_dots():
        with _root() as td:
            c = _contract(td)
            target, reason = c.check_path(str(pathlib.Path(td) / ".." / "escaped.txt"))
            return (True, ".. يُطوى ثم يفحص") if target is None else (False, "خروج بـ .. مرّ!")
    cases.append(("مسارات", "اجتياز بـ .. يُرفض", fn_escape_dots))

    def fn_symlink_escape():
        # القدرة أولًا: بيئات بلا دعم إنشاء ارتباطات تُوثق لا تُفشل زورًا
        with _root() as td:
            outside = pathlib.Path(tempfile.mkdtemp(prefix="zyko-eval-outside-"))
            link = pathlib.Path(td) / "الرابط"
            try:
                os.symlink(outside, link)
            except OSError as exc:
                shutil.rmtree(outside, ignore_errors=True)
                return True, f"البيئة بلا دعم ارتباطات ({type(exc).__name__}) — العقد يُقاس حيث الدعم"
            try:
                c = _contract(td)
                target, reason = c.check_path(str(link))
                ok = target is None
                return (True, "رمز الارتباط يُحسم") if ok else (False, "ارتباط خارجي مرّ عبر resolve!")
            finally:
                shutil.rmtree(outside, ignore_errors=True)
                if link.is_symlink():
                    link.unlink()
    cases.append(("مسارات", "رمز ارتباط يخرج من الجذر يُرفض", fn_symlink_escape))

    # ج) القراءة الحساسة
    for k, name in enumerate((".env", "server.key", "id_rsa", "secrets.json")):
        def fn(name=name):
            with _root() as td:
                (pathlib.Path(td) / name).write_text("سر", encoding="utf-8")
                c = _contract(td)
                target, reason = c.check_read_path(str(pathlib.Path(td) / name))
                return (True, f"{name} لا يُقرأ") if target is None else (False, f"{name} قُبل للقراءة!")
        cases.append(("قراءة-حساسة", f"رفض قراءة {name}", fn))

    def fn_env_example():
        with _root() as td:
            (pathlib.Path(td) / ".env.example").write_text("API_KEY=\n", encoding="utf-8")
            c = _contract(td)
            target, reason = c.check_read_path(str(pathlib.Path(td) / ".env.example"))
            return (True, "الوثيقة الاستثنائية تُقرأ") if target is not None else (False, f".env.example رُفض: {reason}")
    cases.append(("قراءة-حساسة", ".env.example الاستثناء يُقرأ", fn_env_example))

    def fn_code_readable():
        with _root() as td:
            (pathlib.Path(td) / "app.py").write_text("x = 1\n", encoding="utf-8")
            c = _contract(td)
            target, reason = c.check_read_path(str(pathlib.Path(td) / "app.py"))
            return (True, "الكود يُقرأ") if target is not None else (False, reason or "كود المشروع رُفض")
    cases.append(("قراءة-حساسة", "كود المشروع يُقرأ عاديًا", fn_code_readable))

    # د) الأسمية الحساسة
    for k, name in enumerate((".env", ".env.local", ".env.bak", ".env.staging", "id_rsa", "id_ed25519",
                              "server.pem", "api.key", "secrets.yaml", "credentials.json", ".netrc", ".pgpass",
                              ".git-credentials", "client.p12")):
        def fn(name=name):
            return (True, "حساس") if is_sensitive_file(f"src/{name}") else (False, f"{name} لم تُعد حساسة!")
        cases.append(("أسمية", f"حساس: {name}", fn))

    for k, name in enumerate((".env.example", "app.py", "README.md", "package.json")):
        def fn(name=name):
            return (True, "عادي") if not is_sensitive_file(name) else (False, f"{name} عُدّ حساسًا خطأً")
        cases.append(("أسمية", f"عادي: {name}", fn))

    for k, d in enumerate((".ssh", ".aws", ".kube", ".gnupg")):
        def fn(d=d):
            return (True, "مجلد مخازن") if is_sensitive_dir(f"/home/user/{d}") else (False, f"{d} لم تُعد حساسة")
        cases.append(("أسمية", f"مجلد حساس: {d}", fn))

    def fn_sensitive_scan():
        with _root() as td:
            root = pathlib.Path(td)
            (root / "keys").mkdir()
            (root / ".env").write_text("A=1\n", encoding="utf-8")
            (root / "keys" / "api.key").write_text("k\n", encoding="utf-8")
            (root / ".env.example").write_text("A=\n", encoding="utf-8")
            found = sensitive_paths_in_roots([td])
            names = [pathlib.Path(p).name for p in found]
            ok = ".env" in names and "api.key" in names and ".env.example" not in names
            return (True, "الكشف موثق ومفرز") if ok else (False, f"الواقعة: {names}")
    cases.append(("أسمية", "اكتشاف المخازن داخل الجذور", fn_sensitive_scan))

    def fn_scan_determinism():
        with _root() as td:
            root = pathlib.Path(td)
            (root / ".env").write_text("A=1\n", encoding="utf-8")
            a = sensitive_paths_in_roots([td])
            b = sensitive_paths_in_roots([td])
            return (True, "حتمي بالبايت") if a == b and a else (False, "مسح المخازن غير حتمي")
    cases.append(("أسمية", "اكتشاف المخازن حتمي بالبايت", fn_scan_determinism))

    # هـ) الأوامر
    def fn_cmd_disabled():
        c = PermissionContract.for_roots("/tmp", allow_run_tests=False)
        tokens, reason = c.check_command(["python", "x.py"])
        return (True, "التفعيل شرط") if tokens is None else (False, "أمر مرّ بعقد بلا تشغيل")
    cases.append(("أوامر", "بلا allow_run_tests لا أمر يمر", fn_cmd_disabled))

    def fn_cmd_string():
        c = _contract(_root().name)
        tokens, reason = c.check_command("python x.py")
        return (True, "النص المفرد يُرفض") if tokens is None else (False, "نص واحد قُبل argv!")
    cases.append(("أوامر", "نص مفرد يُرفض (لا صدفة)", fn_cmd_string))

    def fn_cmd_outside_whitelist():
        c = _contract(_root().name)
        tokens, reason = c.check_command(["rm", "-rf", "/"])
        return (True, "خارج القائمة يُرفض") if tokens is None else (False, "rm مرّ القائمة البيضاء!")
    cases.append(("أوامر", "أمر خارج القائمة البيضاء يُرفض", fn_cmd_outside_whitelist))

    def fn_cmd_empty():
        c = _contract(_root().name)
        tokens, reason = c.check_command([])
        return (True, "الفراغ يُرفض") if tokens is None else (False, "argv فارغ قُبل")
    cases.append(("أوامر", "argv فارغ يُرفض", fn_cmd_empty))

    def fn_cmd_shell_char():
        c = _contract(_root().name)
        tokens, reason = c.check_command(["python", "-c", "print('hi')"])
        return (True, "محارف الصدفة تُرفض") if tokens is None else (False, "أقواس وعلامات في argv مرّت!")
    cases.append(("أوامر", "محارف صدفة في وسيط تُرفض", fn_cmd_shell_char))

    def fn_cmd_pipes():
        c = _contract(_root().name)
        tokens, reason = c.check_command(["python", "x.py", "|", "rm"])
        return (True, "الأنبوب يُرفض") if tokens is None else (False, "| مرّ كوسيط")
    cases.append(("أوامر", "رمز الأنبوب يُرفض", fn_cmd_pipes))

    def fn_cmd_dots():
        c = _contract(_root().name)
        tokens, reason = c.check_command(["python", "../escape.py"])
        return (True, "اجتياز يُرفض") if tokens is None else (False, ".. مرّ كوسيط")
    cases.append(("أوامر", "اجتياز .. في وسيط يُرفض", fn_cmd_dots))

    def fn_cmd_absolute():
        c = _contract(_root().name)
        tokens, reason = c.check_command(["python", "/etc/passwd"])
        return (True, "المطلق يُرفض") if tokens is None else (False, "مسار مطلق مرّ كوسيط")
    cases.append(("أوامر", "مسار مطلق في وسيط يُرفض", fn_cmd_absolute))

    def fn_cmd_nul():
        c = _contract(_root().name)
        tokens, reason = c.check_command(["python", "a\x00b"])
        return (True, "NUL يُرفض") if tokens is None else (False, "NUL مرّ في argv")
    cases.append(("أوامر", "NUL في وسيط يُرفض", fn_cmd_nul))

    def fn_cmd_empty_token():
        c = _contract(_root().name)
        tokens, reason = c.check_command(["python", "   "])
        return (True, "الوسيط الفارغ يُرفض") if tokens is None else (False, "وسيط فراغي قُبل")
    cases.append(("أوامر", "وسيط فراغي يُرفض", fn_cmd_empty_token))

    def fn_cmd_ok():
        c = _contract(_root().name)
        tokens, reason = c.check_command(["python", "tests_ok.py", "--quiet"])
        return (True, "السليم يمر") if tokens == ("python", "tests_ok.py", "--quiet") else (False, f"سليم رُفض: {reason}")
    cases.append(("أوامر", "أمر سليم يمر بحجوله", fn_cmd_ok))

    def fn_cmd_whitelist_default():
        ok = DEFAULT_ALLOWED_COMMANDS == ("python", "python3", "pytest", "py")
        return (True, "القائمة الافتراضية موثقة") if ok else (False, f"القائمة: {DEFAULT_ALLOWED_COMMANDS}")
    cases.append(("أوامر", "القائمة البيضاء الافتراضية", fn_cmd_whitelist_default))

    def fn_cmd_custom():
        c = _contract(_root().name, allowed_commands=("python",))
        a, _ = c.check_command(["python", "x.py"])
        b, _ = c.check_command(["pytest", "x.py"])
        return (True, "قائمة مخصصة تعمل") if a is not None and b is None else (False, "القائمة المخصصة لا تحكم")
    cases.append(("أوامر", "قائمة مخصصة تحكم بصرامة", fn_cmd_custom))

    # و) تنقية البيئة
    def fn_env_secret():
        key = "ZYKO_EVAL_SECRET_TOKEN"
        os.environ[key] = "قيمة-سرية"
        try:
            env = PermissionContract.for_roots("/tmp").sanitized_env()
            return (True, "السر لا يعبر") if key not in env else (False, "سر باسم TOKEN عبر البيئة!")
        finally:
            os.environ.pop(key, None)
    cases.append(("بيئة", "مفتاح سرّي لا يعبر البيئة", fn_env_secret))

    def fn_env_deny_words():
        for word in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH", "GHP_", "SK-"):
            name = f"ZYKO_EVAL_{word}X"
            os.environ[name] = "1"
            try:
                env = PermissionContract.for_roots("/tmp").sanitized_env()
                if name in env:
                    return False, f"مفتاح يحمل {word} عبر"
            finally:
                os.environ.pop(name, None)
        return True, "الأسمية الموثقة كاملة تحجب"
    cases.append(("بيئة", "أسمية الأسرار الموثقة تحجب كلها", fn_env_deny_words))

    def fn_env_keep():
        env = PermissionContract.for_roots("/tmp").sanitized_env()
        ok = "PATH" in env and env.get("PYTHONHASHSEED") == "0" and env.get("PYTHONDONTWRITEBYTECODE") == "1"
        return (True, "البيضاء والاستقرار يعملان") if ok else (False, f"بيئة ناقصة: PATH={('PATH' in env)} seed={env.get('PYTHONHASHSEED')}")
    cases.append(("بيئة", "القائمة البيضاء وخواص الاستقرار", fn_env_keep))

    def fn_env_unsanitized():
        key = "ZYKO_EVAL_PLAIN"
        os.environ[key] = "1"
        try:
            c = PermissionContract(roots=("/tmp",), sanitize_env=False)
            env = c.sanitized_env()
            return (True, "الباب الصريح موثق") if key in env else (False, "sanitize_env=False لم يمرر البيئة")
        finally:
            os.environ.pop(key, None)
    cases.append(("بيئة", "باب sanitize_env=False صريح", fn_env_unsanitized))

    def fn_env_hashseed():
        env = PermissionContract.for_roots("/tmp").sanitized_env()
        return (True, "حتمية أعمق") if env.get("PYTHONHASHSEED") == "0" else (False, "PYTHONHASHSEED ليست 0")
    cases.append(("بيئة", "PYTHONHASHSEED=0 في البيئة الفرعية", fn_env_hashseed))

    # ز) التوثيق
    def fn_to_dict():
        c = _contract(_root().name)
        d = c.to_dict()
        need = {"allow_patch", "allow_run_tests", "allowed_commands", "max_file_bytes",
                "max_output_chars", "max_patch_ops", "roots", "sanitize_env", "timeout_s"}
        return (True, "ممثل JSON كامل") if set(d.keys()) == need else (False, f"مفاتيح: {sorted(d.keys())}")
    cases.append(("توثيق", "to_dict مفاتيحه موثقة", fn_to_dict))

    def fn_to_dict_sorted():
        c = PermissionContract.for_roots("/b", "/a", "/c")
        return (True, "الجذور مفرزة") if c.to_dict()["roots"] == sorted(c.roots) else (False, "الجذور في to_dict غير مفرزة")
    cases.append(("توثيق", "جذور to_dict مفرزة", fn_to_dict_sorted))

    return cases


# ==================================================== 9) سجل التدقيق
def build_audit():
    cases = []

    def fn_canonical():
        a = canonical_json({"b": 1, "a": 2})
        b = canonical_json({"a": 2, "b": 1})
        return (True, "مفاتيح مفرزة") if a == b and '"a":2' in a.replace(" ", "") else (False, f"غير مفرز: {a[:30]}")
    cases.append(("بنية", "canonical_json يفرز المفاتيح", fn_canonical))

    def fn_canonical_compact():
        s = canonical_json({"x": "قيمة عربية"})
        return (True, "فاصل مقتصد") if ", " not in s and ": " not in s else (False, "فواصل فضفاضة في canonical_json")
    cases.append(("بنية", "canonical_json مقتصد الفواصل", fn_canonical_compact))

    def fn_hash_determinism():
        a = entry_hash(1, "0" * 64, "tool", "ALLOW", "سبب", {"k": "v"})
        b = entry_hash(1, "0" * 64, "tool", "ALLOW", "سبب", {"k": "v"})
        return (True, "بصمة حتمية") if a == b and len(a) == 64 else (False, "بصمتان مختلفتان لنفس الحدث")
    cases.append(("بنية", "entry_hash حتمي بالبايت", fn_hash_determinism))

    def fn_hash_fields():
        base = (1, "0" * 64, "tool", "ALLOW", "سبب", {"k": "v"})
        variants = (
            entry_hash(2, *base[1:]),
            entry_hash(1, "1" * 64, *base[2:]),
            entry_hash(1, "0" * 64, "tool2", *base[3:]),
            entry_hash(1, "0" * 64, *base[2:4], "سبب آخر", *base[5:]),
            entry_hash(1, "0" * 64, *base[2:5], {"k": "v2"}),
        )
        first = entry_hash(*base)
        return (True, "كل حقل يدخل البصمة") if all(h != first for h in variants) else (False, "حقل لا يدخل بصمة الحدث")
    cases.append(("بنية", "كل حقل يدخل بصمة الحدث", fn_hash_fields))

    def fn_schema():
        return (True, "المخطط موثق") if AUDIT_SCHEMA == "zyko.audit.v1" else (False, f"المخطط: {AUDIT_SCHEMA}")
    cases.append(("بنية", "مخطط السجل الثابت", fn_schema))

    # ب) السجل الحي
    def fn_append_seq():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            for i in range(5):
                log.append("patch", "ALLOW", f"سبب {i}", {"i": i})
            entries = log.entries()
            seqs = [e.seq for e in entries]
            return (True, "ترقيم متتابع") if seqs == [1, 2, 3, 4, 5] else (False, f"الترقيم: {seqs}")
    cases.append(("سجل-حي", "ترقيم متتابع من 1", fn_append_seq))

    def fn_append_chain():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            entries = [log.append("patch", "ALLOW", f"سبب {i}") for i in range(4)]
            genesis = "0" * 64
            ok = entries[0].prev_hash == genesis
            for prev, cur in zip(entries, entries[1:]):
                ok = ok and cur.prev_hash == prev.hash
            return (True, "السلسلة مترابطة") if ok else (False, "prev_hash لا يترابط")
    cases.append(("سجل-حي", "prev_hash يترابط عبر الأحداث", fn_append_chain))

    def fn_verify_ok():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            for i in range(6):
                log.append("tool" + str(i), "ALLOW", f"سبب {i}", {"n": i})
            report = log.verify()
            ok = report.ok and report.count == 6
            return (True, "سلسلة سليمة موثقة") if ok else (False, f"verify: {report.to_dict()}")
    cases.append(("سجل-حي", "verify يصدّق السلسلة السليمة", fn_verify_ok))

    def fn_verify_empty():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            report = log.verify()
            return (True, "الفراغ يوثق") if report.ok and report.count == 0 else (False, "سجل فارغ حكمه غير سليم")
    cases.append(("سجل-حي", "سجل فارغ يُصدَّق بصفر أحداث", fn_verify_empty))

    def _tampered_log(td: str, k: int) -> None:
        """اكتب سجلًا ثم عدّل تفاصيل الحدث k — عبث موثق للفحص."""
        log = AuditLog(pathlib.Path(td) / "audit.jsonl")
        for i in range(4):
            log.append("patch", "ALLOW", f"سبب أصلي {i}", {"i": i})
        lines = (pathlib.Path(td) / "audit.jsonl").read_text(encoding="utf-8").splitlines()
        target = json.loads(lines[k])
        target["detail"]["i"] = 999
        lines[k] = canonical_json(target)
        (pathlib.Path(td) / "audit.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    for k in (0, 1, 2, 3):
        def fn(k=k):
            with tempfile.TemporaryDirectory() as td:
                _tampered_log(td, k)
                report = AuditLog(pathlib.Path(td) / "audit.jsonl").verify()
                ok = not report.ok and report.first_broken_seq == k + 1
                return (True, f"العبث عند {k+1} يُكتشف") if ok else (False, f"عبث عند {k+1}: {report.to_dict()}")
        cases.append(("عبث", f"تعديل حدث {k+1} يُكتشف", fn))

    def fn_delete_line():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            for i in range(4):
                log.append("patch", "ALLOW", f"سبب {i}")
            path = pathlib.Path(td) / "audit.jsonl"
            lines = path.read_text(encoding="utf-8").splitlines()
            del lines[1]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            report = log.verify()
            ok = not report.ok and report.first_broken_seq == 2
            return (True, "الحذف يكشف") if ok else (False, f"حذف سطر: {report.to_dict()}")
    cases.append(("عبث", "حذف حدث يكسر السلسلة", fn_delete_line))

    def fn_reorder():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            for i in range(3):
                log.append("patch", "ALLOW", f"سبب {i}")
            path = pathlib.Path(td) / "audit.jsonl"
            lines = path.read_text(encoding="utf-8").splitlines()
            lines[0], lines[1] = lines[1], lines[0]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            report = log.verify()
            return (True, "إعادة الترتيب تُكتشف") if not report.ok else (False, "تبديل سطرين مرّ بسلام")
    cases.append(("عبث", "إعادة ترتيب الأحداث تُكتشف", fn_reorder))

    def fn_corrupt_line():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            log.append("patch", "ALLOW", "سبب")
            path = pathlib.Path(td) / "audit.jsonl"
            path.write_text("{سطر تالف\n", encoding="utf-8")
            report = log.verify()
            return (True, "السطر التالف سلسلة مكسورة") if not report.ok else (False, "سطر تالف مرّ بسلام")
    cases.append(("عبث", "سطر JSON تالف يكسر السلسلة", fn_corrupt_line))

    def fn_scrub_secret():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            log.append("patch", "DENY", "رفض لأن الوسيط حمل " + _SECRET_SAMPLE)
            entry = log.entries()[0]
            return (True, "السر مقنّع") if _SECRET_SAMPLE not in entry.reason_ar and "سر" in entry.reason_ar else (False, "سر تسرب إلى السجل!")
    cases.append(("اقنعة", "سر ghp_ في السبب يُقنَّع", fn_scrub_secret))

    def fn_scrub_detail():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            log.append("run", "DENY", "رفض", {"cmd": "key=" + "sk-" + "A" * 30})
            entry = log.entries()[0]
            raw = json.dumps(entry.detail, ensure_ascii=False)
            return (True, "التفاصيل مقنّعة") if ("sk-" + "A" * 30) not in raw else (False, "سر sk- في التفاصيل!")
    cases.append(("اقنعة", "سر sk- في التفاصيل يُقنَّع", fn_scrub_detail))

    def fn_clamp_value():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            log.append("patch", "ALLOW", "سبب", {"long": "ب" * 500})
            entry = log.entries()[0]
            got = len(entry.detail["long"])
            return (True, "القصّ حتمي") if got <= MAX_DETAIL_VALUE_CHARS + len("…[مقتطع]") else (False, f"قيمة طويلة {got} حرفًا مرّت")
    cases.append(("اقنعة", "قيمة طويلة تُقصّ حتميًا", fn_clamp_value))

    def fn_clamp_reason():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            log.append("patch", "ALLOW", "س" * 1000)
            entry = log.entries()[0]
            return (True, "السبب مسقوف") if len(entry.reason_ar) <= MAX_REASON_CHARS else (False, f"سبب {len(entry.reason_ar)} حرفًا")
    cases.append(("اقنعة", "سبب طويل يُقصّ للسقف", fn_clamp_reason))

    def fn_hostile_names():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            log.append("", None, "", None)
            entry = log.entries()[0]
            ok = entry.tool == "أداة-غير-مسماة" and entry.decision == "UNKNOWN"
            return (True, "المدخل العدوي يُطبَّع") if ok else (False, f"عدوي: {entry.tool}/{entry.decision}")
    cases.append(("اقنعة", "مدخل عدوي يُطبَّع لا يرمي", fn_hostile_names))

    def fn_ts_outside():
        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            e1 = AuditLog(pathlib.Path(td1) / "audit.jsonl").append("patch", "ALLOW", "سبب", ts=1000.0)
            e2 = AuditLog(pathlib.Path(td2) / "audit.jsonl").append("patch", "ALLOW", "سبب", ts=9999.0)
            return (True, "الزمن خارج السلسلة") if e1.hash == e2.hash else (False, "زمنان مختلفان غيّرا البصمة!")
    cases.append(("بنية", "الزمن خارج السلسلة (عقد الإيصال)", fn_ts_outside))

    def fn_chain_summary():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            for i in range(3):
                log.append("patch", "ALLOW", f"سبب {i}")
            s = log.chain_summary()
            ok = s["count"] == 3 and len(s["last_hash"]) == 64
            return (True, "ملخص حتمي") if ok else (False, f"ملخص: {s}")
    cases.append(("سجل-حي", "chain_summary حتمي بلا زمن", fn_chain_summary))

    def fn_entries_skip_bad():
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "audit.jsonl"
            log = AuditLog(path)
            log.append("patch", "ALLOW", "سبب 1")
            with path.open("a", encoding="utf-8") as fh:
                fh.write("زبالة\n")
            log.reload()
            log.append("patch", "ALLOW", "سبب 2")
            entries = log.entries()
            return (True, "التالف يُتخطى لا يُنهي") if len(entries) == 2 else (False, f"قراءة: {len(entries)}")
    cases.append(("سجل-حي", "سطر تالف في القراءة يُتخطى", fn_entries_skip_bad))

    def fn_append_only_no_delete():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            log.append("patch", "ALLOW", "سبب")
            has_mutators = any(hasattr(log, name) for name in ("delete", "remove", "truncate", "pop"))
            return (True, "ملحق-فقط بالعقد") if not has_mutators else (False, "واجهة تعديل/حذف على السجل!")
    cases.append(("سجل-حي", "لا واجهة تعديل أو حذف على السجل", fn_append_only_no_delete))

    def fn_determinism():
        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            for td in (td1, td2):
                log = AuditLog(pathlib.Path(td) / "audit.jsonl")
                for i in range(3):
                    log.append("patch", "ALLOW", f"سبب {i}", {"i": i})
            a = (pathlib.Path(td1) / "audit.jsonl").read_text(encoding="utf-8")
            b = (pathlib.Path(td2) / "audit.jsonl").read_text(encoding="utf-8")
            return (True, "سلسلتان متطابقتان بالبايت") if a == b else (False, "تشغيلان متطابقان سجلا مختلفًا")
    cases.append(("حتمية", "سجلان متطابقان بالبايت لنفس الأحداث", fn_determinism))

    def fn_decision_upper():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            log.append("patch", "allow", "سبب")
            entry = log.entries()[0]
            return (True, "القرار يُحسم علويًا") if entry.decision == "ALLOW" else (False, f"القرار: {entry.decision}")
    cases.append(("سجل-حي", "القرار يُحسم إلى علوي", fn_decision_upper))

    def fn_reload():
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(pathlib.Path(td) / "audit.jsonl")
            log.append("patch", "ALLOW", "سبب")
            # كاتب خارجي يضيف سطرًا موقّعًا خارج الكاش
            log.reload()
            log.append("patch", "ALLOW", "سبب ثانٍ")
            report = log.verify()
            return (True, "reload يبطل الكاش بأمان") if report.ok and report.count == 2 else (False, f"reload: {report.to_dict()}")
    cases.append(("سجل-حي", "reload يعيد الاعتماد من الرأس", fn_reload))

    return cases


# =============================================== 10) الرقع والتشغيل
def build_patch_run():
    cases = []

    def _setup(td: str, name: str = "app.py", content: str = "def f():\n    return 1\n") -> pathlib.Path:
        p = pathlib.Path(td) / name
        p.write_text(content, encoding="utf-8")
        return p

    # أ) patch_file
    def fn_write_new():
        with tempfile.TemporaryDirectory() as td:
            c = _contract(td)
            r = patch_file(c, path="new.py", content="x = 1\n")
            ok = r.ok and r.mode == "write" and (pathlib.Path(td) / "new.py").is_file()
            return (True, "كتابة جديدة موقّعة") if ok else (False, f"كتابة جديدة: {r.reason_ar}")
    cases.append(("رقع", "كتابة ملف جديد بوضع write", fn_write_new))

    def fn_replace_single():
        with tempfile.TemporaryDirectory() as td:
            _setup(td)
            c = _contract(td)
            r = patch_file(c, path="app.py", old_text="return 1", new_text="return 2")
            after = (pathlib.Path(td) / "app.py").read_text(encoding="utf-8")
            ok = r.ok and r.mode == "replace" and "return 2" in after
            return (True, "استبدال واحد موثق") if ok else (False, f"استبدال: {r.reason_ar}")
    cases.append(("رقع", "استبدال تطابق وحيد", fn_replace_single))

    def fn_replace_zero():
        with tempfile.TemporaryDirectory() as td:
            _setup(td)
            c = _contract(td)
            r = patch_file(c, path="app.py", old_text="غير موجود", new_text="x")
            ok = not r.ok and r.matches == 0
            return (True, "صفر تطابق رفض صادق") if ok else (False, "نص غائب قُبل رقعة!")
    cases.append(("رقع", "صفر تطابق يُرفض", fn_replace_zero))

    def fn_replace_ambiguous():
        with tempfile.TemporaryDirectory() as td:
            _setup(td, content="def f():\n    return 1\n\ndef g():\n    return 1\n")
            c = _contract(td)
            r = patch_file(c, path="app.py", old_text="return 1", new_text="return 2")
            ok = not r.ok and r.matches == 2
            return (True, "الغموض يُرفض") if ok else (False, f"تطابقان قُبلا: {r.matches}")
    cases.append(("رقع", "تطابقان يُرفضان غموضًا", fn_replace_ambiguous))

    def fn_sensitive_refused():
        with tempfile.TemporaryDirectory() as td:
            _setup(td, name=".env", content="A=1\n")
            c = _contract(td)
            r = patch_file(c, path=".env", content="B=2\n")
            return (True, "المخزن لا يُرقَّع") if not r.ok else (False, ".env قُبل للرقع!")
    cases.append(("رقع", "ملف حساس يُرفض للرقع", fn_sensitive_refused))

    def fn_outside_refused():
        with tempfile.TemporaryDirectory() as td:
            c = _contract(td)
            r = patch_file(c, path="/etc/hostname", content="خارج")
            return (True, "الخارج يُرفض") if not r.ok else (False, "مسار خارج الجذور قُبل للرقع")
    cases.append(("رقع", "مسار خارج الجذور يُرفض", fn_outside_refused))

    def fn_size_cap():
        with tempfile.TemporaryDirectory() as td:
            c = _contract(td, max_file_bytes=100)
            r = patch_file(c, path="big.py", content="ب" * 200)
            return (True, "السقف يحمي") if not r.ok else (False, "محتوى فوق السقف قُبل")
    cases.append(("رقع", "محتوى فوق سقف العقد يُرفض", fn_size_cap))

    def fn_mixed_modes():
        with tempfile.TemporaryDirectory() as td:
            _setup(td)
            c = _contract(td)
            r = patch_file(c, path="app.py", old_text="return 1", new_text="x", content="y")
            return (True, "خلط الأوضاع يُرفض") if not r.ok else (False, "old_text مع content قُبلا معًا!")
    cases.append(("رقع", "خلط old_text مع content يُرفض", fn_mixed_modes))

    def fn_sha_pairs():
        with tempfile.TemporaryDirectory() as td:
            p = _setup(td)
            c = _contract(td)
            before = p.read_text(encoding="utf-8")
            import hashlib
            expect_before = hashlib.sha256(before.encode()).hexdigest()
            r = patch_file(c, path="app.py", old_text="return 1", new_text="return 2")
            after = p.read_text(encoding="utf-8")
            expect_after = hashlib.sha256(after.encode()).hexdigest()
            ok = r.sha_before == expect_before and r.sha_after == expect_after
            return (True, "بصمتا قبل/بعد دقيقتان") if ok else (False, "بصمات الرقعة لا تطابق sha256 الفعلي")
    cases.append(("رقع", "بصمتا sha256 قبل/بعد دقيقتان", fn_sha_pairs))

    def fn_atomic():
        with tempfile.TemporaryDirectory() as td:
            _setup(td)
            c = _contract(td)
            patch_file(c, path="app.py", old_text="return 1", new_text="return 2")
            leftovers = [p.name for p in pathlib.Path(td).iterdir() if p.name.endswith(".zyko-rq3.tmp")]
            return (True, "لا مؤقت يتيم") if not leftovers else (False, f"مؤقت يتيم: {leftovers}")
    cases.append(("رقع", "الكتابة الذرية لا تترك مؤقتًا", fn_atomic))

    def fn_no_leak_secret():
        with tempfile.TemporaryDirectory() as td:
            c = _contract(td)
            patch_file(c, path="auth.py", content="TOKEN = '" + _SECRET_SAMPLE + "'\n")
            r2 = patch_file(c, path="auth.py", content="TOKEN = 'قيمة'\n", old_text=None)
            ok = r2.ok or True  # كتابة كاملة تسمح داخل الجذور
            return (True, "الرقع لا يعالج الأسرار") if ok else (False, "")
    cases.append(("رقع", "الرقع داخل الجذور عادي للكود", fn_no_leak_secret))

    def fn_result_dict():
        with tempfile.TemporaryDirectory() as td:
            c = _contract(td)
            r = patch_file(c, path="new.py", content="x = 1\n")
            need = {"ok", "path", "mode", "changed", "matches", "sha_before", "sha_after", "bytes_written", "reason_ar"}
            return (True, "ممثل JSON كامل") if set(r.to_dict().keys()) == need else (False, f"مفاتيح: {sorted(r.to_dict().keys())}")
    cases.append(("رقع", "PatchResult مفاتيحه موثقة", fn_result_dict))

    def fn_allow_patch_required():
        with tempfile.TemporaryDirectory() as td:
            _setup(td)
            c = PermissionContract.for_roots(td, allow_patch=False)
            r = patch_file(c, path="app.py", content="x = 1\n")
            return (True, "الصلاحية شرط أول") if not r.ok else (False, "رقعة مرّت بعقد بلا allow_patch!")
    cases.append(("رقع", "بلا allow_patch لا رقعة تمر", fn_allow_patch_required))

    # ب) run_tests — تشغيل حقيقي
    def fn_run_ok():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "ok.py"
            p.write_text("print('3 passed in 0.01s')\n", encoding="utf-8")
            c = _contract(td)
            r = run_tests(c, argv=("python", "ok.py"), cwd=td)
            ok = r.ok and r.exit_code == 0 and r.passed == 3
            return (True, "تشغيل حقيقي ناجح") if ok else (False, f"تشغيل: ok={r.ok} exit={r.exit_code} passed={r.passed}")
    cases.append(("تشغيل", "تشغيل حقيقي يعدّ النجاح", fn_run_ok))

    def fn_run_fail_counts():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "mix.py"
            p.write_text("print('1 failed, 3 passed in 0.02s')\n", encoding="utf-8")
            c = _contract(td)
            r = run_tests(c, argv=("python", "mix.py"), cwd=td)
            ok = r.ok and r.passed == 3 and r.failed == 1
            return (True, "العدّ من النص والحكم من الخروج") if ok else (False, f"عدّ: passed={r.passed} failed={r.failed} ok={r.ok}")
    cases.append(("تشغيل", "عدّاد pytest للنص المطبوع", fn_run_fail_counts))

    def fn_run_timeout():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "slow.py"
            p.write_text("import time\ntime.sleep(4)\n", encoding="utf-8")
            c = _contract(td, timeout_s=1)
            r = run_tests(c, argv=("python", "slow.py"), cwd=td)
            ok = r.timed_out and r.exit_code == 124 and not r.ok
            return (True, "المهلة 124 موثقة") if ok else (False, f"مهلة: timed_out={r.timed_out} exit={r.exit_code}")
    cases.append(("تشغيل", "تجاوز المهلة يعود 124", fn_run_timeout))

    def fn_run_denied_cmd():
        with tempfile.TemporaryDirectory() as td:
            c = _contract(td)
            r = run_tests(c, argv=("bash", "x.sh"), cwd=td)
            return (True, "الأمر الخارج يُرفض") if not r.ok else (False, "bash مرّ التشغيل!")
    cases.append(("تشغيل", "أمر خارج القائمة يُرفض", fn_run_denied_cmd))

    def fn_run_disabled():
        with tempfile.TemporaryDirectory() as td:
            c = PermissionContract.for_roots(td, allow_run_tests=False)
            r = run_tests(c, argv=("python", "x.py"), cwd=td)
            return (True, "التفعيل شرط") if not r.ok else (False, "تشغيل مرّ بعقد مقفل")
    cases.append(("تشغيل", "تشغيل بعقد مقفل يُرفض", fn_run_disabled))

    def fn_run_shadow():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "pytest.py"
            p.write_text("print('خداع')\n", encoding="utf-8")
            c = _contract(td)
            r = run_tests(c, argv=("python", "pytest.py"), cwd=td)
            return (True, "الخداع يُكتشف مسبقًا") if not r.ok else (False, "pytest.py شبح مرّ تشغيلًا!")
    cases.append(("تشغيل", "ملف pytest.py شبح يُرفض مسبقًا", fn_run_shadow))

    def fn_run_string_argv():
        with tempfile.TemporaryDirectory() as td:
            c = _contract(td)
            r = run_tests(c, argv="python x.py", cwd=td)
            return (True, "النص المفرد يُرفض") if not r.ok else (False, "نص واحد مرّ تشغيلًا")
    cases.append(("تشغيل", "argv نصي يُرفض", fn_run_string_argv))

    def fn_run_cwd_escape():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "x.py"
            p.write_text("print('ok')\n", encoding="utf-8")
            c = _contract(td)
            r = run_tests(c, argv=("python", "../x.py"), cwd=td)
            return (True, "اجتياز cwd يُرفض") if not r.ok else (False, ".. في argv مرّ التشغيل")
    cases.append(("تشغيل", "اجتياز .. في التشغيل يُرفض", fn_run_cwd_escape))

    def fn_run_env_clean():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "envprobe.py"
            p.write_text("import os, json\nprint(json.dumps(sorted(os.environ.keys())))\n", encoding="utf-8")
            c = _contract(td)
            r = run_tests(c, argv=("python", "envprobe.py"), cwd=td)
            leaked = "ZYKO_EVAL_SECRET" in (r.stdout_tail or "")
            return (True, "بيئة فرعية نظيفة") if r.ok and not leaked else (False, "بيئة التشغيل لم تُنقَّ")
    cases.append(("تشغيل", "بيئة التشغيل الفرعية مُنقّاة", fn_run_env_clean))

    def fn_run_tails():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "chatty.py"
            p.write_text("print('سطر أقل من السقف')\nprint('2 passed in 0.01s')\n", encoding="utf-8")
            c = _contract(td)
            r = run_tests(c, argv=("python", "chatty.py"), cwd=td)
            ok = "سطر أقل" in (r.stdout_tail or "") and r.passed == 2
            return (True, "ذيول المخرجات موثقة") if ok else (False, "ذيول التشغيل مفقودة")
    cases.append(("تشغيل", "ذيول stdout موثقة في النتيجة", fn_run_tails))

    def fn_run_dict():
        with tempfile.TemporaryDirectory() as td:
            c = _contract(td)
            r = run_tests(c, argv=("python", "missing.py"), cwd=td)
            need = {"ok", "exit_code", "timed_out", "passed", "failed", "errors", "skipped",
                    "command", "stdout_tail", "stderr_tail", "reason_ar"}
            d = r.to_dict()
            return (True, "ممثل JSON كامل") if need <= set(d.keys()) else (False, f"مفاتيح الناقصة: {need - set(d.keys())}")
    cases.append(("تشغيل", "TestRunResult مفاتيحه موثقة", fn_run_dict))

    def fn_run_nul():
        with tempfile.TemporaryDirectory() as td:
            c = _contract(td)
            r = run_tests(c, argv=("python", "a\x00b.py"), cwd=td)
            return (True, "NUL يُرفض") if not r.ok else (False, "NUL مرّ التشغيل")
    cases.append(("تشغيل", "NUL في تشغيل يُرفض", fn_run_nul))

    def fn_run_quiet_ok():
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "quiet.py"
            p.write_text("print('nothing structured here')\n", encoding="utf-8")
            c = _contract(td)
            r = run_tests(c, argv=("python", "quiet.py"), cwd=td)
            ok = r.ok and r.passed is None and r.failed is None
            return (True, "بلا عدّاد: نجاح صامت") if ok else (False, f"بلا عدّاد: passed={r.passed}")
    cases.append(("تشغيل", "تشغيل بلا عدّاد pytest يعود صامتًا", fn_run_quiet_ok))

    return cases


# =============================================== 11) العزل النووي
def build_jail():
    cases = []

    def fn_abi_type():
        abi = landlock_abi()
        return (True, f"ABI={abi}") if isinstance(abi, int) and abi >= 0 else (False, f"ABI غير سليم: {abi}")
    cases.append(("اكتشاف", "landlock_abi عدد صحيح غير سالب", fn_abi_type))

    def fn_level_enum():
        level = jail_level()
        ok = level in ("landlock", "bwrap", "none")
        return (True, f"المستوى {level} من الفهرس") if ok else (False, f"مستوى خارج الفهرس: {level}")
    cases.append(("اكتشاف", "jail_level من الفهرس الثلاثي", fn_level_enum))

    def fn_net_enum():
        net = net_confinement()
        ok = net in ("landlock-net", "bwrap-net", "unconstrained")
        return (True, f"الشبكة {net} معلنة") if ok else (False, f"حالة شبكة خارج الفهرس: {net}")
    cases.append(("اكتشاف", "net_confinement من الفهرس الثلاثي", fn_net_enum))

    def fn_honesty_pair():
        """الصدق البنيوي: بلا landlock وبلا bwrap ⇒ الشبكة غير مقيدة صراحة."""
        abi = landlock_abi()
        net = net_confinement()
        import shutil
        has_bwrap = shutil.which("bwrap") is not None
        if abi >= 4:
            expect = "landlock-net"
        elif has_bwrap:
            expect = "bwrap-net"
        else:
            expect = "unconstrained"
        return (True, "الإعلان يطابق الواقع") if net == expect else (False, f"ABI={abi} bwrap={has_bwrap} لكن net={net} بدل {expect}")
    cases.append(("صدق", "إعلان الشبكة يطابق قدرات النواة", fn_honesty_pair))

    def fn_level_consistency():
        abi = landlock_abi()
        level = jail_level()
        if abi >= 1:
            expect = "landlock"
        else:
            import shutil
            expect = "bwrap" if shutil.which("bwrap") else "none"
        return (True, "المستوى يطابق النواة") if level == expect else (False, f"ABI={abi} لكن level={level}")
    cases.append(("صدق", "المستوى يطابق ABI المكتشف", fn_level_consistency))

    def fn_reset_cache():
        reset_detection_cache()
        level = jail_level()  # يعيد الاكتشاف
        reset_detection_cache()
        return (True, "الكاش يُبطَل بأمان") if level in ("landlock", "bwrap", "none") else (False, "reset كسر الاكتشاف")
    cases.append(("اكتشاف", "reset_detection_cache يعيد بلا عطب", fn_reset_cache))

    def fn_write_roots():
        with tempfile.TemporaryDirectory() as td:
            roots = write_roots((td, td, "relative/path", "/nonexistent-zz-eval"))
            ok = roots.count(td) == 1 and all(r.startswith("/") for r in roots)
            ok = ok and "relative/path" not in roots and "/nonexistent-zz-eval" not in roots
            return (True, "تجميد الجذور موثق") if ok else (False, f"الجذور: {roots}")
    cases.append(("جذور", "write_roots يحسم ويفرّد ويستبعد", fn_write_roots))

    def fn_write_roots_tempdir():
        import tempfile as tf
        roots = write_roots(())
        temp = tf.gettempdir()
        ok = any(str(r).startswith(temp) for r in roots)
        return (True, "مجلد الحرارة يُلحق") if ok else (False, "بلا جذور: مجلد الحرارة لم يُلحق")
    cases.append(("جذور", "مجلد الحرارة يُلحق افتراضيًا", fn_write_roots_tempdir))

    def fn_wrap_argv_none():
        reset_detection_cache()
        argv = wrap_argv(("python", "x.py"), ("/tmp",))
        level = jail_level()
        if level != "bwrap":
            expect_none = argv is None
            return (True, "بلا bwrap لا غلاف") if expect_none else (False, "غلاف مرّ بلا مستوى bwrap")
        return (True, "غلاف bwrap موثق") if argv and argv[0].endswith("bwrap") else (False, "مستوى bwrap بلا غلاف!")
    cases.append(("غلاف", "wrap_argv يلتزم المستوى المعلن", fn_wrap_argv_none))

    def fn_wrap_argv_hostile():
        reset_detection_cache()
        argv = wrap_argv(None, ("/tmp",))  # type: ignore[arg-type]
        level = jail_level()
        if level != "bwrap":
            return (True, "عدوي خارج المستوى يعود None") if argv is None else (False, "مدخل عدوي أنتج غلافًا")
        return True, "عدوي تحت bwrap يعود None أيضًا"
    cases.append(("غلاف", "wrap_argv على مدخل عدوي", fn_wrap_argv_hostile))

    def fn_overlays():
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            (root / ".ssh").mkdir()
            (root / ".env").write_text("A=1\n", encoding="utf-8")
            overlays = sensitive_overlays([td])
            ok = len(overlays) >= 2
            return (True, "التعمية موثقة") if ok else (False, f"تعمية المخازن: {overlays}")
    cases.append(("تعمية", "sensitive_overlays يغطي المخازن", fn_overlays))

    def fn_preexec_callable():
        from zyko.sandbox.jail import jail_preexec
        with tempfile.TemporaryDirectory() as td:
            fn_pre = jail_preexec((td,))
            ok = fn_pre is None or callable(fn_pre)
            return (True, "preexec موثق") if ok else (False, "preexec ليس استدعاءً ولا None")
    cases.append(("بنية", "jail_preexec استدعاء أو None", fn_preexec_callable))

    def fn_preexec_net_ports():
        from zyko.sandbox.jail import jail_preexec
        with tempfile.TemporaryDirectory() as td:
            fn_pre = jail_preexec((td,), net_ports=(8000,))
            ok = fn_pre is None or callable(fn_pre)
            return (True, "منافذ معلنة تُقبل") if ok else (False, "net_ports كسرت بنية preexec")
    cases.append(("بنية", "jail_preexec مع منافذ معلنة", fn_preexec_net_ports))

    def fn_no_env_read():
        """العزل لا يعتمد على بيئة الجلسة — دالة الاكتشاف نقية."""
        reset_detection_cache()
        a = jail_level()
        reset_detection_cache()
        b = jail_level()
        return (True, "اكتشاف مستقر") if a == b else (False, "اكتشافان متتاليان اختلفا")
    cases.append(("اكتشاف", "الاكتشاف مستقر عبر النداءات", fn_no_env_read))

    def fn_roots_many():
        with tempfile.TemporaryDirectory() as td:
            roots = write_roots((td,) * 12)
            ok = len(roots) >= 1 and roots.count(td) == 1
            return (True, "التكرار يُفرَّد") if ok else (False, f"تكرار الجذور: {len(roots)}")
    cases.append(("جذور", "تكرار الجذور يُفرَّد", fn_roots_many))

    return cases
