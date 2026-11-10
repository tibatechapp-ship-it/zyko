"""Deterministic HTML + Markdown dashboard for ZYKO factory gates.

Design principles:
  * Status-first: overall verdict at the top.
  * Data is the interface: dense tables > decorative charts.
  * Quiet confidence: thin borders, muted colors.
  * Byte-deterministic: same input → same sha256, always.
  * Dark mode: respects prefers-color-scheme.
  * Accessible: anchor links, viewport meta, semantic HTML, table labels.
"""

from __future__ import annotations

import hashlib
import html
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GateResult:
    """One gate's outcome. Deterministic by construction."""

    name: str
    passed: bool
    reason_ar: str = ""
    duration_ms: int = 0


@dataclass(frozen=True)
class FileScore:
    """One file's score delta. Either side may be None for partial data."""

    path: str
    score_before: int | None = None
    score_after: int | None = None


@dataclass(frozen=True)
class DashboardInput:
    """Complete dashboard input. Everything downstream depends only on this."""

    project_name: str
    version: str
    gates: tuple[GateResult, ...]
    files: tuple[FileScore, ...] = ()


# ── Public builders ──────────────────────────────────────────────


def build_from_gates(
    project_name: str,
    version: str,
    gates_data: list[dict[str, Any]],
    files_data: list[dict[str, Any]] | None = None,
) -> str:
    """Render HTML from plain dicts (JSON-friendly)."""
    return build_dashboard(_coerce(project_name, version, gates_data, files_data))


def build_markdown_from_gates(
    project_name: str,
    version: str,
    gates_data: list[dict[str, Any]],
    files_data: list[dict[str, Any]] | None = None,
) -> str:
    """Render Markdown from plain dicts (JSON-friendly)."""
    return build_markdown(_coerce(project_name, version, gates_data, files_data))


def build_dashboard(data: DashboardInput) -> str:
    """Render the dashboard as a deterministic HTML string."""
    gates = sorted(data.gates, key=lambda g: g.name)
    files = sorted(data.files, key=lambda f: f.path)

    overall_class, overall_text = _overall(gates)
    gates_html = "\n".join(_gate_row(g) for g in gates) or _empty_row(4, "لا توجد بوابات")
    files_html = "\n".join(_file_row(f) for f in files) or _empty_row(3, "لا توجد ملفات مسجلة")

    body = _body(overall_class, overall_text, gates_html, files_html)
    fingerprint = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return _page(data.project_name, data.version, body, fingerprint)


def build_markdown(data: DashboardInput) -> str:
    """Render the dashboard as a deterministic Markdown string."""
    gates = sorted(data.gates, key=lambda g: g.name)
    files = sorted(data.files, key=lambda f: f.path)

    _, overall_text = _overall(gates)
    lines: list[str] = [
        f"# لوحة تحكم {data.project_name}",
        "",
        f"**الإصدار:** {data.version}",
        "",
        "## الحالة العامة",
        "",
        overall_text,
        "",
        "## البوابات",
        "",
        "| الحالة | البوابة | السبب | الزمن |",
        "|:---|:---|:---|:---|",
    ]
    for g in gates:
        icon = "✅" if g.passed else "❌"
        reason = _md_cell(g.reason_ar) or "—"
        lines.append(f"| {icon} | {_md_cell(g.name)} | {reason} | {_duration(g)} |")

    if files:
        lines += [
            "",
            "## درجات الملفات",
            "",
            "| الملف | قبل ← بعد | الفرق |",
            "|:---|:---|:---|",
        ]
        for f in files:
            lines.append(f"| {_md_cell(f.path)} | {_scores(f)} | {_delta(f)} |")

    body_md = "\n".join(lines)
    fingerprint = hashlib.sha256(body_md.encode("utf-8")).hexdigest()
    lines += ["", "---", f"البصمة: `{fingerprint}`"]
    return "\n".join(lines)


# ── Internals ────────────────────────────────────────────────────


def _coerce(
    project: str,
    version: str,
    gates_data: list[dict[str, Any]],
    files_data: list[dict[str, Any]] | None,
) -> DashboardInput:
    gates = tuple(
        GateResult(
            name=g["name"],
            passed=bool(g["passed"]),
            reason_ar=g.get("reason_ar", ""),
            duration_ms=int(g.get("duration_ms", 0)),
        )
        for g in gates_data
    )
    files = tuple(
        FileScore(
            path=f["path"],
            score_before=f.get("score_before"),
            score_after=f.get("score_after"),
        )
        for f in (files_data or [])
    )
    return DashboardInput(project, version, gates, files)


def _overall(gates: tuple[GateResult, ...]) -> tuple[str, str]:
    total = len(gates)
    if total == 0:
        return "warn", "لا توجد بوابات مسجلة"
    passed = sum(1 for g in gates if g.passed)
    if passed == total:
        return "ok", f"✅ {passed}/{total} بوابة ناجحة"
    return "fail", f"❌ {passed}/{total} ناجحة — {total - passed} فاشلة"


def _gate_row(g: GateResult) -> str:
    icon = "✅" if g.passed else "❌"
    cls = "ok" if g.passed else "fail"
    name = html.escape(g.name)
    reason = html.escape(g.reason_ar) if g.reason_ar else "—"
    return (
        f'<tr class="{cls}">'
        f"<td>{icon}</td><td>{name}</td><td>{reason}</td><td>{_duration(g)}</td>"
        f"</tr>"
    )


def _file_row(f: FileScore) -> str:
    cls = ""
    if f.score_before is not None and f.score_after is not None and f.score_after != f.score_before:
        cls = "ok" if f.score_after > f.score_before else "fail"
    return (
        f'<tr class="{cls}">'
        f"<td>{html.escape(f.path)}</td>"
        f"<td>{_scores(f)}</td>"
        f"<td>{_delta(f)}</td>"
        f"</tr>"
    )


def _scores(f: FileScore) -> str:
    before = f.score_before if f.score_before is not None else "—"
    after = f.score_after if f.score_after is not None else "—"
    return f"{before} → {after}"


def _delta(f: FileScore) -> str:
    if f.score_before is None or f.score_after is None:
        return "—"
    d = f.score_after - f.score_before
    if d > 0:
        return f"+{d}"
    return str(d)


def _duration(g: GateResult) -> str:
    return f"{g.duration_ms} ms" if g.duration_ms > 0 else "—"


def _md_cell(value: str) -> str:
    """Keep Markdown tables intact: no raw pipes, no embedded newlines."""
    return value.replace("|", "\\|").replace("\n", " ")


def _empty_row(cols: int, msg: str) -> str:
    return f'<tr><td colspan="{cols}">{html.escape(msg)}</td></tr>'


def _body(overall_class: str, overall_text: str, gates: str, files: str) -> str:
    return (
        f'<div class="status {overall_class}">{overall_text}</div>\n'
        '<nav class="toc">\n'
        '  <a href="#gates">البوابات</a> · <a href="#files">درجات الملفات</a>\n'
        "</nav>\n"
        '<section id="gates">\n  <h2>البوابات</h2>\n'
        '  <table aria-label="نتائج البوابات">\n'
        "    <thead><tr><th>الحالة</th><th>البوابة</th><th>السبب</th>"
        "<th>الزمن</th></tr></thead>\n"
        f"    <tbody>{gates}</tbody>\n  </table>\n</section>\n"
        '<section id="files">\n  <h2>درجات الملفات</h2>\n'
        '  <table aria-label="درجات الملفات">\n'
        "    <thead><tr><th>الملف</th><th>قبل ← بعد</th><th>الفرق</th></tr></thead>\n"
        f"    <tbody>{files}</tbody>\n  </table>\n</section>"
    )


def _page(project: str, version: str, body: str, fingerprint: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>لوحة تحكم ZYKO — {html.escape(project)}</title>
<style>
:root {{
  --bg: #fafafa; --fg: #1a1a1a; --muted: #6b6b6b; --border: #e0e0e0;
  --ok: #16a34a; --ok-bg: #f0fdf4; --fail: #dc2626; --fail-bg: #fef2f2;
  --warn: #ca8a04; --warn-bg: #fefce8;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #0a0a0a; --fg: #fafafa; --muted: #a0a0a0; --border: #333;
    --ok: #22c55e; --ok-bg: #052e16; --fail: #ef4444; --fail-bg: #450a0a;
    --warn: #eab308; --warn-bg: #422006;
  }}
  table {{ background: #1a1a1a; }}
  thead {{ background: #111; }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 24px; max-width: 1100px; margin-inline: auto;
  background: var(--bg); color: var(--fg);
  font-family: -apple-system, "Segoe UI", "Tahoma", sans-serif;
  font-size: 14px; line-height: 1.6;
}}
header {{ margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }}
header h1 {{ margin: 0; font-size: 20px; font-weight: 600; }}
header .meta {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
.status {{
  padding: 20px 24px; border-radius: 8px; font-size: 18px; font-weight: 600;
  margin-bottom: 16px; border: 1px solid;
}}
.status.ok {{ background: var(--ok-bg); color: var(--ok); border-color: var(--ok); }}
.status.fail {{ background: var(--fail-bg); color: var(--fail); border-color: var(--fail); }}
.status.warn {{ background: var(--warn-bg); color: var(--warn); border-color: var(--warn); }}
.toc {{ margin-bottom: 24px; font-size: 13px; }}
.toc a {{ color: var(--muted); text-decoration: none; margin-left: 8px; }}
.toc a:hover {{ color: var(--fg); }}
section {{ margin-bottom: 24px; }}
h2 {{
  font-size: 12px; font-weight: 600; color: var(--muted);
  margin: 0 0 8px; text-transform: uppercase; letter-spacing: 0.05em;
}}
table {{
  width: 100%; border-collapse: collapse; background: white;
  border: 1px solid var(--border); border-radius: 6px; overflow: hidden;
}}
thead {{ background: var(--bg); }}
th, td {{ padding: 8px 12px; text-align: right; border-bottom: 1px solid var(--border); }}
th {{ font-weight: 600; color: var(--muted); font-size: 12px; }}
tbody tr:last-child td {{ border-bottom: none; }}
tr.ok td:first-child {{ color: var(--ok); }}
tr.fail td:first-child {{ color: var(--fail); }}
footer {{
  margin-top: 32px; padding-top: 16px; border-top: 1px solid var(--border);
  color: var(--muted); font-size: 11px;
  font-family: ui-monospace, monospace; word-break: break-all;
}}
</style>
</head>
<body>
<header>
  <h1>{html.escape(project)}</h1>
  <div class="meta">الإصدار {html.escape(version)}</div>
</header>
{body}
<footer>البصمة: {fingerprint}</footer>
</body>
</html>
"""
