import { useMemo, useState } from "react";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ReferenceArea,
} from "recharts";
import { GATEWAY_COLORS, GRIDLINE, INK_MUTED, INK_SECONDARY, CHART_SURFACE } from "../palette";

function formatTick(iso) {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:00`;
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div className="bg-surface-raised border border-surface-border rounded-lg px-3 py-2 text-xs shadow-lg">
      <div className="text-slate-400 mb-1">{formatTick(label)}</div>
      {payload
        .slice()
        .sort((a, b) => b.value - a.value)
        .map((p) => (
          <div key={p.dataKey} className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full" style={{ background: p.color }} />
            <span className="text-slate-300">{p.dataKey}</span>
            <span className="ml-auto font-medium text-slate-100">{(p.value * 100).toFixed(1)}%</span>
          </div>
        ))}
    </div>
  );
}

export default function PaymentHealthChart({ healthData, events, slices, method, onMethodChange }) {
  const gateways = useMemo(() => {
    if (!slices?.bank_gateways) return [];
    return slices.bank_gateways;
  }, [slices]);

  const pivoted = useMemo(() => {
    if (!healthData?.length) return [];
    const byTime = new Map();
    for (const row of healthData) {
      if (row.payment_method !== method) continue;
      if (!byTime.has(row.timestamp)) byTime.set(row.timestamp, { timestamp: row.timestamp });
      byTime.get(row.timestamp)[row.bank_gateway] = row.success_rate;
    }
    return Array.from(byTime.values()).sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  }, [healthData, method]);

  // Highlight EVERY detected event for the selected method (the original seed anomaly
  // plus any live-triggered ones), not just the first — so a freshly injected event
  // shows up alongside the original rather than being hidden behind it.
  const matchingEvents = useMemo(() => {
    if (!events?.length) return [];
    const matches = events.filter((e) => e.payment_method === method);
    return matches.length ? matches : (events[0] ? [events[0]] : []);
  }, [events, method]);

  // payment_health.timestamp uses "YYYY-MM-DD HH:MM:SS" (space); degradation_events
  // window_start/window_end are ISO strings with a "T" separator. Normalize so each
  // ReferenceArea's x1/x2 exactly match a category value on the chart's x-axis.
  const eventWindows = useMemo(() => matchingEvents.map((e) => ({
    key: e.event_id,
    x1: e.window_start.replace("T", " "),
    x2: e.window_end.replace("T", " "),
  })), [matchingEvents]);

  return (
    <div className="bg-surface-raised border border-surface-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-100">Payment health over time</h3>
          <p className="text-xs text-slate-500">Success rate by gateway — degradation window highlighted</p>
        </div>
        <select
          value={method}
          onChange={(e) => onMethodChange(e.target.value)}
          className="bg-surface border border-surface-border rounded-md text-xs px-2 py-1 text-slate-200"
        >
          {(slices?.payment_methods || []).map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>

      {pivoted.length === 0 ? (
        <div
          className="flex items-center justify-center text-xs text-slate-500 border border-dashed border-surface-border rounded-lg"
          style={{ height: 320 }}
        >
          No health data yet — run <span className="text-slate-400 mx-1">1. Diagnose</span> to load the payment health timeline.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={pivoted} margin={{ top: 4, right: 12, left: 0, bottom: 4 }}>
            <CartesianGrid stroke={GRIDLINE} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="timestamp"
              tickFormatter={formatTick}
              stroke={INK_MUTED}
              tick={{ fontSize: 11, fill: INK_MUTED }}
              minTickGap={60}
            />
            <YAxis
              domain={[0.5, 1]}
              tickFormatter={(v) => `${Math.round(v * 100)}%`}
              stroke={INK_MUTED}
              tick={{ fontSize: 11, fill: INK_MUTED }}
              width={44}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ fontSize: 11, color: INK_SECONDARY }} />
            {eventWindows.map((w) => (
              <ReferenceArea
                key={w.key}
                x1={w.x1}
                x2={w.x2}
                fill="#d03b3b"
                fillOpacity={0.12}
                stroke="#d03b3b"
                strokeOpacity={0.4}
                strokeDasharray="4 2"
                label={{ value: "degradation window", position: "insideTop", fill: "#e66767", fontSize: 10 }}
              />
            ))}
            {gateways.map((g) => (
              <Line
                key={g}
                type="monotone"
                dataKey={g}
                stroke={GATEWAY_COLORS[g] || "#3987e5"}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
