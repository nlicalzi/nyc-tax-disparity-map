import {
  Map as MapLibreMap,
  NavigationControl,
  Popup,
  addProtocol,
  setWorkerUrl,
  type DataDrivenPropertyValueSpecification,
  type FilterSpecification,
  type LngLatLike,
  type MapSourceDataEvent,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Geometry } from "geojson";
import { Protocol } from "pmtiles";
import "./style.css";
import {
  makeHatchPattern,
  rateColorExpression,
  divergenceColorExpression,
  divergenceIndexExpression,
  NO_DATA_COLOR,
} from "./colors";
import { buildLegend } from "./legend";
import { buildMethodology } from "./methodology";
import { createFilterController, renderFilterControls, type FilterableLayer } from "./filters";
import { buildPopupHtml, type BuildingProps } from "./popup";
import { setupSearch, type SearchRecord } from "./search";
import { setupStory, GRIFFIN_CENTER, GRIFFIN_BBL } from "./story";
import { addressLabel, buildResultsList, rateLabelFor, rateValueFor, type ResultEntry } from "./results";

const TIER2_LAYER_IDS = ["fill-tier2", "fill-tier2-hatch", "circle-tier2"];

// Every layer a click/search selection should be able to surface a popup
// from -- includes the tier2 outline, since that's the only visible
// representation of tier2 buildings when the filled/hatched view is off.
// fill-tier2/fill-tier2-hatch/circle-tier2 are added lazily (see
// ensureTier2Layers below) and pushed in here once they exist.
const CLICKABLE_LAYERS = [
  "fill-tier1",
  "fill-nodata",
  "line-tier2-outline",
  "circle-tier1",
  "circle-nodata",
];

// See scripts/copy-maplibre-worker.mjs for why this is needed.
setWorkerUrl(`${import.meta.env.BASE_URL}vendor/maplibre/maplibre-gl-worker.mjs`);

const protocol = new Protocol();
addProtocol("pmtiles", protocol.tile);

// Per PLAN.md's agent-workflow rules: dev iteration uses the Manhattan-only
// dev sample, never the full 856K-feature citywide file. `npm run dev`
// serves site/public/tiles/dev-sample.pmtiles (gitignored copy of
// data/cache/dev_sample.pmtiles); production build uses buildings.pmtiles.
const TILES_URL = import.meta.env.DEV
  ? `${import.meta.env.BASE_URL}tiles/dev-sample.pmtiles`
  : `${import.meta.env.BASE_URL}tiles/buildings.pmtiles`;

const SOURCE_ID = "buildings";
const SOURCE_LAYER = "buildings";

// NYC citywide bounds (approx) -- fixed landing view per PLAN.md Site UX #1.
const NYC_BOUNDS: [[number, number], [number, number]] = [
  [-74.2591, 40.4774],
  [-73.7002, 40.9176],
];

const BASEMAP_STYLE_URL = "https://tiles.openfreemap.org/styles/positron";

const map = new MapLibreMap({
  container: "map",
  // An inline style, not the OpenFreeMap URL directly. Passing a URL forces
  // MapLibre to fetch+parse that remote style JSON (and its sprite/glyph
  // refs) before `style.load` fires at all -- and everything below (our own
  // buildings source, every addLayer call, click/search/filter/legend/story
  // wiring) lived inside that callback, so a first-time visitor's entire app
  // was gated behind a third-party host's round trip for zero real reason.
  // This inline style needs no network fetch, so `style.load` fires on the
  // next tick; the actual OpenFreeMap basemap is fetched independently by
  // loadBasemap() below and spliced in underneath once it's ready, fully
  // decoupled from our own data and interactivity. See PERFORMANCE.md.
  style: {
    version: 8,
    sources: {},
    layers: [
      { id: "background", type: "background", paint: { "background-color": "#fcfcfb" } },
    ],
  },
  bounds: NYC_BOUNDS,
  fitBoundsOptions: { padding: 20 },
  maxZoom: 18,
  minZoom: 9,
});

map.addControl(new NavigationControl({ showCompass: false }), "top-right");

// Dev-only hook for driving the map from a headless browser check; dead-code
// eliminated from production builds since import.meta.env.DEV is statically false.
if (import.meta.env.DEV) (window as unknown as { __map: typeof map }).__map = map;

// Fetches OpenFreeMap's style JSON ourselves and splices its sources/layers
// in below our own bottom layer (fill-nodata), rather than using it as the
// Map's top-level `style` (see the constructor comment above). Purely
// additive and best-effort: if it's slow or fails, the app above is already
// fully interactive against the plain background color. Fire-and-forget --
// called as the first line of the style.load handler below, so by the time
// this network fetch resolves, fill-nodata is guaranteed to already exist
// (nothing else in that handler awaits, so it runs to completion first).
async function loadBasemap(): Promise<void> {
  let styleJson: StyleSpecification;
  try {
    styleJson = (await (await fetch(BASEMAP_STYLE_URL)).json()) as StyleSpecification;
  } catch {
    return;
  }
  if (typeof styleJson.sprite === "string") map.setSprite(styleJson.sprite);
  if (styleJson.glyphs) map.setGlyphs(styleJson.glyphs);
  for (const [id, source] of Object.entries(styleJson.sources ?? {})) {
    if (!map.getSource(id)) map.addSource(id, source);
  }
  for (const layer of styleJson.layers ?? []) {
    if (layer.type === "background" || map.getLayer(layer.id)) continue;
    map.addLayer(layer, "fill-nodata");
  }
}

// `style.load`, not `load` -- `load` fires only after the basemap's own
// initial tiles finish rendering ("first visually complete rendering" per
// MapLibre's docs), which would needlessly serialize our own buildings
// source behind the (now-async, see loadBasemap above) basemap fetch instead
// of letting both load concurrently. `style.load` fires as soon as the
// (now-inline, no-network) style is parsed -- addSource/addLayer are valid
// from here on.
map.on("style.load", () => {
  void loadBasemap();

  map.addSource(SOURCE_ID, {
    type: "vector",
    url: `pmtiles://${TILES_URL}`,
  });

  // Performance-gate instrumentation (Milestone 6): a `performance.mark`,
  // not DEV-gated, so a real production build can be measured for "first
  // tiles painted" against PLAN.md's throttled-4G budget without needing
  // the dev-only `window.__map` hook (stripped from prod builds).
  let firstTilesMarked = false;
  map.on("sourcedata", (e) => {
    if (firstTilesMarked || e.sourceId !== SOURCE_ID || !e.isSourceLoaded) return;
    firstTilesMarked = true;
    performance.mark("first-tiles-painted");
  });

  const noDataFilter = ["all", ["==", ["get", "t1"], 0], ["==", ["get", "r2"], null]];
  const tier2Filter = ["all", ["==", ["get", "t1"], 0], ["!=", ["get", "r2"], null]];
  const tier1Filter = ["==", ["get", "t1"], 1];

  // Fill layers (polygon geometry only -- MapLibre fill layers automatically
  // skip point features, so no extra geometry-type filter is needed).
  map.addLayer({
    id: "fill-nodata",
    type: "fill",
    source: SOURCE_ID,
    "source-layer": SOURCE_LAYER,
    filter: noDataFilter as FilterSpecification,
    paint: {
      "fill-color": NO_DATA_COLOR,
      "fill-opacity": 0.45,
    },
  });

  // Tier-2 (DOF-fallback, no qualifying sale) is hidden by default -- that
  // number isn't trustworthy enough to earn a place on the map's primary
  // scale (see the tiering discussion: DOF's own market value for co-ops/
  // condos is already the deflated number the disparity comes from, so
  // tax/DOF-value nets out to a near-uniform ~5.6% and doesn't show the
  // story at all). A thin outline keeps the ~73% of buildings without a
  // sale visible as footprints -- the city shouldn't look like it's missing
  // buildings -- without their untrustworthy rate competing for attention
  // with the tier-1 buildings that actually prove the pattern. The legend's
  // toggle can turn the filled/hatched version back on.
  map.addLayer({
    id: "line-tier2-outline",
    type: "line",
    source: SOURCE_ID,
    "source-layer": SOURCE_LAYER,
    filter: tier2Filter as FilterSpecification,
    paint: {
      "line-color": "#c3c2b7",
      "line-width": 0.5,
      "line-opacity": 0.6,
    },
  });

  // fill-tier2/fill-tier2-hatch/circle-tier2 (Milestone 6): NOT added here.
  // MapLibre still builds GL buckets/buffers for a layer with
  // `visibility: "none"` -- hiding is a render-time switch, not a
  // tile-processing one -- so eagerly adding these 3 layers meant every tile
  // load paid full bucket-build cost for tier2's ~73% of citywide features
  // (the majority of the dataset) to produce something invisible on first
  // paint. Found via a Lighthouse long-tasks trace showing multiple
  // 200ms-1100ms main-thread tasks between FCP and TTI (simulated 4x CPU
  // throttle), tracing back to this "hidden but still built" cost. Deferred
  // to ensureTier2Layers(), called only when the legend checkbox is first
  // switched on -- so the ~73% majority of the dataset costs nothing until a
  // user actually asks to see it.

  // Tier-1 (sale-verified): the map's headline layer. Colored by the
  // divergence between rate and value (see colors.ts) -- red where rate
  // outpaces value (overtaxed relative to worth), blue where value
  // outpaces rate (the "expensive = lower rate" headline case), neutral
  // where the two track proportionately.
  map.addLayer({
    id: "fill-tier1",
    type: "fill",
    source: SOURCE_ID,
    "source-layer": SOURCE_LAYER,
    filter: tier1Filter as FilterSpecification,
    paint: {
      "fill-color": divergenceColorExpression(
        ["get", "mkt"],
        ["get", "r1"],
      ) as DataDrivenPropertyValueSpecification<string>,
      "fill-opacity": 0.9,
    },
  });

  // Circle layers for the small fraction of buildings that only resolved to
  // a point centroid (gsrc=point_fallback, ~0.04% of buildings -- see
  // PLAN.md Milestone 2). Unlike fill layers, circle layers do NOT skip
  // non-point geometry on their own -- they'll draw a circle at every
  // vertex of a matching polygon, which is why an explicit geometry-type
  // check is required here (found by inspecting rendered features: without
  // it, circle-tier1/circle-tier2 were drawing a dot on every vertex of
  // every building polygon, not just the point-fallback ones).
  const isPoint = ["==", ["geometry-type"], "Point"];
  const pointNoDataFilter = ["all", noDataFilter, isPoint];
  const pointTier2Filter = ["all", tier2Filter, isPoint];
  const pointTier1Filter = ["all", tier1Filter, isPoint];

  map.addLayer({
    id: "circle-nodata",
    type: "circle",
    source: SOURCE_ID,
    "source-layer": SOURCE_LAYER,
    filter: pointNoDataFilter as FilterSpecification,
    paint: {
      "circle-color": NO_DATA_COLOR,
      "circle-radius": 4,
      "circle-opacity": 0.5,
    },
  });

  // circle-tier2: see the fill-tier2/-hatch note above -- lazily added by
  // ensureTier2Layers(), not here.

  map.addLayer({
    id: "circle-tier1",
    type: "circle",
    source: SOURCE_ID,
    "source-layer": SOURCE_LAYER,
    filter: pointTier1Filter as FilterSpecification,
    paint: {
      "circle-color": divergenceColorExpression(
        ["get", "mkt"],
        ["get", "r1"],
      ) as DataDrivenPropertyValueSpecification<string>,
      "circle-radius": 4.5,
      "circle-opacity": 0.9,
    },
  });

  // Griffin's building highlight -- hidden except during the story's Griffin
  // step (story.ts's onGriffinFocus). A soft glow under a crisp outline,
  // matching the halo+ring treatment the scatter chart uses for the same
  // building (scatter.ts) so the two callouts read as one visual language.
  const griffinFilter: FilterSpecification = ["==", ["get", "bbl"], GRIFFIN_BBL];
  map.addLayer({
    id: "highlight-griffin-glow",
    type: "line",
    source: SOURCE_ID,
    "source-layer": SOURCE_LAYER,
    filter: griffinFilter,
    layout: { visibility: "none" },
    paint: {
      "line-color": "#e0362f",
      "line-width": 10,
      "line-opacity": 0.35,
      "line-blur": 2,
    },
  });
  map.addLayer({
    id: "highlight-griffin",
    type: "line",
    source: SOURCE_ID,
    "source-layer": SOURCE_LAYER,
    filter: griffinFilter,
    layout: { visibility: "none" },
    paint: {
      "line-color": "#e0362f",
      "line-width": 3,
      "line-opacity": 1,
    },
  });

  // Borough / tax-class filters (Site UX #4) -- combine with each layer's
  // own tier/geometry-type base filter, per filters.ts. fill-tier2/
  // fill-tier2-hatch/circle-tier2 are registered lazily, in ensureTier2Layers.
  // fill-tier1/circle-tier1 also carry a `divergence` expression -- the same
  // -2..+2 index they're colored by (colors.ts) -- so the legend's
  // divergence-bucket filter can slice on exactly what's on screen. tier2/
  // nodata layers aren't colored by this axis and don't get one.
  const divergenceIndex = divergenceIndexExpression(["get", "mkt"], ["get", "r1"]);
  const filterableLayers: FilterableLayer[] = [
    { id: "fill-nodata", base: noDataFilter },
    { id: "line-tier2-outline", base: tier2Filter },
    { id: "fill-tier1", base: tier1Filter, divergence: divergenceIndex },
    { id: "circle-nodata", base: pointNoDataFilter },
    { id: "circle-tier1", base: pointTier1Filter, divergence: divergenceIndex },
  ];
  // Forward-declared: the results-list panel (built further down, after
  // popup/whenBuildingsSourceLoaded exist) needs to refresh on every filter
  // change, but filterController -- created here -- needs the callback at
  // construction time. Reassigned to the real implementation below.
  let refreshResults: () => void = () => {};
  // `setFilter` schedules a repaint but `queryRenderedFeatures` right after
  // it (synchronously, same tick) can still reflect the *previous* filter
  // state -- confirmed directly: after narrowing the divergence filter, an
  // immediate refresh showed 134 buildings (essentially unfiltered), while
  // a refresh forced a moment later showed the correct 2. Deferring to the
  // next `render` event (fired once the map has actually redrawn against
  // the new filter) instead of calling refreshResults synchronously fixes
  // it; safe to queue repeatedly (each rapid filter change queues its own
  // `once` listener, but each reads live state when it fires, so the very
  // last one to fire always reflects the true final filter state).
  function scheduleResultsRefresh() {
    map.once("idle", () => refreshResults());
  }
  const filterController = createFilterController(map, filterableLayers, scheduleResultsRefresh);
  renderFilterControls(document.getElementById("filters")!, filterController);

  // Adds fill-tier2/fill-tier2-hatch/circle-tier2 the first time the legend
  // checkbox is switched on (see the note above map.addLayer("fill-tier1")).
  // Registers each with filterController so an already-applied borough/class
  // selection carries over, and extends CLICKABLE_LAYERS so clicks/search on
  // tier2 buildings work once they're actually on screen.
  let tier2LayersAdded = false;
  function ensureTier2Layers() {
    if (tier2LayersAdded) return;
    tier2LayersAdded = true;

    map.addImage("tier2-hatch", makeHatchPattern());

    map.addLayer({
      id: "fill-tier2",
      type: "fill",
      source: SOURCE_ID,
      "source-layer": SOURCE_LAYER,
      filter: tier2Filter as FilterSpecification,
      paint: {
        "fill-color": rateColorExpression(["get", "r2"]) as DataDrivenPropertyValueSpecification<string>,
        "fill-opacity": 0.5,
      },
    });

    // Hatch overlay on top of tier-2 fill only -- the primary visual signal
    // (per PLAN.md must-do) that tier-2 is a structurally different,
    // DOF-assessed-value-based number, not a directly comparable rate.
    map.addLayer({
      id: "fill-tier2-hatch",
      type: "fill",
      source: SOURCE_ID,
      "source-layer": SOURCE_LAYER,
      filter: tier2Filter as FilterSpecification,
      paint: {
        "fill-pattern": "tier2-hatch",
        "fill-opacity": 0.6,
      },
    });

    map.addLayer({
      id: "circle-tier2",
      type: "circle",
      source: SOURCE_ID,
      "source-layer": SOURCE_LAYER,
      filter: pointTier2Filter as FilterSpecification,
      paint: {
        "circle-color": rateColorExpression(["get", "r2"]) as DataDrivenPropertyValueSpecification<string>,
        "circle-radius": 4,
        "circle-opacity": 0.45,
        "circle-stroke-width": 1.5,
        "circle-stroke-color": "#0d366b",
        "circle-stroke-opacity": 0.5,
      },
    });

    filterController.addLayer({ id: "fill-tier2", base: tier2Filter });
    filterController.addLayer({ id: "fill-tier2-hatch", base: tier2Filter });
    filterController.addLayer({ id: "circle-tier2", base: pointTier2Filter });
    CLICKABLE_LAYERS.push("fill-tier2", "fill-tier2-hatch", "circle-tier2");
    for (const id of ["fill-tier2", "fill-tier2-hatch", "circle-tier2"]) {
      map.on("mouseenter", id, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", id, () => {
        map.getCanvas().style.cursor = "";
      });
    }
  }

  buildLegend(document.getElementById("legend")!, {
    tier2Visible: false,
    onToggleTier2: (visible) => {
      if (visible) ensureTier2Layers();
      const visibility = visible ? "visible" : "none";
      for (const id of TIER2_LAYER_IDS) {
        if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visibility);
      }
      scheduleResultsRefresh();
    },
    isDivergenceSelected: filterController.isDivergenceSelected,
    onToggleDivergence: filterController.toggleDivergence,
  });

  buildMethodology(document.getElementById("methodology")!);

  // Popups (Site UX #2) -- single reused Popup instance, opened either by a
  // direct map click or by selecting a search result.
  const popup = new Popup({ closeButton: true, maxWidth: "300px" });

  function showPopup(lngLat: LngLatLike, props: BuildingProps) {
    popup.setLngLat(lngLat).setHTML(buildPopupHtml(props)).addTo(map);
  }

  map.on("click", (e) => {
    const features = map.queryRenderedFeatures(e.point, { layers: CLICKABLE_LAYERS });
    if (!features.length) return;
    showPopup(e.lngLat, features[0].properties as BuildingProps);
  });

  for (const id of CLICKABLE_LAYERS) {
    map.on("mouseenter", id, () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", id, () => {
      map.getCanvas().style.cursor = "";
    });
  }

  // Waits for the buildings source specifically, not the map-wide `idle`
  // event -- `idle` only fires once *every* source (including the live,
  // continuously-tile-fetching OpenFreeMap basemap) has nothing pending, so
  // searching soon after landing on the free-roam map (while the basemap is
  // still loading tiles from the initial pan/zoom) could leave a search
  // selection's flyTo waiting on `idle` indefinitely -- found via testing
  // during Milestone 7, reproduces on the pre-M7 build too. Mirrors the
  // isSourceLoaded check the first-tiles-painted perf mark above already
  // uses, just reusable and post-initial-load.
  function whenBuildingsSourceLoaded(cb: () => void) {
    if (map.isSourceLoaded(SOURCE_ID)) {
      cb();
      return;
    }
    const handler = (e: MapSourceDataEvent) => {
      if (e.sourceId !== SOURCE_ID || !e.isSourceLoaded) return;
      map.off("sourcedata", handler);
      cb();
    };
    map.on("sourcedata", handler);
  }

  // Shared by search selection, the results-list panel, and (partially) the
  // Griffin callout below: wait for a just-triggered camera move to settle
  // and the buildings source to actually be loaded, then look up the real
  // tile feature at the target and show its popup -- built from actual tile
  // properties, never a hand-typed stand-in, so it can't drift from what a
  // genuine click on the same building shows.
  function waitForBuildingPopup(target: LngLatLike, matchBbl: string, layers: string[]) {
    map.once("moveend", () => whenBuildingsSourceLoaded(() => {
      const point = map.project(target);
      const box: [[number, number], [number, number]] = [
        [point.x - 6, point.y - 6],
        [point.x + 6, point.y + 6],
      ];
      const features = map.queryRenderedFeatures(box, { layers });
      const match = features.find((f) => f.properties?.bbl === matchBbl) ?? features[0];
      if (match) showPopup(target, match.properties as BuildingProps);
    }));
  }

  function flyToBuildingAndPopup(target: LngLatLike, matchBbl: string, layers: string[] = CLICKABLE_LAYERS) {
    map.flyTo({ center: target, zoom: 17, essential: true });
    waitForBuildingPopup(target, matchBbl, layers);
  }

  // Search (Site UX #3) -- lazy-loaded index (search.ts), fly to the
  // selected building and open its popup once the tile covering it has
  // loaded (queryRenderedFeatures only sees rendered/loaded tiles).
  setupSearch(document.getElementById("search")!, (record: SearchRecord) => {
    flyToBuildingAndPopup([record.lon, record.lat], record.bbl);
  });

  // Results-list panel (added after user feedback: a narrowed
  // divergence-axis filter showed color-coded matches but made them hard to
  // actually *find* on the map). Client-side only -- built from whatever's
  // currently rendered and passing the active filters, so it can never
  // disagree with what's on screen. See results.ts.
  const MAX_RESULTS = 200;
  const resultsRoot = document.getElementById("results")!;
  const resultsController = buildResultsList(resultsRoot, {
    onSelect: (entry: ResultEntry) => flyToBuildingAndPopup([entry.lon, entry.lat], entry.bbl),
  });

  /** Centroid-ish point (average of the exterior ring's vertices -- not a
   * true area centroid, but plenty accurate for "fly the camera here"). */
  function featureCenter(geom: Geometry): [number, number] {
    if (geom.type === "Point") return geom.coordinates as [number, number];
    const ring = geom.type === "Polygon" ? geom.coordinates[0] : geom.type === "MultiPolygon" ? geom.coordinates[0]?.[0] : undefined;
    if (!ring?.length) return [0, 0];
    let sx = 0;
    let sy = 0;
    for (const [x, y] of ring) {
      sx += x;
      sy += y;
    }
    return [sx / ring.length, sy / ring.length];
  }

  const DIVERGENCE_LAYERS = ["fill-tier1", "circle-tier1"];

  refreshResults = function refreshResultsImpl() {
    const filtered = filterController.isFiltered();
    resultsRoot.hidden = !filtered;
    if (!filtered) return;

    // tier2/nodata layers carry no divergence classification at all (only
    // fill-tier1/circle-tier1 do -- see colors.ts), so their own MapLibre
    // filter never excludes anything based on the divergence buckets.
    // Querying them here once a divergence slice is selected would silently
    // pad the list with every uncolored building still on screen, alongside
    // the (correctly narrowed) tier-1 matches -- restrict to tier-1 layers
    // in that case so the list actually matches what was selected.
    const layers = filterController.isDivergenceNarrowed()
      ? DIVERGENCE_LAYERS.filter((id) => CLICKABLE_LAYERS.includes(id))
      : CLICKABLE_LAYERS;
    const features = map.queryRenderedFeatures({ layers });
    let sawUnaddressed = false;
    const byBbl = new Map<string, ResultEntry>();
    for (const f of features) {
      const props = f.properties as BuildingProps;
      if (!props?.bbl || byBbl.has(props.bbl) || !f.geometry) continue;
      // addr is a detail-zoom-only field (see results.ts's addressLabel) --
      // rather than showing a BBL-labeled row, skip it and let the "zoom in"
      // hint below explain why the list looks sparse while zoomed out.
      if (!props.addr) {
        sawUnaddressed = true;
        continue;
      }
      const [lon, lat] = featureCenter(f.geometry);
      byBbl.set(props.bbl, {
        bbl: props.bbl,
        label: addressLabel(props.addr),
        boro: props.boro,
        lon,
        lat,
        rateLabel: rateLabelFor(props.t1, props.r1, props.r2),
        rate: rateValueFor(props.t1, props.r1, props.r2),
      });
    }

    // Decreasing effective rate (most-overtaxed first) per user request --
    // rows with no rate at all ("no data") sort to the bottom regardless.
    const entries = [...byBbl.values()].sort((a, b) => {
      if (a.rate == null && b.rate == null) return a.label.localeCompare(b.label);
      if (a.rate == null) return 1;
      if (b.rate == null) return -1;
      return b.rate - a.rate;
    });

    const emptyHint = sawUnaddressed && entries.length === 0 ? "Zoom in to see building addresses." : undefined;
    resultsController.update(entries.slice(0, MAX_RESULTS), entries.length > MAX_RESULTS, emptyHint);
  };
  map.on("moveend", refreshResults);

  // Griffin step callout (Site UX #5 / story.ts's onGriffinFocus): shows the
  // highlight outline and opens the *real* popup for 220 Central Park South
  // -- built from the same tile properties a genuine click would use, not a
  // hand-typed stand-in -- so it can never drift out of sync with what
  // clicking the building anywhere else on the map shows. Waits on `moveend`
  // (the story's own flyTo to Griffin's building) + the buildings source
  // actually being loaded, same pattern as the search-selection popup above.
  function showGriffinCallout(show: boolean) {
    const visibility = show ? "visible" : "none";
    for (const id of ["highlight-griffin-glow", "highlight-griffin"]) {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visibility);
    }
    if (!show) {
      popup.remove();
      return;
    }
    waitForBuildingPopup(GRIFFIN_CENTER, GRIFFIN_BBL, ["fill-tier1"]);
  }

  // Scrollytelling intro (Site UX #5) -- pins this same map instance behind
  // the story steps, flying its camera to Ken Griffin's penthouse and back
  // before handing off into the free-roam experience above. See story.ts.
  setupStory(document.getElementById("story")!, {
    map,
    cityBounds: NYC_BOUNDS,
    chartContainer: document.getElementById("chart-pin")!,
    onGriffinFocus: showGriffinCallout,
  });
});
