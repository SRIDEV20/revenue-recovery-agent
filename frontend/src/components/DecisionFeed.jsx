import { useEffect, useState } from "react";
import { api } from "../api";
import { rupee } from "../format";

const DECISION_LABELS = {
  retry_now: "Retry now",
  retry_delayed: "Retry (delayed)",
  send_discount: "Send discount",
  send_reminder: "Send reminder",
  reroute_gateway: "Reroute gateway",
  escalate: "Escalate",
  give_up: "Give up",
};

const DECISION_COLOR = {
  retry_now: "text-sky-400 border-sky-800 bg-sky-950/40",
  retry_delayed: "text-amber-400 border-amber-800 bg-amber-950/40",
  send_discount: "text-violet-400 border-violet-800 bg-violet-950/40",
  send_reminder: "text-emerald-400 border-emerald-800 bg-emerald-950/40",
  reroute_gateway: "text-teal-400 border-teal-800 bg-teal-950/40",
  escalate: "text-rose-400 border-rose-800 bg-rose-950/40",
  give_up: "text-slate-400 border-slate-700 bg-slate-800/40",
};

export default function DecisionFeed() {
  const [policy, setPolicy] = useState("agent");
  const [degOnly, setDegOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(false);
  const pageSize = 10;

  useEffect(() => {
    setLoading(true);
    const params = { policy, page, page_size: pageSize };
    if (degOnly) params.degradation_linked = true;
    api.getDecisions(params)
      .then(setData)
      .catch(() => setData({ items: [], total: 0 }))
      .finally(() => setLoading(false));
  }, [policy, degOnly, page]);

  const totalPages = Math.max(1, Math.ceil(data.total / pageSize));

  return (
    <div className="bg-surface-raised border border-surface-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h3 className="text-sm font-semibold text-slate-100">Decision feed</h3>
        <div className="flex items-center gap-2">
          <select
            value={policy}
            onChange={(e) => { setPolicy(e.target.value); setPage(1); }}
            className="bg-surface border border-surface-border rounded-md text-xs px-2 py-1 text-slate-200"
          >
            <option value="agent">Agent</option>
            <option value="baseline">Baseline</option>
          </select>
          <label className="flex items-center gap-1.5 text-xs text-slate-400">
            <input
              type="checkbox"
              checked={degOnly}
              onChange={(e) => { setDegOnly(e.target.checked); setPage(1); }}
              className="accent-sky-500"
            />
            degradation-linked only
          </label>
        </div>
      </div>

      <div className="flex flex-col gap-2 min-h-[280px]">
        {loading && <div className="text-xs text-slate-500 py-8 text-center">Loading…</div>}
        {!loading && data.items.length === 0 && (
          <div className="text-xs text-slate-500 py-8 text-center">
            No decisions yet — run the {policy} batch from the controls above.
          </div>
        )}
        {!loading && data.items.map((d) => (
          <div key={d.decision_id} className="border border-surface-border rounded-lg p-3">
            <div className="flex items-center gap-2 flex-wrap mb-1.5">
              <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${DECISION_COLOR[d.decision] || ""}`}>
                {DECISION_LABELS[d.decision] || d.decision}
              </span>
              {!!d.degradation_linked && (
                <span className="text-xs px-2 py-0.5 rounded-full border border-rose-800 text-rose-400 bg-rose-950/30">
                  degradation-linked
                </span>
              )}
              <span className="text-xs text-slate-500 ml-auto">{d.transaction_id}</span>
            </div>
            <p className="text-sm text-slate-300 leading-snug">{d.reasoning}</p>
            <div className="flex gap-3 mt-2 text-xs text-slate-500 flex-wrap">
              <span>{d.payment_method} · {d.bank_gateway}</span>
              <span>{d.failure_type}</span>
              <span>{rupee(d.amount)}</span>
              <span>confidence {Math.round((d.confidence || 0) * 100)}%</span>
              {d.success != null && (
                <span className={d.success ? "text-emerald-400" : "text-slate-500"}>
                  {d.success ? `recovered ${rupee(d.net_recovered)}` : "not recovered"}
                </span>
              )}
              {!d.allowed && d.block_reason && (
                <span className="text-amber-400">rule override: {d.block_reason}</span>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between mt-3 text-xs text-slate-500">
        <span>{data.total} decisions</span>
        <div className="flex items-center gap-2">
          <button
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => p - 1)}
            className="px-2 py-1 border border-surface-border rounded-md disabled:opacity-30"
          >
            prev
          </button>
          <span>{page} / {totalPages}</span>
          <button
            disabled={page >= totalPages || loading}
            onClick={() => setPage((p) => p + 1)}
            className="px-2 py-1 border border-surface-border rounded-md disabled:opacity-30"
          >
            next
          </button>
        </div>
      </div>
    </div>
  );
}
