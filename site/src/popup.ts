import {
  BOROUGH_NAMES,
  TAX_CLASS_LABELS,
  escapeHtml,
  formatDate,
  formatMoney,
  formatRate,
  titleCaseAddress,
} from "./format";

/** Matches the tile schema built in pipeline/11_build_tileset.py. Detail
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
  // v2 roadmap (PLAN.md milestone 10): owner-entity, stacked-benefit, and
  // dollar-gap fields, all detail-zoom-only like the fields above. llcPct/
  // ownerEntity/benefits are only present at all when nonzero/applicable
  // (pipeline/11_build_tileset.py NULLs out the default case rather than
  // shipping an explicit 0/false for 856K features) -- absent here means
  // either "not zoomed in" or "genuinely none," which render identically
  // (nothing shown), so no separate signal is needed to tell them apart.
  llcPct?: number | null;
  ownerEntity?: string | null;
  // Bitmask: 1=421-a exemption, 2=J-51 exemption, 4=J-51 abatement,
  // 8=co-op/condo abatement -- see 11_build_tileset.py's matching comment.
  benefits?: number | null;
  gap?: number | null;
}

const BENEFIT_LABELS: Array<[bit: number, label: string]> = [
  [1, "421-a exemption"],
  [2, "J-51 exemption"],
  [4, "J-51 abatement"],
  [8, "co-op/condo abatement"],
];

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
    // v2 roadmap item 1 -- only defined for class-2 (co-op/condo) buildings,
    // see pipeline/07_compute_dollar_gap.py. Shown even at $0, which is
    // itself a real, meaningful result (see that script's module docstring
    // -- a same-priced 1-3 family sale's own trend line is often just as
    // low, not a "no data" case), never blended into the effective-rate row
    // above. Like `sale` above, this is a SUM across every unit in the
    // building that sold -- explicitly labeled "combined" when nsale > 1 so
    // it doesn't read as this one building's own unit-lot figure (a multi-
    // unit tower's total can differ a lot from any single unit's own gap,
    // e.g. 220 Central Park South's combined total is nonzero even though
    // Ken Griffin's own unit computes to exactly $0 -- see "The story").
    if (p.cls === "2" && p.gap != null) {
      const combined = (p.nsale ?? 1) > 1;
      rows.push(
        p.gap > 0
          ? `<p class="popup-scale">An estimated ${formatMoney(p.gap * 100)}${combined ? " combined" : ""} below what a similarly priced 1&ndash;3 family sale's own trend line predicts (2016&ndash;2025 sales-verified sample)${combined ? ", summed across this building's sold units" : ""}.</p>`
          : `<p class="popup-scale">At or above what a similarly priced 1&ndash;3 family sale's own trend line predicts.</p>`,
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

  // Owner-entity flag (PLAN.md v2 roadmap item 2). A single owner's actual
  // NAME is only ever shipped when it's an LLC/LP-style entity (see
  // pipeline/11_build_tileset.py) -- an individual homeowner's name is
  // never surfaced, by design, so no line is shown for that case rather
  // than reporting "not an entity."
  if (p.units === 1 && p.ownerEntity) {
    rows.push(row("Owner on record", escapeHtml(p.ownerEntity), "LLC/LP"));
  } else if (p.units > 1 && p.llcPct != null) {
    rows.push(row("Held by an LLC/LP-named owner", `${p.llcPct}% of units`));
  }

  // Stacked-benefit flags (PLAN.md v2 roadmap item 3) -- reported as
  // separate, plainly-labeled facts, never folded into the effective-rate
  // row. `benefits` is only present at all when at least one bit is set
  // (see BuildingProps), so no length check is needed here.
  if (p.benefits != null) {
    const benefits = BENEFIT_LABELS.filter(([bit]) => (p.benefits! & bit) !== 0).map(([, label]) => label);
    rows.push(row("Tax benefits on record", benefits.join(", ")));
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
