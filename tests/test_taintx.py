"""اختبارات مرساة التلوث بين الإجرائيات (الموجة 27 — بنية 5).

العقد: الحدود تعبر بثلاث قنوات موثقة (معاملات/عوائد/مصادر)، الغموض
تخطٍ معلن، العودية تثبت، العائلتان منفصلتان، والحتمية بالبايت.
"""

from __future__ import annotations

import ast
import json

from zyko.reviewer.taintx import collect_inter_taints


def _run(src: str):
    return collect_inter_taints(ast.parse(src))


def test_param_flow_across_functions():
    src = (
        "def sink(data):\n"
        "    os.system(data)\n"          # المعامل يستخدم في حوض
        "def source():\n"
        "    name = input('؟ ')\n"
        "    sink(name)\n"
    )
    res = _run(src)
    inp = res["input"]
    assert inp.functions["source"]["tainted_locals"] == ["name"]
    assert inp.functions["sink"]["tainted_params"] == ["data"]
    assert {"caller": "source", "callee": "sink", "param": "data", "line": 5} in inp.flows


def test_return_flow_back_to_caller():
    src = (
        "def grab():\n"
        "    return input('؟ ')\n"
        "def main():\n"
        "    x = grab()\n"
        "    os.system(x)\n"
    )
    inp = _run(src)["input"]
    assert inp.functions["grab"]["returns_tainted"] is True
    assert inp.functions["main"]["tainted_locals"] == ["x"]


def test_return_of_param_propagates():
    src = (
        "def relay(p):\n"
        "    return p\n"
        "def start():\n"
        "    q = input()\n"
        "    z = relay(q)\n"
        "    os.system(z)\n"
    )
    inp = _run(src)["input"]
    assert inp.functions["relay"]["tainted_params"] == ["p"]
    assert inp.functions["relay"]["returns_tainted"] is True
    assert inp.functions["start"]["tainted_locals"] == ["q", "z"]


def test_request_family_separate_from_input():
    src = (
        "def view(request):\n"
        "    q = request.args.get('q')\n"
        "    sink(q)\n"
        "def sink(data):\n"
        "    log(data)\n"
    )
    res = _run(src)
    assert res["request"].functions["sink"]["tainted_params"] == ["data"]
    assert res["input"].functions["sink"]["tainted_params"] == []  # العائلتان منفصلتان


def test_no_taint_no_flows():
    src = "def a():\n    return 1\n\ndef b():\n    return a() + 2\n"
    res = _run(src)
    assert res["input"].flows == ()
    assert res["input"].functions["b"]["tainted_locals"] == []


def test_recursion_terminates():
    src = (
        "def rec(n):\n"
        "    if n > 0:\n"
        "        return rec(n - 1)\n"
        "    return input()\n"
    )
    inp = _run(src)["input"]  # لا تعليق ولا انفجار
    assert inp.functions["rec"]["returns_tainted"] is True


def test_ambiguous_simple_name_skipped_documented():
    src = (
        "def f(x):\n"
        "    return x\n"
        "def f(x):\n"
        "    return 1\n"
        "def start():\n"
        "    q = input()\n"
        "    f(q)\n"
    )
    inp = _run(src)["input"]
    assert inp.flows == ()  # غامض: تخطٍ معلن لا تخمين
    assert inp.functions["start"]["tainted_locals"] == ["q"]  # المصدر المحلي يعمل


def test_keyword_argument_resolves_by_name():
    src = (
        "def sink(data=None):\n"
        "    os.system(data or '')\n"
        "def start():\n"
        "    q = input()\n"
        "    sink(data=q)\n"
    )
    inp = _run(src)["input"]
    assert inp.functions["sink"]["tainted_params"] == ["data"]


def test_byte_determinism():
    src = (
        "def sink(data):\n"
        "    os.system(data)\n"
        "def source():\n"
        "    name = input()\n"
        "    sink(name)\n"
    )
    j1 = json.dumps({k: v.to_dict() for k, v in _run(src).items()}, sort_keys=True)
    j2 = json.dumps({k: v.to_dict() for k, v in _run(src).items()}, sort_keys=True)
    assert j1 == j2
    assert json.loads(j1)["input"]["schema"] == "zyko.taintx/1"
