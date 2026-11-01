"""Kernel math + parity between backends."""

from __future__ import annotations

import math

from zyko import kernel
from zyko.kernel import python_impl


def test_estimate_tokens():
    assert python_impl.estimate_tokens("") == 0
    # "hello world" → 11 chars → ceil(11/4)=3, 2 words → 3
    assert python_impl.estimate_tokens("hello world") == 3
    # long word without spaces: word count dominates
    assert python_impl.estimate_tokens("a" * 3) == 1


def test_estimate_messages_tokens():
    from zyko.core.messages import Message

    total = python_impl.estimate_messages_tokens([Message.user("hi there friend")])
    assert total == python_impl.estimate_tokens("hi there friend") + 4


def test_cosine_similarity():
    assert python_impl.cosine_similarity([1, 0], [1, 0]) == pytest_approx(1.0)
    assert python_impl.cosine_similarity([1, 0], [0, 1]) == pytest_approx(0.0)
    assert python_impl.cosine_similarity([], []) == 0.0


def pytest_approx(value):
    class _A:
        def __eq__(self, other):
            return math.isclose(other, value, rel_tol=1e-9)

    return _A()


def test_top_k_and_moving_average():
    assert python_impl.top_k([0.1, 0.9, 0.5], 2) == [1, 2]
    assert python_impl.moving_average([1, 2, 3], 2) == [1.0, 1.5, 2.5]


def test_kernel_backend_is_consistent():
    assert kernel.backend() in ("python", "rust")
    # public API equals python reference when running on the python backend
    assert kernel.estimate_tokens("hello world") == python_impl.estimate_tokens("hello world")
    assert kernel.top_k([0.1, 0.9, 0.5], 2) == [1, 2]


def test_bench_suite_is_deterministic():
    from zyko.benchmarks.routing_bench import build_suite, suite_hash

    a, b = build_suite(), build_suite()
    assert [t.prompt for t in a] == [t.prompt for t in b]
    assert suite_hash(a) == suite_hash(b)
    assert len(a) == 24
    categories = {t.category for t in a}
    assert categories == {"instruction_following", "extraction", "classification", "math", "summarization", "format"}


def test_bench_graders():
    from zyko.benchmarks.routing_bench import GRADERS

    assert GRADERS["exact"]("  River-Market-Signal\n", "river-market-signal", {})
    assert GRADERS["contains_all"]("has market and river", "market||river", {})
    assert GRADERS["json"]('sure: {"units": 5, "topic": "energy"}', "units,topic", {})
    assert GRADERS["numeric"]("The answer is 1,234.", "1234", {})
    assert GRADERS["regex"]("ID[river:07]", r"ID\[river:07\]", {})
    assert not GRADERS["json"]("no json here", "units,topic", {})
