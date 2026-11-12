"""zyko.sandbox.jail — العزل بنواة نظام التشغيل (الأولوية 5).

الفجوة الموثقة في ``runner``: العقد يقيّد ما **يعبر** من zyko إلى
العملية الفرعية (أسرار، جذور، زمن) لا ما تفعله العملية *داخلها* —
كود الاختبارات يُنفَّذ بعقده هو. هذه الوحدة تُغلق الباب الكتابي على
مستوى النواة لا الوعد: كود الابن يحاول الكتابة خارج جذور العقد فيفشل
بـ ``EPERM`` من النواة نفسها، حتى لو تظاهر بشيء آخر أو استعار ثغرة.

المستويات، بالترتيب الأقوى أولًا، وكلها مكتشفة لا مفترضة:

  1. **landlock** — Linux ≥ 5.13 عبر ``ctypes`` مباشرة (444/445/446):
     حصر الكتابة على الجذور بلا اعتمادية جديدة ولا مستخدم namespaces —
     يعمل داخل الحاويات حيث يفشل bwrap غالبًا. يُطبَّق في ``preexec_fn``
     قبل ``exec``، فالكود الابن يُولد مقيدًا لا يُولد حرًا ثم يُقيَّد.
  2. **bwrap** — bubblewrap إن وُجد الثنائي وعمل فعلًا (فحص ذاتي بتشغيل
     «true» تحت التغليف الكامل): mount/pid/net namespaces — أصرم
     (عزل شبكة) لكنه يعتمد user namespaces غير المتاحة دائمًا.
  3. **none** — بلا عزل نواتي متاح: يُعلن في الإيصال والتدقيق كما هو —
     الصدق قبل التفاؤل، والتخفي المنظم لا التظاهر بالحماية.

حد الصدقة المعلن: Landlock هنا يحصر **الكتابة** فقط — القراءة مفتوحة
عمدًا (تشغيل اختبارات مشروع يتطلب قراءة ذلك المشروع وكود المشغّل)،
والشبكة لا تُمس تحت landlock ABI v1–v3 — وكلاهما فجوة موثقة لا ثغرة
مخفية. نصف القراءة محسوم اليوم بحرس الاعتماد الحساس (المستعار من
nexus-core): يد zyko نفسها لا تقرأ مخازن الأسرار (``.env``/المفاتيح)
حتى داخل الجذور، وتحت bwrap تُعمى المخازن نفسها في الابن بتراكب mount
— وبقي تحت landlock قراءة الابن للجذور مفتوحة، فجوة أصغر موثقة حتى
يتيح نواة CI حصر القراءة الانتقائي.

وفشل تقييد النواة داخل الابن **فشل مغلق**: وسم عربي على
stderr وخروج 126 — لا تشغيل بلا عزل على مضاربة الهدوء.
"""

from __future__ import annotations

import ctypes
import functools
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from zyko.sandbox.contracts import sensitive_paths_in_roots

# نتيجة بروبة الإقامة — تُقاس مرة واحدة لكل جلسة (حتمية للبيئة الواحدة)
_ESTABLISHMENT_PROBE: bool | None = None

# ------------------------------------------------------------ المستويات
JAIL_LEVEL_NONE = "none"
JAIL_LEVEL_LANDLOCK = "landlock"
JAIL_LEVEL_BWRAP = "bwrap"

_EXIT_JAIL_FAIL = 126  # خروج الابن المقفل — فشل العزل قبل التنفيذ
_STDERR_MARK = (
    "[zyko-jail] فشل تقييد النواة قبل التنفيذ — أُنهي الابن مغلقاً لا مشغلاً بلا عزل"
).encode("utf-8")

# أرقام الاستدعاءات النظامية — موحّدة على المعماريات الرئيسية منذ 5.13
_SYSCALLS_BY_ARCH = {
    "x86_64": (444, 445, 446),
    "aarch64": (444, 445, 446),
    "armv7l": (444, 445, 446),
    "riscv64": (444, 445, 446),
    "ppc64le": (444, 445, 446),
    "s390x": (444, 445, 446),
}

_CREATE_RULESET_VERSION_FLAG = 1  # استعلام ABI لا إنشاء مجموعة
_RULE_PATH_BENEATH = 1
_PR_SET_NO_NEW_PRIVS = 38

# حقوق الكتابة (ABI v1) — المقبول للجذور، والمتعامل معه للنواة
_ACCESS_WRITE_FILE = 1 << 1
_ACCESS_REMOVE_FILE = 1 << 2
_ACCESS_REMOVE_DIR = 1 << 3
_ACCESS_MAKE_CHAR = 1 << 4
_ACCESS_MAKE_DIR = 1 << 5
_ACCESS_MAKE_REG = 1 << 6
_ACCESS_MAKE_SOCK = 1 << 7
_ACCESS_MAKE_FIFO = 1 << 8
_ACCESS_MAKE_BLOCK = 1 << 9
_ACCESS_MAKE_SYM = 1 << 10
_WRITE_BASE = (
    _ACCESS_WRITE_FILE
    | _ACCESS_REMOVE_FILE
    | _ACCESS_REMOVE_DIR
    | _ACCESS_MAKE_CHAR
    | _ACCESS_MAKE_DIR
    | _ACCESS_MAKE_REG
    | _ACCESS_MAKE_SOCK
    | _ACCESS_MAKE_FIFO
    | _ACCESS_MAKE_BLOCK
    | _ACCESS_MAKE_SYM
)
_ACCESS_REFER = 1 << 11  # ABI v2 — إعادة تربية الارتباطات بين الأدلة
_ACCESS_TRUNCATE = 1 << 12  # ABI v3 — البتر بلا فتح كتابة

# الشبكة (ABI v4 — نواة ‎6.7+): حصر TCP bind/connect — جولة 11
_ACCESS_NET_BIND_TCP = 1 << 16
_ACCESS_NET_CONNECT_TCP = 1 << 17
_NET_SCOPE = _ACCESS_NET_BIND_TCP | _ACCESS_NET_CONNECT_TCP
_RULE_NET_PORT = 3  # landlock_rule_type — قاعدة منفذ شبكي

_libc: ctypes.CDLL | None = None


class _RulesetAttr(ctypes.Structure):
    """landlock_ruleset_attr — ABI v1–v3: ملفات فقط (8 بايت)."""

    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _RulesetAttrNet(ctypes.Structure):
    """landlock_ruleset_attr — ABI v4+: ملفات + نطاق الشبكة (16 بايت).

    حجم البنية يُسقف حسب ABI المكتشف: نواة أقدم ترفض 16 بايت بـ EINVAL
    — فالحصر الشبكي يُبنى فقط حين تعلن النواة ABI ≥ 4، والفجوة تُعلن لا
    تُخمّن (نمط 0.29.0 نفسه).
    """

    _fields_ = [
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_scoped", ctypes.c_uint64),
    ]


class _NetPortAttr(ctypes.Structure):
    """landlock_net_port_attr — قاعدة منفذ مسموح (ABI v4)."""

    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("port", ctypes.c_uint16),
    ]


class _PathBeneathAttr(ctypes.Structure):
    """landlock_path_beneath_attr — قاعدة «تحت هذا المسار»."""

    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
    ]


def _libc_handle() -> ctypes.CDLL:
    """مكتبة C للعملية — تُنشأ مرة واحدة، وفشلها استثناء داخلي مُسقوف."""
    global _libc
    if _libc is None:
        _libc = ctypes.CDLL(None, use_errno=True)
    return _libc


# ------------------------------------------------------------ الكشف
def landlock_abi() -> int:
    """نسخة ABI المدعومة في النواة — 0 يعني «غير مدعوم» بلا إطلاق.

    الاستعلام استدعاء نظامي واحد بلا إنشاء شيء: النواة القديمة تعيد
    ENOSYS، والحاوية الممنوعة تعيد EPERM — كلاهما 0 صادق لا استثناء.
    """
    machine = platform.machine()
    if platform.system() != "Linux" or machine not in _SYSCALLS_BY_ARCH:
        return 0
    try:
        libc = _libc_handle()
        nr_create = _SYSCALLS_BY_ARCH[machine][0]
        abi = libc.syscall(
            nr_create,
            ctypes.c_void_p(0),
            ctypes.c_size_t(0),
            ctypes.c_uint(_CREATE_RULESET_VERSION_FLAG),
        )
        return int(abi) if abi and int(abi) > 0 else 0
    except Exception:  # noqa: BLE001 — الكشف حتمي: فشل = غير مدعوم
        return 0


def _bwrap_works() -> bool:
    """bwrap يعمل فعلًا لا موجود فعلًا — فحص ذاتي بالتغليف الكامل."""
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return False
    target = shutil.which("true") or "/bin/true"
    argv = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--ro-bind",
        "/",
        "/",
        "--dev-bind",
        "/dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--unshare-net",
        target,
    ]
    try:
        proc = subprocess.run(  # noqa: S603 — argv ثابت مبني هنا لا من المدخل  # nosec B603
            argv, capture_output=True, timeout=10
        )
        return proc.returncode == 0
    except Exception:  # noqa: BLE001 — فشل الفحص = لا bwrap
        return False


_level_cache: str | None = None  # الكشف مرة للعملية — النواة لا تتغير وسط جلسة


def jail_level() -> str:
    """مستوى العزل الفعلي لهذه البيئة — «landlock» أو «bwrap» أو «none».

    حتمي للبيئة الواحدة ويُعلن في الإيصال وسجل التدقيق كما يُعلن
    ``backend()`` في ``zyko.kernel`` — القوة تُكتشف لا تُدَّعى.
    """
    global _level_cache
    if _level_cache is None:
        if landlock_abi() >= 1:
            _level_cache = JAIL_LEVEL_LANDLOCK
        elif _bwrap_works():
            _level_cache = JAIL_LEVEL_BWRAP
        else:
            _level_cache = JAIL_LEVEL_NONE
    return _level_cache


def reset_detection_cache() -> None:
    """أبطل كاش الكشف — للاختبارات والفحص اليدوي لا لمسار التشغيل."""
    global _level_cache
    _level_cache = None


# ------------------------------------------------------------ الجذور
def write_roots(roots: object) -> tuple[str, ...]:
    """جذور الكتابة المسموحة: جذور العقد + مجلد الحرارة النظامي.

    ``run_tests`` يكتب مخازن pytest المؤقتة في مجلد حرارة النظام
    (``tmp_path`` وغيره) — منحه مع الجذور ضرورة تشغيل لا رخاوة أمن،
    وما عدا ذلك من القرص يظل خارج الحصر مقفلاً. التكرار يُدْمَج،
    والجذر الفارغ/العديوي/**الغير موجود** يُتخطى — لا قاعدة لغير
    الموجود ولا ربط لمجلد ليس كائناً، والجذور تُحسم مطلقة.
    """
    out: list[str] = []
    for root in tuple(roots or ()) + (tempfile.gettempdir(),):
        try:
            text = str(root or "").strip()
            if not text:
                continue
            path = Path(text)
            if not path.is_absolute():
                continue  # جذر نسبي = مدخل عديوي — العزل جذور مطلقة فقط
            if not path.exists():
                continue  # غير موجود = لا قاعدة ولا ربط — يُتخطى موثقاً
            resolved = str(path.resolve())
            if resolved not in out:
                out.append(resolved)
        except Exception:  # noqa: BLE001 — جذر عديوي يُتخطى لا يفجّر  # nosec B112
            continue
    return tuple(out)


# ------------------------------------------------------------ Landlock
def _handled_access(abi: int) -> int:
    """الحقوق التي تتعامل معها مجموعة القواعد — حسب ABI المكتشَف."""
    handled = _WRITE_BASE
    if abi >= 2:
        handled |= _ACCESS_REFER
    if abi >= 3:
        handled |= _ACCESS_TRUNCATE
    return handled


def _net_scope(abi: int) -> int:
    """نطاق الشبكة المتعامل معه — صفر تحت ABI v4، وbind/connect فوقها.

    الحصر الشبكي افتراضي أصرم: من يقيد، يُحجب كل TCP — ومن يحتاج منافذ
    يععلنها في ``net_ports`` فتُضاف قواعد سماح مرتبة حتمياً.
    """
    return _NET_SCOPE if abi >= 4 else 0


def _ruleset_struct(abi: int, handled: int) -> tuple[Any, int]:
    """بنية مجموعة القواعد بحسب ABI — 8 بايت للملفات، 16 مع الشبكة."""
    if abi >= 4:
        return _RulesetAttrNet(handled, _net_scope(abi)), ctypes.sizeof(_RulesetAttrNet)
    return _RulesetAttr(handled), ctypes.sizeof(_RulesetAttr)


def _landlock_restrict(allowed: tuple[str, ...], *, net_ports: tuple[int, ...] = ()) -> None:
    """قيّد العملية الحالية: الكتابة داخل الجذور فقط + الشبكة محصورة — استدعاءات مباشرة.

    تحت ABI v4 تُحجب كل اتصالات/bind TCP إلا المنافذ المعلنة في
    ``net_ports`` (قواعد سماح مرتبة، كل منفذ قاعدة NET_PORT واحدة) —
    وتحت ABI أقدم تبقى الشبكة كما كانت: فجوة معلنة لا ثغرة مخفية.

    تُستدعى داخل الابن (post-fork/pre-exec) حيث الخيط وحيد والنواة
    بلا اتصال بالأصل؛ أي فشل هنا استثناء يلتقطه ``_restrict_child``
    ويحوّله إغلاقاً موثقاً.
    """
    machine = platform.machine()
    if machine not in _SYSCALLS_BY_ARCH:
        raise OSError(f"معمارية غير مدعومة للعزل النواتي — {machine}")
    nr_create, nr_add, nr_restrict = _SYSCALLS_BY_ARCH[machine]
    abi = landlock_abi()
    if abi < 1:
        raise OSError("Landlock غير مدعوم في هذه النواة")
    libc = _libc_handle()
    handled = _handled_access(abi)
    ruleset, ruleset_size = _ruleset_struct(abi, handled)
    fd = libc.syscall(
        nr_create,
        ctypes.byref(ruleset),
        ctypes.c_size_t(ruleset_size),
        ctypes.c_uint(0),
    )
    if fd < 0:
        raise OSError(ctypes.get_errno(), "landlock_create_ruleset فشل")
    try:
        granted = handled  # المسموح للجذور = كل ما نتعامل معه من كتابة
        for root in allowed:
            try:
                root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            except OSError:
                continue  # جذر لم يُنشأ بعد — لا قاعدة لغير الموجود
            try:
                rule = _PathBeneathAttr(granted, root_fd)
                rc = libc.syscall(
                    nr_add,
                    ctypes.c_int(fd),
                    ctypes.c_int(_RULE_PATH_BENEATH),
                    ctypes.byref(rule),
                    ctypes.c_uint(0),
                )
                if rc != 0:
                    raise OSError(ctypes.get_errno(), "landlock_add_rule فشل")
            finally:
                os.close(root_fd)
        for port in sorted(set(int(p) for p in net_ports)):
            net_rule = _NetPortAttr(_ACCESS_NET_CONNECT_TCP, port)
            rc = libc.syscall(
                nr_add,
                ctypes.c_int(fd),
                ctypes.c_int(_RULE_NET_PORT),
                ctypes.byref(net_rule),
                ctypes.c_uint(0),
            )
            if rc != 0:
                raise OSError(ctypes.get_errno(), f"landlock_add_rule(NET_PORT {port}) فشل")
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS فشل")
        if libc.syscall(nr_restrict, ctypes.c_int(fd), ctypes.c_uint(0)) != 0:
            raise OSError(ctypes.get_errno(), "landlock_restrict_self فشل")
    finally:
        os.close(fd)


def _restrict_child(allowed: tuple[str, ...], net_ports: tuple[int, ...] = ()) -> None:
    """دالة preexec — تقييد النواة أو الإغلاق الموثق، لا ثالث.

    الفشل المغلق: وسم عربي على stderr ثم ``os._exit(126)`` — الابن
    لا يعمل بلا عزل على مضاربة الهدوء، والناتج 126 موثق في الإيصال.
    """
    try:
        _landlock_restrict(allowed, net_ports=net_ports)
    except BaseException:  # noqa: BLE001 — preexec لا يرمي: يغلق لا يهرب
        try:
            os.write(2, _STDERR_MARK + b"\n")
        except OSError:
            pass
        os._exit(_EXIT_JAIL_FAIL)


def jail_establishment_ok() -> bool:
    """بروب إقامة حقيقي: هل يُقام الحبس فعلاً في هذه البيئة؟

    الكشف (jail_level) يقيس توفر الواجهة فقط؛ الإقامة قد تفشل رغم توفرها
    (سياسات seccomp في حاويات CI تحجب landlock_add_rule) — والفارق
    بينهما يظهر فقط ببناء حبس حقيقي في ابن فعلي. البروب حتمي ومُخزّن
    لكل جلسة: ابن واحد يُنشأ بعقود حبس صغيرة ونجاته تثبت الإقامة.
    """
    global _ESTABLISHMENT_PROBE
    if _ESTABLISHMENT_PROBE is None:
        try:
            probe_root = tempfile.mkdtemp(prefix="zyko-jail-probe-")
            probe = subprocess.run(  # nosec B603 — ابن البروب: argv ثابت بلا مدخل
                [sys.executable, "-c", "import sys; sys.exit(0)"],
                preexec_fn=jail_preexec((probe_root,)),
                capture_output=True,
                timeout=60,
            )
            _ESTABLISHMENT_PROBE = probe.returncode == 0
        except Exception:
            _ESTABLISHMENT_PROBE = False
    return _ESTABLISHMENT_PROBE


def jail_preexec(
    roots: object,
    *,
    net_ports: tuple[int, ...] = (),
) -> Callable[[], None] | None:
    """دالة عزل لـ ``subprocess`` أو None — بحسب المستوى المكتشَف.

    تحت landlock ABI v4 الشبكة محصورة تلقائياً: كل TCP محجوب إلا
    المنافذ المعلنة في ``net_ports`` (تصريح صريح لا افتراض صامت).
    تُمرَّر كما هي إلى ``preexec_fn`` حيث landlock هو المستوى النشط؛
    وbwrap يُطبَّق بتغليف ``argv`` لا بـ preexec (مسار مختلف تماماً)،
    وnone يعيد None — الصدق معلن في كل مسار.
    """
    if platform.system() != "Linux":
        return None
    if jail_level() != JAIL_LEVEL_LANDLOCK:
        return None
    allowed = write_roots(roots)
    return functools.partial(_restrict_child, allowed, net_ports)


def net_confinement() -> str:
    """مستوى حصر الشبكة الفعلي — معلن لا مفترض (جولة 11).

    ``landlock-net``: نواة ABI ≥ 4 وكل TCP محجوب إلا المنافذ المعلنة؛
    ``bwrap-net``: شبكة مقطوعة كلياً تحت التغليف الكامل (أصرم)؛
    ``unconstrained``: فجوة موثقة تحت نواة قديمة أو بلا عزل — تُعلن
    في الإيصالات كما يُعلن ``jail_level()``.
    """
    level = jail_level()
    if level == JAIL_LEVEL_LANDLOCK:
        return "landlock-net" if landlock_abi() >= 4 else "unconstrained"
    if level == JAIL_LEVEL_BWRAP:
        return "bwrap-net"
    return "unconstrained"


# ------------------------------------------------------------ bwrap
# -------------------------------------------------- تعمية المخازن الحساسة
def sensitive_overlays(roots: object) -> list[str]:
    """أوسمة تراكب تعمّى مخازن الاعتماد داخل الابن تحت bwrap — حتمية.

    المستعار من nexus-core: حصر الجذر لا يكفي لأن ``.env`` في الجذر
    مخزن أسرار. المجلد الحساس (``.ssh``) يُستبدل tmpfs فارغًا، والملف
    السري يُربط ``/dev/null`` فوقه للقراءة فقط — فكود الاختبارات يقرأ
    المشروع كله إلا الأسرار. لا شيء هنا تحت landlock: بلا mount
    namespace لا تراكب — والفجوة تُعلن لا تُخفى.
    """
    overlays: list[str] = []
    try:
        for store in sensitive_paths_in_roots(roots):
            if Path(store).is_dir():
                overlays += ["--tmpfs", store]
            else:
                overlays += ["--ro-bind", "/dev/null", store]
    except Exception:  # noqa: BLE001 — فشل الكشف = لا تراكب، والمستوى معلن أصلًا
        return []
    return overlays


def wrap_argv(argv: object, roots: object) -> list[str] | None:
    """غلِّف argv تحت bubblewrap — فقط عندما يكون bwrap هو المستوى النشط.

    غلاف موحّد: كل شيء للقراءة فقط، الكتابة للجذور، ``/tmp`` tmpfs
    فراغ خاص، والشبكة مقطوعة — أصرم من landlock في الشبكة، أخفّ منه
    في الحصر لأنه يعتمد user namespaces. None عند غياب المستوى أو
    مدخل عديوي — المستدعي يكمل بلا غلاف والمستوى معلن أصلًا.
    """
    if jail_level() != JAIL_LEVEL_BWRAP:
        return None
    try:
        tokens = [str(token) for token in argv]  # type: ignore[union-attr]
        if not tokens:
            return None
    except Exception:  # noqa: BLE001 — مدخل عديوي = بلا غلاف، والقرار موثق
        return None
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return None
    temp_dir = str(Path(tempfile.gettempdir()).resolve())
    binds: list[str] = []
    for root in write_roots(roots):
        if root == temp_dir:
            continue  # tmpfs /tmp يعوض ربط مجلد الحرارة — عزل أصرم
        binds += ["--bind", root, root]
    return [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--ro-bind",
        "/",
        "/",
        "--dev-bind",
        "/dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--unshare-net",
        *binds,
        *sensitive_overlays(roots),
        "--",
        *tokens,
    ]


__all__ = [
    "JAIL_LEVEL_BWRAP",
    "JAIL_LEVEL_LANDLOCK",
    "JAIL_LEVEL_NONE",
    "jail_level",
    "jail_preexec",
    "landlock_abi",
    "net_confinement",
    "reset_detection_cache",
    "sensitive_overlays",
    "wrap_argv",
    "write_roots",
]
