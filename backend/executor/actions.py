"""
Mock execution of recovery actions. No real payment/notification systems are called -
each action's outcome is simulated using the transaction's hidden ground-truth recovery
probability (which is already degradation-aware, see data/generate_transactions.py),
adjusted per action type, plus randomness. Every action + outcome is logged to the
audit log via executor/audit_log.py.

Ground-truth probability selection (this is what makes agent vs baseline diverge):
  - retry_now: uses `ground_truth_recovery_probability` as-is - i.e. "right now", which
    is LOW if the transaction is degradation-linked and still inside the outage window.
  - retry_delayed / reroute_gateway (when degradation-linked): uses
    `ground_truth_recovery_probability_after_recovery` - the probability once the
    underlying gateway issue has resolved, since the agent deliberately waited it out
    or routed around it.
  - send_discount / send_reminder / escalate: apply a fixed uplift to the base "now"
    probability, modeling the intervention's own persuasive effect.
  - give_up: never recovers (by definition).

ACTION_COST_RS is a flat nominal cost per executed action (SMS/notification/gateway
call overhead), applied uniformly regardless of action type, per the buildathon spec.
"""

import numpy as np

ACTION_COST_RS = 2.0


def already_processed(conn, transaction_id: str, policy: str) -> bool:
    """Idempotency guard: True if this (transaction_id, policy) pair already has a
    completed outcome recorded. Checked by the pipeline orchestrator before executing
    an action, so re-running a batch (e.g. clicking 'Run agent' twice without
    re-diagnosing in between) can't execute the same transaction again and
    double-count its recovered revenue in metrics/evaluate.py's aggregation - it has
    no other way to distinguish "two real outcome rows" from "one outcome counted
    twice"."""
    row = conn.execute(
        "SELECT 1 FROM outcomes o JOIN actions_taken a ON o.action_id = a.action_id "
        "WHERE o.transaction_id = ? AND o.policy = ? LIMIT 1",
        (transaction_id, policy),
    ).fetchone()
    return row is not None

# fixed per-action probability adjustments applied to the "now" ground truth probability
DISCOUNT_UPLIFT_BASE = 0.20   # scaled further by discount_pct / MAX_DISCOUNT_PCT
REMINDER_UPLIFT = 0.15
ESCALATE_UPLIFT = 0.30
RETRY_DELAYED_NONDEGRADED_UPLIFT = 0.10  # customer given time, e.g. insufficient_funds -> payday

_rng = np.random.default_rng(2026)


def _resolve_probability(action: str, txn: dict, discount_pct: int | None) -> float:
    now_prob = float(txn.get("ground_truth_recovery_probability", 0.0))
    after_recovery_prob = float(txn.get(
        "ground_truth_recovery_probability_after_recovery", now_prob
    ))
    degradation_linked = bool(txn.get("degradation_linked", False))

    if action == "give_up":
        return 0.0
    if action == "retry_now":
        return now_prob
    if action == "retry_delayed":
        if degradation_linked:
            return after_recovery_prob
        return float(np.clip(now_prob + RETRY_DELAYED_NONDEGRADED_UPLIFT, 0, 0.97))
    if action == "reroute_gateway":
        return after_recovery_prob if degradation_linked else float(np.clip(now_prob + 0.10, 0, 0.97))
    if action == "send_discount":
        pct = discount_pct or 0
        uplift = DISCOUNT_UPLIFT_BASE * (pct / 15.0)
        return float(np.clip(now_prob + uplift, 0, 0.97))
    if action == "send_reminder":
        return float(np.clip(now_prob + REMINDER_UPLIFT, 0, 0.97))
    if action == "escalate":
        return float(np.clip(now_prob + ESCALATE_UPLIFT, 0, 0.97))
    return now_prob


def execute_action(action: str, txn: dict, delay_hours: int | None, discount_pct: int | None) -> dict:
    """
    Simulates executing `action` against `txn`. Returns an outcome dict:
      {success, amount_recovered, discount_cost, action_cost, net_recovered, probability_used}
    Does NOT touch the DB - the caller (pipeline orchestrator) is responsible for
    persisting actions_taken / outcomes / audit_log rows.
    """
    amount = float(txn["amount"])
    probability = _resolve_probability(action, txn, discount_pct)

    if action == "give_up":
        success = False
    else:
        success = bool(_rng.random() < probability)

    amount_recovered = amount if success else 0.0
    discount_cost = 0.0
    if action == "send_discount" and success:
        discount_cost = round(amount_recovered * (discount_pct or 0) / 100.0, 2)

    action_cost = ACTION_COST_RS if action != "give_up" else 0.0
    net_recovered = round(amount_recovered - discount_cost - action_cost, 2)

    return {
        "action_type": action,
        "success": success,
        "amount_recovered": round(amount_recovered, 2),
        "discount_cost": discount_cost,
        "action_cost": action_cost,
        "net_recovered": net_recovered,
        "probability_used": round(probability, 4),
        "delay_hours": delay_hours,
        "discount_pct": discount_pct,
    }
