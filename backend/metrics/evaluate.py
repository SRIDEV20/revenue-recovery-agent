"""
Agent vs baseline evaluation, read from the persisted outcomes/decisions/transactions.

Computes, per policy ('agent' vs 'baseline'):
  - total_revenue_recovered_rs   : sum of amount_recovered where success
  - net_revenue_recovered_rs     : sum of net_recovered (minus discount cost + action cost)
  - recovery_rate_pct            : successes / total transactions attempted, as %
  - cost_to_recover_per_100      : (total discount_cost + action_cost) / gross recovered * 100
  - escalation_count             : count of actions_taken where action_type == 'escalate'
  - total_transactions           : count of transactions this policy acted on

Also breaks out the SAME metrics restricted to degradation_linked = true transactions,
which is the number that should show the biggest agent-vs-baseline gap (proves the
root-cause layer matters) - since baseline retries blindly into the outage while the
agent waits/reroutes.
"""

import pandas as pd

from db import get_connection


def _load_outcomes_df() -> pd.DataFrame:
    conn = get_connection()
    try:
        df = pd.read_sql_query(
            """
            SELECT o.transaction_id, o.policy, o.success, o.amount_recovered, o.discount_cost,
                   o.action_cost, o.net_recovered, a.action_type, d.decision, d.degradation_linked
            FROM outcomes o
            JOIN actions_taken a ON o.action_id = a.action_id
            JOIN decisions d ON a.decision_id = d.decision_id
            """,
            conn,
        )
    finally:
        conn.close()
    return df


def _summarize(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "total_transactions": 0, "successes": 0, "recovery_rate_pct": 0.0,
            "total_revenue_recovered_rs": 0.0, "net_revenue_recovered_rs": 0.0,
            "total_cost_rs": 0.0, "cost_to_recover_per_100": 0.0, "escalation_count": 0,
        }

    total = len(df)
    successes = int(df["success"].sum())
    gross = float(df.loc[df["success"] == 1, "amount_recovered"].sum())
    net = float(df["net_recovered"].sum())
    total_cost = float((df["discount_cost"] + df["action_cost"]).sum())
    escalations = int((df["action_type"] == "escalate").sum())

    return {
        "total_transactions": total,
        "successes": successes,
        "recovery_rate_pct": round(100 * successes / total, 2) if total else 0.0,
        "total_revenue_recovered_rs": round(gross, 2),
        "net_revenue_recovered_rs": round(net, 2),
        "total_cost_rs": round(total_cost, 2),
        "cost_to_recover_per_100": round(100 * total_cost / gross, 2) if gross > 0 else 0.0,
        "escalation_count": escalations,
    }


def compute_metrics() -> dict:
    df = _load_outcomes_df()

    result = {"agent": {}, "baseline": {}}
    for policy in ("agent", "baseline"):
        policy_df = df[df.policy == policy]
        result[policy]["overall"] = _summarize(policy_df)
        result[policy]["degradation_linked"] = _summarize(policy_df[policy_df.degradation_linked == 1])
        result[policy]["non_degradation_linked"] = _summarize(policy_df[policy_df.degradation_linked == 0])

    # headline comparison deltas
    agent_overall = result["agent"]["overall"]
    baseline_overall = result["baseline"]["overall"]
    agent_degraded = result["agent"]["degradation_linked"]
    baseline_degraded = result["baseline"]["degradation_linked"]

    result["comparison"] = {
        "net_revenue_delta_rs": round(
            agent_overall["net_revenue_recovered_rs"] - baseline_overall["net_revenue_recovered_rs"], 2
        ),
        "recovery_rate_delta_pct_points": round(
            agent_overall["recovery_rate_pct"] - baseline_overall["recovery_rate_pct"], 2
        ),
        "degradation_linked_recovery_rate_delta_pct_points": round(
            agent_degraded["recovery_rate_pct"] - baseline_degraded["recovery_rate_pct"], 2
        ),
        "degradation_linked_net_revenue_delta_rs": round(
            agent_degraded["net_revenue_recovered_rs"] - baseline_degraded["net_revenue_recovered_rs"], 2
        ),
    }

    return result


if __name__ == "__main__":
    import json
    print(json.dumps(compute_metrics(), indent=2))
