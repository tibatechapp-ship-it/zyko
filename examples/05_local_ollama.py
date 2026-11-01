"""05 — Local & offline: Ollama as a keyless, private routing candidate.

Start Ollama (laptop or phone/Termux):  ollama serve  +  ollama pull llama3.2
Then this script runs with ZERO API keys and ZERO data leaving the machine.
"""

from zyko import Zyko

zk = Zyko(strategy="cost")  # local models are $0 — cost strategy loves them

plan = zk.explain()
local = [e for e in plan["ranking"] if e["candidate"].startswith("ollama/")]
print("ollama candidates:", [e["candidate"] for e in local] or "(ollama not running)")

try:
    outcome = zk.ask("In one sentence: why is local inference valuable?")
    print("\n", outcome.response.text)
    print("routed via:", outcome.receipt["chosen"])
except Exception as exc:
    print("\n(ollama unreachable — start it and retry:", exc, ")")
