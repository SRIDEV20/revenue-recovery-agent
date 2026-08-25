"""
Orchestrates the full revenue recovery pipeline end to end, and persists every
stage to SQLite so the FastAPI routes and dashboard can read real results:

  payment_health.csv -> health_monitor -> anomaly_detector -> root_cause
      -> affected_transactions -> decision_engine (agent) / baseline_policy
      -> stopping_rules -> actions -> outcomes -> audit_log

Two entry points:
  run_health_and_diagnosis()  - Steps 1-6: detect events, diagnose root cause,
                                 link + persist transactions. Cheap, no API calls.
  run_decision_batch(policy)  - Step 7-10 for one policy ('agent' or 'baseline'):
                                 decide -> enforce -> execute -> persist. The
                                 'agent' policy makes real OpenAI API calls.
"""

import os
import sys
from datetime import datetime, timezone

import pandas as pd

from db import db_session, init_db
from monitoring.health_monitor import load_health_data, compute_rolling_baseline
from monitoring.anomaly_detector import detect_degradation_events
from diagnosis.root_cause import analyze
from diagnosis.affected_transactions import link_transactions_to_all_events
from agent.decision_engine import run_batch as run_agent_batch
from agent.baseline_policy import run_batch_baseline
from agent.decision_schema import validate_decision
from executor.stopping_rules import check_and_enforce
from executor.actions import execute_action, already_processed
from executor import audit_log

TXN_CSV = os.path.join(os.path.dirname(__file__), "data", "failed_transactions.csv")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_health_and_diagnosis() -> dict:
    """Steps 1-6. Persists payment_health, degradation_events, transactions.
    Returns {events: [...with root cause & db event_id...], linked_df: DataFrame}."""
    health_df = load_health_data()
    enriched = compute_rolling_baseline(health_df)
    raw_events = detect_degradation_events(enriched)
    root_causes = [analyze(e, health_df) for e in raw_events]

    transactions_df = pd.read_csv(TXN_CSV, parse_dates=["timestamp"])
    linked = link_transactions_to_all_events(transactions_df, raw_events)
    linked["degradation_linked"] = linked["linked_to_event"]

    with db_session() as conn:
        # payment_health
        health_records = health_df.copy()
        health_records["timestamp"] = health_records["timestamp"].astype(str)
        conn.executemany(
            "INSERT INTO payment_health (timestamp, payment_method, bank_gateway, "
            "success_rate, avg_latency_ms, transaction_volume) VALUES (?, ?, ?, ?, ?, ?)",
            health_records[["timestamp", "payment_method", "bank_gateway",
                             "success_rate", "avg_latency_ms", "transaction_volume"]].itertuples(
                index=False, name=None
            ),
        )

        # degradation_events
        db_event_ids = []
        for event, rc in zip(raw_events, root_causes):
            cur = conn.execute(
                "INSERT INTO degradation_events (payment_method, bank_gateway, window_start, "
                "window_end, baseline_rate, current_rate, severity, z_score, root_cause_statement, "
                "detected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event["payment_method"], event["bank_gateway"], event["window_start"],
                 event["window_end"], event["baseline_rate"], event["current_rate"],
                 event["severity"], event["z_score"], rc["root_cause_statement"], _now()),
            )
            db_event_ids.append(cur.lastrowid)
            audit_log.log_event("pipeline", {
                "action": "degradation_event_detected",
                "event": event,
                "root_cause": rc["root_cause_statement"],
                "classification": rc["classification"],
            }, conn=conn)

        # transactions
        txn_records = linked.copy()
        txn_records["timestamp"] = txn_records["timestamp"].astype(str)
        rows = []
        for _, r in txn_records.iterrows():
            rows.append((
                r["transaction_id"], r["payment_method"], r["bank_gateway"], r["timestamp"],
                float(r["amount"]), r["customer_id"], r["customer_history"],
                int(r["retry_count_so_far"]), r["failure_type"], int(bool(r["degradation_linked"])),
                int(bool(r["ground_truth_recoverable"])), float(r["ground_truth_recovery_probability"]),
                float(r["ground_truth_recovery_probability_after_recovery"]),
            ))
        conn.executemany(
            "INSERT INTO transactions (transaction_id, payment_method, bank_gateway, timestamp, "
            "amount, customer_id, customer_history, retry_count_so_far, failure_type, "
            "degradation_linked, ground_truth_recoverable, ground_truth_recovery_probability, "
            "ground_truth_recovery_probability_after_recovery) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    events_with_context = []
    for event, rc, db_id in zip(raw_events, root_causes, db_event_ids):
        events_with_context.append({**event, **rc, "event_id": db_id})

    return {"events": events_with_context, "linked": linked}


def _root_cause_context_map(linked: pd.DataFrame, events_with_context: list[dict]) -> dict:
    ctx = {}
    for _, row in linked[linked.degradation_linked].iterrows():
        idx = int(row["matched_event_index"])
        if 0 <= idx < len(events_with_context):
            ctx[row["transaction_id"]] = events_with_context[idx]["root_cause_statement"]
    return ctx


def run_decision_batch(policy: str, events_with_context: list[dict], linked: pd.DataFrame,
                        progress_callback=None) -> list[dict]:
    """policy: 'agent' or 'baseline'. Runs decisions -> stopping rules -> actions -> persists all."""
    assert policy in ("agent", "baseline")

    txns = linked.assign(timestamp=linked.timestamp.astype(str)).to_dict(orient="records")
    event_id_by_index = {i: e["event_id"] for i, e in enumerate(events_with_context)}

    if policy == "agent":
        ctx_map = _root_cause_context_map(linked, events_with_context)
        decisions = run_agent_batch(txns, ctx_map, progress_callback=progress_callback)
    else:
        decisions = run_batch_baseline(txns)

    txn_by_id = {t["transaction_id"]: t for t in txns}
    outcomes_out = []

    with db_session() as conn:
        for decision in decisions:
            txn = txn_by_id.get(decision["transaction_id"])
            if txn is None:
                # Defense in depth: decision_engine.py now forces the correct
                # transaction_id onto every decision it returns, so this shouldn't
                # happen from the agent path anymore - but a single unrecognized id
                # (from any future decision source) must never take down the other
                # ~300 transactions in the batch.
                print(f"[pipeline] decision references unknown transaction_id="
                      f"{decision['transaction_id']!r} (policy={policy}) - skipping it, "
                      f"batch continues.", file=sys.stderr)
                audit_log.log_event("action", {
                    "action_type": "skipped_unknown_transaction",
                    "reason": f"decision.transaction_id={decision['transaction_id']!r} did not "
                              f"match any transaction in this batch - skipped, not executed.",
                }, transaction_id=decision.get("transaction_id"), policy=policy, conn=conn)
                continue

            try:
                validate_decision(decision)
            except ValueError as e:
                print(f"[pipeline] invalid decision schema for transaction_id="
                      f"{decision['transaction_id']!r} (policy={policy}): {e} - skipping it, "
                      f"batch continues.", file=sys.stderr)
                audit_log.log_event("action", {
                    "action_type": "skipped_invalid_decision_schema",
                    "reason": str(e),
                }, transaction_id=decision["transaction_id"], policy=policy, conn=conn)
                continue

            if already_processed(conn, decision["transaction_id"], policy):
                audit_log.log_event("action", {
                    "action_type": "skipped_duplicate",
                    "reason": f"{decision['transaction_id']} already has a completed outcome "
                              f"under policy='{policy}' - skipping to avoid double-counting revenue.",
                }, transaction_id=decision["transaction_id"], policy=policy, conn=conn)
                continue

            event_id = None
            if txn.get("degradation_linked") and txn.get("matched_event_index", -1) >= 0:
                event_id = event_id_by_index.get(int(txn["matched_event_index"]))

            cur = conn.execute(
                "INSERT INTO decisions (transaction_id, policy, decision, reasoning, confidence, "
                "delay_hours, discount_pct, degradation_linked, event_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (decision["transaction_id"], policy, decision["decision"], decision.get("reasoning"),
                 decision.get("confidence"), decision.get("delay_hours"), decision.get("discount_pct"),
                 int(bool(txn.get("degradation_linked"))), event_id, _now()),
            )
            decision_id = cur.lastrowid
            audit_log.log_event("decision", decision, transaction_id=decision["transaction_id"], policy=policy, conn=conn)

            rule_result = check_and_enforce(decision, txn)
            audit_log.log_event("rule_check", rule_result, transaction_id=decision["transaction_id"], policy=policy, conn=conn)

            allowed_action = rule_result["allowed_action"]
            action_executed_at = _now()
            cur2 = conn.execute(
                "INSERT INTO actions_taken (decision_id, transaction_id, policy, action_type, "
                "allowed, block_reason, executed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (decision_id, decision["transaction_id"], policy, allowed_action,
                 int(rule_result["allowed"]), rule_result["block_reason"], action_executed_at),
            )
            action_id = cur2.lastrowid
            audit_log.log_event("action", {"action_type": allowed_action, **rule_result},
                                 transaction_id=decision["transaction_id"], policy=policy, conn=conn)

            if allowed_action == "escalate":
                audit_log.log_event("escalation", {
                    "reason": rule_result["block_reason"] or "agent_decision",
                    "failure_type": txn.get("failure_type"),
                    "amount": txn.get("amount"),
                }, transaction_id=decision["transaction_id"], policy=policy, conn=conn)

            outcome = execute_action(allowed_action, txn, rule_result["delay_hours"], rule_result["discount_pct"])
            conn.execute(
                "INSERT INTO outcomes (action_id, transaction_id, policy, success, amount_recovered, "
                "discount_cost, action_cost, net_recovered, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (action_id, decision["transaction_id"], policy, int(outcome["success"]),
                 outcome["amount_recovered"], outcome["discount_cost"], outcome["action_cost"],
                 outcome["net_recovered"], _now()),
            )
            audit_log.log_event("outcome", outcome, transaction_id=decision["transaction_id"], policy=policy, conn=conn)

            outcomes_out.append({
                "transaction_id": decision["transaction_id"],
                "policy": policy,
                "degradation_linked": bool(txn.get("degradation_linked")),
                "decision": decision["decision"],
                "allowed_action": allowed_action,
                **outcome,
            })

    return outcomes_out


def run_full_pipeline(reset: bool = True, agent_progress_callback=None) -> dict:
    """Convenience: full end-to-end run for both policies. Used by the CLI demo run."""
    init_db(reset=reset)
    diagnosis = run_health_and_diagnosis()
    baseline_outcomes = run_decision_batch("baseline", diagnosis["events"], diagnosis["linked"])
    agent_outcomes = run_decision_batch("agent", diagnosis["events"], diagnosis["linked"],
                                         progress_callback=agent_progress_callback)
    return {
        "events": diagnosis["events"],
        "baseline_outcomes": baseline_outcomes,
        "agent_outcomes": agent_outcomes,
    }


if __name__ == "__main__":
    def _progress(done, total):
        print(f"  agent decisions: {done}/{total}", end="\r")

    result = run_full_pipeline(reset=True, agent_progress_callback=_progress)
    print()
    print(f"Detected {len(result['events'])} degradation event(s).")
    for e in result["events"]:
        print(f"  - {e['root_cause_statement']}")
    print(f"Baseline outcomes: {len(result['baseline_outcomes'])}, Agent outcomes: {len(result['agent_outcomes'])}")
