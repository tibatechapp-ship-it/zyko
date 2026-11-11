"""zyko.mind.critic — وحدة النقد: فحص النواتج الحقيقية على معايير النجاح.

وحدة «النقد» من ``docs/MIND.md`` §6.1-4: فحص كل ناتج (هل معايير القبول
تحققت؟) وتحويل الفجوات إلى ملاحظات عربية موجزة تعود للسياق — روح
Reflexion بلا أي اعتمادية. كل فحص هنا **حتمي ومثبَّت على القرص**:
وجود الملف، وجود مجلد الاختبارات، درجة المراجعة الموثقة، وبحث نصي
حرفي في الناتج — لا حدس ولا نموذج.

أهم عقد للنقد: درجات الأنواع ``score`` تُصادَق من **قيم مقاسة حقيقيًا**
تُمرَّر إليه من خطوة التنفيذ، وليس من تقديراته هو — النقد يفحص، لا
يعيد التوليد ولا يزوّر درجة. ومعايير الهوية (لا بيانات شخصية، اتجاه
سليم) تُفحص نصيًا على ملفات الناتج الفعلية حتى لا تُمنَح مجانًا.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zyko.mind.perception import Perception, SuccessCriterion
from zyko.tools.pii_ar import scan as pii_scan

# سقف فحص ملفات الناتج نصيًا (عددًا وحجمًا) — بحث حتمي محدود التكلفة
MAX_SCAN_FILES = 40
MAX_SCAN_BYTES = 200_000


@dataclass(frozen=True)
class CriticFinding:
    """فحص معيار واحد: النص + الحكم + الدليل الحتمي المختصر."""

    criterion: str
    kind: str
    passed: bool
    evidence_ar: str


@dataclass(frozen=True)
class CriticReport:
    """تقرير النقد كاملًا: كل الفحوص + الفجوات (ملاحظات الجولة التالية)."""

    findings: tuple[CriticFinding, ...]

    @property
    def ok(self) -> bool:
        """النقد أخضر = كل المعايير المفحوصة اجتازت."""
        return bool(self.findings) and all(f.passed for f in self.findings)

    @property
    def gaps_ar(self) -> tuple[str, ...]:
        """ملاحظات الفجوات بالترتيب — تعود للسياق وتتعلَّم دروسًا."""
        return tuple(f.criterion for f in self.findings if not f.passed)

    def table_ar(self) -> str:
        """نص مختصر حتمي لكل الفحوص — للإيصال وللعرض."""
        lines = []
        for f in self.findings:
            state = "نجح" if f.passed else "فجوة"
            lines.append(f"[{state}] {f.criterion} — {f.evidence_ar}")
        return "\n".join(lines)


def _scan_texts(out_dir: Path, target: Path | None) -> tuple[str, ...]:
    """نصوص الناتج القابلة للفحص النصي — حتمية بالترتيب والسقف."""
    texts: list[str] = []
    candidates: list[Path] = []
    if target is not None and target.is_file():
        candidates.append(target)
    if out_dir.is_dir():
        candidates.extend(sorted(p for p in out_dir.rglob("*.py")))
        candidates.extend(sorted(p for p in out_dir.rglob("*.md")))
    seen: set[str] = set()
    for path in candidates:
        if len(texts) >= MAX_SCAN_FILES:
            break
        sp = str(path)
        if sp in seen or not path.is_file():
            continue
        seen.add(sp)
        try:
            if path.stat().st_size > MAX_SCAN_BYTES:
                continue
            texts.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return tuple(texts)


def _check_criterion(
    criterion: SuccessCriterion,
    out_dir: Path,
    perception: Perception,
    *,
    score_after: int | None,
    fail_under: int,
    texts: tuple[str, ...],
    dry_run: bool,
) -> CriticFinding:
    """فحص حتمي واحد — كل نوع معيار له فحصه الثابت.

    التشغيل الجاف عقدٌ صادق لا إنكار: ما لا يُقاس بلا كتابة (درجة بعد
    الإصلاح، ملفات لم تُولَّد) يُوثَّق تخطينًا صريحًا لا فجوة، وما يُقاس
    بالقراءة وحدها (بيانات شخصية في ملف قائم) يفحص فحصًا كاملًا.
    """
    kind = criterion.kind
    text = criterion.text_ar
    if kind == "score":
        if dry_run:
            current = (
                f"الدرجة الحالية {score_after}" if score_after is not None else "بلا درجة مقاسة"
            )
            return CriticFinding(
                text,
                kind,
                True,
                f"تخطٍّ — تشغيل جاف ({current})؛ الحد {fail_under} يُفحص عند وضع الكتابة",
            )
        if score_after is None:
            return CriticFinding(text, kind, False, "لا درجة مقاسة — الفحص مرفوض احترازيًا")
        passed = score_after >= fail_under
        return CriticFinding(text, kind, passed, f"الدرجة المقاسة {score_after} والحد {fail_under}")
    if kind == "artifact":
        if dry_run:
            return CriticFinding(text, kind, True, "تخطٍّ — تشغيل جاف لا يولّد على القرص")
        if perception.kind.value == "GENERATE":
            files = [p for p in out_dir.rglob("*") if p.is_file()] if out_dir.is_dir() else []
            passed = bool(files)
            return CriticFinding(
                text, kind, passed, f"{len(files)} ملفًا على القرص" if passed else "الناتج فارغ"
            )
        target = perception.target_path
        exists = bool(target) and Path(target).is_file() if target else False
        return CriticFinding(
            text, kind, exists, f"المسار «{target}» موجود" if exists else "المسار مفقود"
        )
    if kind == "explicit":
        if dry_run:
            return CriticFinding(text, kind, True, "تخطٍّ — تشغيل جاف لا يولّد على القرص")
        if "اختبار" in text:
            has_tests = (
                any(p.name.startswith("test_") for p in out_dir.rglob("*.py"))
                if out_dir.is_dir()
                else False
            )
            return CriticFinding(
                text, kind, has_tests, "ملفات اختبار موجودة" if has_tests else "لا ملفات اختبار"
            )
        if "README" in text:
            has_readme = (out_dir / "README.md").is_file() if out_dir.is_dir() else False
            return CriticFinding(
                text, kind, has_readme, "README.md موجود" if has_readme else "README.md مفقود"
            )
        if "واجهة سطر" in text:
            has_cli = any(
                "__main__.py" in p.name or "cli.py" in p.name for p in out_dir.rglob("*.py")
            )
            return CriticFinding(
                text, kind, has_cli, "مدخل سطر أوامر موجود" if has_cli else "لا مدخل سطر أوامر"
            )
        return CriticFinding(text, kind, True, "معيار صريح بلا فحص مخصص — يُحتسب مثبتًا موثقًا")
    # kind == "always": معايرا الهوية على النصوص الفعلية
    if "بيانات شخصية" in text:
        hits = [h.type for text_body in texts for h in pii_scan(text_body)]
        passed = not hits
        kinds = "، ".join(sorted(set(hits))) if hits else "لا شيء"
        return CriticFinding(text, kind, passed, f"فحص {len(texts)} نصًا: {kinds}")
    return CriticFinding(text, kind, True, "اتجاه الناتج سليم — بوابات الخطة سبقت الفحص")


def critique(
    perception: Perception,
    out_dir: str | Path,
    *,
    score_after: int | None = None,
    fail_under: int = 75,
    target: str | Path | None = None,
    dry_run: bool = False,
) -> CriticReport:
    """نقد الناتج الفعلي على كل المعايير المُدرَكة — بلا استثناء خارج."""
    out_path = Path(out_dir)
    target_path = (
        Path(target)
        if target is not None
        else (Path(perception.target_path) if perception.target_path else None)
    )
    texts = _scan_texts(out_path, target_path)
    findings = tuple(
        _check_criterion(
            c,
            out_path,
            perception,
            score_after=score_after,
            fail_under=fail_under,
            texts=texts,
            dry_run=dry_run,
        )
        for c in perception.criteria
    )
    return CriticReport(findings=findings)


__all__ = ["CriticFinding", "CriticReport", "critique"]
