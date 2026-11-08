"""zyko.coder.generate — المولّد الحتمي (D12–13).

From a validated :class:`ProjectPlan` to a complete file tree on disk:
write files, build RECEIPT.md, optionally ``git init`` + an initial
Arabic commit. Deterministic by construction:

- no clock in file contents (the receipt has no timestamp);
- the git identity and dates are pinned so two runs of the same plan
  produce byte-identical repositories (``--real-dates`` opts out).

Any pre-existing directory refuses generation unless empty — we never
overwrite user work.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .plan import ProjectPlan
from .receipt import receipt_md
from .templates import GenFile, build_tree

# هوية وتاريخ ثابتان — نفس المخطط يعطي مستودعًا مطابقًا بايت-ببايت.
GIT_AUTHOR = "zyko-coder"
GIT_EMAIL = "coder@zyko.local"
FIXED_DATE = "2026-01-01T00:00:00+00:00"
INIT_COMMIT_MSG = "التوليد الأول: مشروع من مخطط متحقق عبر zyko.coder"


@dataclass
class GenerateResult:
    """نتيجة التوليد: ما كُتب، وما فعله git، ومشاكل غير قاتلة."""

    root: Path
    files: list[str] = field(default_factory=list)
    git_committed: bool = False
    git_skipped_reason: str = ""
    warnings: list[str] = field(default_factory=list)


def _write_file(root: Path, f: GenFile) -> None:
    target = root / f.path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f.content, encoding="utf-8", newline="\n")


def _git_env(real_dates: bool) -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_AUTHOR_NAME"] = GIT_AUTHOR
    env["GIT_AUTHOR_EMAIL"] = GIT_EMAIL
    env["GIT_COMMITTER_NAME"] = GIT_AUTHOR
    env["GIT_COMMITTER_EMAIL"] = GIT_EMAIL
    if not real_dates:
        env["GIT_AUTHOR_DATE"] = FIXED_DATE
        env["GIT_COMMITTER_DATE"] = FIXED_DATE
    return env


def _git(root: Path, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # المدخلات داخلية ثابتة (git + لائحة أوسطات مبرمجة) — بلا shell ولا مدخلات مستخدم
    return subprocess.run(  # nosec B607 B603
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def build_all_files(
    plan: ProjectPlan, model_log: list[dict[str, str]] | None = None
) -> dict[str, GenFile]:
    """الشجرة الكاملة: القالب + RECEIPT — حتمية وقابلة للاختبار بلا قرص."""
    tree = build_tree(plan)
    tree["RECEIPT.md"] = receipt_md(plan, tree, model_log=model_log)
    return tree


def materialize(
    plan: ProjectPlan,
    out_dir: Path,
    git_init: bool = True,
    real_dates: bool = False,
    model_log: list[dict[str, str]] | None = None,
) -> GenerateResult:
    """يكتب المشروع كاملًا على القرص ويعيد النتيجة.

    يرفض الكتابة فوق مجلد غير فارغ (بلا استثناءات صامتة).
    """
    root = Path(out_dir)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(
            f"المجلد «{root}» غير فارغ — اختر مجلدًا جديدًا حتى لا يُكتب فوق عمل قائم"
        )
    root.mkdir(parents=True, exist_ok=True)

    tree = build_all_files(plan, model_log=model_log)
    for path in sorted(tree):
        _write_file(root, tree[path])

    result = GenerateResult(root=root, files=sorted(tree))

    if not git_init:
        return result

    env = _git_env(real_dates)
    git = _git(root, "--version", env=env)
    if git.returncode != 0:
        result.git_skipped_reason = "git غير متاح في هذا الجهاز"
        result.warnings.append(result.git_skipped_reason)
        return result

    for cmd in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", INIT_COMMIT_MSG]):
        r = _git(root, *cmd, env=env)
        if r.returncode != 0:
            reason = (r.stderr or r.stdout).strip().splitlines()
            result.git_skipped_reason = reason[0][:160] if reason else f"فشل git {' '.join(cmd)}"
            result.warnings.append(f"تخطّي git: {result.git_skipped_reason}")
            return result
    result.git_committed = True
    return result


__all__ = [
    "FIXED_DATE",
    "GenerateResult",
    "INIT_COMMIT_MSG",
    "build_all_files",
    "materialize",
]
