// Dark-mode chart palette, values from the dataviz skill's validated reference
// palette (dark column) - the app renders dark-by-default per the project brief.

export const CHART_SURFACE = "#1a1a19";
export const PAGE_PLANE = "#0d0d0d";
export const INK_PRIMARY = "#ffffff";
export const INK_SECONDARY = "#c3c2b7";
export const INK_MUTED = "#898781";
export const GRIDLINE = "#2c2c2a";
export const BASELINE_AXIS = "#383835";

// fixed categorical order - never reassign per filter, never cycle past slot 8
export const CATEGORICAL = [
  "#3987e5", // 1 blue
  "#d95926", // 2 orange
  "#199e70", // 3 aqua
  "#c98500", // 4 yellow
  "#d55181", // 5 magenta
  "#008300", // 6 green
  "#9085e9", // 7 violet
  "#e66767", // 8 red
];

export const STATUS = {
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
};

export const SEQUENTIAL_BLUE = [
  "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b",
];

// stable gateway -> color assignment (categorical slots 1-6, fixed order)
export const GATEWAY_COLORS = {
  "PayFast Gateway": CATEGORICAL[0],
  "SecureBank Gateway": CATEGORICAL[1],
  "QuickPay Gateway": CATEGORICAL[2],
  "TrustBank Gateway": CATEGORICAL[3],
  "NationalPay Gateway": CATEGORICAL[4],
  "SwiftBank Gateway": CATEGORICAL[5],
};

export const SEVERITY_COLOR = {
  low: STATUS.good,
  medium: STATUS.warning,
  high: STATUS.serious,
  critical: STATUS.critical,
};
