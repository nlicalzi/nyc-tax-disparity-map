import type { FilterSpecification, Map as MapLibreMap } from "maplibre-gl";
import { ALL_BOROUGHS, ALL_TAX_CLASSES, TAX_CLASS_LABELS } from "./format";

export interface FilterableLayer {
  id: string;
  base: unknown[];
}

/** Combines each layer's base tier/geometry filter with the borough and
 * tax-class selections from the filter UI. Omits a category's clause
 * entirely when everything in it is selected, so buildings with a missing
 * boro/cls value (rare, but see 04_build_effective_rates.py's mode()
 * aggregate) don't vanish under the default "everything on" state -- an
 * `in` filter against a value list only matches non-null fields, so it
 * would otherwise hide those buildings even though nothing was deselected. */
export function createFilterController(map: MapLibreMap, layers: FilterableLayer[]) {
  const selectedBoroughs = new Set(ALL_BOROUGHS);
  const selectedClasses = new Set(ALL_TAX_CLASSES);
  const tracked = [...layers];

  function filterFor(base: unknown[]): FilterSpecification {
    const clauses: unknown[] = [];
    if (selectedBoroughs.size < ALL_BOROUGHS.length) {
      clauses.push(["in", ["get", "boro"], ["literal", [...selectedBoroughs]]]);
    }
    if (selectedClasses.size < ALL_TAX_CLASSES.length) {
      clauses.push(["in", ["get", "cls"], ["literal", [...selectedClasses]]]);
    }
    return (clauses.length ? ["all", base, ...clauses] : base) as FilterSpecification;
  }

  function apply() {
    for (const { id, base } of tracked) map.setFilter(id, filterFor(base));
  }

  return {
    isBoroughSelected: (b: string) => selectedBoroughs.has(b),
    isClassSelected: (c: string) => selectedClasses.has(c),
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
    // Registers a layer added after construction (see main.ts's lazy tier2
    // layers) and immediately applies the current borough/class selection to
    // it, so a layer created after the user has already filtered doesn't
    // start out showing everything.
    addLayer(layer: FilterableLayer) {
      tracked.push(layer);
      map.setFilter(layer.id, filterFor(layer.base));
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
  titles?: Record<string, string>,
): string {
  return values
    .map(
      (v) =>
        `<button type="button" class="filter-chip${isSelected(v) ? " filter-chip-active" : ""}" data-value="${v}"${
          titles?.[v] ? ` title="${titles[v]}"` : ""
        }>${labels[v] ?? v}</button>`,
    )
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
