"""
Tests for monitoring/anomaly_detector.py against synthetic health series, so the
detection rule (drop-threshold OR z-score, persisted for MIN_CONSECUTIVE_HOURS) is
verified without depending on the real payment_health.csv seed data.
"""

import pandas as pd

from monitoring.anomaly_detector import detect_degradation_events
from monitoring.health_monitor import compute_rolling_baseline


def test_healthy_series_flags_no_anomaly(health_series_factory):
    raw = health_series_factory(
        payment_method="upi", bank_gateway="gw_a",
        start="2026-01-01", hours=72, base_rate=0.95, noise=0.005, seed=1,
    )
    enriched = compute_rolling_baseline(raw)

    events = detect_degradation_events(enriched)

    assert events == []


def test_injected_drop_is_flagged_for_the_right_window(health_series_factory):
    raw = health_series_factory(
        payment_method="upi", bank_gateway="gw_a",
        start="2026-01-01", hours=60, base_rate=0.95, noise=0.005, seed=2,
        drop_start=30, drop_len=5, drop_rate=0.70,
    )
    enriched = compute_rolling_baseline(raw)

    events = detect_degradation_events(enriched)

    assert len(events) >= 1
    event = events[0]
    assert event["payment_method"] == "upi"
    assert event["bank_gateway"] == "gw_a"
    assert event["current_rate"] < event["baseline_rate"]
    assert event["baseline_rate"] - event["current_rate"] >= 0.15

    drop_window_start = raw["timestamp"].iloc[30]
    drop_window_end = raw["timestamp"].iloc[34] + pd.Timedelta(hours=1)
    event_start = pd.to_datetime(event["window_start"])
    event_end = pd.to_datetime(event["window_end"])
    assert event_start >= drop_window_start
    assert event_end <= drop_window_end


def test_healthy_slice_is_not_flagged_while_a_different_slice_degrades(health_series_factory):
    healthy = health_series_factory(
        payment_method="upi", bank_gateway="gw_healthy",
        start="2026-01-01", hours=60, base_rate=0.95, noise=0.005, seed=3,
    )
    degraded = health_series_factory(
        payment_method="upi", bank_gateway="gw_bad",
        start="2026-01-01", hours=60, base_rate=0.95, noise=0.005, seed=4,
        drop_start=30, drop_len=5, drop_rate=0.70,
    )
    combined = pd.concat([healthy, degraded], ignore_index=True)
    enriched = compute_rolling_baseline(combined)

    events = detect_degradation_events(enriched)

    assert len(events) >= 1
    flagged_gateways = {e["bank_gateway"] for e in events}
    assert "gw_bad" in flagged_gateways
    assert "gw_healthy" not in flagged_gateways
