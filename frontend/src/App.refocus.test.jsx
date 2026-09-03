import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

import App from "./App";
import { api } from "./api";

// Controllable clock so we can cross (or not cross) the refocus throttle window.
let nowMs = 1_700_000_000_000;

vi.mock("./api", () => {
  const stub = (value) =>
    vi.fn(async (...args) => (typeof value === "function" ? value(...args) : value));
  return {
    api: {
      getHealthTimeseries: stub([]),
      getHealthSlices: stub({ payment_methods: [], bank_gateways: [] }),
      getDegradationEvents: stub([
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
      getMetrics: stub({
        agent: { overall: { total_transactions: 0 }, degradation_linked: {} },
        baseline: { overall: { total_transactions: 0 }, degradation_linked: {} },
        comparison: {},
      }),
      runDiagnosis: stub({ events_detected: 1, events: [] }),
      triggerInjection: stub({ detected: null, detected_correctly: false, ground_truth: {}, all_events: [] }),
      runPolicyBatch: stub({ policy: "agent", transactions_processed: 380 }),
      getPipelineProgress: stub({ done: 0, total: 0, running: false }),
      getDecisions: stub({ items: [], total: 0 }),
      getEscalations: stub([]),
    },
  };
});

beforeEach(() => {
  nowMs = 1_700_000_000_000;
  vi.spyOn(Date, "now").mockImplementation(() => nowMs);
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function mountAndSettle() {
  render(<App />);
  // let initial effects + both panel fetches resolve
  await waitFor(() => expect(api.getDecisions).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(api.getEscalations).toHaveBeenCalledTimes(1));
}

describe("refetch-on-refocus safeguard (Render cold-start case)", () => {
  it("(a) a focus event after the throttle window bumps the key and refetches BOTH panels", async () => {
    await mountAndSettle();

    nowMs += 60_000; // > REFOCUS_REFETCH_MS (45s) since mount
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });

    await waitFor(() => expect(api.getDecisions).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(api.getEscalations).toHaveBeenCalledTimes(2));
  });

  it("(a') a visibilitychange event (tab becomes visible) also refetches both panels", async () => {
    await mountAndSettle();

    nowMs += 60_000;
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    await waitFor(() => expect(api.getDecisions).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(api.getEscalations).toHaveBeenCalledTimes(2));
  });

  it("(b) two focus events in rapid succession only refetch once, not twice", async () => {
    await mountAndSettle();

    nowMs += 60_000; // cross the window once
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    await waitFor(() => expect(api.getDecisions).toHaveBeenCalledTimes(2));

    // second (and third) focus only 3s later - inside the throttle window
    nowMs += 3_000;
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new Event("focus"));
    });

    // flush anything pending, then assert NO extra refetch happened
    await act(async () => {});
    expect(api.getDecisions).toHaveBeenCalledTimes(2);
    expect(api.getEscalations).toHaveBeenCalledTimes(2);
  });

  it("(b') a deliberate run resets the throttle clock - a focus right after it does NOT refetch again", async () => {
    await mountAndSettle();

    // user clicks "Run baseline" -> bumpDecisionsKey stamps lastBumpRef = now
    nowMs += 60_000;
    fireEvent.click(screen.getByRole("button", { name: /2\. Run baseline/ }));
    await waitFor(() => expect(api.getDecisions).toHaveBeenCalledTimes(2));

    // tab regains focus 10s after the run - within the throttle window
    nowMs += 10_000;
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    await act(async () => {});
    expect(api.getDecisions).toHaveBeenCalledTimes(2);
    expect(api.getEscalations).toHaveBeenCalledTimes(2);
  });

  it("does not refetch on a focus event fired immediately after mount (inside the window)", async () => {
    await mountAndSettle();

    nowMs += 5_000; // only 5s since mount
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    await act(async () => {});
    expect(api.getDecisions).toHaveBeenCalledTimes(1);
    expect(api.getEscalations).toHaveBeenCalledTimes(1);
  });
});
