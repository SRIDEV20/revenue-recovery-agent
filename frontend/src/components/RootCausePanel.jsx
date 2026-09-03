import { useState } from "react";
import { SEVERITY_COLOR } from "../palette";

const VISIBLE_COUNT = 2;

function ChevronIcon({ up }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`transition-transform ${up ? "rotate-180" : ""}`}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

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
  const [expanded, setExpanded] = useState(false);

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

  const visibleEvents = expanded ? events : events.slice(0, VISIBLE_COUNT);
  const remainingCount = events.length - VISIBLE_COUNT;

  return (
    <div className="bg-surface-raised border border-surface-border rounded-xl p-4 flex flex-col gap-4">
      <h3 className="text-sm font-semibold text-slate-100">Root cause analysis</h3>
      {visibleEvents.map((e) => (
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
      {remainingCount > 0 && (
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          className="flex items-center gap-1.5 text-xs font-medium text-slate-400 hover:text-slate-200 transition-colors -mt-2"
        >
          <ChevronIcon up={expanded} />
          {expanded ? "Show less" : `Show ${remainingCount} more event${remainingCount === 1 ? "" : "s"}`}
        </button>
      )}
    </div>
  );
}
