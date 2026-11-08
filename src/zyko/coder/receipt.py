"""zyko.coder.receipt — وصل التوليد (D19).

Every generated project carries ``RECEIPT.md``: the original Arabic
description, the validated plan, every file with its reason, and the
model log (which model filled the plan / wrote custom content).
Deterministic: same plan + same tree = byte-identical receipt — the
sha256 manifest is computed over sorted relative paths, no timestamps.
Verifiable offline with ``sha256sum``.
"""

from __future__ import annotations

import hashlib

from .plan import ProjectPlan
from .templates import GenFile


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def receipt_md(
    plan: ProjectPlan,
    tree: dict[str, GenFile],
    model_log: list[dict[str, str]] | None = None,
) -> GenFile:
    """يبني محتوى RECEIPT.md حتميًا من المخطط وشجرة الملفات."""
    lines: list[str] = [
        "# RECEIPT — وصل التوليد",
        "",
        "هذا الملف يوثّق كيف وُلّد هذا المشروع. قابل للتحقق دون اتصال:",
        "نفس المخطط يعطي نفس الملفات ونفس بصمات sha256 دائمًا.",
        "",
        "## الوصف العربي الأصلي",
        "",
        f"> {plan.description.strip()}",
        "",
        "## المخطط المتحقق",
        "",
        "```json",
        json_dumps(plan.to_dict()),
        "```",
        "",
        "## الملفات وأسبابها",
        "",
        "| الملف | السبب | sha256 (16) |",
        "|---|---|---|",
    ]
    for path in sorted(tree):
        f = tree[path]
        lines.append(f"| `{path}` | {f.reason} | `{_hash(f.content)}` |")

    lines += [
        "",
        "## سجل النماذج",
        "",
    ]
    if model_log:
        for step in model_log:
            role = step.get("role", "?")
            model = step.get("model", "?")
            note = step.get("note", "")
            lines.append(f"- **{role}** عبر `{model}` — {note}")
    else:
        lines.append(
            "- تعبئة حتمية بلا نموذج (heuristics أو يدويًا) — لا اتصال خارجي في هذا التوليد."
        )

    lines += [
        "",
        "## التحقق",
        "",
        "أعد توليد المشروع من نفس المخطط وقارن البصمات، أو احسبها مباشرة:",
        "",
        "```bash",
        "sha256sum <الملف>",
        "```",
        "",
    ]
    return GenFile(
        "RECEIPT.md",
        "\n".join(lines),
        "وصل التوليد: الوصف والمخطط وأسباب الملفات وبصماتها — قابل للتحقق دون اتصال",
    )


def json_dumps(obj: dict) -> str:
    """JSON مضغوط حتميًا (مفاتيح مرتبة، بدون محارف يونيكود مهرّبة)."""
    import json

    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)


__all__ = ["receipt_md"]
