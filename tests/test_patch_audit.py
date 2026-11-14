"""اختبارات مرساة مدقّق الرقع (الموجة 26 — زبدة الطبقة الثابتة الهجينة).

العقد المرساة: المضاف فقط يُفحص، الحذف ليس جريمة، الأسطر أرقام مطلقة
في الملف الهدف، الدرجات بترتيب أسوأ إصابة، والحتمية بالبايت.
"""

from __future__ import annotations

import json

from zyko.benchmarks.patch_audit import DIFF_RULES, audit_patch_text, patch_audit_to_json

# توكن وهمي مُجمَّع برمجياً — لا حرفية سرية في هذا الملف
FAKE36 = "A" * 36


def _diff(*lines: str) -> str:
    return "\n".join(lines)


def test_rule_count_is_contract():
    assert len(DIFF_RULES) == 8


def test_secret_on_added_line_detected_with_file_and_line():
    d = _diff(
        "--- a/app.py",
        "+++ b/app.py",
        "@@ -10,3 +10,4 @@",
        " keep = 1",
        f"+token = 'ghp_{FAKE36}',"
        " other = 2",
    )
    a = audit_patch_text(d)
    assert a.added_count == 1
    f = a.findings[0]
    assert f.rule_id == "SEC-SECRET-001"
    assert f.severity == "critical"
    assert f.file == "app.py"
    assert f.line_in_file == 11  # السطر 10 سياق، المضاف هو 11


def test_removed_secret_is_not_a_crime():
    d = _diff(
        "--- a/app.py",
        "+++ b/app.py",
        "@@ -1,3 +1,3 @@",
        f"-token = 'ghp_{FAKE36}',"
        "+token = load_from_env()",
        " keep = 2",
    )
    a = audit_patch_text(d)
    assert a.findings == []
    assert a.grade_ar == "نظيف"


def test_eval_exec_shell_sqli_high_findings():
    d = _diff(
        "--- a/x.py",
        "+++ b/x.py",
        "@@ -1,1 +1,5 @@",
        "+value = eval(user_text)",
        "+result = exec(payload)",
        "+os.system('rm ' + name)",
        "+subprocess.run(cmd, shell=True)",
        "+cursor.execute(f'SELECT * FROM t WHERE id={uid}')",
    )
    a = audit_patch_text(d)
    ids = {f.rule_id for f in a.findings}
    assert {"SEC-EVAL-001", "SEC-EXEC-001", "SEC-SHELL-001", "SEC-SQLI-001"} <= ids
    assert all(f.severity == "high" for f in a.findings)
    assert a.grade_ar == "مراجعة"


def test_bare_except_and_silent_swallow_medium():
    d = _diff(
        "--- a/y.py",
        "+++ b/y.py",
        "@@ -1,1 +1,6 @@",
        "+try:",
        "+    go()",
        "+except:",
        "+    pass",
        "+except Exception: pass",
        "+finally: clean()",
    )
    a = audit_patch_text(d)
    ids = {f.rule_id for f in a.findings}
    assert "ERR-BAREEXC-001" in ids
    assert "ERR-SILENT-001" in ids
    assert a.grade_ar == "تنبيه"


def test_todo_marker_low_grade():
    d = _diff("--- a/z.py", "+++ b/z.py", "@@ -1,1 +1,2 @@", "+x = 1  # TODO: لاحقاً")
    a = audit_patch_text(d)
    assert [f.rule_id for f in a.findings] == ["QUA-TODO-001"]
    assert a.grade_ar == "ملاحظة"


def test_multi_hunk_line_numbers_are_absolute():
    d = _diff(
        "--- a/m.py",
        "+++ b/m.py",
        "@@ -3,2 +3,3 @@",
        " ctx",
        "+first added",
        " ctx",
        "@@ -40,1 +42,2 @@",
        "+second added",
    )
    a = audit_patch_text(d)
    # لا قاعدة تضرب السطرين النظيفين — نفحص العد عبر الترويسات مباشرة
    assert a.added_count == 2
    # التحقق من الترقيم عبر قاعدة حتمية على سطرين نضيفهما ملوثين
    d2 = _diff(
        "--- a/m.py",
        "+++ b/m.py",
        "@@ -3,2 +3,3 @@",
        " ctx",
        "+value = eval(x)",
        " ctx",
        "@@ -40,1 +42,2 @@",
        "+more = eval(y)",
    )
    a2 = audit_patch_text(d2)
    assert [f.line_in_file for f in a2.findings] == [4, 42]  # +42,2 يبدأ العد من 42


def test_context_and_headers_never_audited():
    d = _diff(
        "diff --git a/a.py b/a.py",
        "index 111..222 100644",
        "--- a/a.py",
        "+++ b/a.py",
        "@@ -1,2 +1,2 @@",
        " eval(before_ctx)",
        "-eval(removed)",
        "+eval(added_real)",
    )
    a = audit_patch_text(d)
    assert len(a.findings) == 1
    assert a.findings[0].evidence == "eval(added_real)"


def test_plain_text_without_headers_is_zero_documented():
    a = audit_patch_text(f"eval(x)\nghp_{FAKE36}\n")
    assert a.findings == []
    assert a.added_count == 0
    assert a.grade_ar == "نظيف"


def test_byte_determinism():
    d = _diff(
        "--- a/a.py",
        "+++ b/a.py",
        "@@ -1,1 +1,2 @@",
        "+os.system('ls')",
        "+except:",
    )
    j1 = patch_audit_to_json(audit_patch_text(d))
    j2 = patch_audit_to_json(audit_patch_text(d))
    assert j1 == j2
    payload = json.loads(j1)
    assert payload["schema"] == "zyko.patch_audit/1"
    assert payload["grade_ar"] == "مراجعة"
