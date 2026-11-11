"""zyko.sandbox.audit — سجل التدقيق: JSONL ملحق-فقط بسلسلة sha256.

كل محاولة أداة — **مسموحة أو مرفوضة أو خاطئة** — تُوقَّع في سجل موثق:
الرفض يُدقَّق لاحقًا فقط إذا كتب، والصمت هنا ثغرة لا فضيلة. السجل
ملحق-فقط (append-only): لا تعديل ولا حذف عبر الواجهة، وكل سطر يحمل
``seq`` و``prev_hash`` و``hash`` — سلسلة تجزئة يكشف أي عبث (تعديل
سطر، حذف سطر، إعادة ترتيب) بإعادة الحساب من الرأس.

الزمن خارج السلسلة — عقد إيصال العقل نفسه: ``ts`` يُخزَّن في السطر
للجدولة البشرية ولا يدخل حساب الهاش، فالتشغيلات المتطابقة تعطي سلسلة
متطابقة بالبايت مهما تأخر الزمن، وإعادة توليد الأحداث نفسها تعيد نفس
السجل. التفاصيل المسقوفة حتميًا (سقف محارف بقصّة موثقة) فلا ينمو
السطر بلا حد مع مدخل عدوي، وأي نص يشبه سرًا يُقنَّع قبل التدوين —
دفاع عمق فوق عقد «لا تسرّب الأسرار» في المستودع.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

AUDIT_SCHEMA = "zyko.audit.v1"  # مخطط السجل — التغيير كسر موثق للسلسلة

MAX_DETAIL_VALUE_CHARS = 240  # سقف قيمة مفردة في التفاصيل قبل القصّ الموثق
MAX_REASON_CHARS = 600  # سقف السبب العربي — نفس ميزانية ملاحظة الانعكاس
ENTRY_TRUNCATION_MARK = "…[مقتطع]"  # علامة القصّ الحتمية داخل القيمة

# أنماط الأسرار الشائعة — تُقنَّع في أي قيمة نصية قبل التدوين (دفاع عمق)
_SECRET_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
)
_SECRET_MASK = "[سر-مقنّع]"


def _scrub(text: str) -> str:
    """اقنَع كل ما يشبه سرًا في النص — قبل أن يلمس القرص بأي شكل."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_SECRET_MASK, text)
    return text


def _clamp_value(value: str) -> str:
    """قصّ حتمي لقيمة طويلة — نفس المدخل يعطي نفس المقتطع بالبايت."""
    if len(value) <= MAX_DETAIL_VALUE_CHARS:
        return value
    keep = max(0, MAX_DETAIL_VALUE_CHARS - len(ENTRY_TRUNCATION_MARK))
    return value[:keep] + ENTRY_TRUNCATION_MARK


def _clean_detail(detail: dict) -> dict:
    """طبّع التفاصيل: نصوص مقنّعة ومقتطعة، مفاتيح نصية، أرقام كما هي."""
    cleaned: dict = {}
    for key, value in dict(detail or {}).items():
        key = _scrub(str(key))[:MAX_DETAIL_VALUE_CHARS] or "مفتاح-فارغ"
        if isinstance(value, bool) or isinstance(value, int) or isinstance(value, float):
            cleaned[key] = value
        elif value is None:
            cleaned[key] = None
        else:
            cleaned[key] = _clamp_value(_scrub(str(value)))
    return cleaned


def canonical_json(payload: dict) -> str:
    """JSON حتمي بالبايت — مفاتيح مفرزة، فاصل مقتصد، بلا تهريب."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def entry_hash(seq: int, prev_hash: str, tool: str, decision: str, reason_ar: str, detail: dict) -> str:
    """بصمة الحدث — محتواه المعنوي + السلسلة، بلا زمن ولا بيئة."""
    payload = {
        "detail": detail,
        "decision": decision,
        "prev_hash": prev_hash,
        "reason_ar": reason_ar,
        "schema": AUDIT_SCHEMA,
        "seq": int(seq),
        "tool": tool,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditEntry:
    """حدث تدقيق واحد موقّع: seq، سلسلة، أداة، قرار، سبب، تفاصيل، زمن."""

    seq: int
    prev_hash: str
    hash: str
    tool: str
    decision: str
    reason_ar: str
    detail: dict
    ts: float | None = None  # خارج السلسلة — عقد إيصال العقل نفسه

    def to_dict(self) -> dict:
        """ممثل JSON حتمي — ts الأخير لأنه خارج السلسلة."""
        return {
            "seq": int(self.seq),
            "prev_hash": self.prev_hash,
            "hash": self.hash,
            "tool": self.tool,
            "decision": self.decision,
            "reason_ar": self.reason_ar,
            "detail": self.detail,
            "ts": self.ts,
        }


@dataclass(frozen=True)
class AuditVerifyReport:
    """نتيجة التحقق من سلامة السلسلة كاملة — موثقة لا حدسية."""

    ok: bool
    count: int
    first_broken_seq: int | None
    reason_ar: str

    def to_dict(self) -> dict:
        """ممثل JSON حتمي."""
        return {
            "ok": self.ok,
            "count": self.count,
            "first_broken_seq": self.first_broken_seq,
            "reason_ar": self.reason_ar,
        }


class AuditLog:
    """سجل تدقيق JSONL ملحق-فقط بسلسلة تجزئة — الكتابة تعلق، العبث يكشف.

    العقد: ``append`` يعود بإدخال موقّع ولا يرمي استثناءً على مدخل
    عدوي (يطبّعه فقط)، و``verify`` يعيد الحساب من الرأس ويحكم بدليل
    عربي، و``entries`` يقرأ ما هو سليم ويتحمل سطرًا تالفًا بلا انهيار.
    الملف نفسه لا توجد واجهة تعديل أو حذف عليه — الملحق فقط.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        # كاش آخر حدث: append-only يثق بكاتبه الواحد (جلسة الأدوات)،
        # فالتوقيع O(1) لا O(ملف) — وأي كاتب خارجي يُكتشف في verify
        # لأنه لا يعرف السلسلة. ``reload`` يبطل الكاش صراحةً.
        self._cached_last: AuditEntry | None = None
        self._cache_loaded = False

    # ------------------------------------------------------------ الكتابة
    def append(
        self,
        tool: object,
        decision: object,
        reason_ar: object,
        detail: dict | None = None,
        *,
        ts: float | None = None,
    ) -> AuditEntry:
        """وقّع حدثًا وألحقه — seq التالي دائمًا، والهاش فوق السابق.

        ``ts`` يُخزَّن في السطر ولا يدخل الهاش (الزمن خارج السلسلة).
        المدخل العدوي (أسماء فارغة، تفاصيل مليئة بأسرار أو محارف بلا
        حد) يُطبَّع ويُقنَّع ويُقصّ — التدقيق لا يرمي، يسجل.
        """
        last = self._last_entry()
        seq = (last.seq + 1) if last else 1
        prev_hash = last.hash if last else "0" * 64
        tool_text = _scrub(str(tool or "").strip())[:64] or "أداة-غير-مسماة"
        decision_text = _scrub(str(decision or "").strip().upper())[:16] or "UNKNOWN"
        reason_text = _scrub(" ".join(str(reason_ar or "").split()))[:MAX_REASON_CHARS] or "بلا سبب موثق"
        if isinstance(detail, dict):
            clean_detail = _clean_detail(dict(detail))
        elif detail is None:
            clean_detail = {}
        else:
            clean_detail = {"المدخل": _clamp_value(_scrub(str(detail)))}
        digest = entry_hash(seq, prev_hash, tool_text, decision_text, reason_text, clean_detail)
        entry = AuditEntry(
            seq=seq,
            prev_hash=prev_hash,
            hash=digest,
            tool=tool_text,
            decision=decision_text,
            reason_ar=reason_text,
            detail=clean_detail,
            ts=float(ts) if ts is not None else None,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = canonical_json(entry.to_dict())
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        self._cached_last = entry
        self._cache_loaded = True
        return entry

    # ------------------------------------------------------------ الكاش
    def _last_entry(self) -> AuditEntry | None:
        """آخر حدث عبر الكاش — قراءة واحدة عند أول توقيع فقط."""
        if not self._cache_loaded:
            entries = self.entries()
            self._cached_last = entries[-1] if entries else None
            self._cache_loaded = True
        return self._cached_last

    def reload(self) -> None:
        """أبطل الكاش — بعد كاتب خارجي أو فحص يدوي للملف."""
        self._cached_last = None
        self._cache_loaded = False

    # ------------------------------------------------------------ القراءة
    def entries(self) -> list[AuditEntry]:
        """اقرأ السطور السليمة بالترتيب — سطر تالف يُتخطى لا يُنهي."""
        if not self.path.is_file():
            return []
        out: list[AuditEntry] = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                out.append(
                    AuditEntry(
                        seq=int(raw["seq"]),
                        prev_hash=str(raw["prev_hash"]),
                        hash=str(raw["hash"]),
                        tool=str(raw["tool"]),
                        decision=str(raw["decision"]),
                        reason_ar=str(raw["reason_ar"]),
                        detail=dict(raw.get("detail") or {}),
                        ts=(float(raw["ts"]) if raw.get("ts") is not None else None),
                    )
                )
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                continue  # سطر تالف — يكشفه verify لا يُخفى هنا
        return out

    # ------------------------------------------------------------ التحقق
    def verify(self) -> AuditVerifyReport:
        """أعد حساب السلسلة من الرأس — أي عبث يُحكم بدليل عربي موثق.

        الفحوص بالترتيب: seq متتابعة من 1، prev_hash يطابق هاش السابق،
        hash يُحسب من المحتوى نفسه (بلا ts) — والسطر التالف سلسلة
        مكسورة صراحة لا تجاهل صامت.
        """
        if not self.path.is_file():
            return AuditVerifyReport(True, 0, None, "السجل فارغ — لا أحداث للتدقيق")
        prev_hash = "0" * 64
        expected_seq = 1
        count = 0
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                recalc = entry_hash(
                    int(raw["seq"]),
                    str(raw["prev_hash"]),
                    str(raw["tool"]),
                    str(raw["decision"]),
                    str(raw["reason_ar"]),
                    dict(raw.get("detail") or {}),
                )
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                return AuditVerifyReport(
                    False, count, expected_seq, f"سطر تالف عند الحدث {expected_seq} — سلسلة مكسورة"
                )
            if int(raw["seq"]) != expected_seq:
                return AuditVerifyReport(
                    False, count, expected_seq,
                    f"ترقيم مكسور: المتوقع {expected_seq} والواقع {raw.get('seq')}",
                )
            if str(raw["prev_hash"]) != prev_hash:
                return AuditVerifyReport(
                    False, count, expected_seq,
                    f"سلسلة مقطوعة عند الحدث {expected_seq} — prev_hash لا يطابق",
                )
            if recalc != str(raw["hash"]):
                return AuditVerifyReport(
                    False, count, expected_seq,
                    f"هاش الحدث {expected_seq} لا يطابق المحتوى — عدل أو حذف",
                )
            prev_hash = str(raw["hash"])
            expected_seq += 1
            count += 1
        return AuditVerifyReport(True, count, None, f"سلسلة سليمة — {count} حدثًا موقّعًا")

    # ------------------------------------------------------------ التوثيق
    def chain_summary(self) -> dict:
        """ملخص حتمي للسلسلة — آخر هاش وعدد الأحداث، بلا أي زمن."""
        entries = self.entries()
        return {
            "count": len(entries),
            "last_hash": entries[-1].hash if entries else "0" * 64,
            "path": self.path.name,
        }


__all__ = [
    "AUDIT_SCHEMA",
    "AuditEntry",
    "AuditLog",
    "AuditVerifyReport",
    "canonical_json",
    "entry_hash",
]
