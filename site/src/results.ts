import { BOROUGH_NAMES, escapeHtml, formatRate, titleCaseAddress } from "./format";

export interface ResultEntry {
  bbl: string;
  label: string; // address (title-cased) or a "BBL ######" fallback
  boro: string;
  lon: number;
  lat: number;
  rateLabel: string; // e.g. "1.42%", "2.10% (est.)", or "no data" -- see rateLabelFor
}

export interface ResultsListOptions {
  onSelect: (entry: ResultEntry) => void;
}

/** Live "buildings in view" panel (added after user feedback that a
 * narrowed divergence-axis filter made it hard to *find* the matching
 * buildings on the map, not just see they existed). Client-side only --
 * built from whatever's currently rendered and passing the active filters
 * (main.ts's queryRenderedFeatures call), not a separate precomputed
 * dataset, so it can never drift from what's actually on screen. */
export function buildResultsList(root: HTMLElement, options: ResultsListOptions): { update: (entries: ResultEntry[], truncated: boolean) => void } {
  root.innerHTML = `
    <div class="results-count"></div>
    <div class="results-items"></div>
  `;
  const countEl = root.querySelector<HTMLElement>(".results-count")!;
  const itemsEl = root.querySelector<HTMLElement>(".results-items")!;

  function update(entries: ResultEntry[], truncated: boolean): void {
    countEl.textContent = entries.length
      ? `${entries.length}${truncated ? "+" : ""} building${entries.length === 1 ? "" : "s"} in view`
      : "No buildings matching the current filter in view -- pan or zoom out.";

    itemsEl.innerHTML = entries
      .map(
        (e) => `
        <button type="button" class="results-item" data-bbl="${escapeHtml(e.bbl)}">
          <span class="results-item-label">${escapeHtml(e.label)}</span>
          <span class="results-item-meta">
            <span class="results-item-boro">${escapeHtml(BOROUGH_NAMES[e.boro] ?? e.boro)}</span>
            <span class="results-item-rate">${escapeHtml(e.rateLabel)}</span>
          </span>
        </button>`,
      )
      .join("");

    itemsEl.querySelectorAll<HTMLButtonElement>(".results-item").forEach((btn, i) => {
      btn.addEventListener("click", () => options.onSelect(entries[i]));
    });
  }

  return { update };
}

/** `addr` only exists in tile properties at the tileset's single highest
 * detail zoom (see PLAN.md Milestone 4's tile-schema size fight) -- at
 * lower zooms, most rendered features won't have one yet. Falls back to the
 * BBL rather than hiding the building from the list. */
export function labelFor(bbl: string, addr: string | null | undefined): string {
  return addr ? titleCaseAddress(addr) : `BBL ${bbl}`;
}

/** Unlike `addr`, r1/r2 are lean-schema fields present at *every* zoom (see
 * colors.ts), so the rate can always be shown regardless of how zoomed out
 * the list was built at. Labeled "(est.)" for the tier-2/DOF-value fallback
 * -- never blended with tier-1's sale-verified number unlabeled, matching
 * the same tier1-vs-tier2 distinction the map/legend/popup all make
 * elsewhere (PLAN.md's Core metric: the two aren't directly comparable). */
export function rateLabelFor(t1: number, r1: number | null | undefined, r2: number | null | undefined): string {
  if (t1 === 1 && r1 != null) return formatRate(r1);
  if (r2 != null) return `${formatRate(r2)} (est.)`;
  return "no data";
}
