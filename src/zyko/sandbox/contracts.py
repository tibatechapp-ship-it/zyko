"""zyko.sandbox.contracts — عقود الصلاحيات: صلاحيات معلنة لا حدس.

عقد الصلاحية هو «ما يُسمح له بحدث» موثق قبل التنفيذ لا بعده — امتداد
لفلسفة الحرس الحتمية في المستودع: لا أمر يمر دون توقيع، ولا توقيع بلا
عقد مكتوب. العقد يجيب حتميًا على ثلاثة أسئلة:

  1. **أين؟** ``check_path`` — المسار داخل جذور مسموحة، بلا ``..``،
     بلا رموز ارتباط تخرج من الجذر، بلا محارف عدوية (NUL).
  2. **ماذا؟** ``allow_patch`` / ``allow_run_tests`` — أدوات مفعّلة
     معلنة؛ ``check_command`` — أول token في قائمة بيضاء وكل token
     خالٍ من محارف الصدفة — فلا صدفة تمر argv قائمة أصلًا، والفحص
     حماية عمق لا ثقة.
  3. **بكم؟** سقوف مُقيَّدة عند الإنشاء — ملف، مخرجات، مهلة، عمليات
     لكل جلسة — والقيم العدوية (سالبة، غير عددية، فوق السقف المطلق)
     تُقيَّد إلى الحد الآمن لا ترمي، عقد الميزانية نفسه في ``reflect``.

تنقية البيئة قائمة **بيضاء** لا سوداء: يُحتفظ بالمفاتيح الضرورية فقط
(PATH/HOME/… وبقايا ويندوز) وكل ما فيه شبه سر (KEY/TOKEN/SECRET/…)
لا يعبر أصلًا — القائمة السوداء تنسى اسمًا واحدًا فتسرب كل شيء.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

# ---------------------------------------------------------------- السقوف
MAX_TIMEOUT_S = 120.0  # السقف المطلق للمهلة — فوقه يُقيَّد لا يمر
MAX_FILE_BYTES_LIMIT = 8 * 1024 * 1024  # سقف حجم الملف المطلق (8MB)
MAX_ROOTS = 8  # عدد الجذور الأقصى — عقد صغير مُدقَّق لا شجرة صلاحيات

DEFAULT_MAX_FILE_BYTES = 1 * 1024 * 1024  # سقف الملف الافتراضي (1MB)
DEFAULT_MAX_OUTPUT_CHARS = 20_000  # سقف مخرجات التشغيل الافتراضي
DEFAULT_TIMEOUT_S = 30.0  # المهلة الافتراضية بالثواني
DEFAULT_MAX_PATCH_OPS = 32  # عمليات الرقعة القصوى لكل جلسة افتراضيًا

# محارف الصدفة — تُرفض من أي token في argv (حماية عمق فوق "بلا shell")
DENY_ARGV_CHARS = tuple(';&|<>\n\r`$(){}[]!*?"\'\\')

# مفاتيح البيئة البقاء الدنيا — قائمة بيضاء دنيا عبر المنصات
ENV_KEEP_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TZ")
# بقايا ويندوز الضرورية لعمل بايثون الفرعي — تُنسخ إن وُجدت فقط
ENV_KEEP_WINDOWS = ("SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "TEMP", "TMP")
# أسمية الأسرار — أي مفتاح بيئة يحويها لا يعبر حتى لو طلبه الملف الأبيض
ENV_DENY_TOKENS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "COOKIE",
    "SESSION",
    "AUTH",
    "GHP_",
    "SK-",
)

# الأوامر المبيّحة الافتراضية لتشغيل الاختبارات — argv[0] فقط من هنا
DEFAULT_ALLOWED_COMMANDS = ("python", "python3", "pytest", "py")


def _clamp_int(value: object, default: int, cap: int) -> int:
    """قيّد عددًا إلى نطاق آمن — العدوي يعطي الافتراضي لا استثناء."""
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(0, min(cap, number))


def _clamp_float(value: object, default: float, cap: float) -> float:
    """قيّد زمنًا إلى نطاق آمن — نفس عقد الأعداد بلا استثناء."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):  # NaN/Inf
        return default
    return max(0.0, min(cap, number))


@dataclass(frozen=True)
class PermissionContract:
    """عقد صلاحيات جلسة أدوات: أين، ماذا، وبكم — كله معلن ومُقيَّد.

    العقد **frozen** — لا جلسة تعدّ عقدها أثناء العمل، وكل قرارات
    الطبقة تُبنى على قراءة العقد فقط. الإنشاء عبر
    ``PermissionContract.for_roots(...)`` يمنح الافتراضيات الآمنة،
    والبناء المباشر ممكن بكل الحقول للتوثيق الصريح في الاختبارات.
    """

    roots: tuple[str, ...] = ()
    allow_patch: bool = False
    allow_run_tests: bool = False
    allowed_commands: tuple[str, ...] = field(default_factory=lambda: DEFAULT_ALLOWED_COMMANDS)
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_patch_ops: int = DEFAULT_MAX_PATCH_OPS
    sanitize_env: bool = True

    # ------------------------------------------------------------ الإنشاء
    @classmethod
    def for_roots(
        cls,
        *roots: object,
        allow_patch: bool = False,
        allow_run_tests: bool = False,
        max_file_bytes: object = DEFAULT_MAX_FILE_BYTES,
        max_output_chars: object = DEFAULT_MAX_OUTPUT_CHARS,
        timeout_s: object = DEFAULT_TIMEOUT_S,
        max_patch_ops: object = DEFAULT_MAX_PATCH_OPS,
        allowed_commands: tuple[str, ...] | None = None,
    ) -> "PermissionContract":
        """ابنِ عقدًا بجذور محدَّدة وافتراضيات آمنة — العدوي يُقيَّد لا يرمي.

        الجذور تُطبع وتُحسم إلى مسارات مطلقة نصية (التحقق الفعلي للدخول
        يتم وقت الاستدعاء بـ ``resolve`` لأن الجذر قد يُنشأ لاحقًا)؛
        عدد الجذور مسقوف، والقيم فوق السقف المطلق تُقيَّد إليه موثقة.
        """
        cleaned: list[str] = []
        for root in roots or ():
            text = str(root or "").strip()
            if not text:
                continue
            candidate = PureWindowsPath(text).as_posix() if PureWindowsPath(text).drive else text
            cleaned.append(str(Path(candidate).absolute()))
            if len(cleaned) >= MAX_ROOTS:
                break
        commands = tuple(allowed_commands) if allowed_commands else DEFAULT_ALLOWED_COMMANDS
        return cls(
            roots=tuple(cleaned),
            allow_patch=bool(allow_patch),
            allow_run_tests=bool(allow_run_tests),
            allowed_commands=tuple(dict.fromkeys(c.strip() for c in commands if str(c).strip())),
            max_file_bytes=_clamp_int(max_file_bytes, DEFAULT_MAX_FILE_BYTES, MAX_FILE_BYTES_LIMIT),
            max_output_chars=_clamp_int(max_output_chars, DEFAULT_MAX_OUTPUT_CHARS, 1_000_000),
            timeout_s=_clamp_float(timeout_s, DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S),
            max_patch_ops=_clamp_int(max_patch_ops, DEFAULT_MAX_PATCH_OPS, 100_000),
        )

    # ------------------------------------------------------------ المواقع
    def check_path(self, path: object) -> tuple[Path | None, str | None]:
        """افحص مسارًا ضد الجذور — يعيد (المحلول، None) أو (None، سبب عربي).

        **المسار النسبي يُثبَّت على الجذر الأول** — لا على مجلد العمل
        للعملية — فلا يتغير معنى المسار بتغير من ينادي؛ والمطلق يفحص
        كما هو. الأسباب الثابتة بالترتيب: بلا جذور في العقد، مسار
        فارغ/عدوي، محارف تحكم (NUL)، خارج كل الجذور. الفحص يresolve
        الفعلي — ``..`` يطويه التطبيع ثم يفحص الناتج، فلا يمر خروج
        مسارًا مكتوبًا بشكل ملتوٍ، ورمز الارتباط مغطى بالحسم لأن
        candidate هو الهدف النهائي بعد متابعة كل الارتباطات.
        """
        if not self.roots:
            return None, "العقد بلا جذور مسموحة — لا مسار يُقبل"
        text = "" if path is None else str(path)
        if not text.strip():
            return None, "المسار فارغ"
        if "\x00" in text:
            return None, "المسار يحوي محرف NUL — مرفوض"
        if not Path(text).is_absolute():
            text = str(Path(self.roots[0]) / text)
        try:
            candidate = Path(text).resolve()
        except (OSError, ValueError) as exc:  # ValueError على المحارف الغريبة
            return None, f"مسار غير قابل للحسم — {type(exc).__name__}"
        for root_text in self.roots:
            root = Path(root_text).resolve()
            if candidate == root or root in candidate.parents:
                # رمز الارتباط مغطى بالحسم: candidate هو الهدف النهائي
                # بعد متابعة كل الارتباطات — خروجه عن الجذر يفشل فحص
                # الأهل هنا فلا يمر خروج مُخفى خلف اسم بريء
                return candidate, None
        return None, f"المسار خارج الجذور المسموحة ({len(self.roots)} جذرًا)"

    # ------------------------------------------------------------ الأوامر
    def check_command(self, argv: object) -> tuple[tuple[str, ...] | None, str | None]:
        """افحص argv ضد القائمة البيضاء ومحارف الصدفة — قائمة أو سبب عربي.

        العقد: argv قائمة نصوص (لا نص واحد يُفتّل صدفة)، أول token
        من ``allowed_commands``، وكل token خالٍ من محارف الصدفة —
        فحص عمق فوق التنفيذ بلا shell أصلًا.
        """
        if not self.allow_run_tests:
            return None, "العقد لا يفعّل تشغيل الاختبارات"
        if not self.allowed_commands:
            return None, "العقد بقائمة أوامر فارغة — لا أمر يُبيَّح"
        if isinstance(argv, str) or not isinstance(argv, (list, tuple)):
            return None, "الأمر يجب أن يكون قائمة tokens لا نصًا واحدًا"
        tokens = tuple(str(t) for t in argv)
        if not tokens or not tokens[0].strip():
            return None, "الأمر فارغ"
        if tokens[0].strip() not in self.allowed_commands:
            return None, f"الأمر «{tokens[0][:24]}» خارج القائمة البيضاء"
        for token in tokens:
            if not token.strip():
                return None, "token فارغ في argv"
            for ch in token:
                if ch in DENY_ARGV_CHARS:
                    return None, f"محرف صدفة مرفوض في argv: {ch!r}"
            if "\x00" in token:
                return None, "محرف NUL في argv — مرفوض"
            if ".." in token:
                return None, "اجتياز جذر في argv مرفوض — لا «..» في أي وسيط"
            if token.startswith("/") or (len(token) > 2 and token[1] == ":"):
                return None, "مسار مطلق في argv مرفوض — التشغيل يثبَّت على جذر العقد"
        return tokens, None

    # ------------------------------------------------------------ البيئة
    def sanitized_env(self) -> dict[str, str]:
        """بيئة تشغيل بيضاء دنيا — بلا سر يعبر مهما كان في البيئة الأصل.

        القائمة البيضاء (``ENV_KEEP_KEYS`` + بقايا ويندوز) تُنسخ من
        البيئة الفعلية، ثم يُسقط منها أي مفتاح فيه شبه سر من
        ``ENV_DENY_TOKENS`` (حماية عمق: مفتاح اسمه فيه TOKEN لا يعبر
        حتى لو أُضيف للقائمة البيضاء لاحقًا)، ثم تُضاف خواص
        الاستقرار (ترميز، لا bytecode). ``sanitize_env=False`` يعطي
        البيئة كما هي — باب صريح موثق للاختبارات لا باب خفي.
        """
        if not self.sanitize_env:
            return dict(os.environ)
        env: dict[str, str] = {}
        keep = ENV_KEEP_KEYS + ENV_KEEP_WINDOWS
        for name in keep:
            value = os.environ.get(name)
            if value is not None and not self._is_secret_name(name):
                env[name] = value
        env.setdefault("LANG", "C.UTF-8")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONHASHSEED"] = "0"  # حتمية أعمق في الأكواد الفرعية
        return env

    @staticmethod
    def _is_secret_name(name: str) -> bool:
        """هل اسم المفتاح يشبه سرًا؟ — فحص علوي الحالة ضد الأسمية الموثقة."""
        upper = name.upper()
        return any(token in upper for token in ENV_DENY_TOKENS)

    # ------------------------------------------------------------ التوثيق
    def to_dict(self) -> dict:
        """ممثل JSON حتمي — مفاتيح مفرزة، جذور مفرزة، بلا أي زمن."""
        return {
            "allow_patch": self.allow_patch,
            "allow_run_tests": self.allow_run_tests,
            "allowed_commands": list(self.allowed_commands),
            "max_file_bytes": self.max_file_bytes,
            "max_output_chars": self.max_output_chars,
            "max_patch_ops": self.max_patch_ops,
            "roots": sorted(self.roots),
            "sanitize_env": self.sanitize_env,
            "timeout_s": self.timeout_s,
        }


__all__ = [
    "DEFAULT_ALLOWED_COMMANDS",
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_MAX_OUTPUT_CHARS",
    "DEFAULT_MAX_PATCH_OPS",
    "DEFAULT_TIMEOUT_S",
    "DENY_ARGV_CHARS",
    "ENV_DENY_TOKENS",
    "ENV_KEEP_KEYS",
    "MAX_FILE_BYTES_LIMIT",
    "MAX_ROOTS",
    "MAX_TIMEOUT_S",
    "PermissionContract",
]
