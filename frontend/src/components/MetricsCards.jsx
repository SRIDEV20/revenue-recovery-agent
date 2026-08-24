import { rupee } from "../format";

const NOT_RUN = "—";

function Card({ label, value, sub, accent }) {
  return (
    <div className="bg-surface-raised border border-surface-border rounded-xl p-4 flex flex-col gap-1">
      <span className="text-xs uppercase tracking-wide text-slate-400">{label}</span>
      <span className={`text-2xl font-semibold ${accent || "text-slate-100"}`}>{value}</span>
      {sub && <span className="text-xs text-slate-500">{sub}</span>}
    </div>
  );
}

export default function MetricsCards({ metrics }) {
  if (!metrics || !metrics.agent) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="bg-surface-raised border border-surface-border rounded-xl p-4 h-24 animate-pulse" />
        ))}
      </div>
    );
  }

  const agent = metrics.agent.overall;
  const baseline = metrics.baseline.overall;
  const comparison = metrics.comparison;
  const agentDeg = metrics.agent.degradation_linked;
  const baselineDeg = metrics.baseline.degradation_linked;

  // Neither side's numbers mean anything until that policy has actually been run -
  // total_transactions === 0 is the signal. Showing a real delta (especially a
  // negative one) against an un-run policy would misleadingly imply it underperformed.
  const agentRun = agent.total_transactions > 0;
  const baselineRun = baseline.total_transactions > 0;
  const bothRun = agentRun && baselineRun;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Card
        label="Agent net revenue recovered"
        value={agentRun ? rupee(agent.net_revenue_recovered_rs) : NOT_RUN}
        sub={agentRun ? `baseline: ${baselineRun ? rupee(baseline.net_revenue_recovered_rs) : "not run yet"}` : "run the agent to see results"}
        accent="text-emerald-400"
      />
      <Card
        label="Revenue delta vs baseline"
        value={bothRun ? `${comparison.net_revenue_delta_rs >= 0 ? "+" : ""}${rupee(comparison.net_revenue_delta_rs)}` : NOT_RUN}
        sub={bothRun ? "agent minus baseline, net" : "run both policies to compare"}
        accent={bothRun ? (comparison.net_revenue_delta_rs >= 0 ? "text-emerald-400" : "text-rose-400") : "text-slate-500"}
      />
      <Card
        label="Recovery rate (overall)"
        value={agentRun ? `${agent.recovery_rate_pct}%` : NOT_RUN}
        sub={`baseline: ${baselineRun ? `${baseline.recovery_rate_pct}%` : "not run yet"}`}
        accent="text-sky-400"
      />
      <Card
        label="Recovery rate (degradation-linked)"
        value={agentRun ? `${agentDeg.recovery_rate_pct}%` : NOT_RUN}
        sub={`baseline: ${baselineRun ? `${baselineDeg.recovery_rate_pct}%` : "not run yet"} — this is the root-cause-layer proof point`}
        accent="text-amber-400"
      />
      <Card
        label="Cost to recover / ₹100"
        value={agentRun ? `₹${agent.cost_to_recover_per_100}` : NOT_RUN}
        sub={`baseline: ${baselineRun ? `₹${baseline.cost_to_recover_per_100}` : "not run yet"}`}
      />
      <Card
        label="Escalations (agent)"
        value={agentRun ? agent.escalation_count : NOT_RUN}
        sub={`baseline: ${baselineRun ? baseline.escalation_count : "not run yet"}`}
      />
      <Card
        label="Transactions processed"
        value={agent.total_transactions}
        sub={agentRun ? `${agent.successes} recovered` : "run the agent from the controls above"}
      />
      <Card
        label="Degradation-linked txns"
        value={agentDeg.total_transactions}
        sub={agentRun ? `${agentDeg.successes} recovered by agent vs ${baselineRun ? baselineDeg.successes : "—"} by baseline` : "run the agent to see this breakdown"}
      />
    </div>
  );
}
