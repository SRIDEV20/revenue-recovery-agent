import { SEVERITY_COLOR } from "../palette";

function fmtPct(v) {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

function fmtWindow(iso) {
  return new Date(iso).toLocaleString(undefined, {
    hour: "2-digit", minute: "2-digit", day: "numeric", month: "short",
  });
}

export default function LiveInjectionPanel({ loading, stageLabel, result }) {
  if (!loading && !result) return null;

  return (
    <div className="border border-amber-800/50 bg-amber-950/10 rounded-xl p-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-amber-400 text-sm font-semibold">⚡ Live degradation trigger</span>
        {loading && <span className="text-xs text-amber-300/90 animate-pulse">{stageLabel}</span>}
      </div>

      {!loading && result && (
        result.detected ? (
          <>
            <div className="flex items-center gap-2 flex-wrap">
              <span
                className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border"
                style={{
                  color: SEVERITY_COLOR[result.detected.severity] || SEVERITY_COLOR.medium,
                  borderColor: SEVERITY_COLOR[result.detected.severity] || SEVERITY_COLOR.medium,
                  background: `${SEVERITY_COLOR[result.detected.severity] || SEVERITY_COLOR.medium}1a`,
                }}
              >
                {result.detected.severity}
              </span>
              <span className="text-xs text-slate-400">
                {result.detected.payment_method} · {result.detected.bank_gateway}
              </span>
              <span className="text-xs text-emerald-400">✓ detected independently by the pipeline</span>
            </div>
            <p className="text-sm text-slate-200 leading-relaxed">{result.detected.root_cause_statement}</p>
            <details className="text-xs text-slate-500">
              <summary className="cursor-pointer select-none hover:text-slate-400">
                Ground truth (what was actually injected, for verification)
              </summary>
              <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 pl-1">
                <span>Slice: <span className="text-slate-300">{result.ground_truth.payment_method} / {result.ground_truth.bank_gateway}</span></span>
                <span>Window: <span className="text-slate-300">{fmtWindow(result.ground_truth.window_start)} – {fmtWindow(result.ground_truth.window_end)}</span></span>
                <span>Baseline → injected: <span className="text-slate-300">{fmtPct(result.ground_truth.baseline_rate)} → {fmtPct(result.ground_truth.injected_rate)}</span></span>
                <span>New transactions: <span className="text-slate-300">{result.ground_truth.new_transaction_count}</span></span>
              </div>
            </details>
          </>
        ) : (
          <div className="text-xs text-rose-400">
            Injected a {result.ground_truth.payment_method}/{result.ground_truth.bank_gateway} degradation
            (baseline {fmtPct(result.ground_truth.baseline_rate)} → {fmtPct(result.ground_truth.injected_rate)}),
            but the detector did not flag it this run — try again (this is rare; it means the random
            trough landed too close to healthy noise to clear the detection threshold).
          </div>
        )
      )}
    </div>
  );
}
