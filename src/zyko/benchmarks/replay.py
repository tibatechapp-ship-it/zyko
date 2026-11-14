"""قاعة إعادة الحكم (الموجة 30) — أي إيصال يُعاد حكمه بأمر واحد.

درس الموجتين 28 و29: البوابتان صارتا في بروتوكول العدّ، والإيصالات
الجديدة تحمل نصوص رقعها كاملة. وهذه القاعة تُغلق الحلقة الأخيرة:
**إعادة الحكم بعد الحدث** عملية معلنة بأمر واحد، بأربع طبقات تحقق
حتمية بلا شبكة وبلا مفتاح وبلا عقل:

1. **بصمة الوثيقة** تُعاد من بايتات الإيصال نفسه — أي تعديل بعد
   الحدث يكسرها (درس ``chain_hash_of`` نفسه).
2. **مشتقات الحكم** تُعاد من الحقول الخام: ``resolved_strict`` و
   ``resolved_env`` و``f2p_repaired_count`` تُحسب من جديد وتُقارن
   بما هو مؤرشف — البصمة تؤمّن البايتات لا الصدق، والكذبة داخل
   ظرف موقَّع تُكشف هنا.
3. **التدقيق الثماني القواعد** يُعاد على نص الرقعة المؤرشف
   (``patch_text`` من الموجة 29) — الرقعة المسمومة التي عداها العدّ
   التاريخي بإصابة نظيفة تُكشف، والحرم يعلن في إعادة العدّ.
4. **العدّ** يُعاد من المحاولات بعقد ``swebench.aggregate`` نفسه —
   تلاعب الخلاصة يُكشف بالمقارنة، ومفاتيح الخلاصة غير القابلة
   لإعادة الإنتاج تُوثَّق لا تُخفى.

والبوابة الثابتة (الموجة 29) تُعاد هي الأخرى عند توفر شجرة الحالة:
تُطبَّق الرقعة المؤرشفة وتحكم القواعد الثمانية والثلاثون ثم تعود
الشجرة إلى الأساس بالبايت — زعم قبول مزوّر يُنفى بالحكم المعاد.

الشكلان المدعومان بصدق:
- **شكل المحاولة** (0.51+): كل محاولة تحمل حكمها وتدقيقها ونصها —
  الطبقات الأربع كاملة.
- **الشكل القديم** (ما قبل 0.51.0، مثل دمج الموجة 25): محاولات
  مسطّحة بلا أحكام وبلا نصوص — يُعاد حكم بصمة الوثيقة ومشتق الحكم
  النهائي وعدّ الأحكام النهائية فقط، والباقي موثق بالاسم لا مخفي.

الناتج قاموس ``zyko.bench_replay/1`` موقَّع بالبصمة، وأكواد الخروج
نمط المصنع: 0 سليم · 1 مخالفة صادقة · 2 خطأ استخدام.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from zyko.benchmarks.patch_audit import audit_patch_text
from zyko.benchmarks.runner import atomic_write_json, chain_hash_of
from zyko.benchmarks.swebench import (
    SWEAttempt,
    SWEVerdict,
    aggregate,
)

Runner = Callable[..., subprocess.CompletedProcess]

_SCHEMA = "zyko.bench_replay/1"

# حقول الحكم القابلة لإعادة البناء من القاموس المؤرشف
_VERDICT_FIELDS = (
    "instance_id",
    "patch_applied",
    "apply_error_ar",
    "f2p_failed_at_base",
    "p2p_failed_at_base",
    "f2p_passed_after",
    "f2p_failed_after",
    "p2p_failed_after",
    "runs_error_ar",
    "patch_sha16",
    "contract_reason_ar",
    "attempts_note_ar",
    "static_gate_reason_ar",
    "static_gate",
)
_TUPLE_FIELDS = frozenset(
    {
        "f2p_failed_at_base",
        "p2p_failed_at_base",
        "f2p_passed_after",
        "f2p_failed_after",
        "p2p_failed_after",
    }
)

# مفاتيح الخلاصة القابلة لإعادة الإنتاج من الأحكام النهائية (الشكل القديم)
_LEGACY_COUNT_KEYS = ("total", "resolved_strict", "resolved_env", "f2p_repaired_total")

_NO_FP_AR = "بصمة الوثيقة غائبة في الإيصال — لا إعادة تحقق بايتية ممكنة"
_DOC_HASH_OK_AR = "بصمة الوثيقة تُعاد من بايتاتها — سليمة"


def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _verdict_from_dict(d: dict[str, Any]) -> SWEVerdict:
    """أعد بناء الحكم من قاموسه المؤرشف — الحقول الخام لا المشتقات."""
    kwargs: dict[str, Any] = {}
    for k in _VERDICT_FIELDS:
        if k not in d:
            continue
        v = d[k]
        if k in _TUPLE_FIELDS:
            v = tuple(v or ())
        kwargs[k] = v
    return SWEVerdict(**kwargs)


def _derivation_mismatches(v: SWEVerdict, archived: dict[str, Any]) -> tuple[str, ...]:
    """المشتقات المزوّرة: المحسوب من الحقول الخام لا يطابق المؤرشف."""
    checks = (
        ("resolved_strict", v.resolved_strict, archived.get("resolved_strict")),
        ("resolved_env", v.resolved_env, archived.get("resolved_env")),
        ("f2p_repaired_count", v.f2p_repaired_count, archived.get("f2p_repaired_count")),
    )
    return tuple(
        name for name, computed, claimed in checks if claimed is not None and computed != claimed
    )


def _finding_key(f: dict[str, Any]) -> tuple[str, str, str, int]:
    return (
        f.get("rule_id") or "",
        f.get("severity") or "",
        f.get("file") or "",
        int(f.get("line_in_file") or 0),
    )


def _audit_mismatch(text: str, archived_audit: dict[str, Any]) -> bool:
    """إعادة التدقيق على النص تخالف الأرشيف — إصابة حُذفت أو اختُلقت أو طُمست."""
    replayed = audit_patch_text(text)
    archived_keys = {_finding_key(f) for f in archived_audit.get("findings") or []}
    replayed_keys = {(f.rule_id, f.severity, f.file, f.line_in_file) for f in replayed.findings}
    return archived_keys != replayed_keys


def _gate_signature(gate: dict[str, Any]) -> tuple[Any, ...]:
    """بصمة حكم البوابة القابلة للمقارنة — القبول والملفات والدرجات."""
    per_file = tuple(
        sorted(
            (
                e.get("path"),
                bool(e.get("accepted")),
                e.get("score_before"),
                e.get("score_after"),
            )
            for e in gate.get("per_file") or []
        )
    )
    skipped = tuple(sorted(s.get("path") or "" for s in gate.get("files_skipped") or []))
    return (bool(gate.get("accepted")), per_file, skipped)


def _replay_static_gate(workdir: Path, patch_text: str, runner: Runner) -> dict[str, Any]:
    """أعد حكم البوابة الثابتة على شجرة حية: طبّق، احكم، ثم أعِد الأساس بالبايت."""
    from zyko.benchmarks.swebench import _restore_touched_files, apply_candidate, run_static_gate

    applied, _reason = apply_candidate(workdir, patch_text, runner)
    if not applied:
        return {"applied": False, "gate": None}
    gate = run_static_gate(workdir, patch_text, runner)
    _restore_touched_files(workdir, patch_text, runner)
    return {"applied": True, "gate": gate}


@dataclass(frozen=True)
class ReplayRow:
    """سطر إعادة حكم لحالة واحدة — الشكل وما أُعيد وما تعذّر."""

    instance_id: str
    shape: str  # "per-attempt" أو "legacy"
    attempts: int
    texts_replayed: int = 0
    text_absent: int = 0
    audit_absent: int = 0
    audit_mismatches: int = 0
    derivation_mismatches: int = 0
    audit_rejections: int = 0
    static_gate_replays: int = 0
    static_gate_skipped: int = 0
    static_gate_mismatches: int = 0
    resolved_strict_replay: int = 0
    resolved_env_replay: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "shape": self.shape,
            "attempts": self.attempts,
            "texts_replayed": self.texts_replayed,
            "text_absent": self.text_absent,
            "audit_absent": self.audit_absent,
            "audit_mismatches": self.audit_mismatches,
            "derivation_mismatches": self.derivation_mismatches,
            "audit_rejections": self.audit_rejections,
            "static_gate_replays": self.static_gate_replays,
            "static_gate_skipped": self.static_gate_skipped,
            "static_gate_mismatches": self.static_gate_mismatches,
            "resolved_strict_replay": self.resolved_strict_replay,
            "resolved_env_replay": self.resolved_env_replay,
        }


@dataclass
class ReplayReport:
    """تقرير القاعة — بلا أزمنة، وبصمته سلسلة موقَّعة بالبايت."""

    protocol: str
    source_label: str
    source_sha16: str
    source_chain_hash: str
    recomputed_chain_hash: str
    doc_hash_ok: bool
    doc_hash_note_ar: str
    rows: list[ReplayRow] = field(default_factory=list)
    archived_aggregate: dict[str, Any] = field(default_factory=dict)
    recomputed_aggregate: dict[str, Any] = field(default_factory=dict)
    count_mismatches: tuple[str, ...] = ()
    legacy_count_keys: tuple[str, ...] = ()

    # ------------------------------------------------------- الإجماليات
    @property
    def attempts_total(self) -> int:
        return sum(r.attempts for r in self.rows)

    @property
    def texts_replayed_total(self) -> int:
        return sum(r.texts_replayed for r in self.rows)

    @property
    def text_absent_total(self) -> int:
        return sum(r.text_absent for r in self.rows)

    @property
    def audit_absent_total(self) -> int:
        return sum(r.audit_absent for r in self.rows)

    @property
    def audit_mismatch_total(self) -> int:
        return sum(r.audit_mismatches for r in self.rows)

    @property
    def derivation_mismatch_total(self) -> int:
        return sum(r.derivation_mismatches for r in self.rows)

    @property
    def audit_rejection_total(self) -> int:
        return sum(r.audit_rejections for r in self.rows)

    @property
    def static_gate_replay_total(self) -> int:
        return sum(r.static_gate_replays for r in self.rows)

    @property
    def static_gate_skipped_total(self) -> int:
        return sum(r.static_gate_skipped for r in self.rows)

    @property
    def static_gate_mismatch_total(self) -> int:
        return sum(r.static_gate_mismatches for r in self.rows)

    @property
    def ok(self) -> bool:
        return (
            self.doc_hash_ok
            and not self.audit_mismatch_total
            and not self.derivation_mismatch_total
            and not self.static_gate_mismatch_total
            and not self.count_mismatches
        )

    # -------------------------------------------------------- التسلسل
    def to_dict(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "schema": _SCHEMA,
            "protocol": self.protocol,
            "source_label": self.source_label,
            "source_sha16": self.source_sha16,
            "source_chain_hash": self.source_chain_hash,
            "recomputed_chain_hash": self.recomputed_chain_hash,
            "doc_hash_ok": self.doc_hash_ok,
            "doc_hash_note_ar": self.doc_hash_note_ar,
            "totals": {
                "instances": len(self.rows),
                "attempts": self.attempts_total,
                "texts_replayed": self.texts_replayed_total,
                "text_absent": self.text_absent_total,
                "audit_absent": self.audit_absent_total,
                "audit_mismatches": self.audit_mismatch_total,
                "derivation_mismatches": self.derivation_mismatch_total,
                "audit_rejections": self.audit_rejection_total,
                "static_gate_replays": self.static_gate_replay_total,
                "static_gate_skipped": self.static_gate_skipped_total,
                "static_gate_mismatches": self.static_gate_mismatch_total,
            },
            "rows": [r.to_dict() for r in self.rows],
            "archived_aggregate": self.archived_aggregate,
            "recomputed_aggregate": self.recomputed_aggregate,
            "count_mismatches": list(self.count_mismatches),
            "legacy_count_keys": list(self.legacy_count_keys),
            "ok": self.ok,
        }
        doc["chain_hash"] = chain_hash_of(doc)
        return doc

    @property
    def chain_hash(self) -> str:
        return self.to_dict()["chain_hash"]

    def table_ar(self) -> str:
        """جدول عربي حتمي — القاعة تعلن ما عادت وما تعذّر بالاسم."""
        lines = [
            "قاعة إعادة الحكم (الموجة 30) — أربع طبقات تحقق بلا عقل",
            f"المصدر: {self.source_label} — بصمة الملف {self.source_sha16}",
        ]
        verdict_doc = "سليمة" if self.doc_hash_ok else f"مخالفة — {self.doc_hash_note_ar}"
        lines.append(f"طبقة البصمة: {verdict_doc}")
        if self.source_chain_hash and self.recomputed_chain_hash:
            lines.append(
                f"بصمة الإيصال: {self.source_chain_hash} ← المُعاد {self.recomputed_chain_hash}"
            )
        lines.append("")
        lines.append(
            "الحالة | الشكل | المحاولات | نصوص مُعادة | بلا نص | تدقيق مخالف | مشتقات مخالفة | بوابة مخالفة | صارم مُعاد | بيئي مُعاد"
        )
        for r in self.rows:
            lines.append(
                f"{r.instance_id} | {r.shape} | {r.attempts} | {r.texts_replayed} | "
                f"{r.text_absent} | {r.audit_mismatches} | {r.derivation_mismatches} | "
                f"{r.static_gate_mismatches} | {r.resolved_strict_replay} | {r.resolved_env_replay}"
            )
        lines.append("")
        lines.append(
            "العدّ المُعاد: "
            + " · ".join(f"{k}={v}" for k, v in sorted(self.recomputed_aggregate.items()))
        )
        if self.count_mismatches:
            lines.append(f"مفاتيح الخلاصة المخالفة: {', '.join(self.count_mismatches)}")
        if self.legacy_count_keys:
            lines.append("الشكل القديم: مفاتيح العدّ المُعاد " + " · ".join(self.legacy_count_keys))
        state = "سليم — لا مخالفة" if self.ok else "مخالفة صادقة — التفاصيل أعلاه"
        lines.append(f"الحكم النهائي: {state}")
        return "\n".join(lines)


# ------------------------------------------------------- طبقة العدّ
def _count_mismatches(archived: dict[str, Any], recomputed: dict[str, Any]) -> tuple[str, ...]:
    """المفاتيح المشتركة المخالفة فقط — والمفاتيح الوحيدة موثقة لا مُخفاة."""
    return tuple(sorted(k for k in set(archived) & set(recomputed) if archived[k] != recomputed[k]))


def _attempts_from_loop(loop: dict[str, Any]) -> tuple[SWEAttempt, ...] | None:
    """أعد بناء المحاولات من الشكل الجديد — أو لا شيء للشكل القديم."""
    attempts = loop.get("attempts") or []
    if not attempts or not isinstance(attempts[0], dict) or "verdict" not in attempts[0]:
        return None
    out: list[SWEAttempt] = []
    for ad in attempts:
        out.append(
            SWEAttempt(
                instance_id=ad.get("instance_id") or loop.get("instance_id") or "",
                file_choice=ad.get("file_choice"),
                choice_reply_sha16=ad.get("choice_reply_sha16") or "",
                diff_reply_sha16=ad.get("diff_reply_sha16") or "",
                proposal_accepted=bool(ad.get("proposal_accepted", False)),
                verdict=_verdict_from_dict(ad.get("verdict") or {}),
                patch_audit=ad.get("patch_audit") or {},
                patch_text=ad.get("patch_text") or "",
            )
        )
    return tuple(out)


def _replay_per_attempt(
    iid: str,
    att_dicts: list[dict[str, Any]],
    *,
    workdirs: Mapping[str, Path] | None,
    runner: Runner,
) -> tuple[ReplayRow, list[SWEAttempt]]:
    """طبقات 2–5 على شكل المحاولة — والعدّ من الأصل لا من الزعم."""
    texts_replayed = text_absent = audit_absent = audit_mismatches = 0
    derivation_mismatches = audit_rejections = 0
    gate_replays = gate_skipped = gate_mismatches = 0
    strict_replay = env_replay = 0
    rebuilt: list[SWEAttempt] = []
    workdir = (workdirs or {}).get(iid)
    for ad in att_dicts:
        archived_verdict = ad.get("verdict") or {}
        text = ad.get("patch_text") or ""
        archived_audit = ad.get("patch_audit") or {}
        replayed_audit: dict[str, Any] | None = None
        if text:
            replayed = audit_patch_text(text)
            if any(f.severity == "critical" for f in replayed.findings):
                audit_rejections += 1
            if archived_audit:  # أرشيف موجود يُقارن مهما ادّعى — والطمس كذبة
                if _audit_mismatch(text, archived_audit):
                    audit_mismatches += 1
            else:
                audit_absent += 1
            replayed_audit = replayed.to_dict()
            texts_replayed += 1
        else:
            text_absent += 1
            if not archived_audit:  # لا نص لإعادة التدقيق ولا أرشيف للمقارنة
                audit_absent += 1
        v = _verdict_from_dict(archived_verdict)
        derivation_mismatches += len(_derivation_mismatches(v, archived_verdict))
        if v.resolved_strict:
            strict_replay += 1
        if v.resolved_env:
            env_replay += 1
        # البوابة الثابتة تُعاد عند توفر الشجرة — وزعم القبول يُنفى
        if text and workdir is not None:
            gate_run = _replay_static_gate(workdir, text, runner)
            if gate_run["gate"] is None:
                gate_skipped += 1
            else:
                gate_replays += 1
                archived_gate = archived_verdict.get("static_gate") or {}
                if archived_gate and _gate_signature(archived_gate) != _gate_signature(
                    gate_run["gate"]
                ):
                    gate_mismatches += 1
        elif text:
            gate_skipped += 1
        rebuilt.append(
            SWEAttempt(
                instance_id=ad.get("instance_id") or iid,
                file_choice=ad.get("file_choice"),
                choice_reply_sha16=ad.get("choice_reply_sha16") or "",
                diff_reply_sha16=ad.get("diff_reply_sha16") or "",
                proposal_accepted=bool(ad.get("proposal_accepted", False)),
                verdict=v,
                patch_audit=replayed_audit if replayed_audit is not None else archived_audit,
                patch_text=text,
            )
        )
    row = ReplayRow(
        instance_id=iid,
        shape="per-attempt",
        attempts=len(att_dicts),
        texts_replayed=texts_replayed,
        text_absent=text_absent,
        audit_absent=audit_absent,
        audit_mismatches=audit_mismatches,
        derivation_mismatches=derivation_mismatches,
        audit_rejections=audit_rejections,
        static_gate_replays=gate_replays,
        static_gate_skipped=gate_skipped,
        static_gate_mismatches=gate_mismatches,
        resolved_strict_replay=strict_replay,
        resolved_env_replay=env_replay,
    )
    return row, rebuilt


def _replay_legacy(iid: str, loop: dict[str, Any]) -> ReplayRow:
    """الشكل القديم: بصمة الحكم النهائي ومشتقاته — والباقي موثق لا مخفي."""
    att_dicts = loop.get("attempts") or []
    archived_verdict = loop.get("verdict") or {}
    derivation_mismatches = strict_replay = env_replay = 0
    if archived_verdict:
        v = _verdict_from_dict(archived_verdict)
        derivation_mismatches = len(_derivation_mismatches(v, archived_verdict))
        strict_replay = 1 if v.resolved_strict else 0
        env_replay = 1 if v.resolved_env else 0
    return ReplayRow(
        instance_id=iid,
        shape="legacy",
        attempts=len(att_dicts),
        text_absent=len(att_dicts),
        derivation_mismatches=derivation_mismatches,
        resolved_strict_replay=strict_replay,
        resolved_env_replay=env_replay,
    )


def replay_receipt(
    receipt: dict[str, Any],
    *,
    source_label: str = "",
    workdirs: Mapping[str, Path] | None = None,
    runner: Runner = subprocess.run,
) -> ReplayReport:
    """أعد الحكم على إيصال كامل — أربع طبقات، والمخالف تُسمّى لا تُشبح."""
    source_sha16 = _sha16(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    source_chain_hash = str(receipt.get("chain_hash") or "")
    recomputed_chain_hash = chain_hash_of(receipt)
    if source_chain_hash:
        doc_hash_ok = source_chain_hash == recomputed_chain_hash
        note_ar = (
            _DOC_HASH_OK_AR
            if doc_hash_ok
            else "بصمة الإيصال لا تطابق إعادة إنتاجها — بايتات تعدّلت بعد الحدث"
        )
    else:
        doc_hash_ok = False
        note_ar = _NO_FP_AR

    rows: list[ReplayRow] = []
    rebuilt_all: list[SWEAttempt] = []
    legacy_sums = {"total": 0, "resolved_strict": 0, "resolved_env": 0, "f2p_repaired_total": 0}
    shapes: set[str] = set()
    for res in receipt.get("results") or []:
        loop = res.get("loop") or {}
        iid = res.get("instance_id") or loop.get("instance_id") or "؟"
        att_dicts = loop.get("attempts") or []
        if att_dicts and isinstance(att_dicts[0], dict) and "verdict" in att_dicts[0]:
            shapes.add("per-attempt")
            row, rebuilt = _replay_per_attempt(
                iid, [a for a in att_dicts if isinstance(a, dict)], workdirs=workdirs, runner=runner
            )
            rows.append(row)
            rebuilt_all.extend(rebuilt)
        else:
            shapes.add("legacy")
            row = _replay_legacy(iid, loop)
            rows.append(row)
            legacy_sums["total"] += 1
            legacy_sums["resolved_strict"] += row.resolved_strict_replay
            legacy_sums["resolved_env"] += row.resolved_env_replay
            legacy_sums["f2p_repaired_total"] += (
                _verdict_from_dict(loop.get("verdict") or {}).f2p_repaired_count
                if loop.get("verdict")
                else 0
            )

    archived_aggregate = dict(receipt.get("aggregate") or {})
    if "per-attempt" in shapes and rebuilt_all:
        recomputed_aggregate = aggregate(tuple(rebuilt_all)).to_dict()
    else:
        recomputed_aggregate = dict(legacy_sums)
    count_mismatches = _count_mismatches(archived_aggregate, recomputed_aggregate)
    legacy_keys = _LEGACY_COUNT_KEYS if shapes == {"legacy"} else ()

    return ReplayReport(
        protocol=str(receipt.get("protocol") or ""),
        source_label=source_label or "إيصال",
        source_sha16=source_sha16,
        source_chain_hash=source_chain_hash,
        recomputed_chain_hash=recomputed_chain_hash,
        doc_hash_ok=doc_hash_ok,
        doc_hash_note_ar=note_ar,
        rows=rows,
        archived_aggregate=archived_aggregate,
        recomputed_aggregate=recomputed_aggregate,
        count_mismatches=count_mismatches,
        legacy_count_keys=legacy_keys,
    )


def replay_file(
    path: Path,
    *,
    source_label: str = "",
    workdirs: Mapping[str, Path] | None = None,
    runner: Runner = subprocess.run,
) -> ReplayReport:
    """حمّل الإيصال من ملفه وأعد حكمه — بصمة الملف من بايتاته الخام."""
    raw = Path(path).read_text(encoding="utf-8")
    receipt = json.loads(raw)
    report = replay_receipt(
        receipt, source_label=source_label or str(path), workdirs=workdirs, runner=runner
    )
    # بصمة الملف من بايتاته الخام — ما قبل التحليل لا ما بعده
    report.source_sha16 = _sha16(raw)
    return report


def run_replay(args: Any) -> int:
    """`zyko bench-replay` — قاعة إعادة الحكم على سطر الأوامر.

    أكواد الخروج — نمط المصنع: 0 سليم · 1 مخالفة صادقة · 2 خطأ استخدام.
    """
    receipt_path = Path(getattr(args, "receipt", "") or "")
    if not receipt_path:
        print("خطأ: --receipt مطلوب — لا قاعة بلا إيصال", file=sys.stderr)
        return 2
    if not receipt_path.exists():
        print(f"خطأ: الإيصال غير موجود — {receipt_path}", file=sys.stderr)
        return 2
    try:
        report = replay_file(receipt_path, source_label=str(receipt_path))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"خطأ: إيصال غير مقروء — {exc}", file=sys.stderr)
        return 2
    print(report.table_ar())
    out = getattr(args, "json_out", None)
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(out_path, report.to_dict())
    return 0 if report.ok else 1
