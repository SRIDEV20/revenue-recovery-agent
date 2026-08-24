"""
Baseline policy - the control group the AI Recovery Agent is measured against.

This policy is deliberately naive and degradation-blind: it retries every failed
transaction exactly once, immediately, regardless of whether the transaction's
gateway is currently in an active degradation window. It represents "what most
systems do today" - a dumb retry-on-failure loop with no awareness of systemic
root cause. It still respects the hard stopping rules (won't retry past the cap),
but has no concept of delay/reroute/root-cause-awareness at all.
"""


def decide_single_baseline(txn: dict) -> dict:
    """No API call - deterministic, rule-free policy. Always retries now unless
    the transaction has already exhausted the retry cap, in which case it gives up
    (a naive system still can't retry past a hard technical limit)."""
    retry_count_so_far = int(txn.get("retry_count_so_far", 0))
    MAX_RETRIES = 3  # same hard technical cap as the agent's stopping rules

    if retry_count_so_far >= MAX_RETRIES:
        decision = "give_up"
        reasoning = f"Retry cap ({MAX_RETRIES}) already reached; no further attempts possible."
    else:
        decision = "retry_now"
        reasoning = "Baseline policy: retry immediately on any failure, blind to gateway health."

    return {
        "transaction_id": txn["transaction_id"],
        "decision": decision,
        "reasoning": reasoning,
        "confidence": 1.0,
        "delay_hours": None,
        "discount_pct": None,
        "policy": "baseline",
        "degradation_linked": bool(txn.get("degradation_linked", False)),
    }


def run_batch_baseline(transactions: list[dict]) -> list[dict]:
    return [decide_single_baseline(txn) for txn in transactions]
