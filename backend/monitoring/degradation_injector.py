"""
On-demand live degradation injector, for proving the detection/root-cause pipeline
works on a FRESH anomaly in real time (not just the hardcoded Aug 13 UPI/PayFast
scenario baked into the seed data).

inject_random_degradation() picks a random (payment_method, bank_gateway) slice and
appends a new window of hours immediately after the current end of the timeseries -
degrading that slice to a randomly chosen trough (55-80% success rate) using the same
organic half-sine dip-and-recover shape as the original seed data's Day-6 anomaly in
generate_timeseries_dataset.py, plus healthy rows for every other slice in that same
window (so root-cause's cross-slice comparisons still have real data to check against).
It also appends a batch of new degradation-linked failed transactions timestamped
inside the injected window.

Both CSVs are the pipeline's actual source of truth (pipeline.run_health_and_diagnosis
reloads them fresh on every diagnose), so anything written here is picked up by the
normal detection flow exactly like the original seed anomaly - the detector and root
cause modules are never handed the injected parameters directly. The ground-truth
summary returned here exists only so the API layer can show what was actually
injected, for verification against what the pipeline independently found.
"""

import os
import uuid

import numpy as np
import pandas as pd
from datetime import timedelta

HEALTH_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "payment_health.csv")
TXN_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "failed_transactions.csv")

PAYMENT_METHODS = ["UPI", "card", "netbanking", "wallet"]
BANK_GATEWAYS = [
    "PayFast Gateway", "SecureBank Gateway", "QuickPay Gateway",
    "TrustBank Gateway", "NationalPay Gateway", "SwiftBank Gateway",
]

METHOD_PROFILE = {
    "UPI":        {"success_rate": 0.96, "latency_ms": 850,  "volume_mean": 220},
    "card":       {"success_rate": 0.95, "latency_ms": 1400, "volume_mean": 160},
    "netbanking": {"success_rate": 0.94, "latency_ms": 2100, "volume_mean": 90},
    "wallet":     {"success_rate": 0.97, "latency_ms": 600,  "volume_mean": 70},
}

TROUGH_RANGE = (0.55, 0.80)
WINDOW_HOURS_RANGE = (6, 9)          # inclusive; matches the original 8h anomaly's order of magnitude
N_NEW_TRANSACTIONS_RANGE = (15, 30)  # inclusive

FAILURE_TYPES_DEGRADATION = ["gateway_timeout", "gateway_error", "processor_declined"]
CUSTOMER_HISTORY_TIERS = ["new", "repeat", "high_value", "at_risk"]


def _daily_seasonality(hour_of_day: float) -> float:
    return 0.55 + 0.45 * np.sin((hour_of_day - 6) / 24 * 2 * np.pi) ** 2


def _rand_amount(rng: np.random.Generator) -> float:
    return round(float(np.clip(rng.lognormal(mean=7.2, sigma=0.9), 200, 15000)), 2)


def inject_random_degradation(rng: np.random.Generator | None = None) -> dict:
    """
    Appends one fresh, randomized degradation event (health rows + linked transactions)
    to the seed CSVs, immediately after the current end of the timeseries. Returns the
    ground-truth summary of what was injected - keep this separate from whatever the
    detector independently reports; it is not shown to any detection/root-cause code.
    """
    rng = rng or np.random.default_rng()

    # read as plain strings (no parse_dates) so the round-trip write-back can't
    # reformat existing rows or upcast dtypes when concatenated with new string rows
    health_df = pd.read_csv(HEALTH_CSV)
    last_ts = pd.to_datetime(health_df["timestamp"]).max()

    method = str(rng.choice(PAYMENT_METHODS))
    gateway = str(rng.choice(BANK_GATEWAYS))
    window_hours = int(rng.integers(WINDOW_HOURS_RANGE[0], WINDOW_HOURS_RANGE[1] + 1))
    trough_rate = round(float(rng.uniform(*TROUGH_RANGE)), 3)
    baseline_rate = METHOD_PROFILE[method]["success_rate"]

    window_start = last_ts + timedelta(hours=1)
    window_end = window_start + timedelta(hours=window_hours)
    timestamps = [window_start + timedelta(hours=h) for h in range(window_hours)]

    new_health_rows = []
    for m in PAYMENT_METHODS:
        profile = METHOD_PROFILE[m]
        for g in BANK_GATEWAYS:
            gateway_offset = rng.normal(0, 0.005)
            for ts in timestamps:
                vol_season = _daily_seasonality(ts.hour)
                base_success = profile["success_rate"] + gateway_offset
                base_latency = profile["latency_ms"]
                base_volume = profile["volume_mean"] * vol_season

                success_rate = float(np.clip(base_success + rng.normal(0, 0.012), 0.90, 0.99))
                latency_ms = max(50, base_latency + rng.normal(0, base_latency * 0.08))
                volume = max(0, int(rng.poisson(max(base_volume, 1))))

                if m == method and g == gateway:
                    hours_in = (ts - window_start).total_seconds() / 3600
                    dip_shape = np.sin(np.pi * hours_in / window_hours)  # 0 -> 1 -> 0
                    drop = (baseline_rate - trough_rate) * dip_shape
                    success_rate = float(np.clip(baseline_rate - drop + rng.normal(0, 0.01), 0.50, 0.99))
                    latency_ms = base_latency * (1 + 1.8 * dip_shape) + rng.normal(0, 50)
                    volume = max(0, int(volume * (1 - 0.15 * dip_shape)))

                new_health_rows.append({
                    "timestamp": ts.isoformat(),
                    "payment_method": m,
                    "bank_gateway": g,
                    "success_rate": round(success_rate, 4),
                    "avg_latency_ms": round(float(latency_ms), 1),
                    "transaction_volume": int(volume),
                })

    combined_health = pd.concat([health_df, pd.DataFrame(new_health_rows)], ignore_index=True)
    combined_health = combined_health.sort_values(
        ["payment_method", "bank_gateway", "timestamp"]
    ).reset_index(drop=True)
    combined_health.to_csv(HEALTH_CSV, index=False)

    # ---- degradation-linked transactions inside the injected window ----
    n_txn = int(rng.integers(N_NEW_TRANSACTIONS_RANGE[0], N_NEW_TRANSACTIONS_RANGE[1] + 1))
    window_seconds = window_hours * 3600
    txn_rows = []
    for i in range(n_txn):
        offset_s = int(rng.uniform(0, window_seconds))
        ts = window_start + timedelta(seconds=offset_s)
        hours_in = offset_s / 3600
        dip_shape = np.sin(np.pi * hours_in / window_hours)

        failure_type = str(rng.choice(FAILURE_TYPES_DEGRADATION, p=[0.55, 0.30, 0.15]))
        retry_count_so_far = int(rng.choice([0, 1, 2], p=[0.7, 0.22, 0.08]))
        customer_history = str(rng.choice(CUSTOMER_HISTORY_TIERS, p=[0.3, 0.4, 0.2, 0.1]))

        base_recovery_if_healthy = 0.82
        suppression = 0.65 * dip_shape
        recovery_prob_now = float(np.clip(
            base_recovery_if_healthy - suppression + rng.normal(0, 0.04), 0.03, 0.92
        ))

        txn_rows.append({
            "transaction_id": f"txn_live_{uuid.uuid4().hex[:10]}",
            "payment_method": method,
            "bank_gateway": gateway,
            "timestamp": ts.isoformat(),
            "amount": _rand_amount(rng),
            "customer_id": f"cust_live_{int(rng.integers(100000, 999999))}",
            "customer_history": customer_history,
            "retry_count_so_far": retry_count_so_far,
            "failure_type": failure_type,
            "degradation_linked": True,
            "ground_truth_recoverable": True,
            "ground_truth_recovery_probability": round(recovery_prob_now, 4),
            "ground_truth_recovery_probability_after_recovery": round(
                float(np.clip(base_recovery_if_healthy + rng.normal(0, 0.04), 0.5, 0.95)), 4
            ),
        })

    txn_df = pd.read_csv(TXN_CSV)
    combined_txn = pd.concat([txn_df, pd.DataFrame(txn_rows)], ignore_index=True)
    combined_txn = combined_txn.sort_values("timestamp").reset_index(drop=True)
    combined_txn.to_csv(TXN_CSV, index=False)

    return {
        "payment_method": method,
        "bank_gateway": gateway,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "baseline_rate": round(baseline_rate, 4),
        "injected_rate": trough_rate,
        "new_transaction_count": n_txn,
    }


if __name__ == "__main__":
    summary = inject_random_degradation()
    print("Injected:", summary)
