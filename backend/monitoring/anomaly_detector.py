"""
Flags degradation events: windows where a slice's success rate deviates
significantly from its own rolling baseline.

Detection rule (both must hold, to avoid noisy single-hour flags):
  1. Absolute drop: current_rate <= baseline_rate - MIN_DROP_PCT_POINTS (default 15pp), OR
     z-score: (baseline_rate - current_rate) / baseline_std >= Z_THRESHOLD (default 3.0)
  2. Persistence: at least MIN_CONSECUTIVE_HOURS consecutive hourly windows in the
     slice must breach the threshold, so a single noisy hour doesn't trigger a false event.

Contiguous breaching hours for the same slice are merged into one degradation_event
with severity derived from how deep the drop went.
"""

import pandas as pd
from datetime import datetime

from monitoring.health_monitor import load_health_data, compute_rolling_baseline

MIN_DROP_PCT_POINTS = 0.15   # 15 percentage points
Z_THRESHOLD = 3.0
MIN_CONSECUTIVE_HOURS = 3


def _severity(baseline_rate: float, current_rate: float) -> str:
    drop = baseline_rate - current_rate
    if drop >= 0.25:
        return "critical"
    if drop >= 0.15:
        return "high"
    if drop >= 0.08:
        return "medium"
    return "low"


def flag_breaches(enriched: pd.DataFrame) -> pd.DataFrame:
    """Mark each row as breaching or not, using drop-threshold OR z-score."""
    df = enriched.copy()
    df["rolling_baseline_success_rate"] = pd.to_numeric(df["rolling_baseline_success_rate"], errors="coerce")
    df["rolling_baseline_std"] = pd.to_numeric(df["rolling_baseline_std"], errors="coerce")

    has_baseline = df["rolling_baseline_success_rate"].notna()
    drop = df["rolling_baseline_success_rate"] - df["success_rate"]
    std = df["rolling_baseline_std"].fillna(0.02).clip(lower=0.005)  # floor to avoid div-by-~0
    z = drop / std

    df["drop_pct_points"] = drop
    df["z_score"] = z
    df["breach"] = has_baseline & ((drop >= MIN_DROP_PCT_POINTS) | (z >= Z_THRESHOLD))
    return df


def detect_degradation_events(enriched: pd.DataFrame) -> list[dict]:
    """
    Groups consecutive breaching hours per slice into degradation_event dicts:
      {payment_method, bank_gateway, window_start, window_end, baseline_rate,
       current_rate, severity, z_score}
    """
    flagged = flag_breaches(enriched)
    events = []

    for (method, gateway), group in flagged.groupby(["payment_method", "bank_gateway"]):
        group = group.sort_values("timestamp").reset_index(drop=True)
        breach_mask = group["breach"].fillna(False).to_numpy()

        # find runs of consecutive True
        run_start = None
        for i, is_breach in enumerate(breach_mask):
            if is_breach and run_start is None:
                run_start = i
            ends_run = (not is_breach) or (i == len(breach_mask) - 1)
            if run_start is not None and ends_run:
                run_end = i if is_breach else i - 1
                run_len = run_end - run_start + 1
                if run_len >= MIN_CONSECUTIVE_HOURS:
                    window = group.iloc[run_start:run_end + 1]
                    baseline_rate = float(window["rolling_baseline_success_rate"].mean())
                    current_rate = float(window["success_rate"].mean())
                    events.append({
                        "payment_method": method,
                        "bank_gateway": gateway,
                        "window_start": window["timestamp"].iloc[0].isoformat(),
                        "window_end": (window["timestamp"].iloc[-1] + pd.Timedelta(hours=1)).isoformat(),
                        "baseline_rate": round(baseline_rate, 4),
                        "current_rate": round(current_rate, 4),
                        "severity": _severity(baseline_rate, current_rate),
                        "z_score": round(float(window["z_score"].mean()), 2),
                    })
                run_start = None

    return events


if __name__ == "__main__":
    df = load_health_data()
    enriched = compute_rolling_baseline(df)
    events = detect_degradation_events(enriched)
    print(f"Detected {len(events)} degradation event(s):")
    for e in events:
        print(e)
