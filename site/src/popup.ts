import {
  BOROUGH_NAMES,
  TAX_CLASS_LABELS,
  escapeHtml,
  formatDate,
  formatMoney,
  formatRate,
  titleCaseAddress,
} from "./format";

/** Matches the tile schema built in pipeline/08_build_tileset.py. Detail
 * fields (addr/sale/saledt/pctl/nsale) only exist at the tileset's single
 * highest native zoom -- see that script's docstring -- so they're optional
 * here even though every building has an address in the source data. */
export interface BuildingProps {
  bbl: string;
  boro: string;
  units: number;
  mkt: number | null;
  tax: number | null;
  r1: number | null;
  r2: number | null;
  t1: number;
  cls: string | null;
  addr?: string | null;
  sale?: number | null;
  saledt?: string | null;
  pctl?: number | null;
  nsale?: number | null;
}

function row(label: string, value: string, sub?: string): string {
  return `<div class="popup-row"><span class="popup-label">${label}</span><span class="popup-value">${value}${
    sub ? ` <span class="popup-value-sub">${sub}</span>` : ""
  }</span></div>`;
}

/** Builds the popup body per PLAN.md Site UX #2 -- address, tax class,
 * market/sale value, assessed value, computed tax, effective rate, which
 * tier it's based on, and a "for scale" comparison. Plain-language, not
 * internal jargon (t1/r1/tier1 are field names, never surfaced as-is). */
export function buildPopupHtml(p: BuildingProps): string {
  const boroName = BOROUGH_NAMES[p.boro] ?? p.boro;
  const clsLabel = p.cls ? (TAX_CLASS_LABELS[p.cls] ?? `class ${p.cls}`) : null;
  const subParts = [boroName, clsLabel].filter((x): x is string => Boolean(x));
  if (p.units > 1) subParts.push(`${p.units} units`);

  const title = p.addr ? escapeHtml(titleCaseAddress(p.addr)) : "This building";
  const zoomHint = p.addr ? "" : `<p class="popup-note">Zoom in for this building's own address and detail.</p>`;

  const rows: string[] = [];

  if (p.t1 === 1 && p.r1 != null) {
    // `sale` is the SUM of sale prices across every unit in this building
    // that sold in 2016-2025 (see PLAN.md Core metric's building-level
    // aggregation) -- for a single-family home that's one real sale price,
    // but for a co-op/condo tower it's a combined total across however many
    // units traded, not one transaction. Label accordingly so it doesn't
    // read as "this building sold for $4B."
    const soldFor = p.sale != null ? formatMoney(p.sale * 10_000) : null;
    if (soldFor && (p.nsale ?? 1) > 1) {
      rows.push(row(`Combined price, ${p.nsale} units sold here`, soldFor, p.saledt ? `latest ${formatDate(p.saledt)}` : undefined));
    } else if (soldFor) {
      rows.push(row("Sold for", soldFor, p.saledt ? `on ${formatDate(p.saledt)}` : undefined));
    }
    if (p.mkt != null) rows.push(row("DOF's assessed value", formatMoney(p.mkt * 10_000)));
    if (p.tax != null) rows.push(row("Computed annual tax", formatMoney(p.tax * 100)));
    rows.push(row("Effective rate", `${formatRate(p.r1)} of sale price`));
    if (p.pctl != null && clsLabel) {
      rows.push(
        `<p class="popup-scale">Pays a lower effective rate than ${p.pctl}% of ${boroName} buildings in this same tax class with a recent sale.</p>`,
      );
    }
  } else if (p.r2 != null) {
    if (p.mkt != null) rows.push(row("DOF's assessed value", formatMoney(p.mkt * 10_000)));
    if (p.tax != null) rows.push(row("Computed annual tax", formatMoney(p.tax * 100)));
    rows.push(row("Effective rate", `${formatRate(p.r2)} of DOF's value`));
    rows.push(
      `<p class="popup-note">Based on DOF's own valuation &mdash; no qualifying recent sale on record to check it against.</p>`,
    );
  } else {
    rows.push(`<p class="popup-note">No valuation on record (likely tax-exempt).</p>`);
  }

  return `
    <div class="popup">
      <h3>${title}</h3>
      ${subParts.length ? `<p class="popup-sub">${subParts.map(escapeHtml).join(" &middot; ")}</p>` : ""}
      ${zoomHint}
      ${rows.join("")}
      <p class="popup-footer">Tax is computed from public DOF data, not a scraped bill. BBL ${escapeHtml(p.bbl)}</p>
    </div>
  `;
}
