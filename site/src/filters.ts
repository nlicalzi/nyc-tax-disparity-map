import type { FilterSpecification, Map as MapLibreMap } from "maplibre-gl";
import { ALL_BOROUGHS, ALL_TAX_CLASSES, TAX_CLASS_LABELS } from "./format";
import { DIVERGENCE_BUCKETS } from "./colors";

export interface FilterableLayer {
  id: string;
  base: unknown[];
  // The raw -2..+2 divergence index expression (see colors.ts's
  // divergenceIndexExpression) for layers colored by it -- only fill-tier1/
  // circle-tier1. Omitted for tier2/nodata layers, which aren't colored by
  // this axis at all, so a divergence-bucket selection shouldn't touch them.
  divergence?: unknown[];
}

/** Combines each layer's base tier/geometry filter with the borough,
 * tax-class, and (where applicable) divergence-bucket selections from the
 * filter UI. Omits a category's clause entirely when everything in it is
 * selected, so buildings with a missing boro/cls value (rare, but see
 * 04_build_effective_rates.py's mode() aggregate) don't vanish under the
 * default "everything on" state -- an `in` filter against a value list only
 * matches non-null fields, so it would otherwise hide those buildings even
 * though nothing was deselected. */
export function createFilterController(map: MapLibreMap, layers: FilterableLayer[]) {
  const selectedBoroughs = new Set(ALL_BOROUGHS);
  const selectedClasses = new Set(ALL_TAX_CLASSES);
  const selectedDivergence = new Set(DIVERGENCE_BUCKETS);
  const tracked = [...layers];

  function filterFor(layer: FilterableLayer): FilterSpecification {
    const clauses: unknown[] = [];
    if (selectedBoroughs.size < ALL_BOROUGHS.length) {
      clauses.push(["in", ["get", "boro"], ["literal", [...selectedBoroughs]]]);
    }
    if (selectedClasses.size < ALL_TAX_CLASSES.length) {
      clauses.push(["in", ["get", "cls"], ["literal", [...selectedClasses]]]);
    }
    if (layer.divergence && selectedDivergence.size < DIVERGENCE_BUCKETS.length) {
      clauses.push(["in", layer.divergence, ["literal", [...selectedDivergence]]]);
    }
    return (clauses.length ? ["all", layer.base, ...clauses] : layer.base) as FilterSpecification;
  }

  function apply() {
    for (const layer of tracked) map.setFilter(layer.id, filterFor(layer));
  }

  return {
    isBoroughSelected: (b: string) => selectedBoroughs.has(b),
    isClassSelected: (c: string) => selectedClasses.has(c),
    isDivergenceSelected: (idx: number) => selectedDivergence.has(idx),
    toggleBorough(b: string) {
      if (selectedBoroughs.has(b)) selectedBoroughs.delete(b);
      else selectedBoroughs.add(b);
      apply();
    },
    toggleClass(c: string) {
      if (selectedClasses.has(c)) selectedClasses.delete(c);
      else selectedClasses.add(c);
      apply();
    },
    toggleDivergence(idx: number) {
      if (selectedDivergence.has(idx)) selectedDivergence.delete(idx);
      else selectedDivergence.add(idx);
      apply();
    },
    // Registers a layer added after construction (see main.ts's lazy tier2
    // layers) and immediately applies the current borough/class/divergence
    // selection to it, so a layer created after the user has already
    // filtered doesn't start out showing everything.
    addLayer(layer: FilterableLayer) {
      tracked.push(layer);
      map.setFilter(layer.id, filterFor(layer));
    },
  };
}

export type FilterController = ReturnType<typeof createFilterController>;

const BOROUGH_SHORT_LABELS: Record<string, string> = {
  MN: "Manhattan",
  BX: "Bronx",
  BK: "Brooklyn",
  QN: "Queens",
  SI: "Staten Island",
};

const CLASS_SHORT_LABELS: Record<string, string> = {
  "1": "Class 1",
  "2": "Class 2",
  "3": "Class 3",
  "4": "Class 4",
};

function renderToggleGroup(
  values: string[],
  labels: Record<string, string>,
  isSelected: (v: string) => boolean,
  tips?: Record<string, string>,
): string {
  return values
    .map((v) => {
      const label = labels[v] ?? v;
      const tip = tips?.[v];
      // A custom `data-tip` + CSS tooltip, not the native `title` attribute --
      // native tooltips have a long hover delay and are easy to miss (found
      // via user feedback: the tax-class chips already had `title` text and
      // it still wasn't obvious what "Class 2" means). `aria-label` carries
      // the same info for screen readers, which don't read `title` reliably.
      return `<button type="button" class="filter-chip${isSelected(v) ? " filter-chip-active" : ""}" data-value="${v}"${
        tip ? ` data-tip="${tip}" aria-label="${label}: ${tip}"` : ""
      }>${label}</button>`;
    })
    .join("");
}

function wireToggleGroup(root: HTMLElement, selector: string, onToggle: (v: string) => void) {
  root.querySelectorAll<HTMLButtonElement>(selector).forEach((btn) => {
    btn.addEventListener("click", () => {
      btn.classList.toggle("filter-chip-active");
      onToggle(btn.dataset.value!);
    });
  });
}

/** Renders the borough/tax-class toggle chips and wires them to the given
 * controller. Independent of createFilterController so main.ts can build
 * the controller before layers exist and render the UI after. */
export function renderFilterControls(root: HTMLElement, controller: FilterController): void {
  root.innerHTML = `
    <div class="filter-group">
      <span class="filter-group-label">Borough</span>
      <div class="filter-chips" id="filter-boro">
        ${renderToggleGroup(ALL_BOROUGHS, BOROUGH_SHORT_LABELS, controller.isBoroughSelected)}
      </div>
    </div>
    <div class="filter-group">
      <span class="filter-group-label">Tax class</span>
      <div class="filter-chips" id="filter-cls">
        ${renderToggleGroup(ALL_TAX_CLASSES, CLASS_SHORT_LABELS, controller.isClassSelected, TAX_CLASS_LABELS)}
      </div>
    </div>
  `;
  wireToggleGroup(root.querySelector("#filter-boro")!, ".filter-chip", controller.toggleBorough);
  wireToggleGroup(root.querySelector("#filter-cls")!, ".filter-chip", controller.toggleClass);
}
