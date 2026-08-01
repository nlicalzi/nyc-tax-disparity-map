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
          <strong>Data vintage</strong>: DOF FY2026 final assessment roll
          (dataset <code>8y4t-faws</code>, year 2026 period 3); FY2026
          adopted tax class rates
          (nyc.gov/site/finance/property/property-tax-rates.page); NYC
          Citywide Annualized Calendar Sales, 2016&ndash;2025 (dataset
          <code>w2pb-icbu</code>). A single fixed snapshot, not
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
