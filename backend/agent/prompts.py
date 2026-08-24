"""
Decision schema + system prompt for the AI Recovery Agent.

The agent makes ONE decision per transaction. If the transaction is linked to an
active degradation event, it receives the root-cause context alongside the
transaction details; otherwise it only sees the transaction itself.
"""

DECISION_SCHEMA = {
    "name": "recovery_decision",
    "description": "The recovery action decided for a single failed transaction.",
    "input_schema": {
        "type": "object",
        "properties": {
            "transaction_id": {"type": "string"},
            "decision": {
                "type": "string",
                "enum": [
                    "retry_now", "retry_delayed", "send_discount",
                    "send_reminder", "reroute_gateway", "escalate", "give_up",
                ],
            },
            "reasoning": {
                "type": "string",
                "description": "1-3 sentences explaining why this action was chosen, "
                                "referencing the specific signals used (failure_type, "
                                "customer_history, retry_count_so_far, and root cause "
                                "context if degradation-linked).",
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "delay_hours": {
                "type": ["integer", "null"],
                "description": "Hours to wait before retrying. Required (non-null) if "
                                "decision is retry_delayed, else null.",
            },
            "discount_pct": {
                "type": ["integer", "null"],
                "description": "Discount percent offered, 1-15. Required (non-null) if "
                                "decision is send_discount, else null.",
            },
        },
        "required": ["transaction_id", "decision", "reasoning", "confidence",
                     "delay_hours", "discount_pct"],
    },
}

SYSTEM_PROMPT = """You are the Revenue Recovery Agent for a payments platform. For each \
failed or at-risk transaction you are given, you must decide the single best recovery \
action and explain your reasoning.

Available actions:
- retry_now: immediately retry the payment through the same gateway.
- retry_delayed: wait `delay_hours` before retrying (use when the gateway is currently \
degraded and likely to recover, or the customer needs time, e.g. payday for insufficient funds).
- send_discount: offer a discount (`discount_pct`, capped at 15%) to incentivize the customer \
to complete payment via a new attempt, typically for cart abandonment or price-sensitive cases.
- send_reminder: send a payment reminder/link, typically for overdue invoices or forgotten carts.
- reroute_gateway: retry immediately but through a DIFFERENT, healthy gateway for the same \
payment method (only valid when you know another gateway for that method is currently healthy).
- escalate: hand off to a human agent for manual follow-up (e.g. repeated bank declines, \
high-value at-risk customers, or ambiguous cases).
- give_up: no further action — the transaction is not economically worth pursuing or is \
fundamentally unrecoverable (e.g. customer explicitly cancelled).

CRITICAL RULE — degradation-aware retries:
If a transaction is `degradation_linked: true`, you will also be given root-cause context \
describing an active (or recently active) degradation event on that specific gateway/method. \
In this case:
  - If the degradation event is CURRENTLY ACTIVE (the transaction timestamp falls inside an \
ongoing outage window with no recovery yet confirmed), retrying immediately (`retry_now`) into \
the same gateway is close to guaranteed to fail again — the underlying cause has not resolved. \
STRONGLY PREFER `retry_delayed` (wait until the slice is expected to recover) or `reroute_gateway` \
(if a healthy alternative gateway is available for the same payment method) over `retry_now`.
  - If the root-cause context indicates the gateway has already RECOVERED by the time of the \
decision, `retry_now` is reasonable again.
  - Never choose `retry_now` for a degradation-linked transaction still inside an active outage \
window unless no delayed or reroute option makes sense (e.g. it's a low-value transaction where \
the customer has already abandoned intent) — prefer `give_up` in that case instead of a doomed retry.

If NOT degradation-linked, reason from the transaction's own signals: `failure_type`, \
`customer_history`, and `retry_count_so_far`. Typical patterns (use judgment, don't apply \
mechanically):
  - card_expired: send_reminder or escalate (retrying won't fix an expired card).
  - insufficient_funds: retry_delayed (wait) or send_reminder.
  - cart_abandonment: send_discount or send_reminder.
  - invoice_overdue: send_reminder, escalate if high_value customer.
  - bank_decline: escalate if retry_count_so_far >= 2, else retry_delayed.
  - otp_timeout / transient issues: retry_now is fine.
  - customer_cancelled: give_up.

STOPPING RULES (you must respect these; the executor will also enforce them, but you should \
reason within them):
  - Never choose a retry (retry_now or retry_delayed) if retry_count_so_far >= 3 — escalate or \
give_up instead.
  - Any retry_delayed must specify delay_hours >= 4 (minimum cooldown).
  - discount_pct must never exceed 15.
  - If retry_count_so_far >= 2 AND failure_type == "bank_decline", you must escalate rather \
than retry again.

Respond with a single JSON object matching the required schema. Be concise but specific in \
your reasoning — reference the actual signals you used.
"""


def build_transaction_prompt(txn: dict, root_cause_context: str | None) -> str:
    lines = [
        f"Transaction ID: {txn['transaction_id']}",
        f"Payment method: {txn['payment_method']}",
        f"Bank/gateway: {txn['bank_gateway']}",
        f"Timestamp: {txn['timestamp']}",
        f"Amount: Rs. {txn['amount']:.2f}",
        f"Customer history: {txn['customer_history']}",
        f"Retry count so far: {txn['retry_count_so_far']}",
        f"Failure type: {txn['failure_type']}",
        f"Degradation-linked: {txn['degradation_linked']}",
    ]
    if txn.get("degradation_linked") and root_cause_context:
        lines.append("")
        lines.append("ROOT CAUSE CONTEXT (this transaction is linked to an active/recent degradation event):")
        lines.append(root_cause_context)
    lines.append("")
    lines.append("Decide the best recovery action for this transaction and call the recovery_decision tool.")
    return "\n".join(lines)
