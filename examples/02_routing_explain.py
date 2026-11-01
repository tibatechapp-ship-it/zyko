"""02 — Verifiable routing: see the plan before spending a cent."""

from zyko import Zyko

zk = Zyko()

# Planning only — no API call, no cost. Every score component is explicit:
# quality (from the benchmark ledger), cost, latency — with published weights.
plan = zk.explain()

print(f"strategy: {plan['strategy']}\n")
for i, entry in enumerate(plan["ranking"][:8], 1):
    cost = entry["estimated_cost_usd"]
    cost_s = "-" if cost is None else f"${cost:.7f}"
    print(
        f"{i:2}. {entry['candidate']:<44} "
        f"score={entry['total']:.3f} (q={entry['quality']:.2f} c={entry['cost_score']:.2f} l={entry['latency_score']:.2f}) "
        f"~{cost_s}/req"
    )

# The same breakdown ships inside every receipt, so any past decision can be
# replayed and checked offline. That is what "verifiable routing" means.
