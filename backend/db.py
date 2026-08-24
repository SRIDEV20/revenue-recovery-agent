"""
SQLite schema + connection helpers for the Revenue Recovery Agent.

Tables:
  payment_health     - raw hourly health metrics per (payment_method, bank_gateway)
  transactions        - individual failed/at-risk transactions (+ hidden ground-truth cols)
  degradation_events  - anomaly-detector output: flagged degraded slices/windows
  decisions           - per-transaction agent/baseline decisions + reasoning
  actions_taken       - executed actions after stopping-rule checks
  outcomes            - simulated result of each executed action
  audit_log           - append-only log of every decision/rule-check/action/outcome

The live DB file (revenue_recovery.db) is NOT committed to the repo; only this
schema module and the CSV seed data under backend/data/ are.
"""

import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "revenue_recovery.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS payment_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    bank_gateway TEXT NOT NULL,
    success_rate REAL NOT NULL,
    avg_latency_ms REAL NOT NULL,
    transaction_volume INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_health_slice_time
    ON payment_health (payment_method, bank_gateway, timestamp);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    payment_method TEXT NOT NULL,
    bank_gateway TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    amount REAL NOT NULL,
    customer_id TEXT NOT NULL,
    customer_history TEXT NOT NULL,
    retry_count_so_far INTEGER NOT NULL,
    failure_type TEXT NOT NULL,
    degradation_linked INTEGER NOT NULL,
    ground_truth_recoverable INTEGER,
    ground_truth_recovery_probability REAL,
    ground_truth_recovery_probability_after_recovery REAL
);
CREATE INDEX IF NOT EXISTS idx_txn_slice_time
    ON transactions (payment_method, bank_gateway, timestamp);

CREATE TABLE IF NOT EXISTS degradation_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_method TEXT NOT NULL,
    bank_gateway TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    baseline_rate REAL NOT NULL,
    current_rate REAL NOT NULL,
    severity TEXT NOT NULL,
    z_score REAL,
    root_cause_statement TEXT,
    detected_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT NOT NULL,
    policy TEXT NOT NULL,               -- 'agent' | 'baseline'
    decision TEXT NOT NULL,             -- retry_now | retry_delayed | send_discount | ...
    reasoning TEXT,
    confidence REAL,
    delay_hours INTEGER,
    discount_pct INTEGER,
    degradation_linked INTEGER NOT NULL,
    event_id INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (transaction_id) REFERENCES transactions (transaction_id),
    FOREIGN KEY (event_id) REFERENCES degradation_events (event_id)
);

CREATE TABLE IF NOT EXISTS actions_taken (
    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL,
    transaction_id TEXT NOT NULL,
    policy TEXT NOT NULL,
    action_type TEXT NOT NULL,
    allowed INTEGER NOT NULL,          -- 1 if stopping rules permitted it, 0 if blocked
    block_reason TEXT,
    executed_at TEXT NOT NULL,
    FOREIGN KEY (decision_id) REFERENCES decisions (decision_id)
);

CREATE TABLE IF NOT EXISTS outcomes (
    outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id INTEGER NOT NULL,
    transaction_id TEXT NOT NULL,
    policy TEXT NOT NULL,
    success INTEGER NOT NULL,
    amount_recovered REAL NOT NULL,
    discount_cost REAL NOT NULL,
    action_cost REAL NOT NULL,
    net_recovered REAL NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (action_id) REFERENCES actions_taken (action_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    transaction_id TEXT,
    policy TEXT,
    stage TEXT NOT NULL,               -- 'decision' | 'rule_check' | 'action' | 'outcome' | 'escalation'
    detail TEXT NOT NULL               -- JSON blob
);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_session():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(reset: bool = False):
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    with db_session() as conn:
        conn.executescript(SCHEMA)
    print(f"DB initialized at {DB_PATH}")


def clear_run_tables():
    """Clear tables that get rebuilt each pipeline run, keep nothing stale between runs."""
    with db_session() as conn:
        for table in ["outcomes", "actions_taken", "decisions", "degradation_events",
                      "audit_log", "transactions", "payment_health"]:
            conn.execute(f"DELETE FROM {table}")


if __name__ == "__main__":
    init_db(reset=True)
