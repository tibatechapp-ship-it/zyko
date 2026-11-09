"""اختبارات لوحة المصنع HTML (المرحلة 7): حتمية بايتية، تهريب شامل، بلا جافاسكربت.

العقود التي تُحصَّن هنا:
- نفس النتيجة ⇒ نفس البايتات (بلا أختام زمنية إطلاقًا)
- كل نص من القرص أو الوصف يُهرَّب — مسار عدائي لا يولّد HTML غير مقصود
- الصفحة بلا ``<script`` وبلا أصول خارجية، وكل ملاحظة بـ suggestion_ar كما وردت
"""

from __future__ import annotations

import shutil
import sys
from html import escape as html_escape
from pathlib import Path

import pytest

from zyko.cli import main as cli_main
from zyko.factory.report_html import (
    fixer_results_html,
    pipeline_result_html,
    workspace_result_html,
)
from zyko.fixer.engine import FixerEngine
from zyko.workspace.engine import WorkspaceEngine

ENGINE = FixerEngine()
SAMPLE = "import os\n\ndef f(v):\n    return v == None\n"
SAMPLE_DIR = Path("samples/workspace/small_tool")


def _run_workspace(src: str):
    return WorkspaceEngine().run(src, rounds=1)


# ------------------------------------------------------------- الحتمية
def test_workspace_html_deterministic_bytes(tmp_path: Path) -> None:
    """تشغيلان على نفس المجلد (بلا كتابة) ⇒ لوحتان متطابقتان بايتيًا."""
    html_a = workspace_result_html(_run_workspace(str(SAMPLE_DIR)))
    html_b = workspace_result_html(_run_workspace(str(SAMPLE_DIR)))
    assert html_a == html_b
    # نسخة منقولة إلى مجلد آخر: كل شيء متطابق إلا مسار المجلد في بطاقة التشغيل
    moved = tmp_path / "moved"
    shutil.copytree(SAMPLE_DIR, moved)
    html_moved = workspace_result_html(_run_workspace(str(moved)))
    assert html_moved.replace(str(moved), str(SAMPLE_DIR)) == html_a


def test_render_twice_same_object_identical() -> None:
    result = _run_workspace(str(SAMPLE_DIR))
    assert workspace_result_html(result) == workspace_result_html(result)


def test_no_timestamp_no_timing() -> None:
    """اللوحة بلا أوقات — الحتمية لا تُكسر حتى بغير قصد."""
    html = workspace_result_html(_run_workspace(str(SAMPLE_DIR)))
    assert "seconds" not in html
    assert "2026" not in html


# ------------------------------------------------------- الصفحة نفسها
def test_rtl_arabic_self_contained() -> None:
    html = workspace_result_html(_run_workspace(str(SAMPLE_DIR)))
    assert html.startswith("<!doctype html>")
    assert '<html lang="ar" dir="rtl">' in html
    assert "<script" not in html.lower()  # بلا جافاسكربت إطلاقًا
    assert "http://" not in html and "https://" not in html  # بلا أصول خارجية


def test_panel_shows_verdict_and_counters() -> None:
    html = workspace_result_html(_run_workspace(str(SAMPLE_DIR)))
    assert "badge" in html
    assert "أُصلح آليًا" in html
    assert "يدوي" in html
    assert "الدرجة:" in html


# ------------------------------------------------------------ التهريب
def test_hostile_description_escaped(tmp_path: Path) -> None:
    """وصف عدائي في pipeline ⇒ نص مُهرَّب، لا HTML غير مقصود."""
    from zyko.pipeline.engine import PipelineEngine

    result = PipelineEngine().run(
        "أريد أداة <script>alert(1)</script> بسيطة",
        tmp_path / "unused",
        rounds=1,
        write=False,
    )
    html = pipeline_result_html(result)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)" not in html


def test_hostile_file_path_escaped(tmp_path: Path) -> None:
    """مسار ملف عدائي على القرص ⇒ نص مُهرَّب في اللوحة (باسم صالح على كل منصة).

    ``<`` و ``>`` ممنوعان في أسماء ملفات ويندوز؛ لذا الاسم العدائي الكامل
    على POSIX فقط، وعلى ويندوز ``&`` (يُهرَّب إلى ``&amp;``). تهريب
    ``<script>`` الكامل مُغطى على كل المنصات في اختبار الوصف العدائي.
    """
    if sys.platform == "win32":
        name = "img src=x & onerror=alert(1).py"
    else:
        name = "<img src=x onerror=alert(1)>.py"
    evil = tmp_path / name
    evil.write_text("x = 1\n", encoding="utf-8")
    html = workspace_result_html(_run_workspace(str(tmp_path)))
    assert html_escape(name, quote=True) in html
    assert name not in html


# ------------------------------------------------- suggestion_ar حرفيًا
def test_suggestion_ar_verbatim_in_panel() -> None:
    """كل suggestion_ar في النتيجة تظهر في اللوحة كما وردت حرفيًا."""
    result = _run_workspace(str(SAMPLE_DIR))
    html = workspace_result_html(result)
    checked = 0
    for f in result.per_file:
        for o in f["outcomes"]:
            sug = o["suggestion_ar"]
            assert sug in html, f"سقطت اقتراح من اللوحة: {sug!r}"
            checked += 1
    assert checked > 0


def test_fixer_panel_counters_and_table() -> None:
    results = [ENGINE.fix_source(SAMPLE, "r.py")]
    html = fixer_results_html(results)
    assert "تقرير المُصلِح الحتمي" in html
    assert "الإصلاح:" in html
    assert "r.py" in html


def test_fixer_panel_multi_file_verdict() -> None:
    results = [
        ENGINE.fix_source(SAMPLE, "a.py"),
        ENGINE.fix_source("x = 1\n", "b.py"),
    ]
    html = fixer_results_html(results)
    assert "اكتمل الفحص" in html
    assert "a.py" in html and "b.py" in html


# ------------------------------------------------------ الحالات الخاصة
def test_failed_structural_run_renders_failbox(tmp_path: Path) -> None:
    result = _run_workspace(str(tmp_path / "لا-يوجد"))
    assert result.ok is False
    html = workspace_result_html(result)
    assert "فشل مهيكل" in html
    assert "المسح" in html
    assert result.error_ar in html


def test_empty_dir_renders_no_review(tmp_path: Path) -> None:
    html = workspace_result_html(_run_workspace(str(tmp_path)))
    assert "لا مراجعة" in html


# ------------------------------------------------- علم --html في CLI
def test_cli_html_flag_writes_panel(tmp_path: Path) -> None:
    """``zyko factory workspace --html`` يكتب ملفًا يبدأ بdoctype."""
    panel = tmp_path / "لوحة.html"
    rc = cli_main(
        [
            "factory",
            "workspace",
            "--src",
            str(SAMPLE_DIR),
            "--fail-under",
            "0",
            "--format",
            "summary",
            "--html",
            str(panel),
        ]
    )
    assert rc == 0
    assert panel.exists()
    assert panel.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_cli_html_flag_does_not_touch_stdout(tmp_path: Path) -> None:
    """اللوحة تُكتب بجانب الخرج النصي — stdout يبقى حتميًا بايتيًا."""
    argv_tail = [
        "--src",
        str(SAMPLE_DIR),
        "--fail-under",
        "0",
        "--format",
        "summary",
    ]
    rc_plain = cli_main(["factory", "workspace", *argv_tail])
    # capsys يبتلع الخرج بين الاستدعاءين؛ المقارنة هنا على الملف المكتوب فقط
    panel = tmp_path / "p.html"
    rc_html = cli_main(["factory", "workspace", *argv_tail, "--html", str(panel)])
    assert rc_plain == rc_html == 0
    assert panel.exists()


def test_module_html_flag_workspace(tmp_path: Path) -> None:
    """python -m zyko.workspace يدعم --html كذلك (البوابتان سلوك واحد)."""
    from zyko.workspace.__main__ import main as workspace_main

    panel = tmp_path / "panel.html"
    rc = workspace_main(
        [
            "run",
            "--src",
            str(SAMPLE_DIR),
            "--fail-under",
            "0",
            "--format",
            "summary",
            "--html",
            str(panel),
        ]
    )
    assert rc == 0
    assert panel.exists() and "<!doctype html>" in panel.read_text(encoding="utf-8")


def test_module_html_flag_fixer_and_pipeline(tmp_path: Path) -> None:
    from zyko.fixer.__main__ import main as fixer_main
    from zyko.pipeline.__main__ import main as pipeline_main

    dirty = tmp_path / "dirty.py"
    dirty.write_text(SAMPLE, encoding="utf-8")
    p1 = tmp_path / "fix.html"
    assert fixer_main(["fix", "--path", str(dirty), "--format", "summary", "--html", str(p1)]) == 0
    assert p1.exists()

    p2 = tmp_path / "pipe.html"
    rc = pipeline_main(
        [
            "run",
            "--description",
            "أريد قائمة مهام يومية بسيطة أضيف فيها المهام وأشطبها عند إنجازها",
            "--out",
            str(tmp_path / "proj"),
            "--dry-run",
            "--fail-under",
            "0",
            "--format",
            "summary",
            "--html",
            str(p2),
        ]
    )
    assert rc == 0
    assert p2.exists() and "<!doctype html>" in p2.read_text(encoding="utf-8")


def test_html_write_failure_is_structured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """فشل كتابة اللوحة (مجلد غير موجود) ⇒ خطأ مهيكل وخروج 1 — بلا انهيار."""
    bad = tmp_path / "لا-يوجد" / "panel.html"
    rc = cli_main(
        [
            "factory",
            "workspace",
            "--src",
            str(SAMPLE_DIR),
            "--fail-under",
            "0",
            "--format",
            "summary",
            "--html",
            str(bad),
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "تعذّر كتابة لوحة HTML" in err
