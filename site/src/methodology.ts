/**
 * Static methodology/vintage panel (Milestone 7) -- PERFORMANCE.md's
 * recommendation was to document data vintage in the site itself, not just
 * README, so a visitor doesn't have to leave the page to see what's behind
 * the numbers. A <details> element, not hand-rolled toggle JS, since this
 * is static content with no state the rest of the app needs to react to.
 * Collapsed by default (bottom-right, out of the way of legend/header).
 */
export function buildMethodology(root: HTMLElement): void {
  root.innerHTML = `
    <details class="methodology-panel">
      <summary>Methodology &amp; sources</summary>
      <div class="methodology-body">
        <p>
          <strong>Effective rate</strong> = computed tax &divide; actual sale price, for
          buildings with a qualifying arm's-length sale, 2016&ndash;2025
          (&ldquo;sale-verified&rdquo;). Buildings without one fall back to
          computed tax &divide; DOF's own market value, shown muted/hatched
          on the map since that fallback number is structurally different
          (and, for co-ops/condos, much less reliable as a stand-in for true
          value).
        </p>
        <p>
          <strong>Computed tax</strong> = DOF's taxable value (post-cap,
          post-exemption) &times; the FY2026 class rate. This is a
          computation from public assessment and rate data, not a scraped
          tax bill.
        </p>
        <p>
          <strong>&ldquo;Vs. the 1&ndash;3 family trend line&rdquo;</strong>
          (the $67.7M stat and each co-op/condo popup's comparison line) =
          a fitted curve of effective rate against sale price, computed
          across every sale-verified 1&ndash;3 family sale in this same
          2016&ndash;2025 window, then evaluated at each co-op/condo unit's
          own sale price. Only counted when a co-op/condo sale paid
          <em>less</em> than that curve predicts for a 1&ndash;3 family sale
          at the same price &mdash; this is a different, narrower comparison
          than the Griffin anecdote above (his rate vs. a modest home's rate,
          at very different price points), and the two aren't meant to add
          up to one number. Scoped to the 2016&ndash;2025 sales-verified
          sample (about 124,000 co-op/condo sales), not the citywide
          standing population of co-op/condo units.
        </p>
        <p>
          <strong>Owner-on-record / tax-benefit flags</strong> (popup-only,
          never blended into the effective-rate figures above): an
          LLC/LP-style owner name is a simple text-pattern match against
          DOF's own recorded owner field, not a legal determination of who
          controls a property. 421-a, J-51, and co-op/condo abatement flags
          come from DOF's own exemption/abatement rolls for the same FY2026
          vintage below.
        </p>
        <p>
          <strong>Data vintage</strong>: DOF FY2026 final assessment roll
          (dataset <code>8y4t-faws</code>, year 2026 period 3); FY2026
          adopted tax class rates
          (nyc.gov/site/finance/property/property-tax-rates.page); NYC
          Citywide Annualized Calendar Sales, 2016&ndash;2025 (dataset
          <code>w2pb-icbu</code>); DOF Property Exemption Detail (dataset
          <code>muvi-b6kx</code>) and Property Abatement Detail (dataset
          <code>rgyu-ii48</code>), FY2026. A single fixed snapshot, not
          live-refreshing &mdash; see the project README for the full
          pipeline and re-fetch instructions.
        </p>
        <p>
          <a href="https://github.com/nlicalzi/nyc-tax-disparity-map" target="_blank" rel="noopener">
            Source code &amp; full methodology on GitHub &rarr;
          </a>
        </p>
      </div>
    </details>
  `;
}
