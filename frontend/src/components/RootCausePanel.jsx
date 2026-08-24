import { SEVERITY_COLOR } from "../palette";

function SeverityBadge({ severity }) {
  const color = SEVERITY_COLOR[severity] || SEVERITY_COLOR.medium;
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border"
      style={{ color, borderColor: color, background: `${color}1a` }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />
      {severity}
    </span>
  );
}

export default function RootCausePanel({ events }) {
  if (!events || events.length === 0) {
    return (
      <div className="bg-surface-raised border border-surface-border rounded-xl p-4">
        <h3 className="text-sm font-semibold text-slate-100 mb-1">Root cause</h3>
        <p className="text-xs text-slate-500">
          No degradation events detected yet. Run diagnosis to scan payment health.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-surface-raised border border-surface-border rounded-xl p-4 flex flex-col gap-4">
      <h3 className="text-sm font-semibold text-slate-100">Root cause analysis</h3>
      {events.map((e) => (
        <div key={e.event_id} className="border-l-2 pl-3" style={{ borderColor: SEVERITY_COLOR[e.severity] }}>
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <SeverityBadge severity={e.severity} />
            <span className="text-xs text-slate-400">
              {e.payment_method} · {e.bank_gateway}
            </span>
            <span className="text-xs text-slate-600">z={e.z_score}</span>
          </div>
          <p className="text-sm text-slate-200 leading-relaxed">{e.root_cause_statement}</p>
          <div className="flex gap-4 mt-2 text-xs text-slate-500">
            <span>Baseline: <span className="text-slate-300">{Math.round(e.baseline_rate * 100)}%</span></span>
            <span>Trough: <span className="text-slate-300">{Math.round(e.current_rate * 100)}%</span></span>
            <span>Window: <span className="text-slate-300">
              {new Date(e.window_start).toLocaleString(undefined, { hour: "2-digit", minute: "2-digit", day: "numeric", month: "short" })}
              {" – "}
              {new Date(e.window_end).toLocaleString(undefined, { hour: "2-digit", minute: "2-digit" })}
            </span></span>
          </div>
        </div>
      ))}
    </div>
  );
}
