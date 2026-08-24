import { useEffect, useState, useCallback, useRef } from "react";
import { api } from "./api";
import MetricsCards from "./components/MetricsCards";
import PaymentHealthChart from "./components/PaymentHealthChart";
import RootCausePanel from "./components/RootCausePanel";
import RecoveryChart from "./components/RecoveryChart";
import DecisionFeed from "./components/DecisionFeed";
import EscalationQueue from "./components/EscalationQueue";
import LiveInjectionPanel from "./components/LiveInjectionPanel";

const INJECT_STAGES = ["Injecting anomaly…", "Detecting…", "Isolating root cause…"];

function StepButton({ label, onClick, loading, loadingLabel, done, disabled }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      className={`px-3 py-1.5 rounded-md text-xs font-medium border transition-colors
        ${done ? "border-emerald-700 text-emerald-400 bg-emerald-950/30" : "border-surface-border text-slate-200 bg-surface hover:bg-surface-raised"}
        disabled:opacity-40 disabled:cursor-not-allowed`}
    >
      {loading ? (loadingLabel || "Running…") : done ? `✓ ${label}` : label}
    </button>
  );
}

export default function App() {
  const [healthData, setHealthData] = useState([]);
  const [slices, setSlices] = useState(null);
  const [method, setMethod] = useState("UPI");
  const [events, setEvents] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [decisionsKey, setDecisionsKey] = useState(0);

  const [diagnoseState, setDiagnoseState] = useState("idle"); // idle | loading | done
  const [baselineState, setBaselineState] = useState("idle");
  const [agentState, setAgentState] = useState("idle");
  const [error, setError] = useState(null);

  const [injectState, setInjectState] = useState("idle");
  const [injectStageIdx, setInjectStageIdx] = useState(0);
  const [injectResult, setInjectResult] = useState(null);
  const injectTimerRef = useRef(null);

  const [agentProgress, setAgentProgress] = useState({ done: 0, total: 0 });
  const agentProgressTimerRef = useRef(null);

  const refreshReadData = useCallback(async () => {
    const [hd, sl, ev] = await Promise.all([
      api.getHealthTimeseries(),
      api.getHealthSlices(),
      api.getDegradationEvents(),
    ]);
    setHealthData(hd);
    setSlices(sl);
    setEvents(ev);
    if (ev.length && ev[0].payment_method) setMethod(ev[0].payment_method);
    // Rehydrate the "done" checkmark on page load/refresh from what's actually
    // persisted, rather than defaulting to "idle" just because local React state
    // doesn't survive a reload - the underlying data always did (it's fetched from
    // the backend/DB here, never held only client-side).
    if (ev.length) setDiagnoseState("done");
  }, []);

  const refreshMetrics = useCallback(async () => {
    try {
      const m = await api.getMetrics();
      setMetrics(m);
      if (m?.baseline?.overall?.total_transactions > 0) setBaselineState("done");
      if (m?.agent?.overall?.total_transactions > 0) setAgentState("done");
    } catch {
      setMetrics(null);
    }
  }, []);

  useEffect(() => {
    refreshReadData().catch((e) => setError(String(e)));
    refreshMetrics();
  }, [refreshReadData, refreshMetrics]);

  const runDiagnose = async () => {
    setError(null);
    setDiagnoseState("loading");
    try {
      await api.runDiagnosis(true);
      await refreshReadData();
      setDiagnoseState("done");
      setBaselineState("idle");
      setAgentState("idle");
    } catch (e) {
      setError(String(e.message || e));
      setDiagnoseState("idle");
    }
  };

  const runBaseline = async () => {
    setError(null);
    setBaselineState("loading");
    try {
      await api.runPolicyBatch("baseline");
      await refreshMetrics();
      setDecisionsKey((k) => k + 1);
      setBaselineState("done");
    } catch (e) {
      setError(String(e.message || e));
      setBaselineState("idle");
    }
  };

  const runAgent = async () => {
    setError(null);
    setAgentState("loading");
    setAgentProgress({ done: 0, total: 0 });
    // The agent run is one blocking POST making real OpenAI calls per transaction -
    // there's no other channel back to the client mid-request, so poll the backend's
    // progress counter (updated from inside the batch loop) to show real "X of Y"
    // progress instead of a bare spinner for what can be a couple of minutes.
    agentProgressTimerRef.current = setInterval(() => {
      api.getPipelineProgress().then(setAgentProgress).catch(() => {});
    }, 600);
    try {
      await api.runPolicyBatch("agent");
      await refreshMetrics();
      setDecisionsKey((k) => k + 1);
      setAgentState("done");
    } catch (e) {
      setError(String(e.message || e));
      setAgentState("idle");
    } finally {
      clearInterval(agentProgressTimerRef.current);
    }
  };

  const runInject = async () => {
    setError(null);
    setInjectState("loading");
    setInjectStageIdx(0);
    // Stage the loading text forward every ~800ms while the request is in flight -
    // purely cosmetic pacing of real progress, not an artificial delay: if the
    // response comes back sooner the stages just stop wherever they got to, and if
    // it takes longer the last stage stays shown until it resolves.
    injectTimerRef.current = setInterval(() => {
      setInjectStageIdx((i) => Math.min(i + 1, INJECT_STAGES.length - 1));
    }, 800);
    try {
      const result = await api.triggerInjection();
      await refreshReadData();
      if (result.detected) setMethod(result.detected.payment_method);
      setInjectResult(result);
      setInjectState("done");
      setDiagnoseState("done");
      setBaselineState("idle");
      setAgentState("idle");
    } catch (e) {
      setError(String(e.message || e));
      setInjectState("idle");
    } finally {
      clearInterval(injectTimerRef.current);
    }
  };

  return (
    <div className="min-h-screen bg-surface text-slate-100">
      <header className="border-b border-surface-border sticky top-0 bg-surface/95 backdrop-blur z-10">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-lg font-semibold">Revenue Recovery Agent</h1>
            <p className="text-xs text-slate-500">Payment degradation → root cause → recovery</p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <StepButton label="1. Diagnose" onClick={runDiagnose} loading={diagnoseState === "loading"} done={diagnoseState === "done"} />
            <StepButton label="2. Run baseline" onClick={runBaseline} loading={baselineState === "loading"} done={baselineState === "done"} disabled={diagnoseState === "idle" && !events.length} />
            <StepButton
              label="3. Run agent"
              onClick={runAgent}
              loading={agentState === "loading"}
              loadingLabel={agentProgress.total > 0 ? `Processing ${agentProgress.done}/${agentProgress.total}…` : "Starting…"}
              done={agentState === "done"}
              disabled={diagnoseState === "idle" && !events.length}
            />
            <span className="w-px h-5 bg-surface-border mx-1" />
            <StepButton
              label="⚡ Trigger live degradation"
              onClick={runInject}
              loading={injectState === "loading"}
              loadingLabel={INJECT_STAGES[injectStageIdx]}
              done={false}
            />
          </div>
        </div>
      </header>

      {error && (
        <div className="max-w-7xl mx-auto px-6 pt-4">
          <div className="border border-rose-800 bg-rose-950/40 text-rose-300 text-xs rounded-lg px-3 py-2">
            {error}
          </div>
        </div>
      )}

      <main className="max-w-7xl mx-auto px-6 py-6 flex flex-col gap-6">
        <LiveInjectionPanel
          loading={injectState === "loading"}
          stageLabel={INJECT_STAGES[injectStageIdx]}
          result={injectResult}
        />

        <MetricsCards metrics={metrics} />

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
          <div className="lg:col-span-2">
            <PaymentHealthChart
              healthData={healthData}
              events={events}
              slices={slices}
              method={method}
              onMethodChange={setMethod}
            />
          </div>
          <RootCausePanel events={events} />
        </div>

        <RecoveryChart metrics={metrics} />

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
          <div className="lg:col-span-2" key={`feed-${decisionsKey}`}>
            <DecisionFeed />
          </div>
          <div key={`esc-${decisionsKey}`}>
            <EscalationQueue />
          </div>
        </div>

        <footer className="text-xs text-slate-600 text-center py-4">
          Razorpay AI Buildathon 2026 — AI Revenue Recovery Track
        </footer>
      </main>
    </div>
  );
}
