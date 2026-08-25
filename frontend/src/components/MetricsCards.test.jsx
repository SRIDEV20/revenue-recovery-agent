import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import MetricsCards from "./MetricsCards";

const EMPTY_SUMMARY = {
  total_transactions: 0,
  successes: 0,
  recovery_rate_pct: 0,
  total_revenue_recovered_rs: 0,
  net_revenue_recovered_rs: 0,
  total_cost_rs: 0,
  cost_to_recover_per_100: 0,
  escalation_count: 0,
};

function summary(overrides) {
  return { ...EMPTY_SUMMARY, ...overrides };
}

describe("MetricsCards", () => {
  it("renders a loading skeleton and does not crash when metrics is missing", () => {
    const { container } = render(<MetricsCards metrics={null} />);

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders a loading skeleton when only baseline has run (no agent data yet)", () => {
    const { container } = render(
      <MetricsCards metrics={{ baseline: { overall: summary({ total_transactions: 10 }) } }} />
    );

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("does not crash on an all-zero (nothing run yet) metrics payload", () => {
    const metrics = {
      agent: { overall: EMPTY_SUMMARY, degradation_linked: EMPTY_SUMMARY },
      baseline: { overall: EMPTY_SUMMARY, degradation_linked: EMPTY_SUMMARY },
      comparison: {
        net_revenue_delta_rs: 0,
        recovery_rate_delta_pct_points: 0,
        degradation_linked_recovery_rate_delta_pct_points: 0,
        degradation_linked_net_revenue_delta_rs: 0,
      },
    };

    render(<MetricsCards metrics={metrics} />);

    expect(screen.getByText("Transactions processed")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("renders real recovered-revenue figures once both policies have run", () => {
    const metrics = {
      agent: {
        overall: summary({
          total_transactions: 300,
          successes: 242,
          recovery_rate_pct: 80.81,
          net_revenue_recovered_rs: 121000,
          cost_to_recover_per_100: 3.5,
          escalation_count: 12,
        }),
        degradation_linked: summary({
          total_transactions: 80,
          successes: 65,
          recovery_rate_pct: 81.25,
        }),
      },
      baseline: {
        overall: summary({
          total_transactions: 300,
          successes: 89,
          recovery_rate_pct: 29.65,
          net_revenue_recovered_rs: 44000,
          cost_to_recover_per_100: 5.1,
          escalation_count: 4,
        }),
        degradation_linked: summary({
          total_transactions: 80,
          successes: 24,
          recovery_rate_pct: 30.0,
        }),
      },
      comparison: {
        net_revenue_delta_rs: 77000,
        recovery_rate_delta_pct_points: 51.16,
        degradation_linked_recovery_rate_delta_pct_points: 51.16,
        degradation_linked_net_revenue_delta_rs: 30000,
      },
    };

    render(<MetricsCards metrics={metrics} />);

    expect(screen.getByText("₹1,21,000")).toBeInTheDocument();
    expect(screen.getByText("80.81%")).toBeInTheDocument();
    expect(screen.getByText("+₹77,000")).toBeInTheDocument();
  });
});
