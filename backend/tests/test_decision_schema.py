"""
Tests for agent/decision_schema.py: the defense-in-depth validation layer both
policies' decisions pass through in pipeline.py before being persisted/executed.
"""

import pytest

from agent.decision_schema import validate_decision

VALID_DECISION = {
    "transaction_id": "txn_1",
    "decision": "retry_now",
    "reasoning": "otp_timeout is transient, safe to retry immediately.",
    "confidence": 0.8,
    "delay_hours": None,
    "discount_pct": None,
}


def test_valid_decision_passes_through():
    result = validate_decision(VALID_DECISION)

    assert result["transaction_id"] == "txn_1"
    assert result["decision"] == "retry_now"


def test_decision_missing_required_field_is_rejected():
    incomplete = dict(VALID_DECISION)
    del incomplete["reasoning"]

    with pytest.raises(ValueError):
        validate_decision(incomplete)


def test_decision_missing_confidence_is_rejected():
    incomplete = dict(VALID_DECISION)
    del incomplete["confidence"]

    with pytest.raises(ValueError):
        validate_decision(incomplete)


def test_decision_outside_allowed_enum_is_rejected():
    invalid = dict(VALID_DECISION)
    invalid["decision"] = "teleport_customer"

    with pytest.raises(ValueError):
        validate_decision(invalid)
