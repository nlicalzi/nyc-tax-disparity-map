import { DIVERGENCE_STEPS, HATCH_LINE_COLOR, NO_DATA_COLOR } from "./colors";

export interface LegendOptions {
  tier2Visible: boolean;
  onToggleTier2: (visible: boolean) => void;
}

/** Renders the tier1 divergence legend (single diverging bar), the tier2 toggle, and the basis key. */
export function buildLegend(root: HTMLElement, options: LegendOptions): void {
  const gradientCss = DIVERGENCE_STEPS.map(
    ([step, color]) => `${color} ${((step + 2) / 4) * 100}%`,
  ).join(", ");
  const headlineColor = DIVERGENCE_STEPS[DIVERGENCE_STEPS.length - 1][1];

  root.innerHTML = `
    <div class="legend-section">
      <h2>Is tax proportionate to value?</h2>
      <div class="legend-ramp" style="background: linear-gradient(to right, ${gradientCss})"></div>
      <div class="legend-ramp-labels legend-ramp-labels-wide">
        <span>overtaxed<br/>vs. value</span>
        <span>proportionate</span>
        <span>underpriced<br/>vs. value</span>
      </div>
    </div>
    <div class="legend-section">
      <h2>Coverage</h2>
      <div class="legend-row">
        <span class="legend-swatch" style="background:${headlineColor}"></span>
        <span>Colored buildings have a real sale (2016&ndash;2025) to check the rate against</span>
      </div>
      <label class="legend-row legend-toggle">
        <input type="checkbox" id="tier2-toggle" />
        <span class="legend-swatch legend-swatch-hatch"></span>
        <span>~73% have no recent sale and aren't shown &mdash; DOF's own estimate isn't
          reliable enough to plot. Show them anyway</span>
      </label>
      <div class="legend-row">
        <span class="legend-swatch legend-swatch-nodata"></span>
        <span>No data (exempt, or no valuation on record)</span>
      </div>
    </div>
    <p class="legend-note">
      Tax is computed from public DOF assessment and rate data, not a scraped
      bill.
    </p>
  `;

  const style = document.createElement("style");
  style.textContent = `
    .legend-sub {
      font-size: 11px;
      color: var(--text-secondary);
      margin: 0 0 6px;
    }
    .legend-ramp-labels-wide span {
      flex: 1;
      line-height: 1.3;
    }
    .legend-ramp-labels-wide span:first-child { text-align: left; }
    .legend-ramp-labels-wide span:nth-child(2) { text-align: center; }
    .legend-ramp-labels-wide span:last-child { text-align: right; }
    .legend-toggle { cursor: pointer; align-items: flex-start; }
    .legend-toggle input { margin-top: 2px; flex: none; }
    .legend-swatch-hatch {
      background: repeating-linear-gradient(
        45deg,
        ${HATCH_LINE_COLOR} 0px,
        ${HATCH_LINE_COLOR} 1.5px,
        transparent 1.5px,
        transparent 6px
      ), #86b6ef88;
    }
    .legend-swatch-nodata { background: ${NO_DATA_COLOR}; }
  `;
  root.appendChild(style);

  const toggle = root.querySelector<HTMLInputElement>("#tier2-toggle")!;
  toggle.checked = options.tier2Visible;
  toggle.addEventListener("change", () => options.onToggleTier2(toggle.checked));
}
