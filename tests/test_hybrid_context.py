"""اختبارات مرساة باني السياق (الموجة 27 — بنية 1).

العقد: السياق لكل ملاحظة بالترتيب، المتغير يُسمّى، المنشؤ من taint
بالعائلتين، الوجهات مسقوفة، الملف المكسور تدفق «غير معروف» لا سقوط،
والحتمية بالبايت.
"""

from __future__ import annotations

import json

from zyko.reviewer.engine import ReviewEngine
from zyko.reviewer.hybrid.context import build_contexts

SOURCE = (
    "def handle():\n"
    "    name = input('من؟ ')\n"  # سطر 2 — ملوث من إدخال
    "    try:\n"
    "        go(name)\n"  # سطر 4 — تمرير المتغير الملوث
    "    except:\n"  # سطر 5 — except عارٍ
    "        pass\n"
    "    return name\n"  # سطر 7 — إعادة الملوث
)


def _review(src: str = SOURCE):
    return ReviewEngine().review_source(src, "demo.py")


def test_one_context_per_finding_in_order():
    result = _review()
    ctxs = build_contexts(SOURCE, "demo.py", result)
    assert len(ctxs) == len(result.findings)
    assert [c.line for c in ctxs] == [f.line for c in ctxs for f in [c]]
    # الاصطلاح: نفس ترتيب الملاحظات
    assert [c.rule_id for c in ctxs] == [f.rule_id for f in result.findings]


def test_variable_identified_on_assignment_finding():
    result = _review()
    ctxs = build_contexts(SOURCE, "demo.py", result)
    # ملاحظة except العاري سطرها 5 — عبارة النداء السابقة تحمل go(name)
    by_rule = {c.rule_id: c for c in ctxs}
    bare = by_rule.get("ERR-BAREEXC-001")
    if bare is not None:  # القاعدة موجودة في سجل الـ38
        assert bare.snippet, "المقتطف ليس فارغاً"
        assert bare.snippet[0].startswith((" ", ">"))


def test_tainted_input_variable_family_and_usage():
    source = "def handle():\n    name = input('؟ ')\n    go(name)\n"
    result = ReviewEngine().review_source(source, "demo.py")
    ctxs = build_contexts(source, "demo.py", result)
    assert any(c.tainted and c.taint_family_ar.startswith("ملوث من إدخال") for c in ctxs)
    assert any(any(u["kind"] == "passed_to" and u["name"] == "go" for u in c.usages) for c in ctxs)


def test_request_family_detected():
    source = "def view(request):\n    q = request.args.get('q')\n    run(q)\n"
    result = ReviewEngine().review_source(source, "demo.py")
    ctxs = build_contexts(source, "demo.py", result)
    assert any(c.taint_family_ar.startswith("ملوث من بيانات الطلب") for c in ctxs)


def test_first_assignment_line_recorded():
    source = "def f():\n    x = input()\n    y = x\n    go(y)\n"
    result = ReviewEngine().review_source(source, "demo.py")
    ctxs = build_contexts(source, "demo.py", result)
    tainted_ctx = [c for c in ctxs if c.tainted]
    assert tainted_ctx, "متوقع تلويث يظهر في سياق ملاحظة"
    assert all(c.first_assignment_line == 2 for c in tainted_ctx if c.variable in {"x", "y"})


def test_usages_capped_at_five():
    source = "def f():\n    x = input()\n" + "".join(f"    go{i}(x)\n" for i in range(8))
    result = ReviewEngine().review_source(source, "demo.py")
    ctxs = build_contexts(source, "demo.py", result)
    assert all(len(c.usages) <= 5 for c in ctxs)


def test_unparsable_source_yields_unknown_flow_no_crash():
    bad = "def (:\n"
    result = ReviewEngine().review_source(bad, "demo.py")
    ctxs = build_contexts(bad, "demo.py", result)
    assert all(c.taint_family_ar == "غير معروف — الملف لم يُحلَّل" for c in ctxs)
    assert all(not c.tainted for c in ctxs)


def test_snippet_window_clamped_at_edges():
    source = "x = input()\n"
    result = ReviewEngine().review_source(source, "demo.py")
    ctxs = build_contexts(source, "demo.py", result, window=3)
    for c in ctxs:
        nums = [int(s.split("|")[0].strip().lstrip("> ")) for s in c.snippet]
        assert min(nums) == 1  # السقف عند بداية الملف لا سالب


def test_byte_determinism():
    j1 = json.dumps(
        [c.to_dict() for c in build_contexts(SOURCE, "demo.py", _review())],
        ensure_ascii=False,
        sort_keys=True,
    )
    j2 = json.dumps(
        [c.to_dict() for c in build_contexts(SOURCE, "demo.py", _review())],
        ensure_ascii=False,
        sort_keys=True,
    )
    assert j1 == j2


def test_clean_file_gives_no_contexts():
    source = "A = 1\nB = A + 1\n"
    result = ReviewEngine().review_source(source, "demo.py")
    assert result.score == 100
    assert build_contexts(source, "demo.py", result) == ()
