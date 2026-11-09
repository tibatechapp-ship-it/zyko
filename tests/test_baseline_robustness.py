"""اختبارات متانة zyko.baseline: مدخلات عدائية ⇒ فشل مهيكل، لا انهيار أبدًا.

كل اختبار هنا يهاجم واجهة update/check بمدخل فاسد ويتطلب:
- لا استثناءات خارجية إطلاقًا (EngineError-free surface)
- نتيجة موقعة: ok=False + failed_stage + error_ar عربي غير فارغ + خروج 2
- أو حالة موثقة (لا خط أساس: ok=True + خروج 1) حين يكون الغياب هو الوضع
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zyko.baseline.engine import (
    STAGE_BASELINE,
    STAGE_REVIEWER,
    STAGE_SCAN,
    BaselineEngine,
)

CLEAN = '"""نظيف."""\n\n\ndef add(a, b):\n    return a + b\n'


@pytest.fixture()
def engine():
    return BaselineEngine()


@pytest.fixture()
def project(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    (src / "a.py").write_text(CLEAN, encoding="utf-8", newline="\n")
    return src


def _assert_structured_failure(result) -> None:
    assert result.ok is False
    assert result.exit_code == 2
    assert result.failed_stage in (STAGE_SCAN, STAGE_REVIEWER, STAGE_BASELINE)
    assert result.error_ar
    assert result.verdict_ar


# ------------------------------------------------- مسارات عدائية
def test_update_missing_dir(engine, tmp_path):
    _assert_structured_failure(engine.update(tmp_path / "لا-يوجد"))


def test_check_missing_dir(engine, tmp_path):
    _assert_structured_failure(engine.check(tmp_path / "لا-يوجد"))


def test_update_file_instead_of_dir(engine, tmp_path):
    f = tmp_path / "plain.txt"
    f.write_text("ملف لا مجلد", encoding="utf-8")
    _assert_structured_failure(engine.update(f))


def test_check_file_instead_of_dir(engine, tmp_path):
    f = tmp_path / "plain.txt"
    f.write_text("ملف لا مجلد", encoding="utf-8")
    _assert_structured_failure(engine.check(f))


@pytest.mark.parametrize("bad_src", [None, 42, b"/tmp/bytes", [], {}, True])
def test_update_hostile_src_types(engine, bad_src):
    _assert_structured_failure(engine.update(bad_src))


@pytest.mark.parametrize("bad_src", [None, 42, b"/tmp/bytes", [], {}, True])
def test_check_hostile_src_types(engine, bad_src):
    _assert_structured_failure(engine.check(bad_src))


def test_update_empty_string_path(engine):
    _assert_structured_failure(engine.update(""))
    _assert_structured_failure(engine.update("   "))


def test_check_empty_string_path(engine):
    _assert_structured_failure(engine.check(""))
    _assert_structured_failure(engine.check("  "))


# ------------------------------------------------- خطوط أساس عدائية
def _write_baseline(tmp_path, content: object, name: str = "b.json") -> Path:
    p = tmp_path / name
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(str(content), encoding="utf-8", newline="\n")
    return p


def test_check_corrupt_json(engine, project, tmp_path):
    bad = _write_baseline(tmp_path, "{ليس json أبدًا")
    _assert_structured_failure(engine.check(project, baseline_path=bad))


def test_check_bad_encoding(engine, project, tmp_path):
    bad = _write_baseline(tmp_path, '{"schema": "zyko.baseline/1"}'.encode("utf-16"))
    _assert_structured_failure(engine.check(project, baseline_path=bad))


def test_check_baseline_is_a_list(engine, project, tmp_path):
    bad = _write_baseline(tmp_path, "[1, 2, 3]")
    _assert_structured_failure(engine.check(project, baseline_path=bad))


def test_check_unknown_schema(engine, project, tmp_path):
    bad = _write_baseline(tmp_path, '{"schema": "zyko.baseline/99", "files": {}}')
    _assert_structured_failure(engine.check(project, baseline_path=bad))


def test_check_files_not_a_dict(engine, project, tmp_path):
    bad = _write_baseline(tmp_path, '{"schema": "zyko.baseline/1", "files": ["قائمة لا قاموس"]}')
    _assert_structured_failure(engine.check(project, baseline_path=bad))


def test_check_record_not_a_dict(engine, project, tmp_path):
    bad = _write_baseline(tmp_path, '{"schema": "zyko.baseline/1", "files": {"a.py": 100}}')
    _assert_structured_failure(engine.check(project, baseline_path=bad))


def test_check_score_not_int(engine, project, tmp_path):
    bad = _write_baseline(
        tmp_path,
        '{"schema": "zyko.baseline/1", "files": {"a.py": {"score": "عالٍ",'
        ' "findings": [], "sha256": "x"}}}',
    )
    _assert_structured_failure(engine.check(project, baseline_path=bad))


def test_check_score_bool_rejected(engine, project, tmp_path):
    bad = _write_baseline(
        tmp_path,
        '{"schema": "zyko.baseline/1", "files": {"a.py": {"score": true,'
        ' "findings": [], "sha256": "x"}}}',
    )
    _assert_structured_failure(engine.check(project, baseline_path=bad))


def test_check_score_out_of_range(engine, project, tmp_path):
    bad = _write_baseline(
        tmp_path,
        '{"schema": "zyko.baseline/1", "files": {"a.py": {"score": 101,'
        ' "findings": [], "sha256": "x"}}}',
    )
    _assert_structured_failure(engine.check(project, baseline_path=bad))


def test_check_findings_not_strings(engine, project, tmp_path):
    bad = _write_baseline(
        tmp_path,
        '{"schema": "zyko.baseline/1", "files": {"a.py": {"score": 90,'
        ' "findings": [7], "sha256": "x"}}}',
    )
    _assert_structured_failure(engine.check(project, baseline_path=bad))


def test_check_sha_not_string(engine, project, tmp_path):
    bad = _write_baseline(
        tmp_path,
        '{"schema": "zyko.baseline/1", "files": {"a.py": {"score": 90,'
        ' "findings": [], "sha256": 5}}}',
    )
    _assert_structured_failure(engine.check(project, baseline_path=bad))


def test_check_history_not_a_list(engine, project, tmp_path):
    bad = _write_baseline(
        tmp_path,
        '{"schema": "zyko.baseline/1", "files": {}, "history": {"run_no": 1}}',
    )
    _assert_structured_failure(engine.check(project, baseline_path=bad))


def test_check_baseline_is_a_directory(engine, project, tmp_path):
    d = tmp_path / "baseline-dir"
    d.mkdir()
    _assert_structured_failure(engine.check(project, baseline_path=d))


def test_check_baseline_path_empty_string(engine, project):
    # مسار فارغ ⇒ لا ملف في المسار ⇒ حالة «لا خط أساس» الموثقة (ليست انهيارًا)
    r = engine.check(project, baseline_path="")
    assert r.ok and r.baseline_status == "missing" and r.exit_code == 1


def test_update_baseline_path_is_a_directory(engine, project, tmp_path):
    d = tmp_path / "bdir"
    d.mkdir()
    _assert_structured_failure(engine.update(project, baseline_path=d))


def test_update_baseline_path_empty_string(engine, project):
    _assert_structured_failure(engine.update(project, baseline_path=""))


# -------------------------------------------- قراءة فقط في كل الحالات
def test_check_never_writes_even_on_failure(engine, project, tmp_path):
    from zyko.baseline.engine import BASELINE_DIRNAME, BASELINE_FILENAME

    before = sorted(str(p) for p in project.rglob("*"))
    bad = _write_baseline(tmp_path, "{فاسد")
    _assert_structured_failure(engine.check(project, baseline_path=bad))
    # حتى حالة «لا خط أساس» لا تنشئ المجلد
    fresh = tmp_path / "fresh-proj"
    fresh.mkdir()
    (fresh / "a.py").write_text(CLEAN, encoding="utf-8")
    missing = engine.check(fresh)
    assert missing.ok and missing.baseline_status == "missing"
    assert not (fresh / BASELINE_DIRNAME / BASELINE_FILENAME).exists()
    after = sorted(str(p) for p in project.rglob("*"))
    assert before == after
