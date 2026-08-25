"""
Shared pytest fixtures for the backend test suite.

Adds backend/ (this file's parent directory) to sys.path so tests can import
backend modules the same way backend code imports itself internally (bare
top-level imports like `from monitoring.health_monitor import ...`, not
`backend.monitoring...`).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest


def _make_health_series(
    payment_method: str,
    bank_gateway: str,
    start: str,
    hours: int,
    base_rate: float = 0.95,
    noise: float = 0.005,
    seed: int = 0,
    drop_start: int | None = None,
    drop_len: int = 0,
    drop_rate: float = 0.70,
) -> pd.DataFrame:
    """Builds an hourly synthetic payment_health-shaped DataFrame for one
    (payment_method, bank_gateway) slice. Optionally injects a flat drop to
    `drop_rate` for `drop_len` consecutive hours starting at index `drop_start`."""
    rng = np.random.default_rng(seed)
    timestamps = pd.date_range(start=start, periods=hours, freq="h")
    rates = np.clip(base_rate + rng.normal(0, noise, size=hours), 0.0, 1.0)

    if drop_start is not None and drop_len > 0:
        rates[drop_start:drop_start + drop_len] = drop_rate

    return pd.DataFrame({
        "timestamp": timestamps,
        "payment_method": payment_method,
        "bank_gateway": bank_gateway,
        "success_rate": rates,
        "avg_latency_ms": np.clip(200 + rng.normal(0, 5, size=hours), 50, None),
        "transaction_volume": rng.integers(50, 150, size=hours),
    })


@pytest.fixture
def health_series_factory():
    """Factory fixture: call with the same kwargs as _make_health_series to build
    a synthetic hourly health DataFrame for one slice."""
    return _make_health_series
