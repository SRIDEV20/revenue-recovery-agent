"""
Unit tests for the safety-layer stopping rules in executor/stopping_rules.py.
These rules run after a decision (from either policy) and before execution, and
can override the decision regardless of what produced it.
"""

from executor.stopping_rules import check_and_enforce, MAX_DISCOUNT_PCT


def test_discount_over_cap_is_clipped_to_max():
    decision = {"decision": "send_discount", "discount_pct": 40, "delay_hours": None}
    txn = {"retry_count_so_far": 0, "failure_type": "cart_abandonment"}

    result = check_and_enforce(decision, txn)

    assert result["allowed_action"] == "send_discount"
    assert result["discount_pct"] == MAX_DISCOUNT_PCT
    assert result["block_reason"] is not None
    assert "discount_capped" in result["block_reason"]


def test_fourth_retry_attempt_is_converted_to_give_up():
    decision = {"decision": "retry_now", "discount_pct": None, "delay_hours": None}
    txn = {"retry_count_so_far": 3, "failure_type": "otp_timeout"}

    result = check_and_enforce(decision, txn)

    assert result["allowed_action"] == "give_up"
    assert result["allowed"] is False
    assert "max_retries_exceeded" in result["block_reason"]


def test_repeated_bank_decline_retry_is_converted_to_escalate():
    decision = {"decision": "retry_now", "discount_pct": None, "delay_hours": None}
    txn = {"retry_count_so_far": 2, "failure_type": "bank_decline"}

    result = check_and_enforce(decision, txn)

    assert result["allowed_action"] == "escalate"
    assert result["allowed"] is False
    assert "escalation_trigger" in result["block_reason"]


def test_repeated_bank_decline_retry_delayed_is_also_converted_to_escalate():
    decision = {"decision": "retry_delayed", "discount_pct": None, "delay_hours": 6}
    txn = {"retry_count_so_far": 2, "failure_type": "bank_decline"}

    result = check_and_enforce(decision, txn)

    assert result["allowed_action"] == "escalate"
    assert result["allowed"] is False


def test_valid_in_bounds_decision_passes_through_unchanged():
    decision = {"decision": "retry_delayed", "discount_pct": None, "delay_hours": 6}
    txn = {"retry_count_so_far": 0, "failure_type": "insufficient_funds"}

    result = check_and_enforce(decision, txn)

    assert result["allowed_action"] == "retry_delayed"
    assert result["allowed"] is True
    assert result["block_reason"] is None
    assert result["delay_hours"] == 6


def test_cooldown_below_minimum_is_raised_to_minimum():
    decision = {"decision": "retry_delayed", "discount_pct": None, "delay_hours": 1}
    txn = {"retry_count_so_far": 0, "failure_type": "insufficient_funds"}

    result = check_and_enforce(decision, txn)

    assert result["allowed_action"] == "retry_delayed"
    assert result["delay_hours"] == 4
    assert "cooldown_enforced" in result["block_reason"]
