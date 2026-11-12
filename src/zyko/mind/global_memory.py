"""zyko.mind.global_memory — الذاكرة العابرة للجلسات والمشاريع (الأولوية 4).

الطبقة الرابعة فوق ``docs/MIND.md`` §6.1-6: ذاكرة ``MindMemory`` مرتبطة
بمجلد مشروع واحد، وهذه الوحدة هي الذاكرة التي تعبر الجلسات والمشاريع —
«العقل يتذكّر دروسه أينما عمل»:

  1. **دفتر الجلسات** ``sessions.jsonl``: ملحق-فقط بسلسلة sha256 — كل
     جلسة حلقة تُوقَّع عند الختام (الهدف بصمة sha256 لا نصًا خامًا —
     الخصوصية بالتصميم: النص الخام يبقى في ذاكرة المشروع وحده).
  2. **الدروس العابرة للمشاريع** ``lessons.json``: مُزالة التكرار بسقف
     حتمي — الإخلاء الأقدم أولًا (FIFO بحسب ``seq``) فلا ينمو بلا حد.
  3. **الذاكرة المقروءة** ``MEMORY.md``: نص عربي حتمي بالبايت للإنسان
     والمستودع.

الاسترجاع (``recall``) حتمي بالبايت: تطبيع عربي، تطابق قياسي للرموز،
ترتيب كسر التعادل (النتيجة ثم الأحدث ثم النص) — بلا ``random`` ولا
``datetime`` في أي حساب. الزمن يُخزَّن خارج السلسلة كما في عقد
``zyko.sandbox.audit`` — التشغيلات المتطابقة تعطي سلسلة متطابقة بالبايت.

المسار الافتراضي ``platform.paths.data_dir()/mind`` — يحترم
``ZYKO_DATA_DIR`` فتبقى الاختبارات محكمة، و``home`` صريح عند الحاجة.
المسار يعتمد تاريخ الجهاز (عدد الجلسات السابقة) — لذلك آثاره موثقة في
الإيصال **خارج** سلسلة ``chain_hash`` كما ``seconds_total``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from zyko.platform.paths import data_dir

LEDGER_SCHEMA = "zyko.mind/session-ledger-v1"
LESSONS_SCHEMA = "zyko.mind/global-lessons-v1"

MAX_GLOBAL_LESSONS = 200  # سقف الدروس العابرة — الإخلاء الأقدم أولًا
MAX_LESSON_CHARS = 300  # سقف نص الدرس — نفس ميزانية ملاحظة الانعكاس
MAX_PROJECT_CHARS = 120  # سقف اسم المشروع في الدفتر
MAX_KIND_CHARS = 32  # سقف نوع الجلسة الموثق
MAX_OUTCOME_CHARS = 120  # سقف نص الخلاصة العربي
MAX_QUERY_RESULTS = 8  # سقف نتائج الاسترجاع في نداء واحد
GENESIS_HASH = "0" * 64  # جذر السلسلة — كعقد سجل التدقيق
TRUNCATION_MARK = "…[مقتطع]"  # علامة القصّ الحتمية
SECRET_MASK = "[سر-مقنّع]"  # nosec B105 — قناع الإخفاء نفسه لا سر

# أنماط الأسرار الشائعة — تُقنَّع قبل أن تلمس القرص (دفاع عمق بلا اعتمادية)
_SECRET_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"ghs_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
)

# تشكيل عربي + تطويل — يُزال قبل المطابقة فتتساوى الكلمة بحروفها وتشكيلها
_DIACRITICS = re.compile(r"[\u064B-\u0652\u0640]")
_TOKEN = re.compile(r"[0-9A-Za-z\u0600-\u06FF]+")

# قطبية الدروس — المستعار من «مضاد النسيان» في nexus-core: «دائمًا»
# مقابل «أبدًا» على الموضوع نفسه ليس اتفاقًا يُدمج بل تناقض يُعلن
# ويُخزن جنبًا إلى جنب — القمع الصامت يهدم معنى الدرسين معًا.
# الرموز بصيغتها المطبوعة (التشكيل أزيله normalize_text) وباللغتين
# معًا — المستودع عربي أولًا لكن الدروس تعبر اللغات.
_POLARITY_NEGATIVE = frozenset(
    {
        "never",
        "avoid",
        "dont",
        "not",
        "no",
        "without",
        "لا",
        "أبدًا",
        "أبدا",
        "ابداً",
        "ابدا",
        "تجنب",
        "تجنّب",
        "تجنبا",
        "بلا",
        "بدون",
        "لن",
        "ممنوع",
        "يُمنع",
        "يمنع",
    }
)
_POLARITY_POSITIVE = frozenset(
    {
        "always",
        "should",
        "must",
        "prefer",
        "recommended",
        "دائمًا",
        "دائما",
        "دوماً",
        "دوما",
        "يجب",
        "ينبغي",
        "يفضل",
        "نوصي",
    }
)
_TOPIC_SIMILAR_THRESHOLD = 0.5  # تشابه الموضوع فوقه مع قطبية معاكسة = تناقض موثق


def _scrub(text: str) -> str:
    """اقنَع كل ما يشبه سرًا — قبل التدوين لا بعده."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(SECRET_MASK, text)
    return text


def _clamp(text: str, limit: int) -> str:
    """قصّ حتمي بالبايت — نفس المدخل يعطي نفس المقتطع."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    keep = max(0, limit - len(TRUNCATION_MARK))
    return text[:keep] + TRUNCATION_MARK


def canonical_json(payload: dict) -> str:
    """JSON حتمي بالبايت — مفاتيح مفرزة، فاصل مقتصد، بلا تهريب."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_text(text: str) -> str:
    """طبّع النص للاسترجاع: تشكيل مُزال، صغير، فواصل مُوحَّدة."""
    lowered = str(text or "").lower()
    return " ".join(_DIACRITICS.sub("", lowered).split())


def recall_score(query: str, lesson: str) -> int:
    """النتيجة الحتمية: كم رمزًا من الاستعلام يظهر في الدرس."""
    query_tokens = set(_TOKEN.findall(normalize_text(query)))
    if not query_tokens:
        return 0
    lesson_text = normalize_text(lesson)
    return sum(1 for token in query_tokens if token in lesson_text)


def lesson_polarity(principle: str) -> int:
    """قطبية الدرس: +1 إيجابي (دائم/يجب) · -1 سلبي (أبدًا/تجنب) · 0 محايد.

    على منهج nexus-core نفسه: السلبي يفوز عند التضارب داخل الدرس
    الواحد («لا تثق ودائمًا تحقق» درس سلبي)، والمحايد لا يتناقض أبدًا.
    """
    tokens = set(_TOKEN.findall(normalize_text(str(principle or ""))))
    if tokens & _POLARITY_NEGATIVE:
        return -1
    if tokens & _POLARITY_POSITIVE:
        return 1
    return 0


def _topic_tokens(principle: str) -> frozenset[str]:
    """رموز الموضوع — كلمات القطبية المنهية تُسقط قبل قياس التشابه."""
    return (
        frozenset(_TOKEN.findall(normalize_text(str(principle or ""))))
        - _POLARITY_NEGATIVE
        - _POLARITY_POSITIVE
    )


def topics_conflict(left: str, right: str, threshold: float = _TOPIC_SIMILAR_THRESHOLD) -> bool:
    """هل الدرسان موضوع واحد بقطبيتين متعاكستين؟ — تناقض معلن لا دمج خادع.

    التشابه Jaccard على رموز الموضوع بعد إسقاط كلمات القطبية — تحت
    العتبة أو إحداهما محايدة أو القطبية متطابقة: لا تناقض، وإن وُجد
    فالجواب حتمي بالبايت لا اجتهاد نماذج.
    """
    left_polarity, right_polarity = lesson_polarity(left), lesson_polarity(right)
    if left_polarity == 0 or right_polarity == 0 or left_polarity == right_polarity:
        return False
    left_topic, right_topic = _topic_tokens(left), _topic_tokens(right)
    if not left_topic or not right_topic:
        return False
    union = left_topic | right_topic
    return len(left_topic & right_topic) / len(union) >= threshold


def _normalize_conflicts(raw: object) -> list[dict]:
    """طبّع قائمة التناقضات من الملف — التالف يُسقط صامتًا لا يفجّر.

    الملف يُكتب آليًا لكنه ملف — تالف أو مدبس يدويًا يعود قائمة فارغة
    آمنة، والازدواج يُكتم، والذات تناقض لذاتها رفض منطقي لا حالة.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            existing_seq, incoming_seq = int(item["existing_seq"]), int(item["incoming_seq"])
        except (KeyError, TypeError, ValueError):
            continue
        if existing_seq < 1 or incoming_seq < 1 or existing_seq == incoming_seq:
            continue
        out.append({"existing_seq": existing_seq, "incoming_seq": incoming_seq})
    return out


def entry_hash(seq: int, prev_hash: str, fields: dict) -> str:
    """بصمة حدث الدفتر — محتواه المعنوي + السلسلة، بلا زمن ولا بيئة."""
    payload = {"fields": fields, "prev_hash": prev_hash, "schema": LEDGER_SCHEMA, "seq": int(seq)}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def goal_digest(goal: object) -> str:
    """بصمة sha256 للهدف — الخصوصية بالتصميم: الدفتر لا يحفظ نصًا خامًا."""
    return hashlib.sha256(str(goal or "").encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SessionEntry:
    """حدث جلسة واحد موقّع: seq، سلسلة، بصمة الهدف، خلاصة، زمن خارج السلسلة."""

    seq: int
    prev_hash: str
    hash: str
    goal_sha256: str
    project: str
    kind: str
    outcome_ar: str
    ok: bool
    lessons_learned: int
    gaps: int
    reflections: int
    ts: float | None = None  # خارج السلسلة — عقد إيصال العقل نفسه

    def to_dict(self) -> dict:
        """ممثل JSON حتمي — ts الأخير لأنه خارج السلسلة."""
        return {
            "goal_sha256": self.goal_sha256,
            "gaps": int(self.gaps),
            "hash": self.hash,
            "kind": self.kind,
            "lessons_learned": int(self.lessons_learned),
            "ok": bool(self.ok),
            "outcome_ar": self.outcome_ar,
            "prev_hash": self.prev_hash,
            "project": self.project,
            "reflections": int(self.reflections),
            "schema": LEDGER_SCHEMA,
            "seq": int(self.seq),
            "ts": self.ts,
        }


@dataclass(frozen=True)
class LedgerVerifyReport:
    """نتيجة التحقق من سلامة سلسلة الدفتر كاملة — موثقة لا حدسية."""

    ok: bool
    count: int
    first_broken_seq: int | None
    reason_ar: str

    def to_dict(self) -> dict:
        """ممثل JSON حتمي."""
        return {
            "count": self.count,
            "first_broken_seq": self.first_broken_seq,
            "ok": self.ok,
            "reason_ar": self.reason_ar,
        }


class GlobalMemory:
    """الذاكرة العابرة للجلسات — دفتر موقّع ودروس بسقف، حتمية بالبايت.

    العقد: ``record_session`` و``learn`` يكتبان فورًا ويعودان بالموقّع أو
    المُضاف فعلًا، و``verify`` يعيد الحساب من الرأس ويحكم بدليل عربي،
    و``recall`` حتمي بلا عشوائية. المدخل العدوي يُطبَّع ويُقنَّع ويُقصّ —
    الذاكرة لا ترمي، تسجل. لا واجهة تعديل أو حذف على الدفتر — الملحق فقط.
    """

    def __init__(self, home: str | Path | None = None) -> None:
        self.home = Path(home) if home is not None else data_dir(create=True) / "mind"
        # كاش آخر حدث وإحصاءات الذاكرة المقروءة: append-only يثق بكاتبه
        # الواحد — توقيع O(1) لا O(ملف)، وكاتب خارجي يكشفه ``verify``.
        # ``reload`` يبطل الكاش صراحةً بعد فحص يدوي للملف.
        self._cached_last: SessionEntry | None = None
        self._cache_loaded = False
        self._stats: list[int] | None = None  # [عدد الجلسات، المكتملة بلا فجوات]

    # ------------------------------------------------------------ المسارات
    @property
    def ledger_path(self) -> Path:
        """مسار دفتر الجلسات الموقّع."""
        return self.home / "sessions.jsonl"

    @property
    def lessons_path(self) -> Path:
        """مسار الدروس العابرة للمشاريع."""
        return self.home / "lessons.json"

    @property
    def memory_md_path(self) -> Path:
        """مسار الذاكرة المقروءة للإنسان."""
        return self.home / "MEMORY.md"

    # ------------------------------------------------------------ دفتر الجلسات
    def record_session(
        self,
        *,
        goal: object,
        project: object,
        kind: object = "",
        ok: bool = True,
        lessons_learned: int = 0,
        gaps: int = 0,
        reflections: int = 0,
        outcome_ar: str | None = None,
        ts: float | None = None,
    ) -> SessionEntry:
        """وقّع جلسة وألحقها بالدفتر — seq التالي دائمًا، والهاش فوق السابق.

        ``ts`` يُخزَّن ولا يدخل الهاش؛ الخلاصة تُشتق حتميًا من ``ok`` و
        ``gaps`` إن لم تُعطَ نصًا صريحًا. المدخل العدوي يُطبَّع لا يرمي.
        """
        last = self._last_entry()
        seq = (last.seq + 1) if last else 1
        prev_hash = last.hash if last else GENESIS_HASH
        gaps_int = max(0, int(gaps)) if str(gaps).strip().lstrip("-").isdigit() else 0
        ok_bool = bool(ok)
        if outcome_ar is None:
            outcome_ar = "اكتمل بلا فجوات" if ok_bool and gaps_int == 0 else "فجوات موثقة تُعالج"
        fields = {
            "goal_sha256": goal_digest(goal),
            "gaps": gaps_int,
            "kind": _clamp(_scrub(str(kind or "")), MAX_KIND_CHARS) or "غير-مصنّف",
            "lessons_learned": max(0, int(lessons_learned))
            if str(lessons_learned).strip().lstrip("-").isdigit()
            else 0,
            "ok": ok_bool,
            "outcome_ar": _clamp(_scrub(str(outcome_ar)), MAX_OUTCOME_CHARS) or "بلا خلاصة موثقة",
            "project": _clamp(_scrub(str(project or "")), MAX_PROJECT_CHARS) or "مشروع-غير-مسماة",
            "reflections": max(0, int(reflections))
            if str(reflections).strip().lstrip("-").isdigit()
            else 0,
        }
        digest = entry_hash(seq, prev_hash, fields)
        entry = SessionEntry(
            seq=seq,
            prev_hash=prev_hash,
            hash=digest,
            goal_sha256=fields["goal_sha256"],
            project=fields["project"],
            kind=fields["kind"],
            outcome_ar=fields["outcome_ar"],
            ok=ok_bool,
            lessons_learned=fields["lessons_learned"],
            gaps=fields["gaps"],
            reflections=fields["reflections"],
            ts=float(ts) if ts is not None else None,
        )
        self.home.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(canonical_json(entry.to_dict()) + "\n")
        self._cached_last = entry
        self._cache_loaded = True
        if self._stats is not None:
            self._stats[0] += 1
            self._stats[1] += 1 if entry.ok else 0
        self._write_md()
        return entry

    def reload(self) -> None:
        """أبطل الكاش — بعد كاتب خارجي أو فحص يدوي للملف."""
        self._cached_last = None
        self._cache_loaded = False
        self._stats = None

    def sessions(self) -> list[SessionEntry]:
        """اقرأ أحداث الدفتر السليمة بالترتيب — سطر تالف يُتخطى لا يُنهي."""
        if not self.ledger_path.is_file():
            return []
        out: list[SessionEntry] = []
        for line in self.ledger_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                out.append(
                    SessionEntry(
                        seq=int(raw["seq"]),
                        prev_hash=str(raw["prev_hash"]),
                        hash=str(raw["hash"]),
                        goal_sha256=str(raw["goal_sha256"]),
                        project=str(raw["project"]),
                        kind=str(raw["kind"]),
                        outcome_ar=str(raw["outcome_ar"]),
                        ok=bool(raw["ok"]),
                        lessons_learned=int(raw.get("lessons_learned") or 0),
                        gaps=int(raw.get("gaps") or 0),
                        reflections=int(raw.get("reflections") or 0),
                        ts=(float(raw["ts"]) if raw.get("ts") is not None else None),
                    )
                )
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                continue  # سطر تالف — يكشفه verify لا يُخفى هنا
        return out

    def verify(self) -> LedgerVerifyReport:
        """أعد حساب سلسلة الدفتر من الرأس — أي عبث يُحكم بدليل عربي موثق."""
        if not self.ledger_path.is_file():
            return LedgerVerifyReport(True, 0, None, "الدفتر فارغ — لا جلسات للتدقيق")
        prev_hash = GENESIS_HASH
        expected_seq = 1
        count = 0
        for line in self.ledger_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                fields = {
                    "goal_sha256": str(raw["goal_sha256"]),
                    "gaps": int(raw.get("gaps") or 0),
                    "kind": str(raw["kind"]),
                    "lessons_learned": int(raw.get("lessons_learned") or 0),
                    "ok": bool(raw["ok"]),
                    "outcome_ar": str(raw["outcome_ar"]),
                    "project": str(raw["project"]),
                    "reflections": int(raw.get("reflections") or 0),
                }
                recalc = entry_hash(int(raw["seq"]), str(raw["prev_hash"]), fields)
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                return LedgerVerifyReport(
                    False, count, expected_seq, f"سطر تالف عند الجلسة {expected_seq} — سلسلة مكسورة"
                )
            if int(raw["seq"]) != expected_seq:
                return LedgerVerifyReport(
                    False,
                    count,
                    expected_seq,
                    f"ترقيم مكسور: المتوقع {expected_seq} والواقع {raw.get('seq')}",
                )
            if str(raw["prev_hash"]) != prev_hash:
                return LedgerVerifyReport(
                    False,
                    count,
                    expected_seq,
                    f"سلسلة مقطوعة عند الجلسة {expected_seq} — prev_hash لا يطابق",
                )
            if recalc != str(raw["hash"]):
                return LedgerVerifyReport(
                    False,
                    count,
                    expected_seq,
                    f"هاش الجلسة {expected_seq} لا يطابق المحتوى — عدل أو حذف",
                )
            prev_hash = str(raw["hash"])
            expected_seq += 1
            count += 1
        return LedgerVerifyReport(True, count, None, f"سلسلة سليمة — {count} جلسة موقّعة")

    def _last_entry(self) -> SessionEntry | None:
        """آخر حدث عبر الكاش — قراءة واحدة عند أول توقيع فقط."""
        if not self._cache_loaded:
            entries = self.sessions()
            self._cached_last = entries[-1] if entries else None
            self._cache_loaded = True
        return self._cached_last

    # ------------------------------------------------------------ الدروس العابرة
    def load_lessons(self) -> tuple[str, ...]:
        """اقرأ الدروس العابرة بترتيب إدراجها — فارغ آمن إن لم تُكتب بعد."""
        data = self._read_lessons()
        return tuple(str(lesson["text"]) for lesson in data.get("lessons", []))

    def conflicts(self) -> tuple[dict, ...]:
        """التناقضات الموثقة بين الدروس — موضوع واحد وقطبيتان متعاكستان.

        عرض صادق للجدل لا قمع له: كل تناقض يحمل نصّي طرفيه الحاليين
        إن كانا حيّين، والترتيب حتمي بالبايت (مفرز بالمفاتيح).
        """
        data = self._read_lessons()
        seq_text = {int(lesson["seq"]): str(lesson["text"]) for lesson in data.get("lessons", [])}
        out: list[dict] = []
        for c in data.get("conflicts", []):
            existing_seq, incoming_seq = int(c["existing_seq"]), int(c["incoming_seq"])
            out.append(
                {
                    "existing_seq": existing_seq,
                    "existing_text": seq_text.get(existing_seq, ""),
                    "incoming_seq": incoming_seq,
                    "incoming_text": seq_text.get(incoming_seq, ""),
                }
            )
        out.sort(key=lambda item: (item["existing_seq"], item["incoming_seq"]))
        return tuple(out)

    def learn(self, lessons) -> tuple[str, ...]:
        """علِّم دروسًا عابرة للمشاريع — إزالة تكرار وسقف حتمي واكتب فورًا.

        يعود tuple الدروس الجديدة المُضافة فعلًا. فوق السقف يُخلى الأقدم
        أولًا (أدنى ``seq``) — حتمي بالبايت في أي جهاز وبأي ترتيب نداء.
        """
        data = self._read_lessons()
        existing_texts = [str(lesson["text"]) for lesson in data.get("lessons", [])]
        # إزالة التكرار على المعنى (جولة 13): المفتاح نصّ مطبّع — التشكيل
        # والتطويل لا يفردان درسًا موجودًا في نسخة حرفية أخرى له
        existing_keys = {normalize_text(t) for t in existing_texts}
        fresh: list[str] = []
        for lesson in lessons or ():
            if lesson is None:
                continue  # لا درس من العدم — يقفز لا يتحول إلى "None"
            text = _clamp(_scrub(str(lesson)), MAX_LESSON_CHARS)
            if text and normalize_text(text) not in existing_keys:
                existing_keys.add(normalize_text(text))
                fresh.append(text)
        if not fresh:
            return ()
        merged = [
            {"seq": int(lesson["seq"]), "text": str(lesson["text"])}
            for lesson in data.get("lessons", [])
        ]
        next_seq = int(data.get("next_seq") or (len(merged) + 1))
        conflicts = _normalize_conflicts(data.get("conflicts"))
        seen_pairs = {(c["existing_seq"], c["incoming_seq"]) for c in conflicts}
        for text in fresh:
            merged.append({"seq": next_seq, "text": text})
            # مضاد النسيان: الدرس الجديد يُقاس على المخزن كله (شاملاً
            # الجديد قبله في الدفعة نفسها) — التناقض يُعلن ويُخزن جنبًا
            # إلى جنب لا يُقمع ولا يُدمج، والازدواج لا يتكرر.
            for item in merged[:-1]:
                other_text = str(item.get("text", ""))
                if other_text and topics_conflict(other_text, text):
                    pair = (int(item["seq"]), next_seq)
                    if pair not in seen_pairs:
                        conflicts.append({"existing_seq": pair[0], "incoming_seq": pair[1]})
                        seen_pairs.add(pair)
            next_seq += 1
        if len(merged) > MAX_GLOBAL_LESSONS:
            merged.sort(key=lambda item: int(item["seq"]), reverse=True)
            merged = merged[:MAX_GLOBAL_LESSONS]
            merged.sort(key=lambda item: int(item["seq"]))
            # الإخلاء الحتمي قد يرحّل طرف تناقض — تناقض بلا طرفيه وثيقة
            # ميتة، فلا يبقى إلا ما يحيل إلى دروس حية بالفعل.
            surviving = {int(item["seq"]) for item in merged}
            conflicts = [
                c
                for c in conflicts
                if c["existing_seq"] in surviving and c["incoming_seq"] in surviving
            ]
        payload = {
            "schema": LESSONS_SCHEMA,
            "next_seq": next_seq,
            "lessons": merged,
            "conflicts": conflicts,
        }
        self.home.mkdir(parents=True, exist_ok=True)
        self.lessons_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self._write_md()
        return tuple(fresh)

    def _read_lessons(self) -> dict:
        """اقرأ ملف الدروس — تالف أو غائب يعود فارغًا آمنًا بلا انهيار."""
        try:
            data = json.loads(self.lessons_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"schema": LESSONS_SCHEMA, "next_seq": 1, "lessons": [], "conflicts": []}
        if not isinstance(data, dict) or data.get("schema") != LESSONS_SCHEMA:
            return {"schema": LESSONS_SCHEMA, "next_seq": 1, "lessons": [], "conflicts": []}
        lessons = data.get("lessons")
        if not isinstance(lessons, list):
            return {"schema": LESSONS_SCHEMA, "next_seq": 1, "lessons": [], "conflicts": []}
        cleaned: list[dict] = []
        for item in lessons:
            if isinstance(item, dict) and "seq" in item and str(item.get("text", "")).strip():
                cleaned.append({"seq": int(item["seq"]), "text": str(item["text"])})
        cleaned.sort(key=lambda item: item["seq"])
        # التالي = الأكبر بين (أعلى seq موجود + 1) و next_seq الموثق في الملف —
        # لا يعاد استخدام تسلسل ولا يقفز فجوات بلا داعٍ.
        max_seq = max((int(item["seq"]) for item in cleaned), default=0)
        next_seq = max(max_seq + 1, int(data.get("next_seq") or 1))
        return {
            "schema": LESSONS_SCHEMA,
            "next_seq": next_seq,
            "lessons": cleaned,
            "conflicts": _normalize_conflicts(data.get("conflicts")),
        }

    # ------------------------------------------------------------ الاسترجاع
    def recall(self, query: object, limit: int = MAX_QUERY_RESULTS) -> tuple[str, ...]:
        """استرجع أقرب الدروس للاستعلام — ترتيب حتمي بالبايت بلا عشوائية.

        الترتيب: النتيجة تنازليًا، ثم الأحدث (أعلى ``seq``)، ثم النص
        معجميًا لكسر التعادل الكامل — نفس الاستعلام ونفس الذاكرة يعطيان
        نفس الناتج بالبايت في أي جهاز.
        """
        try:
            limit_int = max(0, int(limit))
        except (TypeError, ValueError):
            limit_int = 0
        if limit_int == 0:
            return ()
        lessons = self.load_lessons()
        scored = [
            (recall_score(str(query), lesson), index, lesson)
            for index, lesson in enumerate(lessons)
        ]
        seq_by_text = {
            str(lesson["text"]): int(lesson["seq"]) for lesson in self._read_lessons()["lessons"]
        }
        ranked = sorted(
            scored,
            key=lambda item: (-item[0], -seq_by_text.get(item[2], 0), item[2]),
        )
        return tuple(lesson for score, _index, lesson in ranked[:limit_int] if score > 0)

    # ------------------------------------------------------------ الخلاصة والذاكرة المقروءة
    def summary(self) -> dict:
        """ملخص حتمي للذاكرة العابرة — للـ CLI والتوثيق، بلا أي زمن."""
        entries = self.sessions()
        report = self.verify()
        return {
            "home": str(self.home),
            "sessions": len(entries),
            "sessions_ok": sum(1 for entry in entries if entry.ok),
            "lessons": len(self.load_lessons()),
            "conflicts": len(self.conflicts()),
            "verify_ok": report.ok,
            "verify_reason_ar": report.reason_ar,
            "last_seq": entries[-1].seq if entries else 0,
            "last_outcome_ar": entries[-1].outcome_ar if entries else "",
        }

    def _md_stats(self) -> list[int]:
        """إحصاءات الذاكرة المقروءة عبر الكاش — قراءة كاملة مرة واحدة فقط."""
        if self._stats is None:
            entries = self.sessions()
            self._stats = [len(entries), sum(1 for entry in entries if entry.ok)]
        return self._stats

    def _write_md(self) -> None:
        """اكتب ``MEMORY.md`` الحتمي — حالة + دروس، بلا طوابع زمنية."""
        total, ok_count = self._md_stats()
        lessons = self.load_lessons()
        lines = [
            "# الذاكرة العابرة للجلسات — ZYKO Global Memory",
            "",
            f"الجلسات الموثقة: {total} (مكتملة بلا فجوات: {ok_count})",
            f"الدروس العابرة للمشاريع: {len(lessons)}",
            "",
            "## الدروس",
        ]
        if lessons:
            lines.extend(f"{index}. {lesson}" for index, lesson in enumerate(lessons, start=1))
        else:
            lines.append("لا دروس عابرة بعد.")
        self.home.mkdir(parents=True, exist_ok=True)
        self.memory_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = [
    "GENESIS_HASH",
    "LEDGER_SCHEMA",
    "LESSONS_SCHEMA",
    "MAX_GLOBAL_LESSONS",
    "MAX_QUERY_RESULTS",
    "LedgerVerifyReport",
    "SessionEntry",
    "GlobalMemory",
    "canonical_json",
    "entry_hash",
    "goal_digest",
    "lesson_polarity",
    "normalize_text",
    "recall_score",
    "topics_conflict",
]
