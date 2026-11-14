"""اختبارات مرساة بوابة الأسرار (الموجة 26 — درس 19 توكن صار عقداً).

العقد المرساة: البادئات القصيرة لا توقّع، الإثبات بصمة لا قيمة، علامة
الإعفاء صريحة قابلة للبحث، الشجرة تهمل المجلدات المهملة والملفات الضخمة،
والحتمية بالبايت. التوكنات الوهمية هنا مُجمَّعة برمجياً — لا حرفية سرية.
"""

from __future__ import annotations

import json

from zyko.utils.secret_scan import (
    EXEMPT_MARKER,
    SECRET_PATTERNS,
    scan_text,
    scan_to_json,
    scan_tree,
)

FAKE_GHP = "ghp_" + "A" * 36
FAKE_AKIA = "AKIA" + "B" * 16
FAKE_XOX = "xoxb-" + "C" * 12
FAKE_ANT = "sk-ant-" + "D" * 24
FAKE_SK = "sk-" + "E" * 24


def test_pattern_count_is_contract():
    assert len(SECRET_PATTERNS) == 2  # قيمة السر + إسناد الاعتماد


def test_full_ghp_token_detected_at_right_line():
    text = "line1\n" + f"t = '{FAKE_GHP}'" + "\nline3"
    hits = scan_text(text)
    assert len(hits) == 1
    assert hits[0].severity == "critical"
    assert hits[0].line_no == 2


def test_short_prefix_never_flagged():
    hits = scan_text("p = 'ghp_U5Zk'")  # بادئة قائمة الحرق — 4 أحرف بعد ghp_
    assert len(hits) == 0


def test_each_family_detected():
    for value in (FAKE_AKIA, FAKE_XOX, FAKE_ANT, FAKE_SK):
        hits = scan_text(f"x = '{value}'")
        assert len(hits) == 1, value
        assert hits[0].severity == "critical"


def test_private_key_header_detected():
    hits = scan_text("-----BEGIN RSA PRIVATE KEY-----")  # zyko:secret-ok (سطر اختبار للنمط نفسه)
    assert len(hits) == 1


def test_cred_assignment_medium():
    hits = scan_text('password = "hard-coded-pass-99"')  # zyko:secret-ok (سطر اختبار للنمط نفسه)
    assert [h.severity for h in hits] == ["medium"]
    assert hits[0].name == "cred-assignment"


def test_exempt_marker_line_skipped():
    text = f"t = '{FAKE_GHP}'  # {EXEMPT_MARKER}"
    assert len(scan_text(text)) == 0


def test_evidence_is_sha16_never_the_value():
    hits = scan_text(f"t = '{FAKE_GHP}'")
    assert hits[0].evidence_sha16 != FAKE_GHP
    assert len(hits[0].evidence_sha16) == 16
    int(hits[0].evidence_sha16, 16)  # سدس عشري صالح


def test_scan_tree_skips_git_dir_and_huge_files(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "leak.py").write_text(f"t = '{FAKE_GHP}'", encoding="utf-8")
    (tmp_path / "ok.py").write_text(f"t = '{FAKE_GHP}'", encoding="utf-8")
    (tmp_path / "big.py").write_text("x = " + "1" * 3_000_000, encoding="utf-8")
    report = scan_tree(tmp_path)
    files = {h["file"] for h in report["hits"]}
    assert files == {"ok.py"}  # .git مُهمَل والضخم تجاوز بسقف معلن


def test_byte_determinism():
    text = f"a\nx = '{FAKE_AKIA}'\ny = '{FAKE_XOX}'\n"
    j1 = scan_to_json({"hits": [h.to_dict() for h in scan_text(text)]})
    j2 = scan_to_json({"hits": [h.to_dict() for h in scan_text(text)]})
    assert j1 == j2
    assert json.loads(j1)["hits"][0]["name"] == "github-token"


def test_composition_with_patch_audit_added_lines():
    from zyko.benchmarks.patch_audit import added_lines

    diff = "\n".join(
        [
            "--- a/app.py",
            "+++ b/app.py",
            "@@ -1,2 +1,3 @@",
            " ctx",
            "+t = '" + FAKE_GHP + "'",
            "-old = '" + FAKE_AKIA + "'",
        ]
    )
    hits = []
    for file, lineno, text in added_lines(diff):
        for h in scan_text(text):
            hits.append((file, lineno, h.name))
    assert hits == [("app.py", 2, "github-token")]  # المحذوف ليس جريمة
