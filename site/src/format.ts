export const BOROUGH_NAMES: Record<string, string> = {
  MN: "Manhattan",
  BX: "The Bronx",
  BK: "Brooklyn",
  QN: "Queens",
  SI: "Staten Island",
};

export const TAX_CLASS_LABELS: Record<string, string> = {
  "1": "1–3 family home",
  "2": "co-op / condo / rental",
  "3": "utility",
  "4": "commercial / industrial",
};

export const ALL_BOROUGHS = ["MN", "BX", "BK", "QN", "SI"];
export const ALL_TAX_CLASSES = ["1", "2", "3", "4"];

/** mkt/tax/sale tile fields are quantized ($10K or $100 units) -- see PLAN.md Performance strategy. */
export function formatMoney(dollars: number): string {
  // Combined multi-unit sale totals (see popup.ts's nsale handling) can
  // reach into the billions for a whole condo tower's worth of sales.
  if (dollars >= 10_000_000_000) return `$${Math.round(dollars / 1_000_000_000)}B`;
  if (dollars >= 1_000_000_000) return `$${(dollars / 1_000_000_000).toFixed(1)}B`;
  if (dollars >= 10_000_000) return `$${Math.round(dollars / 1_000_000)}M`;
  if (dollars >= 1_000_000) return `$${(dollars / 1_000_000).toFixed(1)}M`;
  if (dollars >= 1_000) return `$${Math.round(dollars / 1000)}K`;
  return `$${Math.round(dollars)}`;
}

/** r1/r2 tile fields are rate*10000 -- see colors.ts. */
export function formatRate(rateX10000: number): string {
  return `${(rateX10000 / 100).toFixed(2)}%`;
}

export function formatDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  if (!y || !m || !d) return isoDate;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** PLUTO addresses come back ALL CAPS -- title-case for display. */
export function titleCaseAddress(addr: string): string {
  return addr
    .toLowerCase()
    .split(" ")
    .map((w) => (w.length ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => {
    switch (c) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      default:
        return "&#39;";
    }
  });
}
