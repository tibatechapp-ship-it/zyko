"""zyko.factory.report_html — لوحة المصنع: تقرير HTML عربي RTL مكتفٍ ذاتيًا.

المرحلة 7: المخرجات النصية (text/json) بقيت كما هي حتمية بايتيًا؛ هذه
الوحدة تضيف **مخرجًا بشريًا ثالثًا**: ملف HTML واحد بلا أي أصل خارجي —
لا شبكة، لا خطوط منزّلة، ولا جافاسكربت إطلاقًا — يُفتح في أي متصفح
وعلى الهاتف، ويعرض المصائر والدرجات وكل ملاحظة بـ ``suggestion_ar``
كما وردت حرفيًا من المراجع والمُصلِح.

العقود:
- **حتمية بايتية**: نفس النتيجة ⇒ نفس البايتات تمامًا (بلا أوقات ولا
  أختام زمنية؛ الزمن يبقى حكرًا على --include-timing في المخرجات النصية).
- **تهريب شامل**: كل نص قادم من القرص أو من الوصف يمر على
  ``html.escape`` قبل أن يلمس الصفحة — مسار ملف أو وصف عدائي لا يولّد
  أي HTML غير مقصود.
- **بلا جافاسكربت**: الصفحة ثابتة تمامًا (``<script`` غير موجود في
  المخرجات أصلًا) — ما يُرى هو ما حفِظ.

نقاط الدخول:
- ``fixer_results_html(results)``   ← نتائج zyko.fixer
- ``pipeline_result_html(result)``  ← نتيجة zyko.pipeline
- ``workspace_result_html(result)`` ← نتيجة zyko.workspace
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from zyko.version import __version__


def write_html_panel(path: str | Path, content: str) -> None:
    """اكتب اللوحة إلى قرص المستخدم — فشل القرص ⇒ ZykoError لا انهيار.

    مسار في مجلد غير موجود أو قرص ممتلئ أو أذونات ناقصة ⇒ خطأ عربي
    مهيكل يلتقطه CLI ويطبع بلا أثر تتبع (نفس عقد الفشل في بقية المصنع).
    """
    from zyko.exceptions import ZykoError

    try:
        Path(path).write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ZykoError(f"تعذّر كتابة لوحة HTML إلى «{path}»: {exc}") from exc


# حالة الملف في workspace (مخطط zyko.workspace/1) — تُقرأ من مفاتيح per_file.
_FILE_STATUS_SKIPPED = "skipped"

# ألوان الخطورة — قيم المراجع ثابتة في المخطط (critical..info).
_SEVERITY_COLOR: dict[str, str] = {
    "critical": "#dc2626",
    "high": "#ea580c",
    "medium": "#d97706",
    "low": "#2563eb",
    "info": "#64748b",
}

_CSS = """\
:root{color-scheme:light}
*{box-sizing:border-box}
body{font-family:"Noto Naskh Arabic","Noto Sans Arabic",Tahoma,Arial,sans-serif;
margin:0;background:#f6f7f9;color:#111827;line-height:1.7}
.wrap{max-width:960px;margin:0 auto;padding:24px 16px 48px}
header.card,section.card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;
padding:20px;margin-bottom:16px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
h1{font-size:1.35rem;margin:0 0 4px}
h2{font-size:1.05rem;margin:0 0 12px;color:#1f2937}
.sub{color:#6b7280;font-size:.9rem;margin:0}
.badge{display:inline-block;border-radius:999px;padding:4px 14px;font-weight:700;font-size:.9rem;margin-top:10px}
.ok{background:#dcfce7;color:#166534}
.warn{background:#fef3c7;color:#92400e}
.fail{background:#fee2e2;color:#991b1b}
.counters{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}
.counter{flex:1 1 120px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;
padding:10px 12px;text-align:center}
.counter b{display:block;font-size:1.3rem}
.counter span{color:#6b7280;font-size:.8rem}
.scorebar{height:12px;background:#e5e7eb;border-radius:999px;overflow:hidden;margin:8px 0 2px;
display:block;min-width:120px}
.scorebar i{display:block;height:100%;background:#22c55e}
.scoreline{font-size:.95rem;margin:10px 0 0}
.arrow{color:#6b7280}
table{width:100%;border-collapse:collapse;font-size:.88rem;margin-top:8px}
th,td{border:1px solid #e5e7eb;padding:7px 9px;text-align:right;vertical-align:top}
th{background:#f3f4f6}
tr:nth-child(even) td{background:#fafafa}
.sev{display:inline-block;border-radius:6px;color:#fff;padding:1px 8px;font-size:.78rem;white-space:nowrap}
.st{white-space:nowrap}
code,.sug{background:#f3f4f6;border-radius:6px;padding:1px 6px;font-size:.85rem;
font-family:inherit;word-break:break-word}
.path{word-break:break-all;font-size:.85rem;color:#374151}
.sug{display:block;margin-top:3px;color:#065f46;background:#ecfdf5}
.note{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:10px 12px;margin-top:10px}
.failbox{background:#fef2f2;border:1px solid #fecaca;border-radius:10px;padding:12px 14px;margin-top:10px}
ul.plain{margin:6px 0 0;padding-inline-start:20px}
footer{color:#9ca3af;font-size:.8rem;text-align:center;margin-top:8px}
"""


def _esc(value: Any) -> str:
    """تهريب شامل — آخر بوابة قبل الصفحة (مسارات/أوصاف عدائية ⇒ نص فقط)."""
    return html.escape(str(value), quote=True)


def _badge(verdict_ar: str, ok: bool) -> str:
    cls = "ok" if ok else "fail"
    return f'<span class="badge {cls}">{_esc(verdict_ar)}</span>'


def _score_bar(score_before: int | None, score_after: int | None) -> str:
    """شريطا درجة قبل/بعد — لا شيء عند الغياب (لا مراجعة/فشل مهيكل)."""
    if score_after is None and score_before is None:
        return ""
    parts = ["<div class='scoreline'>الدرجة: "]
    if score_before is not None:
        pct = max(0, min(100, int(score_before)))
        parts.append(
            f"<span class='scorebar'><i style='width:{pct}%'></i></span>"
            f" <b>{int(score_before)}</b>/100"
        )
    if score_after is not None:
        parts.append(" <span class='arrow'>←</span> ")
        pct = max(0, min(100, int(score_after)))
        parts.append(
            f"<span class='scorebar'><i style='width:{pct}%'></i></span>"
            f" <b>{int(score_after)}</b>/100"
        )
    parts.append("</div>")
    return "".join(parts)


def _counters_html(counters: list[tuple[str, int | str]]) -> str:
    cells = "".join(
        f"<div class='counter'><b>{_esc(v)}</b><span>{_esc(k)}</span></div>" for k, v in counters
    )
    return f"<div class='counters'>{cells}</div>"


def _outcomes_html(outcomes: list[dict[str, Any]]) -> str:
    """جدول الملاحظات — كل صف يعرض suggestion_ar كما وردت حرفيًا."""
    if not outcomes:
        return "<p class='sub'>لا ملاحظات في هذا الملف — نظيف.</p>"
    rows: list[str] = []
    for o in outcomes:
        sev = str(o.get("severity", "info"))
        sev_ar = o.get("severity_ar") or sev
        color = _SEVERITY_COLOR.get(sev, "#64748b")
        status_ar = o.get("status_ar") or o.get("status") or ""
        loc = f"سطر {o.get('line', '؟')}، عمود {o.get('col', '؟')}"
        action = ""
        if o.get("status") != "fixed" and o.get("action_ar"):
            action = f"<span class='sug'>الإجراء: {_esc(o['action_ar'])}</span>"
        rows.append(
            "<tr>"
            f"<td>{_esc(loc)}</td>"
            f"<td><code>{_esc(o.get('rule_id', '؟'))}</code></td>"
            f"<td><span class='sev' style='background:{color}'>{_esc(sev_ar)}</span></td>"
            f"<td class='st'>{_esc(status_ar)}</td>"
            f"<td>{_esc(o.get('message_ar', ''))}"
            f"<span class='sug'>الإصلاح: {_esc(o.get('suggestion_ar', ''))}</span>"
            f"{action}</td>"
            "</tr>"
        )
    body = "".join(rows)
    return (
        "<table><thead><tr><th>الموقع</th><th>القاعدة</th><th>الخطورة</th>"
        "<th>الحالة</th><th>الرسالة والإصلاح</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def _files_html(files: list[dict[str, Any]], written: list[str] | None) -> str:
    if not files:
        return ""
    cards: list[str] = []
    written_set = set(written or [])
    for f in files:
        skipped = f.get("status") == _FILE_STATUS_SKIPPED
        head_bits = [
            f"<b class='path'>{_esc(f.get('path', '؟'))}</b>",
            f.get("reason_ar") and f"<span class='sub'> — {_esc(f['reason_ar'])}</span>",
        ]
        if not skipped:
            arrow = "→" if f.get("changed") else "="
            head_bits.append(
                f"<span class='sub'> — درجة {f.get('score_before', '؟')} {arrow} "
                f"{f.get('score_after', '؟')} — {_esc(f.get('verdict_after_ar', ''))}</span>"
            )
            if f.get("path") in written_set:
                head_bits.append(
                    " <span class='badge ok' style='margin:0;padding:1px 8px'>كُتب</span>"
                )
        head = "".join(b for b in head_bits if b)
        if skipped:
            cards.append(f"<section class='card'><h2>ملف مُتخطّى</h2><p>{head}</p></section>")
            continue
        parse_err = f.get("parse_error")
        err_html = (
            f"<div class='note'>تعذّر تحليل الملف: {_esc(parse_err)}</div>" if parse_err else ""
        )
        cards.append(
            "<section class='card'>"
            f"<h2>{head}</h2>{err_html}{_outcomes_html(list(f.get('outcomes') or []))}"
            "</section>"
        )
    return "".join(cards)


def _render(view: dict[str, Any]) -> str:
    """الصفحة النهائية من نموذج العرض — حتمية بايتيًا وبلا أي أصل خارجي."""
    counters_html = _counters_html(view["counters"])
    notes_html = ""
    if view.get("notes"):
        items = "".join(f"<li>{_esc(n)}</li>" for n in view["notes"])
        notes_html = (
            "<section class='card'><h2>ملاحظات التشغيل</h2>"
            f"<ul class='plain'>{items}</ul></section>"
        )
    fail_html = ""
    if not view.get("ok", True):
        problems = ""
        if view.get("problems"):
            items = "".join(f"<li>{_esc(p)}</li>" for p in view["problems"])
            problems = f"<ul class='plain'>{items}</ul>"
        fail_html = (
            "<div class='failbox'>"
            f"<b>فشل مهيكل في مرحلة: {_esc(view.get('failed_stage_ar') or '؟')}</b>"
            f"<div>{_esc(view.get('error_ar') or '')}</div>{problems}</div>"
        )
    written_html = ""
    if view.get("written"):
        items = "".join(f"<li class='path'>{_esc(w)}</li>" for w in view["written"])
        written_html = (
            "<section class='card'><h2>كُتب على القرص (متحقق من صياغته)</h2>"
            f"<ul class='plain'>{items}</ul></section>"
        )
    files_html = _files_html(view["files"], view.get("written"))
    files_section = (
        f"<section class='card'><h2>{_esc(view['files_title_ar'])}</h2>{files_html}</section>"
        if files_html
        else ""
    )
    meta_rows = "".join(f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>" for k, v in view["meta"])
    meta_table = f"<table><tbody>{meta_rows}</tbody></table>" if meta_rows else ""
    return (
        "<!doctype html>\n"
        '<html lang="ar" dir="rtl">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_esc(view['title_ar'])} — ZYKO v{__version__}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n"
        "<body><div class='wrap'>\n"
        "<header class='card'>\n"
        f"<h1>{_esc(view['title_ar'])}</h1>\n"
        f"<p class='sub'>المصنع ZYKO v{__version__} — توليد ← مراجعة ← إصلاح، بلا نموذج وبلا شبكة</p>\n"
        f"{_badge(view['verdict_ar'], bool(view['ok']))}\n"
        f"{_score_bar(view.get('score_before'), view.get('score_after'))}\n"
        f"{counters_html}\n"
        "</header>\n"
        f"{fail_html}\n"
        f"<section class='card'><h2>بطاقة التشغيل</h2>{meta_table}</section>\n"
        f"{files_section}\n"
        f"{written_html}\n"
        f"{notes_html}\n"
        "<footer>تقرير حتمي البايتات: نفس النتيجة ⇒ نفس الملف حرفيًا — بلا جافاسكربت وبلا أصول خارجية</footer>\n"
        "</div></body>\n</html>\n"
    )


# --------------------------------------------------------------------- fixer
def fixer_results_html(
    results: list[Any],
    *,
    title_ar: str = "تقرير المُصلِح الحتمي",
) -> str:
    """لوحة نتائج zyko.fixer — قائمة FixResult (ملف واحد أو مجلد)."""
    files: list[dict[str, Any]] = []
    fixed = manual = opened = changed = 0
    for r in results:
        outcomes = [o.to_dict() for o in r.outcomes]
        fixed += sum(1 for o in outcomes if o.get("status") == "fixed")
        manual += sum(1 for o in outcomes if o.get("status") == "manual")
        opened += sum(1 for o in outcomes if o.get("status") == "open")
        changed += 1 if r.changed else 0
        files.append(
            {
                "path": r.path,
                "changed": r.changed,
                "score_before": r.score_before,
                "score_after": r.score_after,
                "verdict_after_ar": r.verdict_after_ar,
                "parse_error": r.parse_error,
                "outcomes": outcomes,
            }
        )
    score_before = min((r.score_before for r in results), default=None)
    score_after = min((r.score_after for r in results), default=None)
    verdict = (
        results[0].verdict_after_ar if len(results) == 1 else "اكتمل الفحص — انظر تفاصيل الملفات"
    )
    ok = not any(r.parse_error for r in results)
    view: dict[str, Any] = {
        "title_ar": title_ar,
        "schema": "zyko.fixer/1",
        "ok": ok,
        "verdict_ar": verdict,
        "score_before": score_before,
        "score_after": score_after,
        "counters": [
            ("ملف", len(results)),
            ("عُدّل", changed),
            ("أُصلح آليًا", fixed),
            ("يدوي", manual),
            ("يبقى مفتوحًا", opened),
        ],
        "meta": [("الوحدة", "zyko.fixer"), ("الملفات", len(results))],
        "files": files,
        "files_title_ar": "الملفات والملاحظات",
        "written": None,
        "notes": [],
    }
    return _render(view)


# ------------------------------------------------------------------ pipeline
def pipeline_result_html(result: Any, *, title_ar: str = "تقرير الحلقة الكاملة") -> str:
    """لوحة نتيجة zyko.pipeline — توليد ← مراجعة ← إصلاح في أمر واحد."""
    from zyko.pipeline.engine import STAGE_AR

    plan = result.plan or {}
    counters: list[tuple[str, int | str]] = [
        ("ملفات وُلِّدت", len(result.files)),
        ("رُوجعت", len(result.py_files)),
        ("عُدّل", result.changed_files),
        ("أُصلح آليًا", result.fixed_total),
        ("يدوي", result.manual_total),
        ("يبقى", result.open_total),
    ]
    view: dict[str, Any] = {
        "title_ar": title_ar,
        "schema": "zyko.pipeline/1",
        "ok": result.ok,
        "failed_stage_ar": (
            STAGE_AR.get(result.failed_stage or "", result.failed_stage or "؟")
            if not result.ok
            else None
        ),
        "error_ar": result.error_ar,
        "problems": list(result.problems),
        "verdict_ar": result.verdict_ar if result.ok else "فشل مهيكل",
        "score_before": result.min_score_before if result.ok else None,
        "score_after": result.min_score_after if result.ok else None,
        "counters": counters,
        "meta": [
            ("الوحدة", "zyko.pipeline"),
            ("الوصف", result.description[:200]),
            ("المخطط", f"{plan.get('name', '؟')} ({plan.get('template', '؟')})"),
            ("الجولات", f"{result.rounds_ran}/{result.rounds_requested}"),
        ],
        "files": list(result.per_file),
        "files_title_ar": "الملفات المولّدة والملاحظات",
        "written": list(result.written),
        "notes": list(result.notes),
    }
    return _render(view)


# ----------------------------------------------------------------- workspace
def workspace_result_html(result: Any, *, title_ar: str = "تقرير المحرك على مجلد قائم") -> str:
    """لوحة نتيجة zyko.workspace — مراجعة ← إصلاح لأي مجلد بايثون قائم."""
    from zyko.workspace.engine import STAGE_AR

    counters: list[tuple[str, int | str]] = [
        ("ملفات بايثون", result.files_total),
        ("رُوجعت", result.reviewed),
        ("تُخُطّي", result.skipped),
        ("عُدّل", result.changed_files),
        ("أُصلح آليًا", result.fixed_total),
        ("يدوي", result.manual_total),
        ("يبقى", result.open_total),
    ]
    view: dict[str, Any] = {
        "title_ar": title_ar,
        "schema": "zyko.workspace/1",
        "ok": result.ok,
        "failed_stage_ar": (
            STAGE_AR.get(result.failed_stage or "", result.failed_stage or "؟")
            if not result.ok
            else None
        ),
        "error_ar": result.error_ar,
        "problems": list(result.problems),
        "verdict_ar": result.verdict_ar if result.ok else "فشل مهيكل",
        "score_before": result.min_score_before if result.ok else None,
        "score_after": result.min_score_after if result.ok else None,
        "counters": counters,
        "meta": [
            ("الوحدة", "zyko.workspace"),
            ("المجلد", result.src),
            ("الجولات", f"{result.rounds_ran}/{result.rounds_requested}"),
        ],
        "files": list(result.per_file),
        "files_title_ar": "الملفات والملاحظات",
        "written": list(result.written),
        "notes": list(result.notes),
    }
    return _render(view)


__all__ = [
    "fixer_results_html",
    "pipeline_result_html",
    "workspace_result_html",
    "write_html_panel",
]
