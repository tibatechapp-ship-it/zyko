"""zyko.baseline.engine — حارس الجودة عبر الزمن: خط أساس حتمي وكشف التراجع.

المرحلة 6 من خطة المحرك: حتى المرحلة 5 كان المحرك «لقطة واحدة» — يراجع
ويعالج ثم يودّعك. هذا الملف يجعله **حارسًا دائمًا**: يسجّل حالة مشروعك
في خط أساس حتمي (``.zyko/baseline.json``)، ثم كل فحص لاحق يقارن الوضع
الحالي به ويجيب بالأرقام: ما التراجع؟ ما التحسن؟ وما الجديد؟

العقود الثلاثة كما في كل المراحل:

- الحتمية: نفس الشجرة ⇒ نفس بايتات ملف خط الأساس ونفس الحمولة — بلا
  طوابع زمنية إطلاقًا (رقم التشغيل ``run_no`` هو الساعة الوحيدة)
- الفشل المهيكل: أي مدخل عدائي ⇒ نتيجة موقعة (failed_stage + سبب عربي)
  بلا أي استثناء خارجي — لا انهيار مهما كان خط الأساس فاسدًا
- الأمانة: خط الأساس يسجّل **حالة القرص الفعلية** (درجة كل ملف وملاحظاته
  كما يراها المراجع)، ولا يلمس ``check`` بايتًا واحدًا على القرص

تقسيم الصلاحيات على القرص صريح ومحكم:

- ``update``: يكتب ملفًا واحدًا فقط — خط الأساس — ولا يلمس أي ملف مشروع
- ``check``: يقرأ فقط — لا خط أساس ولا شيفرة تُكتب مهما كانت الظروف
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zyko.reviewer.engine import MAX_SOURCE_BYTES, ReviewEngine, verdict_for_score
from zyko.workspace.engine import _collect_py_files

# مخطط ملف خط الأساس — يتغير فقط بمراجعة مقصودة مع توثيق في CHANGELOG.
SCHEMA = "zyko.baseline/1"

# مكان خط الأساس الافتراضي داخل المشروع: <src>/.zyko/baseline.json
BASELINE_DIRNAME = ".zyko"
BASELINE_FILENAME = "baseline.json"

# سقف سجل التشغيلات المحفوظ (الأحدث في النهاية) — ما فوقه يُنسى من الأقدم.
HISTORY_CAP = 20

STAGE_SCAN = "scan"
STAGE_REVIEWER = "reviewer"
STAGE_BASELINE = "baseline"

STAGE_AR: dict[str, str] = {
    STAGE_SCAN: "المسح",
    STAGE_REVIEWER: "المراجعة",
    STAGE_BASELINE: "خط الأساس",
}

# حالة ملف في المقارنة (خط الأساس ⇦ الحاضر)
F_REGRESSED = "regressed"
F_IMPROVED = "improved"
F_UNCHANGED = "unchanged"
F_NEW = "new"
F_GONE = "gone"
F_SKIPPED = "skipped"

FILE_STATUS_AR: dict[str, str] = {
    F_REGRESSED: "تراجع",
    F_IMPROVED: "تحسّن",
    F_UNCHANGED: "ثابت",
    F_NEW: "جديد",
    F_GONE: "اختفت",
    F_SKIPPED: "تُخُطّي",
}

VERDICT_MISSING = "لا خط أساس — شغّل update أولًا ليُسجَّل الوضع الحالي"
VERDICT_NO_PY = "لا مراجعة — لا ملفات بايثون في المجلد"


def default_baseline_path(src: str | Path) -> Path:
    """المكان الافتراضي لخط الأساس داخل المشروع: ``<src>/.zyko/baseline.json``."""
    return Path(src) / BASELINE_DIRNAME / BASELINE_FILENAME


@dataclass
class BaselineUpdateResult:
    """نتيجة update: تسجيل لقطة الجودة الحالية في خط الأساس."""

    src: str
    baseline_path: str
    ok: bool = True
    failed_stage: str | None = None
    error_ar: str | None = None
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    created: bool = False  # True إن كان هذا أول تسجيل (لا خط أساس سابق)
    run_no: int = 0
    files_total: int = 0
    reviewed: int = 0
    skipped: int = 0
    min_score: int | None = None
    findings_total: int = 0
    history_len: int = 0
    verdict_ar: str = ""
    seconds: float = 0.0

    @property
    def exit_code(self) -> int:
        """اصطلاح المراحل: 0 نجاح، 2 فشل مهيكل (update لا يعيد 1 أبدًا)."""
        return 0 if self.ok else 2

    def to_dict(self, *, include_timing: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "mode": "update",
            "ok": self.ok,
            "src": self.src,
            "baseline_path": self.baseline_path,
            "failed_stage": self.failed_stage,
            "error_ar": self.error_ar,
            "problems": list(self.problems),
            "notes": list(self.notes),
            "created": self.created,
            "run_no": self.run_no,
            "files_total": self.files_total,
            "reviewed": self.reviewed,
            "skipped": self.skipped,
            "min_score": self.min_score,
            "findings_total": self.findings_total,
            "history_len": self.history_len,
            "verdict_ar": self.verdict_ar,
        }
        if include_timing:
            payload["seconds"] = round(self.seconds, 4)
        return payload


@dataclass
class BaselineCheckResult:
    """نتيجة check: مقارنة الوضع الحالي بخط الأساس — قراءة فقط دائمًا."""

    src: str
    baseline_path: str
    ok: bool = True
    failed_stage: str | None = None
    error_ar: str | None = None
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    baseline_status: str = "ok"  # ok | missing
    baseline_run_no: int = 0
    files_total: int = 0
    reviewed: int = 0
    skipped: int = 0
    regressed_files: int = 0
    improved_files: int = 0
    unchanged_files: int = 0
    new_files: int = 0
    gone_files: int = 0
    skipped_files: int = 0
    new_findings_total: int = 0
    resolved_findings_total: int = 0
    min_score_baseline: int | None = None
    min_score_current: int | None = None
    verdict_ar: str = ""
    per_file: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def exit_code(self) -> int:
        """0 لا تراجع، 1 تراجع مكتشف أو لا خط أساس أو توقف القياس، 2 فشل مهيكل."""
        if not self.ok:
            return 2
        if self.baseline_status != "ok":
            return 1
        if self.regressed_files > 0:
            return 1
        # كل الملفات المراقَبة اختفت أو صارت غير قابلة للقراءة ⇒ القياس متوقف
        if self.reviewed == 0 and (self.gone_files + self.skipped_files) > 0:
            return 1
        return 0

    def to_dict(self, *, include_timing: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "mode": "check",
            "ok": self.ok,
            "src": self.src,
            "baseline_path": self.baseline_path,
            "failed_stage": self.failed_stage,
            "error_ar": self.error_ar,
            "problems": list(self.problems),
            "notes": list(self.notes),
            "baseline_status": self.baseline_status,
            "baseline_run_no": self.baseline_run_no,
            "files_total": self.files_total,
            "reviewed": self.reviewed,
            "skipped": self.skipped,
            "regressed_files": self.regressed_files,
            "improved_files": self.improved_files,
            "unchanged_files": self.unchanged_files,
            "new_files": self.new_files,
            "gone_files": self.gone_files,
            "skipped_files": self.skipped_files,
            "new_findings_total": self.new_findings_total,
            "resolved_findings_total": self.resolved_findings_total,
            "min_score_baseline": self.min_score_baseline,
            "min_score_current": self.min_score_current,
            "verdict_ar": self.verdict_ar,
            "per_file": [dict(f) for f in self.per_file],
            "history": [dict(h) for h in self.history],
        }
        if include_timing:
            payload["seconds"] = round(self.seconds, 4)
        return payload


class BaselineEngine:
    """خط أساس حتمي وكشف تراجع لمجلد بايثون قائم — بلا نموذج وبلا شبكة.

    يعتمد على مراجع المرحلة 2 (27 قاعدة AST) لتقييم حالة القرص الفعلية؛
    المُصلِح ليس له دور هنا — خط الأساس يسجّل الواقع لا الطموح.
    """

    def __init__(self, reviewer: ReviewEngine | None = None) -> None:
        self.reviewer = reviewer or ReviewEngine()

    # ------------------------------------------------------------ update
    def update(
        self,
        src: object,
        baseline_path: str | Path | None = None,
    ) -> BaselineUpdateResult:
        """سجّل الوضع الحالي كخط أساس — يكتب ملفًا واحدًا ولا يلمس المشروع."""
        started = time.perf_counter()
        check_src = self._validate_src(src)
        if isinstance(check_src, str):
            return self._fail_update(str(src), check_src, started)
        src_str, root = check_src

        try:
            records, skipped, walk_note = self._review_tree(root)
        except _WalkError as exc:
            return self._fail_update(src_str, str(exc), started)

        bpath, berr = self._resolve_baseline_path(root, baseline_path)
        if berr:
            return self._fail_update(src_str, berr, started)

        # خط أساس سابق؟ الفاسد لا يعيق التحديث — التحديث طريق الإصلاح دائمًا.
        previous, prev_note = self._load_previous(bpath)
        run_no = (previous.get("run_no") or 0) + 1 if previous else 1
        history: list[dict[str, Any]] = list(previous.get("history") or []) if previous else []
        notes = list(walk_note)
        if prev_note:
            notes.append(prev_note)

        scores = [r["score"] for r in records.values()]
        min_score = min(scores) if scores else None
        findings_total = sum(len(r["findings"]) for r in records.values())
        history.append(
            {
                "run_no": run_no,
                "files_total": len(records) + len(skipped),
                "reviewed": len(records),
                "skipped": len(skipped),
                "min_score": min_score,
                "findings_total": findings_total,
            }
        )
        del history[:-HISTORY_CAP]

        snapshot: dict[str, Any] = {
            "schema": SCHEMA,
            "run_no": run_no,
            "files_total": len(records) + len(skipped),
            "reviewed": len(records),
            "skipped": len(skipped),
            "min_score": min_score,
            "findings_total": findings_total,
            "files": records,
            "history": history,
        }
        try:
            bpath.parent.mkdir(parents=True, exist_ok=True)
            bpath.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        except OSError as exc:
            return self._fail_update(src_str, f"تعذرت كتابة خط الأساس: {exc}", started)

        verdict = verdict_for_score(min_score) if min_score is not None else VERDICT_NO_PY
        return BaselineUpdateResult(
            src=src_str,
            baseline_path=str(bpath),
            created=previous is None,
            run_no=run_no,
            files_total=len(records) + len(skipped),
            reviewed=len(records),
            skipped=len(skipped),
            min_score=min_score,
            findings_total=findings_total,
            history_len=len(history),
            verdict_ar=verdict,
            notes=notes,
            seconds=time.perf_counter() - started,
        )

    # ------------------------------------------------------------- check
    def check(
        self,
        src: object,
        baseline_path: str | Path | None = None,
    ) -> BaselineCheckResult:
        """قارن الوضع الحالي بخط الأساس — قراءة فقط: لا يُكتب بايت واحد."""
        started = time.perf_counter()
        check_src = self._validate_src(src)
        if isinstance(check_src, str):
            return self._fail_check(str(src), str(baseline_path or ""), check_src, started)
        src_str, root = check_src

        bpath = Path(baseline_path) if baseline_path else default_baseline_path(root)
        bpath_str = str(bpath)

        # ---- 1) خط الأساس: مفقود ⇒ حالة موثقة (خروج 1) لا فشل مهيكل
        if not bpath.exists():
            result = self._review_and_compare(src_str, root, None, bpath_str, started)
            result.baseline_status = "missing"
            result.verdict_ar = VERDICT_MISSING
            return result
        if bpath.is_dir():
            return self._fail_check(
                src_str, bpath_str, f"مسار خط الأساس مجلد لا ملف: {bpath_str}", started
            )
        try:
            raw = bpath.read_bytes()
        except OSError as exc:
            return self._fail_check(src_str, bpath_str, f"تعذرت قراءة خط الأساس: {exc}", started)
        try:
            stored = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return self._fail_check(
                src_str,
                bpath_str,
                f"خط الأساس فاسد (ليس JSON سليمًا بترميز UTF-8): {type(exc).__name__}"
                " — أعِد إنشاءه بأمر update",
                started,
            )
        verr = _validate_snapshot(stored)
        if verr:
            return self._fail_check(src_str, bpath_str, f"خط الأساس غير صالح: {verr}", started)

        return self._review_and_compare(src_str, root, stored, bpath_str, started)

    # --------------------------------------------------------- المساعدات
    @staticmethod
    def _validate_src(src: object) -> tuple[str, Path] | str:
        """تحقق مدخل المسار — (النص، المسار) أو رسالة عربية."""
        if isinstance(src, bytes):
            return "المسار يجب أن يكون نصًا أو Path — وصل bytes"
        if not isinstance(src, (str, Path)):
            return "المسار يجب أن يكون نصًا أو Path — وصل نوع غير مسار"
        if isinstance(src, str) and not src.strip():
            return "المسار فارغ — أعطِ مجلد المشروع القائم"
        root = Path(src)
        if not root.exists():
            return f"المجلد غير موجود: {src}"
        if not root.is_dir():
            return f"المسار ليس مجلدًا (وُجد ملف): {src}"
        return str(src), root

    @staticmethod
    def _resolve_baseline_path(
        root: Path, baseline_path: str | Path | None
    ) -> tuple[Path | None, str]:
        """تحقق مسار خط الأساس لـupdate — (المسار، "") أو ("", رسالة عربية)."""
        if baseline_path is None:
            return default_baseline_path(root), ""
        if isinstance(baseline_path, bytes):
            return None, "مسار خط الأساس يجب أن يكون نصًا أو Path — وصل bytes"
        if not isinstance(baseline_path, (str, Path)):
            return None, "مسار خط الأساس يجب أن يكون نصًا أو Path — وصل نوع غير مسار"
        if isinstance(baseline_path, str) and not baseline_path.strip():
            return None, "مسار خط الأساس فارغ — أعطِ ملفًا أو اتركه للافتراضي داخل المشروع"
        p = Path(baseline_path)
        if p.is_dir():
            return None, f"مسار خط الأساس مجلد لا ملف: {p}"
        return p, ""

    @staticmethod
    def _load_previous(bpath: Path) -> tuple[dict[str, Any] | None, str]:
        """اقرأ خط أساس سابقًا لأجل run_no والتاريخ — الفاسد يُتجاهل بملاحظة."""
        try:
            raw = bpath.read_bytes()
            stored = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None, "خط الأساس السابق فاسد أو غير مقروء — أُنشئ من جديد"
        if not isinstance(stored, dict) or stored.get("schema") != SCHEMA:
            return None, "خط الأساس السابق بمخطط غير معروف — أُنشئ من جديد"
        if not isinstance(stored.get("files"), dict):
            return None, "خط الأساس السابق بقسم ملفات غير صالح — أُنشئ من جديد"
        return stored, ""

    def _review_tree(
        self, root: Path
    ) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[str]]:
        """راجع شجرة المشروع: سجلات الملفات + المتخطاة + ملاحظات المسح.

        يرفع ``_WalkError`` عند فشل المسح أو عطب المراجع — يتحول فورًا
        إلى فشل مهيكل عند المستدعي.
        """
        try:
            py_files, truncated = _collect_py_files(root)
        except OSError as exc:
            raise _WalkError(f"تعذر مسح المجلد: {exc}") from exc
        notes: list[str] = []
        if truncated:
            notes.append("المجلد يضم ملفات فوق السقف — عولج أول 500 فقط")

        records: dict[str, dict[str, Any]] = {}
        skipped: dict[str, str] = {}
        for p in py_files:
            rel = p.relative_to(root).as_posix()
            try:
                raw = p.read_bytes()
            except OSError as exc:
                skipped[rel] = f"تعذرت قراءة الملف: {exc}"
                continue
            if len(raw) > MAX_SOURCE_BYTES:
                skipped[rel] = f"حجم الملف يتجاوز الحد ({len(raw)} بايت > {MAX_SOURCE_BYTES})"
                continue
            try:
                source = raw.decode("utf-8")
            except UnicodeDecodeError:
                skipped[rel] = "ترميز الملف ليس UTF-8 — مراجعة نصية غير ممكنة"
                continue
            try:
                review = self.reviewer.review_source(source, rel)
            except Exception as exc:  # noqa: BLE001 — عطب مراجع يُصدَر مهيكلاً
                raise _WalkError(f"عطب غير متوقع في المراجع: {type(exc).__name__}") from exc
            records[rel] = {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "score": review.score,
                "findings": sorted(f.rule_id for f in review.findings),
            }
        return records, skipped, notes

    def _review_and_compare(
        self,
        src_str: str,
        root: Path,
        stored: dict[str, Any] | None,
        bpath_str: str,
        started: float,
    ) -> BaselineCheckResult:
        """المراجعة الحالية ثم المقارنة بخط الأساس (أو حالة «مفقود»)."""
        try:
            records, skipped, notes = self._review_tree(root)
        except _WalkError as exc:
            return self._fail_check(src_str, bpath_str, str(exc), started)

        base_files: dict[str, dict[str, Any]] = (stored or {}).get("files") or {}
        base_run_no = int((stored or {}).get("run_no") or 0)
        history = [dict(h) for h in ((stored or {}).get("history") or [])]

        per_file: list[dict[str, Any]] = []
        regressed = improved = unchanged = new = gone = skipped_now = 0
        new_findings_total = resolved_findings_total = 0

        for path in sorted(records):
            cur = records[path]
            base = base_files.get(path)
            if base is None:
                new += 1
                per_file.append(
                    {
                        "path": path,
                        "status": F_NEW,
                        "score_baseline": None,
                        "score_current": cur["score"],
                        "new_findings": len(cur["findings"]),
                        "resolved_findings": 0,
                        "sha_changed": True,
                    }
                )
                new_findings_total += len(cur["findings"])
                continue
            base_findings = Counter(base.get("findings") or [])
            cur_findings = Counter(cur["findings"])
            added = cur_findings - base_findings
            removed = base_findings - cur_findings
            new_n, resolved_n = sum(added.values()), sum(removed.values())
            new_findings_total += new_n
            resolved_findings_total += resolved_n
            score_base, score_cur = int(base.get("score") or 0), cur["score"]
            if score_cur < score_base or new_n > 0:
                status = F_REGRESSED
                regressed += 1
            elif score_cur > score_base or resolved_n > 0:
                status = F_IMPROVED
                improved += 1
            else:
                status = F_UNCHANGED
                unchanged += 1
            per_file.append(
                {
                    "path": path,
                    "status": status,
                    "score_baseline": score_base,
                    "score_current": score_cur,
                    "new_findings": new_n,
                    "resolved_findings": resolved_n,
                    "sha_changed": base.get("sha256") != cur["sha256"],
                }
            )

        for path in sorted(base_files):
            if path in records:
                continue
            score_base = int(base_files[path].get("score") or 0)
            if path in skipped:
                skipped_now += 1
                per_file.append(
                    {
                        "path": path,
                        "status": F_SKIPPED,
                        "score_baseline": score_base,
                        "score_current": None,
                        "new_findings": 0,
                        "resolved_findings": 0,
                        "sha_changed": True,
                    }
                )
            else:
                gone += 1
                per_file.append(
                    {
                        "path": path,
                        "status": F_GONE,
                        "score_baseline": score_base,
                        "score_current": None,
                        "new_findings": 0,
                        "resolved_findings": 0,
                        "sha_changed": True,
                    }
                )
        per_file.sort(key=lambda f: f["path"])

        scores = [r["score"] for r in records.values()]
        min_current = min(scores) if scores else None
        base_scores = [int(v.get("score") or 0) for v in base_files.values()]
        min_base = min(base_scores) if base_scores else None

        if regressed:
            verdict = f"تراجع مكتشف — {regressed} ملفًا تدهورت جودته"
        elif improved:
            verdict = "تحسّن بلا تراجع — حدِّث خط الأساس (update) لتثبيت التحسّن"
        elif records:
            verdict = "الجودة ثابتة — لا تراجع ولا تحسن منذ خط الأساس"
        elif base_files:
            # كل ما كان مراقَبًا اختفى أو صار غير قابل للقراءة — بلا قياس
            verdict = "لا ملفات بايثون قابلة للمراجعة — القياس متوقف"
        else:
            verdict = VERDICT_NO_PY

        return BaselineCheckResult(
            src=src_str,
            baseline_path=bpath_str,
            baseline_status="ok",
            baseline_run_no=base_run_no,
            files_total=len(records) + len(skipped),
            reviewed=len(records),
            skipped=len(skipped),
            regressed_files=regressed,
            improved_files=improved,
            unchanged_files=unchanged,
            new_files=new,
            gone_files=gone,
            skipped_files=skipped_now,
            new_findings_total=new_findings_total,
            resolved_findings_total=resolved_findings_total,
            min_score_baseline=min_base,
            min_score_current=min_current,
            verdict_ar=verdict,
            per_file=per_file,
            history=history,
            notes=list(notes),
            seconds=time.perf_counter() - started,
        )

    @staticmethod
    def _fail_update(src: str, message_ar: str, started: float) -> BaselineUpdateResult:
        return BaselineUpdateResult(
            src=src,
            baseline_path="",
            ok=False,
            failed_stage=_stage_of(message_ar),
            error_ar=message_ar,
            verdict_ar="فشل التحديث",
            seconds=time.perf_counter() - started,
        )

    @staticmethod
    def _fail_check(src: str, bpath: str, message_ar: str, started: float) -> BaselineCheckResult:
        return BaselineCheckResult(
            src=src,
            baseline_path=bpath,
            ok=False,
            failed_stage=_stage_of(message_ar),
            error_ar=message_ar,
            verdict_ar="فشل الفحص",
            seconds=time.perf_counter() - started,
        )


class _WalkError(Exception):
    """خطأ داخلي: فشل المسح أو المراجعة — يتحول فورًا إلى فشل مهيكل."""


def _stage_of(message_ar: str) -> str:
    """اختر المرحلة المناسبة من نص الرسالة — للتوثيق فقط."""
    if "خط الأساس" in message_ar:
        return STAGE_BASELINE
    if "المراجع" in message_ar:
        return STAGE_REVIEWER
    return STAGE_SCAN


def _validate_snapshot(stored: object) -> str:
    """تحقق هيكل خط الأساس المحمَّل — رسالة عربية أو ""."""
    if not isinstance(stored, dict):
        return "خط الأساس ليس كائن JSON (وصلت قائمة أو قيمة)"
    if stored.get("schema") != SCHEMA:
        return f"مخطط غير معروف: {stored.get('schema')!r} — المتوقع {SCHEMA}"
    files = stored.get("files")
    if not isinstance(files, dict):
        return "قسم الملفات (files) ليس كائنًا"
    for path, record in files.items():
        if not isinstance(path, str) or not path:
            return "مفتاح ملف غير صالح داخل files"
        if not isinstance(record, dict):
            return f"سجل الملف {path} ليس كائنًا"
        score = record.get("score")
        if isinstance(score, bool) or not isinstance(score, int):
            return f"درجة الملف {path} ليست عددًا صحيحًا"
        if not 0 <= score <= 100:
            return f"درجة الملف {path} خارج النطاق 0–100 ({score})"
        findings = record.get("findings")
        if not isinstance(findings, list) or any(not isinstance(f, str) for f in findings):
            return f"ملاحظات الملف {path} ليست قائمة نصوص"
        if not isinstance(record.get("sha256"), str):
            return f"بصمة الملف {path} (sha256) ليست نصًا"
    if not isinstance(stored.get("history", []), list):
        return "السجل (history) ليس قائمة"
    return ""


__all__ = [
    "BASELINE_DIRNAME",
    "BASELINE_FILENAME",
    "FILE_STATUS_AR",
    "F_GONE",
    "F_IMPROVED",
    "F_NEW",
    "F_REGRESSED",
    "F_SKIPPED",
    "F_UNCHANGED",
    "HISTORY_CAP",
    "SCHEMA",
    "STAGE_AR",
    "STAGE_BASELINE",
    "STAGE_REVIEWER",
    "STAGE_SCAN",
    "VERDICT_MISSING",
    "VERDICT_NO_PY",
    "BaselineCheckResult",
    "BaselineEngine",
    "BaselineUpdateResult",
    "default_baseline_path",
]
