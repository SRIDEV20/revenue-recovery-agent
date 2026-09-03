import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import App from "./App";
import { api } from "./api";

// Records the order in which api methods are invoked, so we can assert that the
// backend reset (triggerInjection) fully resolves BEFORE either panel refetches.
let callLog = [];

vi.mock("./api", () => {
  const track = (name, value) =>
    vi.fn(async (...args) => {
      callLog.push(name);
      return typeof value === "function" ? value(...args) : value;
    });

  return {
    api: {
      getHealthTimeseries: track("getHealthTimeseries", []),
      getHealthSlices: track("getHealthSlices", { payment_methods: [], bank_gateways: [] }),
      getDegradationEvents: track("getDegradationEvents", [
        {
          event_id: 1,
          payment_method: "UPI",
          bank_gateway: "PayFast Gateway",
          window_start: "2025-08-13T13:00:00",
          window_end: "2025-08-13T19:00:00",
          baseline_rate: 0.95,
          current_rate: 0.74,
          severity: "high",
          z_score: -4.2,
          root_cause_statement: "UPI via PayFast Gateway degraded.",
        },
      ]),
      getMetrics: track("getMetrics", {
        agent: { overall: { total_transactions: 0 }, degradation_linked: {} },
        baseline: { overall: { total_transactions: 0 }, degradation_linked: {} },
        comparison: {},
      }),
      runDiagnosis: track("runDiagnosis", { events_detected: 1, events: [] }),
      triggerInjection: track("triggerInjection", {
        detected: { payment_method: "wallet" },
        detected_correctly: true,
        ground_truth: {},
        all_events: [],
      }),
      runPolicyBatch: track("runPolicyBatch", { policy: "agent", transactions_processed: 380 }),
      getPipelineProgress: track("getPipelineProgress", { done: 0, total: 0, running: false }),

      // The two panels under test. Each returns a DIFFERENT payload on the 2nd+
      // call so a stale render is visually distinguishable from a fresh one.
      getDecisions: vi.fn(async () => {
        callLog.push("getDecisions");
        const n = api.getDecisions.mock.calls.length;
        return n === 1
          ? { items: [{ decision_id: 1, transaction_id: "txn_old", decision: "retry_now", reasoning: "old" }], total: 380 }
          : { items: [], total: 0 };
      }),
      getEscalations: vi.fn(async () => {
        callLog.push("getEscalations");
        const n = api.getEscalations.mock.calls.length;
        return n === 1
          ? [{ transaction_id: "txn_esc_old", amount: 9999, failure_type: "bank_decline", retry_count_so_far: 2, reasoning: "stale escalation" }]
          : [];
      }),
    },
  };
});

beforeEach(() => {
  callLog = [];
  vi.clearAllMocks();
});

describe("Escalation queue / Decision feed desync after Trigger live degradation", () => {
  it("both panels fetch once on initial mount", async () => {
    render(<App />);
    await waitFor(() => expect(api.getDecisions).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(api.getEscalations).toHaveBeenCalledTimes(1));

    // stale data from run #1 is on screen
    expect(await screen.findByText("txn_esc_old")).toBeInTheDocument();
    expect(screen.getByText(/1 pending/)).toBeInTheDocument();
  });

  it("Trigger live degradation remounts and refetches BOTH panels off the same event", async () => {
    render(<App />);
    await waitFor(() => expect(api.getEscalations).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("txn_esc_old")).toBeInTheDocument();

    callLog = [];
    fireEvent.click(screen.getByRole("button", { name: /Trigger live degradation/ }));

    // both panels must have refetched
    await waitFor(() => expect(api.getDecisions).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(api.getEscalations).toHaveBeenCalledTimes(2));

    // and the escalation panel must now show the fresh (empty) state, not the stale row
    await waitFor(() => expect(screen.queryByText("txn_esc_old")).not.toBeInTheDocument());
    expect(screen.getByText(/0 pending/)).toBeInTheDocument();
    expect(screen.getByText(/No escalations/)).toBeInTheDocument();

    // sequencing: the backend reset (triggerInjection) resolves BEFORE either
    // panel refetches - no race against a half-reset DB
    const injectIdx = callLog.indexOf("triggerInjection");
    const firstDecisionsIdx = callLog.indexOf("getDecisions");
    const firstEscalationsIdx = callLog.indexOf("getEscalations");
    expect(injectIdx).toBeGreaterThanOrEqual(0);
    expect(firstDecisionsIdx).toBeGreaterThan(injectIdx);
    expect(firstEscalationsIdx).toBeGreaterThan(injectIdx);
  });

  it("Diagnose also refetches both panels (same reset path)", async () => {
    render(<App />);
    await waitFor(() => expect(api.getEscalations).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: /1\. Diagnose/ }));

    await waitFor(() => expect(api.getDecisions).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(api.getEscalations).toHaveBeenCalledTimes(2));
  });
});
