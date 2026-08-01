import { BOROUGH_NAMES, escapeHtml, titleCaseAddress } from "./format";

export interface ResultEntry {
  bbl: string;
  label: string; // address (title-cased) or a "BBL ######" fallback
  boro: string;
  lon: number;
  lat: number;
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
          <span class="results-item-boro">${escapeHtml(BOROUGH_NAMES[e.boro] ?? e.boro)}</span>
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
