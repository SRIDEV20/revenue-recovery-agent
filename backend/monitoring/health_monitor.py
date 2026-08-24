"""
Rolling baseline computation per (payment_method, bank_gateway) slice.

For every hourly window, computes:
  - the trailing rolling baseline success rate (default: trailing 48h average,
    EXCLUDING the current window itself) per slice
  - the current window's success rate

This gives every point in time a "what's normal for this slice" reference,
which the anomaly detector compares the current reading against.
"""

import os
import pandas as pd

ROLLING_WINDOW_HOURS = 48

_DEFAULT_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "payment_health.csv")


def load_health_data(csv_path: str = _DEFAULT_CSV) -> pd.DataFrame:
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    df = df.sort_values(["payment_method", "bank_gateway", "timestamp"]).reset_index(drop=True)
    return df


def compute_rolling_baseline(df: pd.DataFrame, window_hours: int = ROLLING_WINDOW_HOURS) -> pd.DataFrame:
    """
    Adds columns:
      rolling_baseline_success_rate - trailing mean success_rate over `window_hours`,
                                       shifted by 1 so the current row is excluded
      rolling_baseline_std          - trailing std dev of success_rate (for z-score)
      rolling_baseline_latency      - trailing mean latency
    """
    df = df.sort_values(["payment_method", "bank_gateway", "timestamp"]).reset_index(drop=True).copy()

    grouped = df.groupby(["payment_method", "bank_gateway"], sort=False)["success_rate"]
    shifted = grouped.shift(1)
    roll = shifted.groupby([df["payment_method"], df["bank_gateway"]]).rolling(
        window=window_hours, min_periods=6
    )
    # the double-groupby above produces a MultiIndex; align back via reset_index(drop=True)
    df["rolling_baseline_success_rate"] = roll.mean().reset_index(level=[0, 1], drop=True)
    df["rolling_baseline_std"] = roll.std().reset_index(level=[0, 1], drop=True)

    lat_grouped = df.groupby(["payment_method", "bank_gateway"], sort=False)["avg_latency_ms"]
    lat_shifted = lat_grouped.shift(1)
    lat_roll = lat_shifted.groupby([df["payment_method"], df["bank_gateway"]]).rolling(
        window=window_hours, min_periods=6
    )
    df["rolling_baseline_latency"] = lat_roll.mean().reset_index(level=[0, 1], drop=True)

    return df[[
        "payment_method", "bank_gateway", "timestamp", "success_rate", "avg_latency_ms",
        "transaction_volume", "rolling_baseline_success_rate", "rolling_baseline_std",
        "rolling_baseline_latency"
    ]]


def get_current_window_summary(df: pd.DataFrame, slice_method: str, slice_gateway: str,
                                window_start, window_end) -> dict:
    """Summarize a slice's health over an explicit window (used by root_cause.py)."""
    mask = (
        (df.payment_method == slice_method) &
        (df.bank_gateway == slice_gateway) &
        (df.timestamp >= window_start) &
        (df.timestamp < window_end)
    )
    sub = df[mask]
    if sub.empty:
        return {"success_rate": None, "avg_latency_ms": None, "transaction_volume": 0}
    return {
        "success_rate": float(sub.success_rate.mean()),
        "avg_latency_ms": float(sub.avg_latency_ms.mean()),
        "transaction_volume": int(sub.transaction_volume.sum()),
    }


if __name__ == "__main__":
    df = load_health_data()
    enriched = compute_rolling_baseline(df)
    print(enriched.tail(10))
    print(f"\nRows with a computed baseline: {enriched.rolling_baseline_success_rate.notna().sum()} / {len(enriched)}")
