"""The reproducible ZYKO routing benchmark.

Design principles (see docs + README):
- **Deterministic**: a fixed seed generates the task suite; the same version
  + seed always yields the same tasks and graders, so two runs are comparable
  and any score in the ledger can be re-derived.
- **Honest**: scores come only from real model calls graded by objective
  checkers (exact match, JSON validity, numeric equality, regex, keywords).
  No provider claims, no synthetic numbers, no invented results.
- **Reproducible**: output JSON records zyko version, seed, suite hash and
  per-task verdicts; `--update-ledger` merges aggregates into the ledger the
  router uses.

Usage:
    zyko bench                       # runs against every configured provider
    zyko bench --update-ledger       # also write scores into the ledger
    zyko bench --json-out out.json   # keep the full per-task report
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from zyko import kernel
from zyko.cli import ui
from zyko.config.settings import Settings
from zyko.core.messages import Message
from zyko.core.response import ChatRequest
from zyko.exceptions import ZykoError
from zyko.log import get_logger
from zyko.platform.paths import ledger_file
from zyko.providers import configured_providers
from zyko.router.engine import Router
from zyko.router.quality import QualityLedger
from zyko.version import __version__

log = get_logger("bench")

SEED = 42

_WORDS = [
    "river",
    "market",
    "signal",
    "copper",
    "window",
    "forest",
    "planet",
    "engine",
    "shadow",
    "lantern",
    "harbor",
    "meadow",
    "circuit",
    "marble",
    "anchor",
    "puzzle",
]
_TOPICS = ["logistics", "energy", "health", "education", "agriculture", "transport"]


# --------------------------------------------------------------------- tasks
@dataclass
class Task:
    tid: str
    category: str
    prompt: str
    grader: str  # checker name
    expected: str  # grader argument
    extra: dict[str, Any] = field(default_factory=dict)


def _grade_exact(answer: str, expected: str, extra: dict[str, Any]) -> bool:
    return answer.strip().lower() == expected.strip().lower()


def _grade_contains_all(answer: str, expected: str, extra: dict[str, Any]) -> bool:
    needles = expected.split("||")
    low = answer.lower()
    return all(n.strip().lower() in low for n in needles)


def _grade_json(answer: str, expected: str, extra: dict[str, Any]) -> bool:
    match = re.search(r"\{.*\}", answer, re.S)
    if not match:
        return False
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and all(k in data for k in expected.split(","))


def _grade_numeric(answer: str, expected: str, extra: dict[str, Any]) -> bool:
    numbers = re.findall(r"-?\d+(?:\.\d+)?", answer.replace(",", ""))
    if not numbers:
        return False
    try:
        return abs(float(numbers[0]) - float(expected)) < 0.01
    except ValueError:
        return False


def _grade_regex(answer: str, expected: str, extra: dict[str, Any]) -> bool:
    return re.search(expected, answer) is not None


GRADERS: dict[str, Callable[[str, str, dict[str, Any]], bool]] = {
    "exact": _grade_exact,
    "contains_all": _grade_contains_all,
    "json": _grade_json,
    "numeric": _grade_numeric,
    "regex": _grade_regex,
}


def build_suite(seed: int = SEED) -> list[Task]:
    """Deterministic 24-task suite: 4 tasks per category × 6 categories."""
    rng = random.Random(seed)
    tasks: list[Task] = []

    # 1. instruction_following — strict format
    for i in range(4):
        w1, w2, w3 = rng.sample(_WORDS, 3)
        tasks.append(
            Task(
                f"if_{i}",
                "instruction_following",
                f"Reply with EXACTLY this line and nothing else: {w1}-{w2}-{w3}",
                "exact",
                f"{w1}-{w2}-{w3}",
            )
        )

    # 2. extraction — pull structured fields from a mini-record
    for i in range(4):
        name = rng.choice(_WORDS).title()
        topic = rng.choice(_TOPICS)
        amount = rng.randint(100, 9999)
        tasks.append(
            Task(
                f"ex_{i}",
                "extraction",
                f"Record: {name} ordered {amount} units for the {topic} division. "
                'Reply with JSON only: {"units": <number>, "topic": "<topic>"}',
                "json",
                "units,topic",
            )
        )

    # 3. classification — fixed label set
    labels = {
        "river": "nature",
        "market": "economy",
        "engine": "technology",
        "forest": "nature",
        "harbor": "economy",
        "circuit": "technology",
        "meadow": "nature",
        "lantern": "technology",
        "anchor": "economy",
    }
    for i in range(4):
        word = rng.choice(list(labels))
        tasks.append(
            Task(
                f"cl_{i}",
                "classification",
                f'Classify the word "{word}" into exactly one of: nature, economy, technology. '
                "Answer with the label only.",
                "exact",
                labels[word],
            )
        )

    # 4. math — deterministic arithmetic
    for i in range(4):
        a, b, c = rng.randint(11, 99), rng.randint(2, 9), rng.randint(2, 9)
        expected = a * b + c
        tasks.append(
            Task(
                f"math_{i}",
                "math",
                f"Compute {a} * {b} + {c}. Reply with the number only.",
                "numeric",
                str(expected),
            )
        )

    # 5. summarization — keyword-preserving compression
    for i in range(4):
        keep = rng.sample(_WORDS, 3)
        story = (
            f"The quarterly report mentions {keep[0]} capacity doubled while {keep[1]} "
            f"costs fell; the {keep[2]} program remains funded next year."
        )
        tasks.append(
            Task(
                f"sum_{i}",
                "summarization",
                f"Summarize in one sentence, keeping the words {keep[0]}, {keep[1]} and {keep[2]}:\n{story}",
                "contains_all",
                "||".join(keep),
            )
        )

    # 6. format — output templating (regex-graded)
    for i in range(4):
        word = rng.choice(_WORDS)
        n = rng.randint(1, 99)
        tasks.append(
            Task(
                f"fmt_{i}",
                "format",
                f'Produce one line in the form "ID[{word}:{n:02d}]" with those exact values.',
                "regex",
                rf"ID\[{re.escape(word)}:{n:02d}\]",
            )
        )
    return tasks


def suite_hash(tasks: list[Task]) -> str:
    payload = "|".join(f"{t.tid}:{t.prompt}:{t.grader}:{t.expected}" for t in tasks)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ----------------------------------------------------------------- execution
async def _run_candidate(
    router: Router, provider_name: str, model: str, tasks: list[Task], concurrency: int
):
    provider = router.providers[provider_name]
    info = provider.find_model(model)
    sem = asyncio.Semaphore(max(1, concurrency))
    results: list[dict[str, Any]] = []

    async def one(task: Task) -> dict[str, Any]:
        async with sem:
            request = ChatRequest(messages=[Message.user(task.prompt)], model=model, max_tokens=200)
            started = time.perf_counter()
            try:
                outcome = await provider.acomplete(request, retries=1)
                answer = outcome.text
                latency = (time.perf_counter() - started) * 1000.0
                passed = GRADERS[task.grader](answer, task.expected, task.extra)
                return {
                    "task": task.tid,
                    "category": task.category,
                    "ok": passed,
                    "latency_ms": round(latency, 1),
                    "answer": answer[:200],
                    "input_tokens": outcome.usage.input_tokens,
                    "output_tokens": outcome.usage.output_tokens,
                }
            except ZykoError as exc:
                return {
                    "task": task.tid,
                    "category": task.category,
                    "ok": False,
                    "latency_ms": round((time.perf_counter() - started) * 1000.0, 1),
                    "error": str(exc).splitlines()[0][:200],
                }

    verdicts = await asyncio.gather(*(one(t) for t in tasks))
    results.extend(verdicts)
    per_category: dict[str, list[int]] = {}
    for r in results:
        per_category.setdefault(r["category"], []).append(1 if r["ok"] else 0)
    categories = {cat: sum(v) / len(v) for cat, v in sorted(per_category.items())}
    overall = sum(categories.values()) / len(categories) if categories else 0.0
    latencies = [r["latency_ms"] for r in results if r.get("latency_ms") is not None]
    # Cost from the tokens vendors actually reported; kernel estimates only
    # as a fallback when a provider omits usage data.
    in_tok = sum(int(r.get("input_tokens") or 0) for r in results)
    out_tok = sum(int(r.get("output_tokens") or 0) for r in results)
    if in_tok == 0:
        in_tok = sum(kernel.estimate_tokens(t.prompt) for t in tasks)
    if out_tok == 0:
        out_tok = len(tasks) * 60
    cost = None
    if info is not None:
        cost = info.cost_usd(in_tok, out_tok)
    return {
        "candidate": f"{provider_name}/{model}",
        "overall": round(overall, 4),
        "categories": {k: round(v, 4) for k, v in categories.items()},
        "median_latency_ms": round(sorted(latencies)[len(latencies) // 2], 1)
        if latencies
        else None,
        "estimated_cost_usd": cost,
        "token_usage": {"input": in_tok, "output": out_tok},
        "tasks": results,
    }


def run_bench(args: Any) -> int:
    settings = Settings.load()
    if getattr(args, "demo", False) or os.environ.get("ZYKO_DEMO") == "1":
        from zyko.providers.mock import MockProvider

        providers: dict[str, Any] = {"mock": MockProvider()}
    else:
        providers = configured_providers(settings.provider_settings)
    if not providers:
        print(ui.warn("no providers configured — set an API key or start Ollama, then retry"))
        return 1

    tasks = build_suite(SEED)
    repeats = max(1, int(getattr(args, "repeats", 1) or 1))
    run_tasks = tasks * repeats if repeats > 1 else tasks
    suffix = f", repeats={repeats}" if repeats > 1 else ""
    print(
        ui.info(
            f"suite: {len(tasks)} deterministic tasks (seed={SEED}, hash={suite_hash(tasks)}{suffix})"
        )
    )
    ledger_arg = ledger_file() if not getattr(args, "ledger", None) else Path(args.ledger)
    ledger = QualityLedger.load(ledger_arg)
    router = Router(providers, ledger=ledger, strategy="quality", max_fallbacks=1)

    async def gather_all():
        jobs = []
        for provider_name, provider in sorted(providers.items()):
            for info in provider.catalog():
                jobs.append(
                    _run_candidate(router, provider_name, info.id, run_tasks, args.concurrency)
                )
        return await asyncio.gather(*jobs)

    report = {
        "zyko_version": __version__,
        "seed": SEED,
        "suite_hash": suite_hash(tasks),
        "repeats": repeats,
        "started": time.time(),
        "kernel": kernel.backend(),
        "results": [],
    }
    results = asyncio.run(gather_all())
    report["results"] = [r for r in results]
    report["finished"] = time.time()

    # console summary
    rows = [
        [r["candidate"], f"{r['overall']:.3f}", r["median_latency_ms"], r["estimated_cost_usd"]]
        for r in results
    ]
    ui.table(["candidate", "overall", "median ms", "est $/run"], rows)
    winner = max(results, key=lambda r: r["overall"]) if results else None
    if winner:
        print(ui.ok(f"best overall: {winner['candidate']} ({winner['overall']:.1%})"))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        print(ui.info(f"full report → {args.json_out}"))

    if args.update_ledger:
        others = [r["overall"] for r in results]
        for r in results:
            wins = sum(1 for o in others if r["overall"] >= o)
            win_rate = wins / len(others) if others else 0.5
            ledger.update(
                *r["candidate"].split("/", 1),
                quality=r["overall"],
                win_rate=win_rate,
                samples=len(r["tasks"]),
                categories=r["categories"],
            )
        ledger_path = ledger_file() if not getattr(args, "ledger", None) else Path(args.ledger)
        ledger.save(ledger_path)
        print(ui.ok(f"ledger updated → {ledger_path}"))
        print(ledger.to_table())
    return 0


__all__ = ["build_suite", "run_bench", "suite_hash", "GRADERS", "SEED"]
