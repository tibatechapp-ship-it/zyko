"""zyko.fixer.gate — بوابة قبول المرحلة 3 (D41–58): التقييم أولًا بأول.

ست بوابات كمية تُحسم من عينات المرساة (samples/fix):
  G1 الإصلاح الآلي   — كل قاعدة متوقعة في manifest تُحسم بالكامل على ملفها،
                       ولا تبقى ملاحظة آلية مفتوحة إلا المصرّح بها allow_open
  G2 عدم التلف       — النص المُصلَّح يُعاد تحليله، وتشغيل المُصلِح على ناتجه
                       ينتج صفر تغيير (الاعتدال)، والدرجة لا تنخفض أبدًا
  G3 الحتمية         — تشغيلان متتاليان ⇒ نفس بايتات JSON والنص والناتج
  G4 المتانة         — 11 مدخلًا عدائيًا (فارغ/مكسور/ثنائي/عملاق…) بلا انهيار
  G5 الأداء          — الدفعة كاملة في أقل من ثوانٍ معدودة
  G6 لا مسار ميت     — كل قاعدة آلية تُصلَح فعليًا مرة واحدة على الأقل،
                       وكل قاعدة يدوية تظهر كملاحظة يدوية (suggestion_ar ظاهر)

البوابة هي «التقييم أولًا بأول» المطلوب: تُدار مع كل تعديل، وأي ضعف يظهر
فورًا كصف فاشل بتفصيل عربي — لا يمر شيء بالشعور الشخصي.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zyko.fixer.edits import parses
from zyko.fixer.engine import (
    STATUS_FIXED,
    STATUS_MANUAL,
    STATUS_OPEN,
    FixerEngine,
    FixResult,
)
from zyko.fixer.fixes import AUTO_FIXABLE, MANUAL_RULES
from zyko.fixer.report import fix_result_to_json, fix_result_to_text

DEFAULT_MAX_SECONDS = 5.0


def default_samples_dir() -> Path | None:
    """يرصد مجلد العينات: cwd ثم جذر المستودع ثم جذر الحزمة المستقلة."""
    here = Path(__file__).resolve()
    for candidate in (
        Path.cwd() / "samples" / "fix",
        here.parents[3] / "samples" / "fix",
        here.parents[2] / "samples" / "fix",
    ):
        if (candidate / "manifest.json").is_file():
            return candidate
    return None


@dataclass
class GateRow:
    """نتيجة بوابة واحدة من الست."""

    gate_id: str
    name_ar: str
    passed: bool
    detail_ar: str


@dataclass
class Phase3GateResult:
    """ملخص البوابة كاملة — ok تعني اجتياز الست بلا استثناء."""

    rows: list[GateRow] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.rows) and all(r.passed for r in self.rows)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.rows if r.passed)

    def table_ar(self) -> str:
        lines = ["البوابة | الاسم | الحكم | التفصيل"]
        for r in self.rows:
            mark = "ناجحة" if r.passed else "فاشلة"
            lines.append(f"{r.gate_id} | {r.name_ar} | {mark} | {r.detail_ar}")
        lines.append(
            f"الخلاصة: {self.passed_count}/{len(self.rows)} بوابات — "
            f"الحكم: {'مقبول' if self.ok else 'مرفوض'}"
        )
        return "\n".join(lines)


def _load_manifest(samples_dir: Path) -> dict[str, Any]:
    return json.loads((samples_dir / "manifest.json").read_text(encoding="utf-8"))


def _rule_resolved(result: FixResult, rule_id: str) -> bool:
    """هل حُسمت القاعدة كاملةً في هذا الملف؟ (مصيرها «أُصلح» ولا أثر لها بعده)."""
    return any(
        o.rule_id == rule_id and o.status == STATUS_FIXED for o in result.outcomes
    ) and not any(o.rule_id == rule_id and o.status != STATUS_FIXED for o in result.outcomes)


def _gate_fix(
    fixer: FixerEngine, samples_dir: Path, manifest: dict[str, Any]
) -> tuple[GateRow, dict[str, FixResult]]:
    results: dict[str, FixResult] = {}
    failures: list[str] = []
    for entry in manifest["defective"]:
        result = fixer.fix_file(samples_dir / entry["file"])
        results[entry["file"]] = result
        if result.parse_error is not None:
            failures.append(f"{entry['file']}: {result.parse_error}")
            continue
        for rid in entry.get("expect_fixed", []):
            if not _rule_resolved(result, rid):
                states = [f"{o.rule_id}:{o.status}" for o in result.outcomes if o.rule_id == rid]
                failures.append(
                    f"{entry['file']}: لم تُحسم {rid} ({'، '.join(states) or 'بلا ملاحظات'})"
                )
        allow_open = set(entry.get("allow_open", []))
        for o in result.outcomes:
            if (
                o.rule_id in AUTO_FIXABLE
                and o.status == STATUS_OPEN
                and o.rule_id not in allow_open
            ):
                failures.append(f"{entry['file']}:{o.line}: بقت {o.rule_id} مفتوحة بلا تصريح")
    passed = not failures and bool(manifest["defective"])
    detail = (
        f"{len(manifest['defective'])} ملفات معيبة — كل المتوقع آليًا حُسم والباقي مصرّح به"
        if passed
        else "؛ ".join(failures[:6])
    )
    return GateRow("G1", "الإصلاح الآلي الكامل المتوقع", passed, detail), results


def _gate_no_damage(
    fixer: FixerEngine, samples_dir: Path, manifest: dict[str, Any], results: dict[str, FixResult]
) -> GateRow:
    failures: list[str] = []
    names = [e["file"] for e in manifest["defective"]] + list(manifest["clean"])
    for name in names:
        result = results.get(name) or fixer.fix_file(samples_dir / name)
        if result.parse_error is not None:
            continue  # المتانة بابها الخاص (G4)
        if result.changed and not parses(result.fixed_source):
            failures.append(f"{name}: الناتج لا يُحلَّل — كارثة سلامة")
        if result.score_after < result.score_before:
            failures.append(f"{name}: الدرجة انخفضت ({result.score_before}→{result.score_after})")
        # الاعتدال: تشغيل المُصلِح على ناتجه يجب ألا يغيّر شيئًا
        second = fixer.fix_source(result.fixed_source, name)
        if second.changed:
            failures.append(f"{name}: الجولة الثانية غيّرت النص — الاعتدال منكسر")
    passed = not failures
    detail = (
        "النواتج تُحلَّل، الدرجات لا تنخفض، والجولة الثانية بلا تغيير"
        if passed
        else "؛ ".join(failures[:6])
    )
    return GateRow("G2", "عدم التلف والاعتدال", passed, detail)


def _gate_determinism(fixer: FixerEngine, samples_dir: Path, manifest: dict[str, Any]) -> GateRow:
    names = [e["file"] for e in manifest["defective"]] + list(manifest["clean"])
    diffs: list[str] = []
    for name in names:
        source = (samples_dir / name).read_text(encoding="utf-8")
        first = fixer.fix_source(source, name)
        second = fixer.fix_source(source, name)
        if (
            fix_result_to_json(first) != fix_result_to_json(second)
            or fix_result_to_text(first) != fix_result_to_text(second)
            or first.fixed_source != second.fixed_source
        ):
            diffs.append(name)
    passed = not diffs
    detail = (
        "تشغيلان متتاليان لكل عينة ⇒ بايتات متطابقة"
        if passed
        else "اختلافات في: " + "، ".join(diffs)
    )
    return GateRow("G3", "الحتمية البايتية", passed, detail)


def _robustness_corpus(tmp_dir: Path) -> list[Path]:
    """11 مدخلًا عدائيًا يُولَّد هنا (حتميًا) — يجب ألا يُسقط أي منها المحرك."""
    corpus: list[tuple[str, bytes]] = [
        ("h_empty.py", b""),
        ("h_syntax.py", b"def broken(:\n    pass\n"),
        ("h_nulls.py", b"x = 1\x00y = 2\n"),
        ("h_latin1.py", b"# caf\xe9 latin-1 only\nx = 1\n"),
        ("h_bom.py", b"\xef\xbb\xbfvalue = 1\n"),
        ("h_crlf.py", b"def f():\r\n    return 1\r\n"),
        ("h_tabs.py", b"def f():\n\tif True:\n\t\treturn 1\n"),
        ("h_unicode_names.py", "قيمة = 5\nprint(قيمة)\n".encode("utf-8")),
        ("h_huge_line.py", b"x = '" + b"a" * 300_000 + b"'\n"),
        ("h_comment_only.py", "# لا شيء غير هذا التعليق\n".encode("utf-8")),
        ("h_deep.py", ("x = 0\n" + "if x == 0:\n" * 40 + "    pass\n").encode("utf-8")),
    ]
    paths: list[Path] = []
    for name, data in corpus:
        p = tmp_dir / name
        p.write_bytes(data)
        paths.append(p)
    return paths


def _gate_robustness(fixer: FixerEngine) -> GateRow:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="zyko_fixer_gate4_") as tmp:
        paths = _robustness_corpus(Path(tmp))
        try:
            results = [fixer.fix_file(p) for p in paths]
            for r in results:
                if r.parse_error is None and r.changed and not parses(r.fixed_source):
                    return GateRow(
                        "G4",
                        "متانة المدخلات العدائية",
                        False,
                        f"{r.path}: ناتج غير قابل للتحليل",
                    )
            fixer.fix_path(Path(tmp))  # مسح شجري كامل بلا استثناء أيضًا
        except Exception as exc:  # noqa: BLE001 — أي انهيار هنا فشل بوابة صريح
            return GateRow("G4", "متانة المدخلات العدائية", False, f"انهيار: {type(exc).__name__}")
    return GateRow("G4", "متانة المدخلات العدائية", True, f"{len(paths)} مدخلًا عدائيًا بلا انهيار")


def _gate_performance(
    fixer: FixerEngine, samples_dir: Path, manifest: dict[str, Any], max_seconds: float
) -> GateRow:
    names = [e["file"] for e in manifest["defective"]] + list(manifest["clean"])
    start = time.perf_counter()
    rounds = 3
    for _ in range(rounds):
        for name in names:
            fixer.fix_file(samples_dir / name)
    elapsed = time.perf_counter() - start
    passed = elapsed < max_seconds
    per_file_ms = elapsed / (rounds * max(1, len(names))) * 1000
    return GateRow(
        "G5",
        "الأداء",
        passed,
        f"{len(names)} ملفات × {rounds} جولات في {elapsed:.2f} ث "
        f"(~{per_file_ms:.1f} ملّي/ملف، الحد {max_seconds:.0f} ث)",
    )


def _gate_no_dead_path(
    fixer: FixerEngine, samples_dir: Path, manifest: dict[str, Any], results: dict[str, FixResult]
) -> GateRow:
    fixed_rules: set[str] = set()
    manual_rules: set[str] = set()
    names = [e["file"] for e in manifest["defective"]]
    for name in names:
        result = results.get(name) or fixer.fix_file(samples_dir / name)
        fixed_rules.update(o.rule_id for o in result.outcomes if o.status == STATUS_FIXED)
        manual_rules.update(o.rule_id for o in result.outcomes if o.status == STATUS_MANUAL)
    dead_fix = sorted(set(AUTO_FIXABLE) - fixed_rules)
    silent_manual = sorted(set(MANUAL_RULES) - manual_rules)
    passed = not dead_fix and not silent_manual
    if passed:
        detail = (
            f"{len(fixed_rules)}/{len(AUTO_FIXABLE)} مسارًا آليًا عمل، "
            f"و{len(manual_rules)}/{len(MANUAL_RULES)} قاعدة يدوية ظهرت بإصلاحها المقترح"
        )
    else:
        parts = []
        if dead_fix:
            parts.append("مسارات ميتة: " + "، ".join(dead_fix))
        if silent_manual:
            parts.append("قواعد يدوية صامتة: " + "، ".join(silent_manual))
        detail = "؛ ".join(parts)
    return GateRow("G6", "لا مسار ميت ولا قاعدة صامتة", passed, detail)


def run_phase3_gate(
    samples_dir: str | Path | None = None,
    *,
    max_seconds: float = DEFAULT_MAX_SECONDS,
) -> Phase3GateResult:
    """تشغيل البوابات الست كاملة — نفس نقطة الدخول للاختبارات وللـ CI وللطرفية."""
    resolved = Path(samples_dir) if samples_dir else default_samples_dir()
    result = Phase3GateResult()
    if resolved is None or not (resolved / "manifest.json").is_file():
        result.rows.append(
            GateRow("G0", "توفر عينات المرساة", False, "لم يُعثر على manifest.json — مرّر --samples")
        )
        return result
    fixer = FixerEngine()
    manifest = _load_manifest(resolved)
    row1, results = _gate_fix(fixer, resolved, manifest)
    result.rows.append(row1)
    result.rows.append(_gate_no_damage(fixer, resolved, manifest, results))
    result.rows.append(_gate_determinism(fixer, resolved, manifest))
    result.rows.append(_gate_robustness(fixer))
    result.rows.append(_gate_performance(fixer, resolved, manifest, max_seconds))
    result.rows.append(_gate_no_dead_path(fixer, resolved, manifest, results))
    return result


__all__ = [
    "DEFAULT_MAX_SECONDS",
    "GateRow",
    "Phase3GateResult",
    "run_phase3_gate",
]
