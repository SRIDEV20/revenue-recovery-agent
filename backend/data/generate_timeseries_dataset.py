"""
Generates synthetic payment health time-series data.

Grain: one row per (payment_method, bank_gateway, hourly time_window) over a 14-day period.
Metrics: success_rate, avg_latency_ms, transaction_volume.

INJECTED ANOMALY (search "INJECTED ANOMALY" below to find the exact code):
  We deliberately degrade UPI + "PayFast Gateway" success rate from ~94% down to ~68%
  over an 8-hour window on Day 6 (2026-08-13, 12:00-20:00), then let it recover back
  to baseline. This is the single ground-truth degradation event the whole pipeline
  (anomaly detection -> root cause -> recovery) is built to find and explain.
  Every other slice/window stays in healthy-noise range (94-98% success rate).
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta

SEED = 42
rng = np.random.default_rng(SEED)

PAYMENT_METHODS = ["UPI", "card", "netbanking", "wallet"]

BANK_GATEWAYS = [
    "PayFast Gateway",
    "SecureBank Gateway",
    "QuickPay Gateway",
    "TrustBank Gateway",
    "NationalPay Gateway",
    "SwiftBank Gateway",
]

START = datetime(2026, 8, 8, 0, 0, 0)   # Day 1
DAYS = 14
HOURS = DAYS * 24

# Baseline health characteristics per payment method (mean success rate, latency, volume scale)
METHOD_PROFILE = {
    "UPI":        {"success_rate": 0.96, "latency_ms": 850,  "volume_mean": 220},
    "card":       {"success_rate": 0.95, "latency_ms": 1400, "volume_mean": 160},
    "netbanking": {"success_rate": 0.94, "latency_ms": 2100, "volume_mean": 90},
    "wallet":     {"success_rate": 0.97, "latency_ms": 600,  "volume_mean": 70},
}

# ---- INJECTED ANOMALY parameters ----
ANOMALY_METHOD = "UPI"
ANOMALY_GATEWAY = "PayFast Gateway"
ANOMALY_DAY_OFFSET = 5          # Day 6 (0-indexed offset from START)
ANOMALY_START_HOUR = 12         # 12:00
ANOMALY_END_HOUR = 20           # 20:00 (8-hour window)
ANOMALY_START = START + timedelta(days=ANOMALY_DAY_OFFSET, hours=ANOMALY_START_HOUR)
ANOMALY_END = START + timedelta(days=ANOMALY_DAY_OFFSET, hours=ANOMALY_END_HOUR)
ANOMALY_TROUGH_SUCCESS_RATE = 0.68   # deepest point of the dip
ANOMALY_BASELINE_SUCCESS_RATE = 0.94


def daily_seasonality(hour_of_day: float) -> float:
    """Small realistic diurnal volume pattern: higher during daytime/evening."""
    return 0.55 + 0.45 * np.sin((hour_of_day - 6) / 24 * 2 * np.pi) ** 2


def generate() -> pd.DataFrame:
    rows = []
    timestamps = [START + timedelta(hours=h) for h in range(HOURS)]

    for method in PAYMENT_METHODS:
        profile = METHOD_PROFILE[method]
        for gateway in BANK_GATEWAYS:
            # small per-gateway baseline offset so gateways aren't identical
            gateway_offset = rng.normal(0, 0.005)

            for ts in timestamps:
                hour_of_day = ts.hour
                vol_season = daily_seasonality(hour_of_day)

                base_success = profile["success_rate"] + gateway_offset
                base_latency = profile["latency_ms"]
                base_volume = profile["volume_mean"] * vol_season

                # healthy noise
                success_rate = base_success + rng.normal(0, 0.012)
                success_rate = float(np.clip(success_rate, 0.90, 0.99))
                latency_ms = max(50, base_latency + rng.normal(0, base_latency * 0.08))
                volume = max(0, int(rng.poisson(max(base_volume, 1))))

                # =========================================================
                # INJECTED ANOMALY: UPI + PayFast Gateway degrades sharply
                # for an 8-hour window on Day 6, then recovers. This is the
                # ONE clear degradation event the anomaly detector must find.
                # =========================================================
                if method == ANOMALY_METHOD and gateway == ANOMALY_GATEWAY \
                        and ANOMALY_START <= ts < ANOMALY_END:
                    hours_in = (ts - ANOMALY_START).total_seconds() / 3600
                    window_len = (ANOMALY_END - ANOMALY_START).total_seconds() / 3600
                    # smooth dip-and-recover shape (half-sine trough) so it looks organic,
                    # bottoming out near the middle of the window
                    dip_shape = np.sin(np.pi * hours_in / window_len)  # 0 -> 1 -> 0
                    drop = (ANOMALY_BASELINE_SUCCESS_RATE - ANOMALY_TROUGH_SUCCESS_RATE) * dip_shape
                    success_rate = float(np.clip(ANOMALY_BASELINE_SUCCESS_RATE - drop + rng.normal(0, 0.01), 0.60, 0.99))
                    # latency spikes during the degradation too (gateway under stress)
                    latency_ms = base_latency * (1 + 1.8 * dip_shape) + rng.normal(0, 50)
                    # volume dips slightly (some txns time out / users abandon) but not collapsed
                    volume = max(0, int(volume * (1 - 0.15 * dip_shape)))

                rows.append({
                    "timestamp": ts.isoformat(),
                    "payment_method": method,
                    "bank_gateway": gateway,
                    "success_rate": round(success_rate, 4),
                    "avg_latency_ms": round(float(latency_ms), 1),
                    "transaction_volume": int(volume),
                })

    df = pd.DataFrame(rows)
    df = df.sort_values(["payment_method", "bank_gateway", "timestamp"]).reset_index(drop=True)
    return df


if __name__ == "__main__":
    df = generate()
    out_path = "backend/data/payment_health.csv"
    try:
        df.to_csv(out_path, index=False)
    except FileNotFoundError:
        df.to_csv("payment_health.csv", index=False)
        out_path = "payment_health.csv"

    print(f"Generated {len(df)} rows -> {out_path}")
    print(f"Injected anomaly: {ANOMALY_METHOD} / {ANOMALY_GATEWAY}, "
          f"{ANOMALY_START} to {ANOMALY_END}, "
          f"baseline {ANOMALY_BASELINE_SUCCESS_RATE:.0%} -> trough {ANOMALY_TROUGH_SUCCESS_RATE:.0%}")

    anomaly_rows = df[(df.payment_method == ANOMALY_METHOD) & (df.bank_gateway == ANOMALY_GATEWAY)]
    window = anomaly_rows[(anomaly_rows.timestamp >= ANOMALY_START.isoformat()) &
                           (anomaly_rows.timestamp < ANOMALY_END.isoformat())]
    print(f"Min success rate in injected window: {window.success_rate.min():.3f}")
