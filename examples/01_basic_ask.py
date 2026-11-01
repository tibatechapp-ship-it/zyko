"""01 — Hello ZYKO: one routed, policy-checked, receipted completion."""

from zyko import Zyko

zk = Zyko()  # provider keys come from the environment (e.g. OPENAI_API_KEY)

outcome = zk.ask("Explain Policy-as-Code in one sentence.")

print(outcome.response.text)
print("\n--- routing receipt ---")
receipt = outcome.receipt
print("chosen  :", receipt["chosen"])
print("strategy:", receipt["strategy"])
print("attempts:", receipt["attempts"])
print("top 3   :")
for entry in receipt["ranking"][:3]:
    print(f"  {entry['candidate']:<40} score={entry['total']:.3f}")
