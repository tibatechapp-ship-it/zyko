"""المكوّن 4 — compress: هضم المستودع إلى سياق يحتمل ميزانية الرموز.

الغرض: العقل الحتمي يحتاج «قراءة المستودع» في حجم يفهمه الدماغ — هذه الدالة
تقرأ المستودع بلا كتابة ولا نموذج لغوي، وترتّب ملفاته بترتيب أولوية ثابت
معلن، ثم تحزمها في ميزانية رموز محددة مع سجل كامل بما حُذف ولماذا.

القواعد الحاكمة (من تكليف العقل):
* حتمية بالبايت (R2): لا ``datetime`` ولا ``random`` ولا ``os.environ`` —
  نفس المستودع ونفس الميزانية تعطيان نفس ``CompressedContext`` بالبايت،
  دائماً (مُثبت باختبار 100 تشغيل).
* قراءة فقط (P4): لا تُكتب أي ملف — الدالة نقية على نظام الملفات.
* حذف مُعلن لا صامت: كل ملف أُسقط يظهر في ``omitted`` أو ``skipped_binary``
  مع سبب عربي في ``summary_ar`` — لا حذف خفي.
* ميزانية صادقة: ``_estimate_tokens(compress(...).to_text()) <= tokens_used
  <= max_tokens`` عقد مُثبت باختبار — لأن كل كتلة تُحسب بما ستصيَّر فعلاً
  (ترويسة الملف والمسافات ضمن الحساب، لا خارجها).

الترتيب المعلن (كسر التعادل: المسار أبجدياً):
    README (0) ← بيانات الحزمة pyproject/CITATION (1) ← مصادر src (2)
    ← docs (3) ← tests (4) ← إعدادات نصية (5) ← بقية النصوص (6)

تقدير الرموز heuristic مُعلَّق وموثَّق: ``ceil(عدد المحارف / 4)`` — تقريب
لأعلى عمداً (تحفّظ في الميزانية لا تهور)، لأن العربية تلصق السوابق والضمائر
فيأتي الرمز الفعلي أكبر غالباً من 4 محارف.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zyko.exceptions import ConfigError

# ميزانية صغيرة لا تسمح حتى بالشجرة — رفض مبكر برسالة عربية أوضح من صمت.
MIN_MAX_TOKENS = 32

# سقف قراءة الملف الواحد — ملفات شبه نادرة بهذا الحجم؛ السقف يحمي الذاكرة
# على Termux قبل أي حساب ميزانية (حتمي: نفس السقف لكل ملف بلا استثناء).
_MAX_FILE_CHARS = 100_000

# أدنى اقتطاع يُقبل: ملف لا يُقتطع إلا إذا أعطى الميزانية رأساً معقولاً —
# أقل من ذلك يُحذف كاملاً إلى omitted (مقتطع عديم الفائدة غشّ لا حزم).
MIN_SLICE_CHARS = 256

# علامة الاقتطاع — ثابتة معلنة؛ طولها يدخل حساب الميزانية بدقة.
TRUNCATION_MARKER = "… [مقتطع — الباقي حُذف حتمياً لتناسب الميزانية]"
# علامة اقتطاع الشجرة نفسها — عندما يفوق عدد المسارات الميزانية قبل أي محتوى.
TREE_MARKER = "… [الشجرة مقتطعة — المسارات المتبقية حُذفت حتمياً لتناسب الميزانية]"

# مجلدات الثرثارة التي لا سياق فيها — ثابتة معلنة، لا مفتاح بيئة يغيّرها.
SKIP_DIRS = (
    ".git",
    ".github",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "dist",
    "build",
)

# لواحق ثنائية معروفة — تُتخطى فوراً بلا قراءة (سريع وحتمي).
_SKIP_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
    ".bin",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".whl",
    ".woff",
    ".woff2",
    ".ttf",
    ".mp4",
    ".mp3",
)

# أولوية الحزم — كلما صغُر الرقم أُدخل أولاً؛ التعادل يُكسر أبجدياً.
_PRIORITY_EXACT: dict[str, int] = {
    "pyproject.toml": 1,
    "CITATION.cff": 1,
}
_PRIORITY_DIRS: tuple[tuple[str, int], ...] = (
    ("src", 2),
    ("docs", 3),
    ("tests", 4),
)


def _estimate_tokens(text: str) -> int:
    """تقدير رموز حتمي معلن: ``ceil(المحارف / 4)`` — تقريب لأعلى تحفّظاً."""
    return math.ceil(len(text) / 4)


def _priority_of(rel: str) -> int:
    """رتبة ملف حسب مساره النسبي — ثابتة معلنة في docstring الوحدة."""
    name = rel.rsplit("/", 1)[-1]
    if name.lower().startswith("readme"):
        return 0
    if rel in _PRIORITY_EXACT:
        return _PRIORITY_EXACT[rel]
    for prefix, rank in _PRIORITY_DIRS:
        if rel == prefix or rel.startswith(prefix + "/"):
            return rank
    if name.endswith((".yaml", ".yml", ".json", ".toml", ".cff", ".md", ".rst")):
        return 5
    return 6


def _is_binary_head(path: Path) -> bool:
    """كشف ثنائي رخيص وحتمي: لاحقة معروفة أو بايت NUL في أول 8KB."""
    if path.suffix.lower() in _SKIP_SUFFIXES:
        return True
    try:
        with path.open("rb") as fh:
            return b"\x00" in fh.read(8192)
    except OSError:
        return True


def _canonical(payload: Any) -> str:
    """تسلسل JSON كنسي — نفس الدالة في run وverify (عقد بايت واحد)."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(text: str) -> str:
    """بصمة نص — نفس دالة run لسلسلة البصمات المشتركة."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_block(rel: str, content: str) -> str:
    """الكتلة المُصيَّرة للملف — حرفياً كما ستظهر في ``to_text``؛ مكان واحد."""
    return f"\n\n=== {rel} ===\n{content}"


@dataclass(frozen=True)
class FileSlice:
    """مقتطف ملف مُدخل في السياق: مساره ومحتواه وبصمته ورموز محتواه."""

    path: str
    content: str
    tokens: int  # رموز المحتوى وحده — الترويسة تحسب في ميزانية الحزم بدقة
    sha256: str
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        """ممثل JSON كامل — مفاتيح ثابتة وقيم قابلة للتسلسل."""
        return {
            "path": self.path,
            "content": self.content,
            "tokens": self.tokens,
            "sha256": self.sha256,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class CompressedContext:
    """هضم المستودع الحتمي — مجمّد، قابل للتسلسل، وبصمته sha256."""

    repo_path: str
    max_tokens: int
    files: tuple[FileSlice, ...]
    tree: tuple[str, ...]
    tree_dropped: int  # مسارات الشجرة التي حُذفت لأن الشجرة نفسها فاقت الميزانية
    tree_marker_rendered: bool  # هل اقتضت علامة الاقتطاع مكاناً في الميزانية فعلاً
    skipped_binary: tuple[str, ...]
    omitted: tuple[str, ...]
    tokens_used: int
    summary_ar: str
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        """ممثل JSON كامل — نفس المفتاح دائماً، نفس القيمة بالبايت."""
        return {
            "repo_path": self.repo_path,
            "max_tokens": self.max_tokens,
            "files": [f.to_dict() for f in self.files],
            "tree": list(self.tree),
            "tree_dropped": self.tree_dropped,
            "tree_marker_rendered": self.tree_marker_rendered,
            "skipped_binary": list(self.skipped_binary),
            "omitted": list(self.omitted),
            "tokens_used": self.tokens_used,
            "summary_ar": self.summary_ar,
            "fingerprint": self.fingerprint,
        }

    def to_text(self) -> str:
        """السياق المُصيَّر نصاً — ما يُعرض فعلاً على الدماغ؛ حتمي بالبايت.

        العقد: ``_estimate_tokens(self.to_text()) <= tokens_used <= max_tokens``
        — لأن كل كتلة تُدخل ميزانيتها بما تصيَّر حرفياً (``_file_block``).
        """
        header = f"سياق المستودع — {len(self.tree)} ملفاً نصياً؛ ما دون الفواصل ضمن الميزانية"
        tree_block = "\n".join(self.tree)
        if self.tree_marker_rendered:
            tree_block = tree_block + "\n" + TREE_MARKER if self.tree else TREE_MARKER
        parts = [header, tree_block]
        parts.extend(_file_block(f.path, f.content) for f in self.files)
        return "".join(parts)


def compress(repo_path: str | Path, *, max_tokens: int = 10_000) -> CompressedContext:
    """اهضم المستودع إلى سياق نصي ضمن ميزانية رموز — حتمي بلا كتابة.

    الترتيب: README ثم بيانات الحزمة ثم المصادر ثم docs ثم tests ثم
    الإعدادات ثم البقية؛ التعادل أبجدي. ما لا يسع يُحذف معلناً في
    ``omitted``، والثنائي يُتخطى معلناً في ``skipped_binary``. الملف
    الأكبر من المتبقي يُقتطع رأساً بعلامة عربية إن سمح المتبقي بحد أدنى
    (``MIN_SLICE_CHARS``)، وإلا حُذف كاملاً — مقتطع عديم الفائدة غشّ.
    """
    root = Path("" if repo_path is None else str(repo_path))
    if not root.exists():
        raise ConfigError(f"مسار المستودع غير موجود: {root}")
    if not root.is_dir():
        raise ConfigError(f"مسار المستودع ليس مجلداً: {root}")
    if max_tokens < MIN_MAX_TOKENS:
        raise ConfigError(f"ميزانية الرموز أصغر من الحد الأدنى {MIN_MAX_TOKENS}: {max_tokens}")

    candidates: list[tuple[int, str, Path]] = []
    skipped_binary: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in SKIP_DIRS for part in path.parts[:-1]):
            continue
        if path.name.endswith(".egg-info"):
            continue
        if _is_binary_head(path):
            skipped_binary.append(rel)
            continue
        candidates.append((_priority_of(rel), rel, path))
    candidates.sort(key=lambda c: (c[0], c[1]))

    tree = tuple(rel for _, rel, _ in candidates)
    header = f"سياق المستودع — {len(tree)} ملفاً نصياً؛ ما دون الفواصل ضمن الميزانية"

    # الشجرة نفسها تُدخل الميزانية — لكن بحصة لا تتجاوز نصفها: مستودع ضخم
    # قد تأكل شجرته الميزانية كاملة وتترك صفراً للمحتوى؛ حينها تُقتطع من
    # النهاية (الأدنى أولوية) بإعلان حتمي، ويبقى نصف الميزانية للمحتوى.
    tree_share = max_tokens // 2
    tree_available = min(max_tokens - _estimate_tokens(header), tree_share)
    tree_dropped = 0
    tree_marker_rendered = False
    tree_block = "\n".join(tree)
    if _estimate_tokens(tree_block) > tree_available:
        kept = len(tree)
        tree_block = "\n".join(tree[:kept])
        while kept > 0 and _estimate_tokens(tree_block + "\n" + TREE_MARKER) > tree_available:
            kept -= 1
            tree_block = "\n".join(tree[:kept])
        tree_dropped = len(tree) - kept
        tree = tree[:kept]
        if tree_dropped and _estimate_tokens(TREE_MARKER) <= tree_available:
            tree_marker_rendered = True
            tree_block = tree_block + "\n" + TREE_MARKER if kept else TREE_MARKER
        elif tree_dropped:
            # حتى العلامة لا تسع — الإعلان يبقى في summary_ar وtree_dropped فقط.
            tree_block = "\n".join(tree)

    remaining = max_tokens - _estimate_tokens(header) - _estimate_tokens(tree_block)

    files: list[FileSlice] = []
    omitted: list[str] = []
    spent = 0
    for _, rel, path in candidates:
        try:
            content = path.read_text(encoding="utf-8", errors="strict")[:_MAX_FILE_CHARS]
        except (UnicodeDecodeError, OSError):
            # اكتُشف ثنائياً بعد الفحص الرخيص — إسقاط معلن لا صامت.
            if rel not in skipped_binary:
                skipped_binary.append(rel)
                skipped_binary.sort()
            continue
        block_cost = _estimate_tokens(_file_block(rel, content))
        if block_cost <= remaining:
            files.append(
                FileSlice(rel, content, _estimate_tokens(content), _sha256(content), False)
            )
            remaining -= block_cost
            spent += block_cost
            continue
        # لا يسع كاملاً: اقتطاع رأس بحجم محسوب حرفياً من المتبقي.
        prefix_len = len(_file_block(rel, ""))
        allowed = remaining * 4 - prefix_len - len(TRUNCATION_MARKER)
        if allowed >= MIN_SLICE_CHARS:
            head = content[:allowed]
            head_block = _file_block(rel, head + TRUNCATION_MARKER)
            head_cost = _estimate_tokens(head_block)
            files.append(
                FileSlice(
                    rel,
                    head + TRUNCATION_MARKER,
                    _estimate_tokens(head),
                    _sha256(head + TRUNCATION_MARKER),
                    True,
                )
            )
            remaining -= head_cost
            spent += head_cost
        omitted.append(rel)

    skipped_binary = tuple(sorted(skipped_binary))
    tokens_used = _estimate_tokens(header) + _estimate_tokens(tree_block) + spent
    summary_ar = (
        f"هضم حتمي: {len(tree)} ملفاً نصياً"
        + (f" (اقتُطعت من الشجرة {tree_dropped})" if tree_dropped else "")
        + f"، دخل منها {len(files)} "
        f"(مُقتطع: {sum(1 for f in files if f.truncated)})، حُذف للميزانية {len(omitted)}، "
        f"تخطي ثنائي {len(skipped_binary)} — استُخدم {tokens_used} من {max_tokens} رمزاً"
    )
    payload = {
        "tokens_used": tokens_used,
        "files": [f.to_dict() for f in files],
        "tree": list(tree),
        "tree_dropped": tree_dropped,
        "tree_marker_rendered": tree_marker_rendered,
        "omitted": list(omitted),
        "skipped_binary": list(skipped_binary),
    }
    return CompressedContext(
        repo_path=str(root),
        max_tokens=max_tokens,
        files=tuple(files),
        tree=tree,
        tree_dropped=tree_dropped,
        tree_marker_rendered=tree_marker_rendered,
        skipped_binary=skipped_binary,
        omitted=tuple(omitted),
        tokens_used=tokens_used,
        summary_ar=summary_ar,
        fingerprint=_sha256(_canonical(payload)),
    )
