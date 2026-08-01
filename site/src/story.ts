import type { Map as MapLibreMap, LngLatLike } from "maplibre-gl";

export interface StoryOptions {
  map: MapLibreMap;
  cityBounds: [[number, number], [number, number]];
  chartContainer: HTMLElement;
  // Called with true on entering the Griffin step, false on leaving it --
  // main.ts uses this to show/hide a highlight outline around 220 Central
  // Park South and open its real (tile-driven) popup, "as though clicked".
  onGriffinFocus: (focused: boolean) => void;
}

// 220 Central Park South's real centroid (data/cache/buildings_geom.parquet,
// pluto_bbl 1010307501) -- not eyeballed, queried directly against the same
// geometry the tileset itself is built from. Exported so main.ts's Griffin
// highlight/popup logic shares this one validated coordinate and BBL rather
// than re-deriving or re-typing them.
export const GRIFFIN_CENTER: LngLatLike = [-73.980567, 40.766969];
export const GRIFFIN_BBL = "1010307501";
const GRIFFIN_ZOOM = 17.5;

const MAP_INTERACTION_HANDLERS = [
  "scrollZoom",
  "boxZoom",
  "dragRotate",
  "dragPan",
  "keyboard",
  "doubleClickZoom",
  "touchZoomRotate",
  "touchPitch",
] as const;

function setMapInteractive(map: MapLibreMap, enabled: boolean): void {
  for (const name of MAP_INTERACTION_HANDLERS) {
    const handler = (map as unknown as Record<string, { enable(): void; disable(): void }>)[name];
    if (enabled) handler.enable();
    else handler.disable();
  }
}

/** Drives the scrollytelling intro (PLAN.md milestone 5): an
 * IntersectionObserver watches each `.story-step` and, using a viewport
 * center-line rootMargin, treats exactly one step as "active" at a time
 * regardless of scroll direction. Each step reuses the *same* map instance
 * as the free-roam experience that follows (a scripted flyTo, not a second
 * map) and, for the "it's not just one building" step, swaps in the lazy-
 * loaded Observable Plot scatter (scatter.ts) as the pinned visual instead. */
export function setupStory(root: HTMLElement, opts: StoryOptions): void {
  const { map, cityBounds, chartContainer, onGriffinFocus } = opts;
  const steps = Array.from(root.querySelectorAll<HTMLElement>(".story-step"));

  let activeStep = -1;
  let chartMounted = false;

  // Dynamic import, not a static one -- Observable Plot (and its d3
  // sub-dependencies) has no reason to be in the initial bundle when the
  // chart step is the one part of the story most visitors won't linger on
  // long enough to need loaded eagerly. Matches search.ts's lazy-load of
  // MiniSearch for the same reason (PLAN.md's Performance strategy).
  function showChart(visible: boolean) {
    chartContainer.classList.toggle("chart-pin-visible", visible);
    chartContainer.setAttribute("aria-hidden", visible ? "false" : "true");
    if (visible && !chartMounted) {
      chartMounted = true;
      void import("./scatter").then(({ loadScatterData, renderScatterChart }) =>
        loadScatterData().then((data) => renderScatterChart(chartContainer, data)),
      );
    }
  }

  function applyStep(i: number) {
    if (i === activeStep) return;
    activeStep = i;
    onGriffinFocus(i === 1);
    if (i === 2) {
      showChart(true);
      return;
    }
    showChart(false);
    if (i === 1) {
      map.flyTo({ center: GRIFFIN_CENTER, zoom: GRIFFIN_ZOOM, duration: 1400, essential: true });
    } else {
      // Steps 0 and 3 (intro + handoff) both land on the citywide overview.
      map.fitBounds(cityBounds, { padding: 20, duration: 900 });
    }
  }

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const i = steps.indexOf(entry.target as HTMLElement);
        if (i !== -1) applyStep(i);
      }
    },
    // Shrinks the observer's root to a thin band at the viewport's vertical
    // center -- a step is "active" exactly when it's the one centered on
    // screen, so scrolling up re-triggers earlier steps' effects too.
    { threshold: 0, rootMargin: "-45% 0px -45% 0px" },
  );
  steps.forEach((el) => observer.observe(el));

  setMapInteractive(map, false);
  applyStep(0);

  root.querySelector<HTMLAnchorElement>("#story-skip")?.addEventListener("click", (e) => {
    e.preventDefault();
    steps[steps.length - 1]?.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  root.querySelector<HTMLButtonElement>("#story-enter")?.addEventListener("click", () => {
    setMapInteractive(map, true);
    document.body.classList.remove("story-active");
    document.body.classList.add("story-done");
  });
}
