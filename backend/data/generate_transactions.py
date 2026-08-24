"""
Generates individual failed/at-risk transactions, tied to the injected degradation
event from generate_timeseries_dataset.py.

Two populations:
  1. Degradation-linked cluster: transactions on UPI + PayFast Gateway, timestamped
     inside the injected anomaly window (Day 6, 12:00-20:00). These represent real
     customers whose payments failed BECAUSE of the gateway outage.
  2. Baseline population: transactions scattered across the full 14 days, other
     payment methods/gateways/times, failing for ordinary unrelated reasons
     (card expired, insufficient funds, cart abandonment, invoice overdue).

Hidden eval-only fields (not shown to the agent, used only for scoring):
  ground_truth_recoverable            bool  - could this txn ever be recovered
  ground_truth_recovery_probability   float - true probability retry-now succeeds
                                               AT THE TIME the action is simulated.
                                               Deliberately LOW for degradation-linked
                                               txns if retried during the outage window
                                               (root cause hasn't resolved yet), and
                                               HIGH if retried after the gateway recovers.
                                               This is what makes agent-vs-baseline land:
                                               baseline retries blindly into the outage.
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import uuid

from generate_timeseries_dataset import (
    START, ANOMALY_METHOD, ANOMALY_GATEWAY, ANOMALY_START, ANOMALY_END,
    BANK_GATEWAYS, PAYMENT_METHODS,
)

SEED = 7
rng = np.random.default_rng(SEED)

N_DEGRADATION_LINKED = 140
N_BASELINE = 140

FAILURE_TYPES_DEGRADATION = ["gateway_timeout", "gateway_error", "processor_declined"]
FAILURE_TYPES_BASELINE = [
    "card_expired", "insufficient_funds", "cart_abandonment",
    "invoice_overdue", "bank_decline", "otp_timeout", "customer_cancelled",
]

CUSTOMER_HISTORY_TIERS = ["new", "repeat", "high_value", "at_risk"]


def rand_amount() -> float:
    # log-uniform-ish spread between 200 and 15000, skewed toward smaller amounts
    return round(float(np.clip(rng.lognormal(mean=7.2, sigma=0.9), 200, 15000)), 2)


def rand_customer_id(i: int) -> str:
    return f"cust_{10000 + i}"


def make_degradation_linked_rows(n: int) -> list:
    rows = []
    window_seconds = int((ANOMALY_END - ANOMALY_START).total_seconds())
    for i in range(n):
        offset_s = int(rng.uniform(0, window_seconds))
        ts = ANOMALY_START + timedelta(seconds=offset_s)
        # how far into the outage window (0=start/edge healthier, 0.5=trough, 1=end)
        hours_in = offset_s / 3600
        window_len_h = window_seconds / 3600
        dip_shape = np.sin(np.pi * hours_in / window_len_h)  # 0..1..0, matches health curve

        failure_type = rng.choice(FAILURE_TYPES_DEGRADATION, p=[0.55, 0.30, 0.15])
        retry_count_so_far = int(rng.choice([0, 1, 2], p=[0.7, 0.22, 0.08]))
        customer_history = rng.choice(CUSTOMER_HISTORY_TIERS, p=[0.3, 0.4, 0.2, 0.1])

        # ground truth: recovery prob if retried RIGHT NOW is suppressed proportional
        # to how deep in the outage we are (dip_shape), since the gateway is still down.
        base_recovery_if_healthy = 0.82
        suppression = 0.65 * dip_shape  # up to -0.65 at the trough
        recovery_prob_now = float(np.clip(base_recovery_if_healthy - suppression + rng.normal(0, 0.04), 0.03, 0.92))

        rows.append({
            "transaction_id": f"txn_{uuid.uuid4().hex[:10]}",
            "payment_method": ANOMALY_METHOD,
            "bank_gateway": ANOMALY_GATEWAY,
            "timestamp": ts.isoformat(),
            "amount": rand_amount(),
            "customer_id": rand_customer_id(i),
            "customer_history": customer_history,
            "retry_count_so_far": retry_count_so_far,
            "failure_type": failure_type,
            "degradation_linked": True,
            # hidden eval-only fields
            "ground_truth_recoverable": True,  # gateway issue, not fundamentally unrecoverable
            "ground_truth_recovery_probability": round(recovery_prob_now, 4),
            "ground_truth_recovery_probability_after_recovery": round(
                float(np.clip(base_recovery_if_healthy + rng.normal(0, 0.04), 0.5, 0.95)), 4
            ),
        })
    return rows


def make_baseline_rows(n: int) -> list:
    rows = []
    total_hours = int((START + timedelta(days=14) - START).total_seconds() / 3600)
    for i in range(n):
        # spread across full 14 days, but bias away from the anomaly window/slice
        while True:
            h = int(rng.uniform(0, total_hours))
            ts = START + timedelta(hours=h) + timedelta(minutes=int(rng.uniform(0, 60)))
            method = rng.choice(PAYMENT_METHODS)
            gateway = rng.choice(BANK_GATEWAYS)
            if not (method == ANOMALY_METHOD and gateway == ANOMALY_GATEWAY
                    and ANOMALY_START <= ts < ANOMALY_END):
                break

        failure_type = rng.choice(
            FAILURE_TYPES_BASELINE,
            p=[0.20, 0.20, 0.18, 0.14, 0.14, 0.08, 0.06],
        )
        retry_count_so_far = int(rng.choice([0, 1, 2, 3], p=[0.55, 0.25, 0.13, 0.07]))
        customer_history = rng.choice(CUSTOMER_HISTORY_TIERS, p=[0.35, 0.35, 0.15, 0.15])

        # ground truth recovery probability depends on failure_type, independent of any outage
        recoverability_by_type = {
            "card_expired": (0.15, True),        # needs new card details, rarely recovers via retry
            "insufficient_funds": (0.35, True),   # may recover after payday / balance top-up
            "cart_abandonment": (0.45, True),     # discount/reminder can bring back
            "invoice_overdue": (0.55, True),      # reminder often works
            "bank_decline": (0.25, True),         # often needs escalation
            "otp_timeout": (0.70, True),          # simple retry usually works
            "customer_cancelled": (0.08, False),  # essentially unrecoverable
        }
        base_prob, recoverable = recoverability_by_type[failure_type]
        recovery_prob_now = float(np.clip(base_prob + rng.normal(0, 0.08), 0.02, 0.9))

        rows.append({
            "transaction_id": f"txn_{uuid.uuid4().hex[:10]}",
            "payment_method": method,
            "bank_gateway": gateway,
            "timestamp": ts.isoformat(),
            "amount": rand_amount(),
            "customer_id": rand_customer_id(1000 + i),
            "customer_history": customer_history,
            "retry_count_so_far": retry_count_so_far,
            "failure_type": failure_type,
            "degradation_linked": False,
            # hidden eval-only fields
            "ground_truth_recoverable": bool(recoverable),
            "ground_truth_recovery_probability": round(recovery_prob_now, 4),
            "ground_truth_recovery_probability_after_recovery": round(recovery_prob_now, 4),  # n/a, same
        })
    return rows


def generate() -> pd.DataFrame:
    rows = make_degradation_linked_rows(N_DEGRADATION_LINKED) + make_baseline_rows(N_BASELINE)
    df = pd.DataFrame(rows)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


if __name__ == "__main__":
    df = generate()
    out_path = "backend/data/failed_transactions.csv"
    try:
        df.to_csv(out_path, index=False)
    except FileNotFoundError:
        df.to_csv("failed_transactions.csv", index=False)
        out_path = "failed_transactions.csv"

    print(f"Generated {len(df)} transactions -> {out_path}")
    print(f"Degradation-linked: {df.degradation_linked.sum()}, baseline: {(~df.degradation_linked).sum()}")
    print(df.groupby("degradation_linked")["ground_truth_recovery_probability"].mean())
