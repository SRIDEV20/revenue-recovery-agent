// Single source of truth for currency formatting so the decision feed, metrics
// cards, escalation queue, and recovery chart all render amounts identically.
export function rupee(n) {
  return `₹${Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}
