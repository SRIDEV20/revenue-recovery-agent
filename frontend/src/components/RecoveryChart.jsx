import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend,
} from "recharts";
import { CATEGORICAL, GRIDLINE, INK_MUTED, INK_SECONDARY } from "../palette";

const AGENT_COLOR = CATEGORICAL[0]; // blue
const BASELINE_COLOR = CATEGORICAL[1]; // orange

function CustomTooltip({ active, payload, label, formatter }) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div className="bg-surface-raised border border-surface-border rounded-lg px-3 py-2 text-xs shadow-lg">
      <div className="text-slate-400 mb-1">{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ background: p.color }} />
          <span className="text-slate-300">{p.dataKey}</span>
          <span className="ml-auto font-medium text-slate-100">{formatter(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

function MiniBarChart({ title, data, formatter, unit }) {
  return (
    <div>
      <h4 className="text-xs font-medium text-slate-400 mb-2">{title}</h4>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid stroke={GRIDLINE} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="name" stroke={INK_MUTED} tick={{ fontSize: 11, fill: INK_MUTED }} />
          <YAxis
            stroke={INK_MUTED}
            tick={{ fontSize: 11, fill: INK_MUTED }}
            width={44}
            tickFormatter={(v) => unit === "%" ? `${v}%` : `₹${Math.round(v / 1000)}k`}
          />
          <Tooltip content={<CustomTooltip formatter={formatter} />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
          <Legend wrapperStyle={{ fontSize: 11, color: INK_SECONDARY }} />
          <Bar dataKey="Agent" fill={AGENT_COLOR} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="Baseline" fill={BASELINE_COLOR} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function RecoveryChart({ metrics }) {
  if (!metrics || !metrics.agent) {
    return (
      <div className="bg-surface-raised border border-surface-border rounded-xl p-4 h-64 animate-pulse" />
    );
  }

  const revenueData = [
    { name: "Overall", Agent: metrics.agent.overall.net_revenue_recovered_rs, Baseline: metrics.baseline.overall.net_revenue_recovered_rs },
    { name: "Degradation-linked", Agent: metrics.agent.degradation_linked.net_revenue_recovered_rs, Baseline: metrics.baseline.degradation_linked.net_revenue_recovered_rs },
  ];

  const rateData = [
    { name: "Overall", Agent: metrics.agent.overall.recovery_rate_pct, Baseline: metrics.baseline.overall.recovery_rate_pct },
    { name: "Degradation-linked", Agent: metrics.agent.degradation_linked.recovery_rate_pct, Baseline: metrics.baseline.degradation_linked.recovery_rate_pct },
  ];

  return (
    <div className="bg-surface-raised border border-surface-border rounded-xl p-4">
      <h3 className="text-sm font-semibold text-slate-100 mb-1">Agent vs baseline recovery</h3>
      <p className="text-xs text-slate-500 mb-3">
        Degradation-linked gap is the proof point: baseline retries blindly into the outage, the agent waits/reroutes.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <MiniBarChart title="Net revenue recovered (₹)" data={revenueData} formatter={(v) => `₹${Math.round(v).toLocaleString("en-IN")}`} unit="rs" />
        <MiniBarChart title="Recovery rate (%)" data={rateData} formatter={(v) => `${v}%`} unit="%" />
      </div>
    </div>
  );
}
