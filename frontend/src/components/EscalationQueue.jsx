import { useEffect, useState } from "react";
import { api } from "../api";
import { rupee } from "../format";

export default function EscalationQueue() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.getEscalations("agent")
      .then(setItems)
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="bg-surface-raised border border-surface-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-100">Escalation queue</h3>
        <span className="text-xs text-slate-500">{items.length} pending</span>
      </div>

      {loading && <div className="text-xs text-slate-500 py-6 text-center">Loading…</div>}
      {!loading && items.length === 0 && (
        <div className="text-xs text-slate-500 py-6 text-center">No escalations — nothing needs human follow-up.</div>
      )}

      {!loading && items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500 border-b border-surface-border">
                <th className="text-left py-2 pr-3 font-medium">Transaction</th>
                <th className="text-left py-2 pr-3 font-medium">Amount</th>
                <th className="text-left py-2 pr-3 font-medium">Failure type</th>
                <th className="text-left py-2 pr-3 font-medium">Retries</th>
                <th className="text-left py-2 pr-3 font-medium">Reason</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.transaction_id} className="border-b border-surface-border/50">
                  <td className="py-2 pr-3 text-slate-300">{it.transaction_id}</td>
                  <td className="py-2 pr-3 text-slate-200 font-medium">{rupee(it.amount)}</td>
                  <td className="py-2 pr-3 text-slate-400">{it.failure_type}</td>
                  <td className="py-2 pr-3 text-slate-400">{it.retry_count_so_far}</td>
                  <td className="py-2 pr-3 text-slate-500 max-w-xs truncate" title={it.reasoning}>
                    {it.reasoning}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
