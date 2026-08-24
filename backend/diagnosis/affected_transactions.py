"""
Given a confirmed degradation event (from anomaly_detector + root_cause), identifies
which actual transactions were affected by it.

This intentionally RE-DERIVES linkage from the detected event's slice + window against
each transaction's real (payment_method, bank_gateway, timestamp) — it does not just
trust the `degradation_linked` label baked into the seed data at generation time. That
label only exists to carry ground-truth recovery probabilities for evaluation; the
pipeline itself must independently arrive at the same linkage by matching detected
event windows against transaction records, the way it would against real production data.

Output: every transaction tagged with a boolean `linked_to_event` (renamed
`degradation_linked` downstream) plus the `event_id`/root cause context it was matched to.
"""

import pandas as pd


def link_transactions_to_event(transactions_df: pd.DataFrame, event: dict) -> pd.DataFrame:
    df = transactions_df.copy()
    window_start = pd.to_datetime(event["window_start"])
    window_end = pd.to_datetime(event["window_end"])
    ts = pd.to_datetime(df["timestamp"])

    mask = (
        (df["payment_method"] == event["payment_method"]) &
        (df["bank_gateway"] == event["bank_gateway"]) &
        (ts >= window_start) & (ts < window_end)
    )
    df["linked_to_event"] = mask
    return df


def link_transactions_to_all_events(transactions_df: pd.DataFrame, events: list[dict]) -> pd.DataFrame:
    """Runs linkage across multiple detected events, returns transactions annotated with
    linked_to_event (bool, True if matched to ANY event) and matched_event_index (or -1)."""
    df = transactions_df.copy()
    df["linked_to_event"] = False
    df["matched_event_index"] = -1

    ts = pd.to_datetime(df["timestamp"])
    for idx, event in enumerate(events):
        window_start = pd.to_datetime(event["window_start"])
        window_end = pd.to_datetime(event["window_end"])
        mask = (
            (df["payment_method"] == event["payment_method"]) &
            (df["bank_gateway"] == event["bank_gateway"]) &
            (ts >= window_start) & (ts < window_end) &
            (~df["linked_to_event"])  # don't double-assign if events somehow overlap
        )
        df.loc[mask, "linked_to_event"] = True
        df.loc[mask, "matched_event_index"] = idx

    return df


if __name__ == "__main__":
    from monitoring.health_monitor import load_health_data, compute_rolling_baseline
    from monitoring.anomaly_detector import detect_degradation_events
    import os

    health_df = load_health_data()
    enriched = compute_rolling_baseline(health_df)
    events = detect_degradation_events(enriched)

    txn_path = os.path.join(os.path.dirname(__file__), "..", "data", "failed_transactions.csv")
    transactions_df = pd.read_csv(txn_path, parse_dates=["timestamp"])

    linked = link_transactions_to_all_events(transactions_df, events)
    print(f"Total transactions: {len(linked)}")
    print(f"Linked to a detected degradation event: {linked.linked_to_event.sum()}")
    print(f"Matches seed-data degradation_linked label: "
          f"{(linked.linked_to_event == linked.degradation_linked).sum()} / {len(linked)}")
