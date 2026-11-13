"""deploy.py — سجل أهداف النشر وجاهزيتها (الموجة 23).

zyko وُلد ليعمل فوق كل منصة برمجة — GitHub أولاً، ثم Hugging Face وVercel وLobe.
هذه الوحدة هي نقطة التلاقي الواحدة: كل هدف نشر معرَّف بيانياً (أصوله المطلوبة،
متغيرات بيئته، دليله)، وجاهزيته تُقاس من الشجرة الفعلية لا تُدَّعى — نفس منهج
«بلا عدّاد = بلا ادعاء» الذي يقيس البنش.

الاستعمال:
    python -c "from zyko.platform.deploy import deployment_report; print(deployment_report())"
    zyko doctor            # قسم «أهداف النشر» يقرأ من هذا السجل
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_MARKER = "pyproject.toml"


@dataclass(frozen=True)
class DeployTarget:
    """هدف نشر واحد — أصوله المطلوبة معرَّفة لا مستنتَجة."""

    key: str
    title: str
    summary_ar: str
    required_assets: tuple[str, ...]
    env_vars: tuple[str, ...] = ()
    guide_anchor: str = ""

    @property
    def guide(self) -> str:
        return f"docs/PLATFORMS.md{self.guide_anchor}"


DEPLOY_TARGETS: tuple[DeployTarget, ...] = (
    DeployTarget(
        key="github",
        title="GitHub",
        summary_ar="CI متعدد المنصات + نشر PyPI عبر Trusted Publisher + صفحة مشروع + عقدة مجتمع كاملة",
        required_assets=(
            ".github/workflows/ci.yml",
            ".github/workflows/publish.yml",
            ".github/workflows/pages.yml",
            "Dockerfile",
            "CITATION.cff",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "CODE_OF_CONDUCT.md",
        ),
        guide_anchor="#github",
    ),
    DeployTarget(
        key="huggingface",
        title="Hugging Face Spaces",
        summary_ar="Space بحاوية Docker يشغّل بوابة zyko المتوافقة مع OpenAI — وضع العرض يعمل بلا مفاتيح",
        required_assets=(
            "deploy/huggingface/Dockerfile",
            "deploy/huggingface/README.md",
        ),
        env_vars=("ZYKO_OPENAI_API_KEY", "ZYKO_ANTHROPIC_API_KEY", "ZYKO_GATEWAY_API_KEY"),
        guide_anchor="#hugging-face-spaces",
    ),
    DeployTarget(
        key="vercel",
        title="Vercel",
        summary_ar="دالة Serverless بواجهة متوافقة مع OpenAI فوق موجّه zyko — اعتماديتان إلزاميتان فقط تصلحان للبارد",
        required_assets=(
            "deploy/vercel/api/zyko.py",
            "deploy/vercel/vercel.json",
            "deploy/vercel/requirements.txt",
            "deploy/vercel/README.md",
        ),
        env_vars=("ZYKO_OPENAI_API_KEY", "ZYKO_ANTHROPIC_API_KEY", "ZYKO_GOOGLE_API_KEY"),
        guide_anchor="#vercel",
    ),
    DeployTarget(
        key="lobe",
        title="Lobe (LobeChat)",
        summary_ar="ربط LobeChat ببوابة zyko كمزوّد متوافق مع OpenAI + بيان عرض الإضافة",
        required_assets=(
            "deploy/lobe/manifest.json",
            "deploy/lobe/README.md",
        ),
        guide_anchor="#lobechat",
    ),
)


def repo_root(start: Path | None = None) -> Path | None:
    """جذر المستودع — يمشي للأعلى من نقطة البداية حتى يجد العلامة."""
    current = (start or Path(__file__)).resolve()
    for candidate in (current, *current.parents):
        if (candidate / REPO_MARKER).is_file() and (candidate / "src" / "zyko").is_dir():
            return candidate
    return None


def target_readiness(target: DeployTarget, root: Path | None = None) -> dict[str, object]:
    """جاهزية هدف واحد — الأصول المفقودة معلنة، لا خفاء."""
    missing: list[str] = []
    if root is not None:
        missing = [a for a in target.required_assets if not (root / a).is_file()]
    return {
        "key": target.key,
        "title": target.title,
        "summary_ar": target.summary_ar,
        "required_assets": list(target.required_assets),
        "missing_assets": missing,
        "env_vars": list(target.env_vars),
        "guide": target.guide,
        "ready": bool(root is not None) and not missing,
        "measured": bool(root is not None),
    }


def deployment_report(root: Path | None = None) -> dict[str, object]:
    """تقرير النشر الكامل — قياس من الشجرة الفعلية."""
    resolved = root or repo_root()
    targets = [target_readiness(t, resolved) for t in DEPLOY_TARGETS]
    return {
        "root": str(resolved) if resolved else None,
        "measured": bool(resolved is not None),
        "targets": targets,
        "all_ready": bool(targets) and all(t["ready"] for t in targets),
        "ready_count": sum(1 for t in targets if t["ready"]),
        "total": len(targets),
    }


def format_report_lines(report: dict[str, object]) -> list[str]:
    """أسطر جاهزة للطباعة في ``zyko doctor`` — بلا ادعاء، الفاقد مذكور بالاسم."""
    lines: list[str] = []
    if not report.get("measured"):
        lines.append(
            "  --  deployment targets (نسخة مثبَّتة بلا شجرة مصدر — الأصول في مستودع التطوير)"
        )
        return lines
    for t in report["targets"]:  # type: ignore[index]
        assert isinstance(t, dict)
        missing = t["missing_assets"]  # type: ignore[index]
        if t["ready"]:  # type: ignore[index]
            lines.append(f"  OK  {t['key']:<12} {t['title']}")  # type: ignore[index]
        elif missing:  # type: ignore[index]
            lines.append(
                f"  --  {t['key']:<12} أصول ناقصة: {', '.join(missing)} — الدليل: {t['guide']}"  # type: ignore[index]
            )
        else:
            lines.append(f"  --  {t['key']:<12} غير مقاس")  # type: ignore[index]
    return lines
