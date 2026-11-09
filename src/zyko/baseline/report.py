"""zyko.baseline.report — المخرجات: JSON + نص عربي + تقرير HTML RTL حتمي.

كل المخرجات حتمية البايتات: لا طوابع زمنية، لا أرقام عشوائية، ولا
شيء يتغير بين تشغيلين على نفس الحالة. تقرير HTML عربي كامل الاتجاه
(RTL) بأسلوب مضمّن وبلا جافاسكربت ولا موارد خارجية — يفتح في أي
متصفح ويصلح أصلًا لـCI. كل القيم تمر عبر html.escape بلا استثناء.
"""

from __future__ import annotations

import html
import json
from typing import Any

from zyko.baseline.engine import (
    F_GONE,
    F_IMPROVED,
    F_NEW,
    F_REGRESSED,
    F_SKIPPED,
    FILE_STATUS_AR,
    HISTORY_CAP,
    SCHEMA,
    STAGE_AR,
    VERDICT_MISSING,
    BaselineCheckResult,
    BaselineUpdateResult,
)

_LINE = "-" * 60

# ألوان الحالات — نفس الفئات في النص وHTML
_BAD_STATUSES = (F_REGRESSED, F_GONE)
_GOOD_STATUSES = (F_IMPROVED,)
_INFO_STATUSES = (F_NEW, F_SKIPPED)

_CSS = """\
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font-family: "Noto Naskh Arabic", "Segoe UI", Tahoma, sans-serif;
  background: #f6f4ef; color: #1d2733; margin: 0; padding: 2rem; }
.wrap { max-width: 60rem; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
.sub { color: #5b6b7c; margin: 0 0 1.5rem; font-size: .95rem; }
.cards { display: flex; flex-wrap: wrap; gap: .75rem; margin-bottom: 1.5rem; }
.card { background: #fff; border: 1px solid #dfe5ea; border-radius: .6rem;
  padding: .8rem 1.1rem; min-width: 8.5rem; text-align: center; }
.card .num { font-size: 1.6rem; font-weight: 700; display: block; }
.bad { color: #b3261e; } .good { color: #1b6e3c; } .info { color: #8a6d00; }
table { width: 100%; border-collapse: collapse; background: #fff;
  border: 1px solid #dfe5ea; border-radius: .6rem; overflow: hidden; }
th, td { padding: .5rem .7rem; text-align: right; border-bottom: 1px solid #eef1f4;
  font-size: .92rem; }
th { background: #eef2f6; color: #33414f; }
td.num, th.num { text-align: center; }
tr:last-child td { border-bottom: none; }
.st-regressed { color: #b3261e; font-weight: 700; }
.st-improved { color: #1b6e3c; font-weight: 700; }
.st-unchanged { color: #5b6b7c; }
.st-new { color: #8a6d00; font-weight: 700; }
.st-gone { color: #8a4b00; }
.st-skipped { color: #5b6b7c; }
.verdict { margin: 1.25rem 0; padding: .8rem 1rem; background: #eef2f6;
  border-inline-start: 4px solid #33414f; border-radius: .4rem; }
footer { margin-top: 2rem; color: #7c8894; font-size: .85rem; }
code { background: #eef2f6; padding: .1rem .35rem; border-radius: .3rem; }
h2 { font-size: 1.1rem; margin: 1.75rem 0 .6rem; }
"""


def baseline_update_to_json(result: BaselineUpdateResult, *, include_timing: bool = False) -> str:
    """حمولة JSON حتمية لنتيجة update."""
    return json.dumps(result.to_dict(include_timing=include_timing), ensure_ascii=False, indent=2)


def baseline_check_to_json(result: BaselineCheckResult, *, include_timing: bool = False) -> str:
    """حمولة JSON حتمية لنتيجة check."""
    return json.dumps(result.to_dict(include_timing=include_timing), ensure_ascii=False, indent=2)


def baseline_update_summary_line(result: BaselineUpdateResult) -> str:
    """سطر واحد لنتيجة update."""
    if not result.ok:
        stage = STAGE_AR.get(result.failed_stage or "", result.failed_stage or "؟")
        return f"فشل في {stage}: {result.error_ar}"
    verb = "أُنشئ خط الأساس" if result.created else "حُدِّث خط الأساس"
    return (
        f"{verb} (تشغيل {result.run_no}) — {result.reviewed} ملفًا مراقَبًا"
        f" (تُخُطّي {result.skipped}) — أدنى درجة {result.min_score}"
        f" — {result.findings_total} ملاحظة مسجَّلة"
    )


def baseline_check_summary_line(result: BaselineCheckResult) -> str:
    """سطر واحد لنتيجة check."""
    if not result.ok:
        stage = STAGE_AR.get(result.failed_stage or "", result.failed_stage or "؟")
        return f"فشل في {stage}: {result.error_ar}"
    if result.baseline_status != "ok":
        return f"لا خط أساس: {result.verdict_ar}"
    return (
        f"رُوجعت {result.reviewed} ملفًا مقابل خط الأساس (تشغيل {result.baseline_run_no})"
        f" — تراجع {result.regressed_files}، تحسّن {result.improved_files}"
        f"، ثابت {result.unchanged_files}، جديد {result.new_files}"
        f" — ملاحظات جديدة {result.new_findings_total}، محسومة {result.resolved_findings_total}"
        f" — الدرجة {result.min_score_baseline}←{result.min_score_current}"
    )


def baseline_update_to_text(result: BaselineUpdateResult) -> str:
    """تقرير عربي مقروء لنتيجة update."""
    lines: list[str] = []
    if not result.ok:
        stage = STAGE_AR.get(result.failed_stage or "", result.failed_stage or "؟")
        lines.append(f"فشل التحديث في مرحلة {stage}")
        lines.append(f"السبب: {result.error_ar}")
        for p in result.problems:
            lines.append(f"  - {p}")
        return "\n".join(lines)
    lines.append("حارس الجودة — تسجيل خط الأساس")
    lines.append(f"المجلد: {result.src}")
    lines.append(f"ملف خط الأساس: {result.baseline_path}")
    verb = "أُنشئ الآن (أول تسجيل)" if result.created else f"حُدِّث (تشغيل {result.run_no})"
    lines.append(f"الحالة: {verb}")
    lines.append(
        f"الملفات: {result.files_total} (مراقَب {result.reviewed}، تُخُطّي {result.skipped})"
        f" — أدنى درجة {result.min_score}/100"
        f" — ملاحظات مسجَّلة {result.findings_total}"
        f" — سجل التشغيلات {result.history_len}/{HISTORY_CAP}"
    )
    for n in result.notes:
        lines.append(f"ملاحظة: {n}")
    lines.append("من الآن: كل فحص (check) يقارن بهذا السجل — لا يُكتب على القرص شيء")
    return "\n".join(lines)


def baseline_check_to_text(result: BaselineCheckResult) -> str:
    """تقرير عربي مقروء لنتيجة check — كل ملف بحالته وأرقامه."""
    lines: list[str] = []
    if not result.ok:
        stage = STAGE_AR.get(result.failed_stage or "", result.failed_stage or "؟")
        lines.append(f"فشل الفحص في مرحلة {stage}")
        lines.append(f"السبب: {result.error_ar}")
        for p in result.problems:
            lines.append(f"  - {p}")
        return "\n".join(lines)

    lines.append("حارس الجودة — مقارنة الوضع الحالي بخط الأساس (قراءة فقط)")
    lines.append(f"المجلد: {result.src}")
    lines.append(f"ملف خط الأساس: {result.baseline_path}")
    if result.baseline_status != "ok":
        lines.append(f"الحالة: {VERDICT_MISSING}")
        lines.append("الإجراء: شغّل «update» لتسجيل الوضع الحالي كخط أساس أول")
        return "\n".join(lines)
    lines.append(f"رقم تشغيل خط الأساس: {result.baseline_run_no}")
    lines.append(
        f"الملفات: مراقَب {result.reviewed} — تراجع {result.regressed_files}"
        f" — تحسّن {result.improved_files} — ثابت {result.unchanged_files}"
        f" — جديد {result.new_files} — اختفت {result.gone_files}"
        f" — تُخُطّي {result.skipped_files}"
    )
    lines.append(
        f"الملاحظات: جديدة {result.new_findings_total} — محسومة {result.resolved_findings_total}"
        f" — أدنى درجة {result.min_score_baseline}←{result.min_score_current}/100"
    )
    lines.append(f"الحكم: {result.verdict_ar}")
    for n in result.notes:
        lines.append(f"ملاحظة: {n}")
    if result.history:
        lines.append(_LINE)
        lines.append("الاتجاه عبر التشغيلات (الأحدث في الأسفل):")
        for h in result.history:
            lines.append(
                f"  تشغيل {h.get('run_no')}: مراقَب {h.get('reviewed')}"
                f" — أدنى درجة {h.get('min_score')}"
                f" — ملاحظات {h.get('findings_total')}"
            )
    if result.per_file:
        lines.append(_LINE)
        for f in result.per_file:
            score = f"{f['score_baseline']}←{f['score_current']}"
            lines.append(
                f"[{FILE_STATUS_AR[f['status']]}] {f['path']} — درجة {score}"
                f" — ملاحظات جديدة {f['new_findings']}، محسومة {f['resolved_findings']}"
            )
    return "\n".join(lines)


def baseline_promise_text() -> str:
    """جدول ضمانات حارس الجودة — للتوثيق و«promise» في CLI."""
    lines = [
        f"zyko.baseline (المخطط: {SCHEMA}) — سقف سجل التشغيلات {HISTORY_CAP}",
        _LINE,
        "update : يسجّل حالة القرص الفعلية — يكتب ملفًا واحدًا فقط (.zyko/baseline.json)",
        "check  : قراءة فقط — يقارن ويعلن: تراجع/تحسّن/جديد/مفقود بأرقام دقيقة",
        "الحتمية: نفس الشجرة ⇒ نفس بايتات خط الأساس والتقرير — بلا طوابع زمنية",
        "الكشف  : درجة أقل أو ملاحظات جديدة ⇒ تراجع (خروج 1) — لا انهيار أبدًا",
        "الفشل المهيكل: خط أساس فاسد أو مسار غير صالح ⇒ رسالة عربية وخروج 2",
        "الخرج  : JSON / نص عربي / تقرير HTML عربي RTL — كلها حتمية البايتات",
    ]
    return "\n".join(lines)


def baseline_payload_summary(result: BaselineCheckResult) -> dict[str, Any]:
    """ملخص مضغوط لأداة MCP والبوابات."""
    return {
        "schema": SCHEMA,
        "ok": result.ok,
        "baseline_status": result.baseline_status,
        "failed_stage": result.failed_stage,
        "reviewed": result.reviewed,
        "regressed_files": result.regressed_files,
        "improved_files": result.improved_files,
        "unchanged_files": result.unchanged_files,
        "new_files": result.new_files,
        "gone_files": result.gone_files,
        "new_findings_total": result.new_findings_total,
        "resolved_findings_total": result.resolved_findings_total,
        "min_score_baseline": result.min_score_baseline,
        "min_score_current": result.min_score_current,
        "verdict_ar": result.verdict_ar,
        "status_ar": FILE_STATUS_AR,
    }


def _status_class(status: str) -> str:
    if status in _BAD_STATUSES:
        return "bad"
    if status in _GOOD_STATUSES:
        return "good"
    if status in _INFO_STATUSES:
        return "info"
    return ""


def baseline_check_to_html(result: BaselineCheckResult) -> str:
    """تقرير HTML عربي RTL حتمي — بلا طوابع زمنية ولا جافاسكربت."""
    e = html.escape
    if not result.ok:
        stage = STAGE_AR.get(result.failed_stage or "", result.failed_stage or "؟")
        title = "فشل فحص خط الأساس"
        body_str = (
            '<div class="verdict bad">فشل الفحص في مرحلة '
            f"{e(stage)}: {e(result.error_ar or '')}</div>"
        )
    elif result.baseline_status != "ok":
        title = "لا خط أساس بعد"
        body_str = (
            f'<div class="verdict">{e(VERDICT_MISSING)}</div>'
            "<p>شغّل أمر <code>update</code> لتسجيل الوضع الحالي كخط أساس أول،"
            " ثم تعمل المقارنات تلقائيًا بعد ذلك.</p>"
        )
    else:
        title = "تقرير حارس الجودة"
        body = []
        body.append(
            '<div class="cards">'
            f'<div class="card bad"><span class="num">{result.regressed_files}</span>تراجع</div>'
            f'<div class="card good"><span class="num">{result.improved_files}</span>تحسّن</div>'
            f'<div class="card"><span class="num">{result.unchanged_files}</span>ثابت</div>'
            f'<div class="card info"><span class="num">{result.new_files}</span>جديد</div>'
            f'<div class="card"><span class="num">{result.gone_files}</span>اختفت</div>'
            f'<div class="card"><span class="num">{result.skipped_files}</span>تُخُطّي</div>'
            "</div>"
        )
        body.append(
            '<div class="verdict">'
            f"الملاحظات: جديدة {result.new_findings_total} — محسومة {result.resolved_findings_total}"
            f" &middot; أدنى درجة: {result.min_score_baseline} ← {result.min_score_current} من 100"
            f" &middot; رقم تشغيل خط الأساس: {result.baseline_run_no}"
            "</div>"
        )
        if result.history:
            rows = "".join(
                "<tr>"
                f"<td class='num'>{e(str(h.get('run_no')))}</td>"
                f"<td class='num'>{e(str(h.get('reviewed')))}</td>"
                f"<td class='num'>{e(str(h.get('min_score')))}</td>"
                f"<td class='num'>{e(str(h.get('findings_total')))}</td>"
                "</tr>"
                for h in reversed(result.history)
            )
            body.append(
                "<h2>الاتجاه عبر التشغيلات</h2>"
                "<table><tr><th class='num'>التشغيل</th><th class='num'>ملفات مراقَبة</th>"
                "<th class='num'>أدنى درجة</th><th class='num'>ملاحظات</th></tr>"
                f"{rows}</table>"
            )
        if result.per_file:
            rows = []
            for f in result.per_file:
                score = (
                    f"{f['score_baseline']} ← {f['score_current']}"
                    if f["score_current"] is not None
                    else f"{f['score_baseline']} ← —"
                )
                rows.append(
                    "<tr>"
                    f"<td><code>{e(f['path'])}</code></td>"
                    f"<td class='st-{e(f['status'])}'>{e(FILE_STATUS_AR.get(f['status'], f['status']))}</td>"
                    f"<td class='num'>{e(score)}</td>"
                    f"<td class='num {('bad' if f['new_findings'] else '')}'>{f['new_findings']}</td>"
                    f"<td class='num {('good' if f['resolved_findings'] else '')}'>{f['resolved_findings']}</td>"
                    "</tr>"
                )
            body.append(
                "<h2>الملفات ملفًا ملفًا</h2>"
                "<table><tr><th>المسار</th><th>الحالة</th><th class='num'>الدرجة</th>"
                "<th class='num'>ملاحظات جديدة</th><th class='num'>محسومة</th></tr>"
                f"{''.join(rows)}</table>"
            )
        verdict_cls = "bad" if result.regressed_files else "good"
        body.append(f'<div class="verdict {verdict_cls}">{e(result.verdict_ar)}</div>')
        body_str = "".join(body)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="ar" dir="rtl">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{e(title)} — zyko.baseline</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="wrap">\n'
        f"<h1>{e(title)}</h1>\n"
        f'<p class="sub">المخطط <code>{e(SCHEMA)}</code>'
        f" &middot; المجلد <code>{e(result.src)}</code></p>\n"
        f"{body_str}\n"
        "<footer>تقرير حتمي البايتات من zyko.baseline — بلا طوابع زمنية ولا جافاسكربت</footer>\n"
        "</div>\n"
        "</body>\n"
        "</html>\n"
    )


__all__ = [
    "baseline_check_summary_line",
    "baseline_check_to_html",
    "baseline_check_to_json",
    "baseline_check_to_text",
    "baseline_payload_summary",
    "baseline_promise_text",
    "baseline_update_summary_line",
    "baseline_update_to_json",
    "baseline_update_to_text",
]
