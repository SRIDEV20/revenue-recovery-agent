const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${options.method || "GET"} ${path} failed: ${res.status} ${body}`);
  }
  return res.json();
}

export const api = {
  getHealthTimeseries: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request(`/health/timeseries${qs ? `?${qs}` : ""}`);
  },
  getHealthSlices: () => request("/health/slices"),
  getDegradationEvents: () => request("/health/events"),
  runDiagnosis: (reset = true) => request(`/pipeline/diagnose?reset=${reset}`, { method: "POST" }),
  triggerInjection: () => request("/pipeline/inject-and-detect", { method: "POST" }),
  runPolicyBatch: (policy) => request(`/pipeline/run/${policy}`, { method: "POST" }),
  getPipelineProgress: () => request("/pipeline/progress"),
  getMetrics: () => request("/metrics"),
  getDecisions: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request(`/decisions${qs ? `?${qs}` : ""}`);
  },
  getEscalations: (policy = "agent") => request(`/escalations?policy=${policy}`),
  getAuditLog: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request(`/audit-log${qs ? `?${qs}` : ""}`);
  },
  auditLogExportUrl: () => `${BASE_URL}/audit-log/export`,
};
