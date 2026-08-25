"""
Tests the idempotency guard in executor/actions.py (already_processed) as exercised
by the real pipeline orchestrator: running the same (transaction_id, policy) through
pipeline.run_decision_batch twice must only ever produce one outcome row, with the
second run logged as a skipped no-op rather than a duplicate execution.

Uses the 'baseline' policy so no OpenAI call is involved. Runs against a temporary
on-disk SQLite DB (never the real backend/revenue_recovery.db).
"""

from datetime import datetime, timezone

import pandas as pd
import pytest

import db as db_module
import pipeline
from executor import audit_log

TXN_ID = "txn_idempotency_test"


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_revenue_recovery.db"
    monkeypatch.setattr(db_module, "DB_PATH", str(db_path))
    db_module.init_db(reset=True)

    with db_module.db_session() as conn:
        conn.execute(
            "INSERT INTO transactions (transaction_id, payment_method, bank_gateway, "
            "timestamp, amount, customer_id, customer_history, retry_count_so_far, "
            "failure_type, degradation_linked, ground_truth_recoverable, "
            "ground_truth_recovery_probability, ground_truth_recovery_probability_after_recovery) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (TXN_ID, "upi", "gw_a", "2026-01-01T00:00:00", 500.0, "cust_1", "regular",
             0, "otp_timeout", 0, 1, 0.9, 0.9),
        )
    return db_module


@pytest.fixture
def linked_df():
    return pd.DataFrame([{
        "transaction_id": TXN_ID,
        "payment_method": "upi",
        "bank_gateway": "gw_a",
        "timestamp": pd.Timestamp("2026-01-01T00:00:00"),
        "amount": 500.0,
        "customer_id": "cust_1",
        "customer_history": "regular",
        "retry_count_so_far": 0,
        "failure_type": "otp_timeout",
        "degradation_linked": False,
        "matched_event_index": -1,
        "ground_truth_recoverable": True,
        "ground_truth_recovery_probability": 0.9,
        "ground_truth_recovery_probability_after_recovery": 0.9,
    }])


def test_second_run_is_a_noop_not_a_duplicate(temp_db, linked_df):
    first_run = pipeline.run_decision_batch("baseline", [], linked_df)
    second_run = pipeline.run_decision_batch("baseline", [], linked_df)

    assert len(first_run) == 1
    assert len(second_run) == 0

    with temp_db.db_session() as conn:
        outcome_count = conn.execute(
            "SELECT COUNT(*) FROM outcomes WHERE transaction_id = ? AND policy = ?",
            (TXN_ID, "baseline"),
        ).fetchone()[0]
    assert outcome_count == 1

    logs = audit_log.get_log(transaction_id=TXN_ID, stage="action")
    action_types = [entry["detail"].get("action_type") for entry in logs]
    assert "skipped_duplicate" in action_types
