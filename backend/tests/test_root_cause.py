"""
Tests for diagnosis/root_cause.py: given a flagged degradation event, confirm the
isolation logic and generated statement correctly name the actually-degraded slice
and not a healthy one alongside it.
"""

import pandas as pd

from diagnosis.root_cause import analyze

WINDOW_START = pd.Timestamp("2026-01-01T10:00:00")
WINDOW_END = pd.Timestamp("2026-01-01T13:00:00")


def _rows(payment_method, bank_gateway, success_rate, n=3):
    timestamps = pd.date_range(WINDOW_START, periods=n, freq="h")
    return pd.DataFrame({
        "timestamp": timestamps,
        "payment_method": payment_method,
        "bank_gateway": bank_gateway,
        "success_rate": [success_rate] * n,
        "avg_latency_ms": [200] * n,
        "transaction_volume": [100] * n,
    })


def test_root_cause_names_the_degraded_slice_not_a_healthy_one():
    degraded_gateway = "gw_bad"
    healthy_gateways = ["gw_good1", "gw_good2"]

    health_df = pd.concat([
        _rows("upi", degraded_gateway, success_rate=0.65),
        _rows("upi", healthy_gateways[0], success_rate=0.96),
        _rows("upi", healthy_gateways[1], success_rate=0.97),
        _rows("card", "gw_other_method", success_rate=0.95),
    ], ignore_index=True)

    event = {
        "payment_method": "upi",
        "bank_gateway": degraded_gateway,
        "window_start": WINDOW_START.isoformat(),
        "window_end": WINDOW_END.isoformat(),
        "baseline_rate": 0.95,
        "current_rate": 0.65,
        "severity": "critical",
        "z_score": 5.0,
    }

    result = analyze(event, health_df)

    assert result["classification"] == "gateway_specific_issue"
    assert result["is_isolated"] is True
    assert degraded_gateway in result["root_cause_statement"]
    for healthy_gateway in healthy_gateways:
        # a healthy comparison slice may be *mentioned* as evidence of stability,
        # but must never be blamed as the source of the drop
        assert f"{healthy_gateway} dropped" not in result["root_cause_statement"]
        assert f"on {healthy_gateway} dropped" not in result["root_cause_statement"]
