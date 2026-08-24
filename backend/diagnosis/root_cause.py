"""
Root cause analysis for a flagged degradation event.

Given an event {payment_method, bank_gateway, window_start, window_end, baseline_rate,
current_rate}, confirms whether the drop is isolated to that specific slice by comparing:
  1. Other bank_gateways under the SAME payment_method, in the SAME window
     -> if they're healthy, it's gateway-specific, not a payment-method-wide problem.
  2. The SAME bank_gateway across OTHER payment_methods, in the SAME window (if the
     gateway serves more than one method) -> if only this method is affected, it's
     method+gateway specific rather than gateway-wide.
  3. ALL other slices in the same window, as a global sanity check -> if literally
     everything dropped, it's a platform-wide incident, not isolated.

Produces a structured verdict + a human-readable one-paragraph root cause statement,
which is one of the first things shown on the dashboard.
"""

import pandas as pd

from monitoring.health_monitor import get_current_window_summary

HEALTHY_THRESHOLD = 0.90  # a comparison slice counts as "stable" if success_rate >= this


def analyze(event: dict, health_df: pd.DataFrame) -> dict:
    method = event["payment_method"]
    gateway = event["bank_gateway"]
    window_start = pd.to_datetime(event["window_start"])
    window_end = pd.to_datetime(event["window_end"])

    # 1. other gateways, same payment method, same window
    other_gateways = sorted(health_df.loc[health_df.payment_method == method, "bank_gateway"].unique())
    other_gateways = [g for g in other_gateways if g != gateway]
    other_gateway_rates = {}
    for g in other_gateways:
        summary = get_current_window_summary(health_df, method, g, window_start, window_end)
        if summary["success_rate"] is not None:
            other_gateway_rates[g] = round(summary["success_rate"], 4)
    other_gateways_stable = all(r >= HEALTHY_THRESHOLD for r in other_gateway_rates.values()) if other_gateway_rates else True

    # 2. same gateway, other payment methods, same window (gateways may or may not serve multiple methods)
    other_methods = sorted(health_df.payment_method.unique())
    other_methods = [m for m in other_methods if m != method]
    other_method_rates = {}
    for m in other_methods:
        summary = get_current_window_summary(health_df, m, gateway, window_start, window_end)
        if summary["success_rate"] is not None:
            other_method_rates[m] = round(summary["success_rate"], 4)
    other_methods_stable = all(r >= HEALTHY_THRESHOLD for r in other_method_rates.values()) if other_method_rates else True

    # 3. global sanity check - overall platform success rate in the same window, excluding the affected slice
    mask = (
        (health_df.timestamp >= window_start) & (health_df.timestamp < window_end) &
        ~((health_df.payment_method == method) & (health_df.bank_gateway == gateway))
    )
    global_other_rate = float(health_df.loc[mask, "success_rate"].mean()) if mask.any() else None
    is_isolated = other_gateways_stable and other_methods_stable and (
        global_other_rate is None or global_other_rate >= HEALTHY_THRESHOLD
    )

    if is_isolated:
        classification = "gateway_specific_issue"
    elif not other_gateways_stable and other_methods_stable:
        classification = "payment_method_wide_issue"
    elif other_gateways_stable and not other_methods_stable:
        classification = "gateway_wide_issue"
    else:
        classification = "platform_wide_incident"

    statement = _build_statement(
        event, classification, other_gateway_rates, global_other_rate
    )

    return {
        "event": event,
        "classification": classification,
        "is_isolated": is_isolated,
        "other_gateway_rates": other_gateway_rates,
        "other_method_rates": other_method_rates,
        "global_other_slices_avg_rate": round(global_other_rate, 4) if global_other_rate is not None else None,
        "root_cause_statement": statement,
    }


def _build_statement(event: dict, classification: str, other_gateway_rates: dict, global_other_rate) -> str:
    method = event["payment_method"]
    gateway = event["bank_gateway"]
    baseline_pct = event["baseline_rate"] * 100
    current_pct = event["current_rate"] * 100
    start = pd.to_datetime(event["window_start"])
    end = pd.to_datetime(event["window_end"])
    time_range = f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')} on {start.strftime('%b %d')}"

    if classification == "gateway_specific_issue":
        comparison_note = ""
        if other_gateway_rates:
            best_other = max(other_gateway_rates, key=other_gateway_rates.get)
            comparison_note = (
                f" Other {method} gateways stayed healthy in the same window "
                f"(e.g. {best_other} at {other_gateway_rates[best_other]*100:.0f}%)."
            )
        return (
            f"{method} success rate on {gateway} dropped from {baseline_pct:.0f}% to {current_pct:.0f}% "
            f"between {time_range}, while other gateways remained stable — indicates a "
            f"{gateway}-specific issue, not a {method}-wide problem.{comparison_note}"
        )

    if classification == "payment_method_wide_issue":
        return (
            f"{method} success rate dropped sharply across multiple gateways (including {gateway}, "
            f"from {baseline_pct:.0f}% to {current_pct:.0f}%) during {time_range} — indicates a "
            f"{method}-wide issue rather than a single gateway problem."
        )

    if classification == "gateway_wide_issue":
        return (
            f"{gateway} success rate dropped across multiple payment methods during {time_range} "
            f"(seen here on {method}: {baseline_pct:.0f}% to {current_pct:.0f}%) — indicates a "
            f"{gateway}-wide issue affecting all payment methods routed through it, not just {method}."
        )

    return (
        f"{method} on {gateway} dropped from {baseline_pct:.0f}% to {current_pct:.0f}% during {time_range}, "
        f"alongside a broader decline across other slices (avg other-slice success rate "
        f"{global_other_rate*100:.0f}% in the same window) — indicates a platform-wide incident, "
        f"not isolated to this gateway."
    )


if __name__ == "__main__":
    from monitoring.health_monitor import load_health_data, compute_rolling_baseline
    from monitoring.anomaly_detector import detect_degradation_events

    health_df = load_health_data()
    enriched = compute_rolling_baseline(health_df)
    events = detect_degradation_events(enriched)
    for event in events:
        result = analyze(event, health_df)
        print(result["root_cause_statement"])
        print(f"Classification: {result['classification']}, isolated: {result['is_isolated']}")
