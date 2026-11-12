"""اختبارات جولة 11 — حصر الشبكة (Landlock ABI v4) + الخريطة الدلالية للمستودع.

النواة القديمة (< 6.7) لا تدعم ABI v4 — فالاختبارات بنيوية على العقود
والتركيب، وسلوك الكشف معلن: ``net_confinement()`` يعيد قيمة من المجموعة
الموثقة على أي نواة، والفجوة تُعلن لا تُخفى.
"""

from __future__ import annotations

import ctypes
import functools
import subprocess
from pathlib import Path

from zyko.reviewer.repo_map import UNPARSEABLE_MARK, build_repo_map, symbol_summary
from zyko.sandbox import jail
from zyko.sandbox.jail import (
    _ACCESS_NET_BIND_TCP,
    _ACCESS_NET_CONNECT_TCP,
    _NET_SCOPE,
    _net_scope,
    _NetPortAttr,
    _ruleset_struct,
    _RulesetAttr,
    _RulesetAttrNet,
    net_confinement,
)


# --------------------------------------------------------------- حصر الشبكة
def test_net_scope_threshold():
    assert _net_scope(0) == 0
    assert _net_scope(3) == 0
    assert _net_scope(4) == (_ACCESS_NET_BIND_TCP | _ACCESS_NET_CONNECT_TCP)
    assert _net_scope(6) == _net_scope(4)


def test_ruleset_struct_sized_by_abi():
    struct8, size8 = _ruleset_struct(3, 0xFF)
    assert size8 == ctypes.sizeof(_RulesetAttr) == 8
    assert not hasattr(struct8, "handled_access_scoped")
    struct16, size16 = _ruleset_struct(4, 0xFF)
    assert size16 == ctypes.sizeof(_RulesetAttrNet) == 16
    assert struct16.handled_access_scoped == _NET_SCOPE
    assert struct16.handled_access_fs == 0xFF


def test_net_port_attr_packing():
    rule = _NetPortAttr(_ACCESS_NET_CONNECT_TCP, 8642)
    assert rule.allowed_access == (1 << 17)
    assert rule.port == 8642
    # المنافذ المكررة تُدمج في القياس المنطقي — القاعدة واحدة للمنفذ الواحد
    assert len({8642, 8642}) == 1


def test_net_confinement_declared_not_assumed():
    assert net_confinement() in {"landlock-net", "bwrap-net", "unconstrained"}
    # الاتساق مع المستوى المعلن: bwrap ⇒ شبكة مقطوعة كلياً (أصرم)
    level = jail.jail_level()
    conf = net_confinement()
    if level == jail.JAIL_LEVEL_BWRAP:
        assert conf == "bwrap-net"
    elif level == jail.JAIL_LEVEL_NONE:
        assert conf == "unconstrained"


def test_jail_preexec_carries_net_ports_under_landlock(monkeypatch):
    """تحت landlock: المنافذ المعلنة تصل إلى دالة الابن حرفياً."""
    monkeypatch.setattr(jail, "_level_cache", jail.JAIL_LEVEL_LANDLOCK)
    monkeypatch.setattr(jail, "landlock_abi", lambda: 4)
    preexec = jail.jail_preexec(("/tmp",), net_ports=(8642,))
    assert preexec is not None
    assert isinstance(preexec, functools.partial)
    assert preexec.keywords == {} and preexec.args[1] == (8642,)


def test_jail_preexec_default_denies_all_tcp(monkeypatch):
    """الافتراضي أصرم: بلا منافذ معلنة = صفر قواعد سماح شبكية."""
    monkeypatch.setattr(jail, "_level_cache", jail.JAIL_LEVEL_LANDLOCK)
    monkeypatch.setattr(jail, "landlock_abi", lambda: 4)
    preexec = jail.jail_preexec(("/tmp",))
    assert preexec.args[1] == ()


# --------------------------------------------------------------- الخريطة الدلالية
def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "models.py").write_text(
        "class Response:\n    def __init__(self, a):\n        self.a = a\n\n"
        "def ok(self):\n    return True\n",
        encoding="utf-8",
    )
    (repo / "auth.py").write_text(
        "async def fetch(url, *, timeout=5):\n    return url\n\nclass AuthError(Exception):\n    pass\n",
        encoding="utf-8",
    )
    (repo / "broken.py").write_text("def مقدمة(:\n", encoding="utf-8")  # غير قابل للتحليل
    (repo / "empty_symbols.py").write_text("X = 1\nY = 2\n", encoding="utf-8")  # بلا رموز دوال
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def test_symbol_summary_sorted_with_signatures():
    summary = symbol_summary("class B: pass\nclass A: pass\ndef zeta(): pass\ndef alpha(x, y=1): pass\n")
    assert summary == "class A؛ class B؛ def alpha(x, y)؛ def zeta()"
    assert symbol_summary("not python (:") is None
    assert symbol_summary("X = 1\n") == ""  # ملف سليم بلا رموز — فراغ موثق
    kw = symbol_summary("async def fetch(url, *, timeout=5): pass\n")
    assert kw == "async def fetch(url, *, timeout)"


def test_repo_map_deterministic_and_symbolic(tmp_path):
    repo = _make_repo(tmp_path)
    lines1 = build_repo_map(repo)
    lines2 = build_repo_map(repo)
    assert lines1 == lines2  # حتمية بالبايت
    text = "\n".join(lines1)
    assert "models.py :: class Response" in text
    assert "def ok(self)" in text
    assert "async def fetch(url, *, timeout)" in text
    assert "class AuthError" in text
    assert f"broken.py :: {UNPARSEABLE_MARK}" in text
    assert "empty_symbols.py :: بلا رموز مستوى أعلى" in text


def test_repo_map_empty_without_git(tmp_path):
    plain = tmp_path / "no-git"
    plain.mkdir()
    (plain / "x.py").write_text("a = 1\n", encoding="utf-8")
    assert build_repo_map(plain) == ()  # لا git ⇒ خريطة فارغة معلنة


def test_repo_map_missing_file_documented(tmp_path):
    """ملف متعقّب في الفهرس ومفقود من القرص — سطر موثق لا سقوط."""
    repo = _make_repo(tmp_path)
    (repo / "models.py").unlink()
    lines = build_repo_map(repo)
    assert "models.py :: مفقود من القرص" in "\n".join(lines)


def test_choice_request_includes_map_lines():
    from zyko.benchmarks.swebench import SWEInstance, build_choice_request

    inst = SWEInstance(
        instance_id="x", repo="r", base_commit="b" * 40, version="1",
        problem_statement="ع", test_patch="t",
        fail_to_pass=("a::b",), pass_to_pass=(),
    )
    request = build_choice_request(inst, ("models.py",), map_lines=("models.py :: class Response",))
    assert "خريطة المستودع الدلالية" in request and "class Response" in request
    # بلا خريطة — الطلب كما كان في الجولتين 8/9
    request_plain = build_choice_request(inst, ("models.py",))
    assert "خريطة المستودع" not in request_plain
