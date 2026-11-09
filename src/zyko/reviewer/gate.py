"""zyko.reviewer.gate — بوابة قبول المرحلة 2 (D22–40): التقييم أولًا بأول.

ست بوابات كمية تُحسم من عينات المرساة (samples/review):
  G1 الاسترجاع      — كل عيب مزروع (29 عيبًا) يُكتشف ضمن نافذة سطرين
  G2 الدقة          — العينات النظيفة تبقى نظيفة: صفر ملاحظات إطلاقًا
  G3 الحتمية        — مراجعتان متتاليتان ⇒ نفس بايتات JSON والنص
  G4 المتانة        — 11 مدخلًا عدائيًا (فارغ/مكسور/ثنائي/عملاق…) بلا انهيار
  G5 الأداء         — الدفعة كاملة في أقل من ثوانٍ معدودة
  G6 لا قاعدة ميتة  — كل قاعدة في السجل تُطلق فعليًا على العينات المعيبة

البوابة هي «التقييم أولًا بأول» المطلوب: تُدار مع كل تعديل، وأي ضعف يظهر
فورًا كصف فاشل بتفصيل عربي — لا يمر شيء بالشعور الشخصي.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zyko.reviewer.engine import ReviewEngine
from zyko.reviewer.report import result_to_json, result_to_text
from zyko.reviewer.rules import RULES

# نافذة التطابق بين سطر العيب المزروع وسطر الملاحظة (سطران في الاتجاهين).
DETECT_WINDOW = 2
DEFAULT_MAX_SECONDS = 5.0


def default_samples_dir() -> Path | None:
    """يرصد مجلد العينات: cwd ثم جذر المستودع ثم جذر الحزمة المستقلة."""
    here = Path(__file__).resolve()
    for candidate in (
        Path.cwd() / "samples" / "review",
        here.parents[3] / "samples" / "review",
        here.parents[2] / "samples" / "review",
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
class Phase2GateResult:
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


def _planted_detected(findings: list, planted_line: int) -> bool:
    """العيب مزروع يعتبر مكشوفًا إذا وُجدت ملاحظة ضمن النافذة حول سطره."""
    return any(abs(f.line - planted_line) <= DETECT_WINDOW for f in findings)


def _gate_recall(
    engine: ReviewEngine, samples_dir: Path, manifest: dict[str, Any], min_recall: float
) -> GateRow:
    total = 0
    detected = 0
    misses: list[str] = []
    for entry in manifest["defective"]:
        result = engine.review_file(samples_dir / entry["file"])
        for planted in entry["planted"]:
            total += 1
            if _planted_detected(result.findings, planted["line"]):
                detected += 1
            else:
                misses.append(f"{entry['file']}:{planted['line']} ({planted['id']})")
    passed = total > 0 and (detected / total) >= min_recall
    detail = f"{detected}/{total} عيبًا مزروعًا مكشوفًا"
    if misses:
        detail += " — فائتة: " + "، ".join(misses[:6])
    return GateRow("G1", "استرجاع العيوب المزروعة", passed, detail)


def _gate_precision(engine: ReviewEngine, samples_dir: Path, manifest: dict[str, Any]) -> GateRow:
    leaks: list[str] = []
    total_findings = 0
    for name in manifest["clean"]:
        result = engine.review_file(samples_dir / name)
        total_findings += len(result.findings)
        for f in result.findings:
            leaks.append(f"{name}:{f.line} ({f.rule_id})")
    passed = total_findings == 0
    detail = "صفر ملاحظات على العينات النظيفة" if passed else "تسريبات: " + "، ".join(leaks[:6])
    return GateRow("G2", "نظافة العينات النظيفة (لا إنذارات كاذبة)", passed, detail)


def _gate_determinism(engine: ReviewEngine, samples_dir: Path, manifest: dict[str, Any]) -> GateRow:
    names = [e["file"] for e in manifest["defective"]] + list(manifest["clean"])
    diffs: list[str] = []
    for name in names:
        source = (samples_dir / name).read_text(encoding="utf-8")
        first_json = result_to_json(engine.review_source(source, name))
        first_text = result_to_text(engine.review_source(source, name))
        second_json = result_to_json(engine.review_source(source, name))
        second_text = result_to_text(engine.review_source(source, name))
        if first_json != second_json or first_text != second_text:
            diffs.append(name)
    passed = not diffs
    detail = (
        "مراجعتان متتاليتان لكل عينة ⇒ بايتات متطابقة"
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


def _gate_robustness(engine: ReviewEngine) -> tuple[GateRow, float]:
    import tempfile

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="zyko_gate4_") as tmp:
        paths = _robustness_corpus(Path(tmp))
        start = time.perf_counter()
        try:
            results = [engine.review_file(p) for p in paths]
            for r in results:
                if r.parse_error is None and r.score not in range(0, 101):
                    failures.append(f"{r.path}: درجة خارج النطاق")
        except Exception as exc:  # أي انهيار هنا فشل بوابة صريح
            return GateRow(
                "G4", "متانة المدخلات العدائية", False, f"انهيار: {type(exc).__name__}"
            ), 0.0
        elapsed = time.perf_counter() - start
        # مسح شجري للمجلد العدائي كله لا بد أن يعود بلا استثناء أيضًا
        try:
            engine.review_path(Path(tmp))
        except Exception as exc:
            return GateRow(
                "G4", "متانة المدخلات العدائية", False, f"انهيار مسح شجري: {type(exc).__name__}"
            ), elapsed
    structured = len(paths)
    if failures:
        return GateRow("G4", "متانة المدخلات العدائية", False, "؛ ".join(failures[:4])), elapsed
    return GateRow(
        "G4", "متانة المدخلات العدائية", True, f"{structured} مدخلًا عدائيًا بلا انهيار"
    ), elapsed


def _gate_performance(engine: ReviewEngine, samples_dir: Path, max_seconds: float) -> GateRow:
    names = [e["file"] for e in manifest_files(samples_dir)]
    start = time.perf_counter()
    rounds = 3
    for _ in range(rounds):
        for name in names:
            engine.review_file(samples_dir / name)
    elapsed = time.perf_counter() - start
    per_file_ms = elapsed / (rounds * max(1, len(names))) * 1000
    passed = elapsed < max_seconds
    return GateRow(
        "G5",
        "الأداء",
        passed,
        f"{len(names)} ملفات × {rounds} جولات في {elapsed:.2f} ث (~{per_file_ms:.1f} ملّي/ملف، الحد {max_seconds:.0f} ث)",
    )


def manifest_files(samples_dir: Path) -> list[dict[str, Any]]:
    return _load_manifest(samples_dir)["defective"]


def _gate_rule_coverage(
    engine: ReviewEngine, samples_dir: Path, manifest: dict[str, Any]
) -> GateRow:
    fired: set[str] = set()
    for entry in manifest["defective"]:
        result = engine.review_file(samples_dir / entry["file"])
        fired.update(f.rule_id for f in result.findings)
    all_rules = {r.rule_id for r in RULES}
    dead = sorted(all_rules - fired)
    passed = not dead
    detail = (
        f"{len(fired)}/{len(all_rules)} قاعدة أطلقت على العينات المعيبة"
        if passed
        else "قواعد ميتة: " + "، ".join(dead)
    )
    return GateRow("G6", "لا قاعدة ميتة في السجل", passed, detail)


def run_phase2_gate(
    samples_dir: str | Path | None = None,
    *,
    min_recall: float = 1.0,
    max_seconds: float = DEFAULT_MAX_SECONDS,
) -> Phase2GateResult:
    """تشغيل البوابات الست كاملة — نفس نقطة الدخول للاختبارات وللـ CI وللطرفية."""
    resolved = Path(samples_dir) if samples_dir else default_samples_dir()
    result = Phase2GateResult()
    if resolved is None or not (resolved / "manifest.json").is_file():
        result.rows.append(
            GateRow("G0", "توفر عينات المرساة", False, "لم يُعثر على manifest.json — مرّر --samples")
        )
        return result
    engine = ReviewEngine()
    manifest = _load_manifest(resolved)
    result.rows.append(_gate_recall(engine, resolved, manifest, min_recall))
    result.rows.append(_gate_precision(engine, resolved, manifest))
    result.rows.append(_gate_determinism(engine, resolved, manifest))
    row4, _ = _gate_robustness(engine)
    result.rows.append(row4)
    result.rows.append(_gate_performance(engine, resolved, max_seconds))
    result.rows.append(_gate_rule_coverage(engine, resolved, manifest))
    return result


__all__ = [
    "DETECT_WINDOW",
    "DEFAULT_MAX_SECONDS",
    "GateRow",
    "Phase2GateResult",
    "run_phase2_gate",
]
