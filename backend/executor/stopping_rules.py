"""
Real enforcement of recovery stopping rules. This is the safety layer that runs
AFTER a decision (from either policy) and BEFORE any action is executed - it can
override or block a decision regardless of what the agent/baseline said.

Rules enforced:
  - MAX_RETRIES: no more than 3 retry attempts total per transaction (retry_now
    or retry_delayed both count as a retry attempt).
  - MIN_COOLDOWN_HOURS: a retry_delayed must specify at least 4 hours delay.
  - MAX_DISCOUNT_PCT: send_discount can never exceed 15%.
  - ESCALATION_TRIGGER: if retry_count_so_far >= 2 AND failure_type == 'bank_decline',
    the only allowed actions are escalate or give_up - any retry is blocked and
    force-converted to escalate.
"""

MAX_RETRIES = 3
MIN_COOLDOWN_HOURS = 4
MAX_DISCOUNT_PCT = 15
ESCALATION_RETRY_THRESHOLD = 2
ESCALATION_FAILURE_TYPE = "bank_decline"

RETRY_DECISIONS = {"retry_now", "retry_delayed"}


def check_and_enforce(decision: dict, txn: dict) -> dict:
    """
    Takes a raw decision dict + the source transaction, returns:
      {
        "allowed_action": str,        # the action to actually execute (may differ from decision["decision"])
        "allowed": bool,               # False if the original decision was blocked/overridden
        "block_reason": str | None,
        "delay_hours": int | None,     # clamped/validated
        "discount_pct": int | None,    # clamped/validated
      }
    Never mutates the input decision.
    """
    retry_count_so_far = int(txn.get("retry_count_so_far", 0))
    failure_type = txn.get("failure_type")
    requested_action = decision["decision"]
    delay_hours = decision.get("delay_hours")
    discount_pct = decision.get("discount_pct")

    block_reason = None
    allowed_action = requested_action

    # Escalation trigger overrides everything else
    if (retry_count_so_far >= ESCALATION_RETRY_THRESHOLD and failure_type == ESCALATION_FAILURE_TYPE
            and requested_action in RETRY_DECISIONS):
        allowed_action = "escalate"
        block_reason = (
            f"escalation_trigger: retry_count_so_far={retry_count_so_far} >= "
            f"{ESCALATION_RETRY_THRESHOLD} and failure_type='{ESCALATION_FAILURE_TYPE}'"
        )

    # Max retries cap
    elif requested_action in RETRY_DECISIONS and retry_count_so_far >= MAX_RETRIES:
        allowed_action = "give_up"
        block_reason = f"max_retries_exceeded: retry_count_so_far={retry_count_so_far} >= {MAX_RETRIES}"

    # Cooldown enforcement on retry_delayed
    elif requested_action == "retry_delayed":
        if delay_hours is None or delay_hours < MIN_COOLDOWN_HOURS:
            delay_hours = MIN_COOLDOWN_HOURS
            block_reason = f"cooldown_enforced: delay_hours raised to minimum {MIN_COOLDOWN_HOURS}"

    # Discount cap enforcement
    if requested_action == "send_discount":
        if discount_pct is None:
            discount_pct = MAX_DISCOUNT_PCT
        elif discount_pct > MAX_DISCOUNT_PCT:
            block_reason = (block_reason + "; " if block_reason else "") + \
                f"discount_capped: {discount_pct}% -> {MAX_DISCOUNT_PCT}%"
            discount_pct = MAX_DISCOUNT_PCT

    return {
        "allowed_action": allowed_action,
        "allowed": allowed_action == requested_action,
        "block_reason": block_reason,
        "delay_hours": delay_hours if allowed_action == "retry_delayed" else None,
        "discount_pct": discount_pct if allowed_action == "send_discount" else None,
    }
