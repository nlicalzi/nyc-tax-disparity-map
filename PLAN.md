# NYC Property Tax Disparity Map — 1-Pager

## Status (updated 2026-07-30)
- **Repo**: `nlicalzi/nyc-tax-disparity-map` (private), pushed to `main`.
- **Environment**: Python venv at `.venv/` (duckdb, pandas, pyarrow, requests,
  python-dotenv installed). `duckdb`, `tippecanoe`, `ogr2ogr` installed via
  Homebrew. Socrata app token in `.env` as `SOCRATA_APP_TOKEN` (gitignored;
  `set -a; source .env; set +a` before running fetch scripts). Site at
  `site/` is Vite + TypeScript, no framework; `npm install && npm run dev`
  (dev-sample tiles) or `npm run build && npm run preview` (full citywide
  tiles).
- **Milestone 1 (data pipeline): DONE**, with a post-hoc correction found
  during milestone-3 map work. `pipeline/01`–`05` run end-to-end, full
  citywide scale (1,164,670 unit rows, 857,253 building rows), see
  `pipeline/README.md` for the run order. Validated: Griffin penthouse
  computes to 0.35% effective rate against its real sale (script-asserted),
  and the "expensive = lower rate" pattern holds citywide by sale-price
  decile for class 1 and class 2, not just as an anecdote. Outputs live in
  `data/cache/*.parquet` (gitignored — re-run pipeline to regenerate, ~15 min
  full citywide fetch + a few min compute).
  - **Correction (2026-07-30):** the nominal/non-arms-length sale filter
    (`MIN_ARMS_LENGTH_SALE`, a flat $10K floor) wasn't nearly enough --
    found via the new map's bivariate styling work, which made a $130,000
    "sale" matched to a $1.054B building (BBL 1011300001, tier-1 rate
    39,586%) visually obvious. Fixed in `pipeline/04_build_effective_rates.py`
    with two additions: `MIN_SALE_TO_VALUE_RATIO` (sale price must be >= 1%
    of the unit's own DOF market value -- one-sided, only rejects sale <<
    value, never sale >> value, since the latter is exactly the legitimate
    disparity story) and `EFFECTIVE_RATE_CEILING` (a 25% backstop on the
    computed rate itself, since the >5% tail has no clean natural break
    between "real distressed sale" and "nominal transfer" to threshold on).
    Also surfaced that `valuation_fy2026` isn't unique per (boro, block,
    lot) -- 4,133 keys citywide have multiple rows, patterns ranging from
    a simple real-record-plus-zero-value-placeholder to a few dozen keys
    with many (up to 542) nonzero sibling rows that aren't yet understood.
    Worked around narrowly (`valuation_keymax`, MAX per key) for the sale
    hookup; the broader multi-row question may still affect building-level
    tax/value aggregation and hasn't been investigated further -- flagged,
    not resolved. `pipeline/05_validate.py` now asserts <0.1% of tier-1
    units exceed a 100%-of-sale-price rate (was 0.59%, now 0%) as a
    regression guard. Re-ran 04→05→07→08 after the fix; Griffin assertion
    still passes (0.3486%), tier-1 coverage barely moved (30.4%→29.9%).
- **Milestone 2 (tile build): DONE.** `pipeline/06`–`08` fetch real parcel
  geometry (PLUTO has none — see corrected Data sources), join it to
  `building_effective_rates.parquet`, and build the PMTiles tileset. Output:
  `site/public/tiles/buildings.pmtiles` (856,471 features, 103MB, z9–z16).
  GitHub Pages verified to correctly serve HTTP range requests. See
  Milestones below for full detail and what's explicitly deferred (H3
  low-zoom binning).
- **Milestone 3 (map MVP): DONE**, iterated past the original design after
  user feedback. Vite + TS scaffold in `site/` from scratch; MapLibre GL JS
  + `pmtiles` protocol, OpenFreeMap "positron" as the free no-key basemap.
  Current design (see `site/src/colors.ts`/`main.ts`/`legend.ts`):
  - **Tier 2 (DOF-fallback, ~73% of buildings) is hidden by default**, not
    just visually muted. Rationale from a user conversation: DOF's own
    market value for co-ops/condos is already the deflated number the
    disparity comes from, so tax/DOF-value nets out to a near-uniform
    ~5.6% and doesn't show the story at all -- displaying it at full
    weight let 73% of untrustworthy data visually dilute the 27% that
    actually proves the pattern. A thin gray outline keeps those buildings
    visible as footprints (the city shouldn't look like it's missing
    buildings); a legend checkbox toggles the filled/hatched view back on.
  - **Tier 1 (sale-verified) is colored by the divergence between rate and
    value**, not a plain rate ramp and not an independent rate x value
    bivariate grid (tried first, rejected by the user: muddy middle,
    9-box legend was a puzzle). Buckets mkt/r1 into terciles and colors by
    (valueTier - rateTier) on a validated 5-step diverging palette (blue =
    value outpaces rate, i.e. the headline case; red = rate outpaces
    value; neutral = proportionate) -- a real diverging pair per the
    dataviz skill (equal step count per arm, CVD ΔE 27-29 between
    meaningfully different steps), collapsing to one labeled bar in the
    legend instead of a grid.
  - No popups/search/filters yet (milestone 4). `bbl` renders in tile
    properties as a decimal-formatted string (e.g.
    `"1000010010.00000000"`) — fixed in milestone 4, see below.
  Verified in an actual headless-Chromium render (Playwright, added as a
  devDependency) against both the Manhattan dev sample and the real
  citywide production tileset throughout. Two build gotchas hit along the
  way, both of which silently produced a **blank map with no console
  errors** until diagnosed:
  - MapLibre circle layers do **not** skip non-point geometry on their
    own (unlike fill layers) -- they'll draw a circle at every vertex of a
    matching polygon. The point-fallback circle layers (meant for the
    ~0.04% of buildings that only resolved to a centroid) were drawing a
    dot on every vertex of every tier1/tier2 polygon until an explicit
    `["==", ["geometry-type"], "Point"]` filter was added.
  - maplibre-gl v6 resolves its worker script relative to its own bundle's
    `import.meta.url` at runtime, which Vite's static analysis can't
    follow — the worker (and the shared chunk it imports) were silently
    missing from both the dev server and `dist/`. Fixed by vendoring a
    verbatim copy (`site/scripts/copy-maplibre-worker.mjs`, runs on
    `postinstall`) and pointing maplibre-gl at it via `setWorkerUrl()` in
    `main.ts`. Worth knowing if maplibre-gl is ever upgraded.
- **Milestone 4 (interactivity: popups, search, filters): DONE.**
  - **`bbl` fixed at the source**: PLUTO's `bbl` comes back from Socrata
    already decimal-formatted (`"1010307501.00000000"` — Socrata's own
    `number`-type serialization, confirmed by checking `pluto.parquet`
    directly, not a downstream GeoJSON artifact). Normalized once with
    `SPLIT_PART(bbl, '.', 1)` in `04_build_effective_rates.py`'s `pluto`
    CTE so every downstream consumer (tiles, search index) gets a clean id
    for free. Re-ran `04→05→07→08` (all local/cached, no re-fetch needed).
  - **New per-building fields** threaded through `04`/`07`/`08`: `address`
    (from PLUTO, `ANY_VALUE` per building), `tax_class` (`mode()` of the
    building's unit tax classes — needed for the filter UI), and two new
    `04` aggregates: `tier1_last_sale_date` (`MAX` sale date among the
    building's tier-1 units) and `tier1_pctile_pays_less_than` (a
    `PERCENT_RANK() OVER (PARTITION BY borough, tax_class ORDER BY
    building_effective_rate_tier1 DESC)` — "this building pays a lower
    rate than X% of same-borough, same-class tier-1 peers", feeding the
    popup's "for scale" line).
  - **Tile schema size fight**: naively shipping the new fields (esp.
    `address`, a unique string per building that doesn't dedupe) at every
    zoom pushed the citywide tileset from the milestone-2 baseline of
    103MB to 129MB — over GitHub's 100MB hard push-block. Root cause: each
    zoom level of the tile pyramid stores its own near-complete copy of
    the feature set, so per-feature field cost is multiplied by however
    many zoom levels carry it. Fixed by restricting detail fields
    (`addr`/`sale`/`saledt`/`pctl`/`nsale`) to a **single** top zoom
    (`DETAIL_ZOOM`) rather than a z14-16 band, and capping the tileset's
    own native max zoom at 15 (MapLibre's `maxZoom: 18` in `main.ts`
    just overzooms the z15 tile beyond that, rather than paying for a
    whole extra full-resolution pyramid level). `08_build_tileset.py` now
    runs two tippecanoe passes (lean overview z9-14, full-field detail
    z15) merged with `tile-join`, since tippecanoe has no
    single-invocation per-zoom field filter. Final citywide size: **74MB**.
  - **Search** (`site/src/search.ts`): citywide index
    (`site/public/search-index.json.gz`, 856,389 addresses, array-of-arrays
    not array-of-objects to avoid repeating key names 856K times) built by
    `08_build_tileset.py` alongside the tileset, gzip-compressed per
    PLAN.md's performance-strategy bullet. Client fetches + feeds it to
    MiniSearch (lazy dynamic `import()`, not a static one, so the library
    itself isn't in the initial bundle) on first search-box focus, never
    on first paint. Two things found only by testing against the full
    856K-row citywide index (the 42K-row Manhattan dev sample didn't
    surface either):
    - Vite's dev/preview server (and possibly GitHub Pages — unconfirmed)
      recognizes the `.gz` extension and transparently decodes it,
      setting `Content-Encoding: gzip` on the response — so `fetch()`
      already hands back decompressed bytes, and piping them through a
      second `DecompressionStream("gzip")` throws. Fixed by checking
      `res.headers.get("content-encoding")` and only manually
      decompressing when the server didn't already do it.
    - `MiniSearch.addAll()` over 856K documents blocks the main thread for
      **~10 seconds** (freezing the whole page, not just the search box).
      Switched to `addAllAsync()` (chunked, yields between batches) so the
      map stays interactive during the build, at the cost of a somewhat
      longer wall-clock time (~10-20s first use). This first-use latency
      is a known v1 limitation, not resolved — a real fix would build and
      serialize the MiniSearch index at pipeline time
      (`miniSearch.toJSON()` / `loadJSON()`) instead of reindexing
      client-side; flagged for a future pass, not done here since it's
      outside interactivity scope. A "Loading search index…" message
      covers the wait so it doesn't read as broken.
  - **Popups** (`site/src/popup.ts`): click (or a search selection) opens
    a popup built straight from tile properties — no extra fetch, per
    PLAN.md's performance strategy #1. Shows address, borough, tax class,
    tier basis (sale-verified vs. DOF-value fallback, labeled in plain
    language, never as "tier1"/"t1"), computed tax, effective rate, and
    the percentile "for scale" line. One real bug caught only by clicking
    an actual dense building in the browser, not by reading the code: the
    `sale` tile field is `tier1_sale_basis`, the **sum** of sale prices
    across every unit in the building that sold 2016-2025 (existing
    milestone-1 aggregation, used correctly as a rate denominator) — for
    220 Central Park South (116 sold units) that summed to $4.1B, and an
    early version of the popup displayed it unqualified as "Sold for
    $4118M", reading as a single (wrong) transaction. Fixed by adding a
    `nsale` tile field (`tier1_unit_count`) and branching the label:
    "Sold for $X on {date}" for a single sale, "Combined price, N units
    sold here" otherwise.
  - **Filters** (`site/src/filters.ts`): borough and tax-class toggle
    chips, combined with each layer's existing tier/geometry-type filter
    via `map.setFilter`. A selected-everything category is omitted from
    the filter expression entirely (not turned into an `in [all 5
    values]` clause) so the rare building with a missing `boro`/`cls`
    doesn't vanish under the default "nothing deselected" state — an `in`
    filter only matches non-null fields.
  - **Dev-loop gotcha**: `08 --sample` writes to `data/cache/dev_sample.
    pmtiles`, but `npm run dev` serves `site/public/tiles/dev-sample.
    pmtiles` — a separate, gitignored copy the build script does not
    write directly. Lost real time here mid-milestone: several rebuilds'
    worth of browser checks were silently exercising a stale
    pre-fix tileset (still showing the decimal `bbl`) because this copy
    step was missed. Now documented in `pipeline/README.md`.
  Verified via headless-Chromium (Playwright) against both the Manhattan
  dev sample and the real citywide production build (`npm run build` +
  `npm run preview`) — clicking Central Park South buildings, searching
  "central park", toggling borough/class filters, and inspecting actual
  `queryRenderedFeatures` output at both z9-ish (overview, lean fields)
  and z15 (detail, full fields) to confirm the zoom-band split behaves as
  designed.
- **Milestone 5 (narrative layer): DONE.** Three design decisions were
  checked with the user up front (see `AskUserQuestion` in this session)
  before building: the scrollytelling mechanic is a **pinned live map**
  (not a separate map instance or plain static text), the intro is a
  **full-screen overlay** shown before the free-roam chrome, and the
  scatter's data volume is a **precomputed random sample** (not full
  population or hexbin).
  - **One map instance, not two.** `#map` moved from `position: absolute`
    (within `#app`) to `position: fixed` (full viewport) so the exact same
    MapLibre instance serves both the scripted intro camera moves and the
    free-roam experience afterward — `story.ts` calls `map.flyTo`/
    `map.fitBounds` on it directly, never spins up a second map. An
    `IntersectionObserver` per `.story-step` with a shrunk `rootMargin`
    (`-45% 0px -45% 0px`, a "viewport center line") tracks exactly one
    active step at a time and re-fires on scroll-up too, so reversing
    through the story un-does later steps' effects (chart hides, camera
    flies back) instead of only working one direction.
  - **The on-screen zoom +/- control isn't gated by disabling MapLibre's
    interaction handlers.** `story.ts` disables `scrollZoom`/`dragPan`/etc.
    so the user can't fight the scripted camera, but `NavigationControl`'s
    buttons call `map.zoomIn()`/`zoomOut()` directly and ignore all of
    that — caught only by testing an actual click during the intro, not
    by reading the handler-disable code. Fixed by hiding
    `.maplibregl-ctrl-top-right` via a `body.story-active` CSS rule
    alongside the rest of the free-roam chrome (header/legend), not by
    trying to intercept the control's own click handler.
  - **Handoff out of the story is a deliberate button click**
    (`#story-enter`, "Start exploring the map"), not an automatic trigger
    when the last step scrolls into view. Reaching the last step still
    flies the camera back to the citywide view (a preview), but doesn't
    collapse the story or unlock map interaction until clicked — auto-
    triggering on scroll-into-view would otherwise yank the layout out
    from under the user mid-read the instant the last card centered.
    Clicking it removes `body.story-active`, adds `body.story-done` (CSS
    collapses `#story` to `display: none` and locks `body` scroll, since
    the fixed map is now the sole scrollable/zoomable surface), and
    re-enables the map's interaction handlers.
  - **Scatter data is unit-lot grain, not building grain — a real bug
    caught before it shipped, not after.** The tileset's building-level
    `building_effective_rate_tier1`/`tier1_sale_basis` (used everywhere
    else, e.g. the popup) aggregate a *sum* of every unit that sold
    2016–2025 — for 220 Central Park South that's a combined $4.1B across
    116 units, not Ken Griffin's own $239,958,219 sale. Plotting that
    aggregate would have put Griffin's dot at the wrong x-position relative
    to the exact anchor numbers this same document validates in "The
    story" above. Fixed by having `pipeline/08_build_tileset.py`'s new
    `build_scatter_sample()` read `unit_effective_rates.parquet` (unit-lot
    grain, one row per DOF unit — the pipeline's original, pre-aggregation
    table) instead of `buildings_geom.parquet`, matching the granularity
    the Furman Center comparison itself uses ("for co-op/condo **units**
    sold in 2025..."). Griffin's own unit-lot (boro=1, block=1030,
    lot=1082) is force-included in the sample regardless of the random
    draw, same reasoning as the Griffin assertions in `05_validate.py`.
  - **Sample**: capped at 4,000 sale-verified unit-lots per tax class
    (1 and 2 only — "the disparity is mainly a class-1-vs-class-2 story,"
    per Core metric below — which also keeps the chart's categorical
    legend to 2 validated slots instead of needing an "other" bucket),
    ordered by `hash(boro||block||lot)` for a reproducible-without-a-seed
    sample. Citywide output: 8,000 points, 0.07MB gzipped
    (`site/public/scatter-sample.json.gz`); dev/Manhattan-only counterpart
    at `site/public/scatter-sample-dev.json.gz` (gitignored, same pattern
    as the search index's `-sample` file).
  - **Bundle-size regression caught by rebuilding, not assumed.** The
    milestone's own name says "lazy loaded," but the first working version
    statically `import`ed `scatter.ts` (and therefore
    `@observablehq/plot` and its d3 sub-dependencies) from `story.ts` --
    TypeScript happily compiled it and Playwright didn't catch it since
    nothing about it changes runtime *behavior*, only the bundle
    contents. `npm run build`'s own output surfaced it: one 1.2MB/339KB-
    gzipped chunk, over the Performance strategy's <300KB budget. Fixed
    by dynamic `import("./scatter")` inside `story.ts`'s `showChart()`,
    the same lazy-import pattern `search.ts` already uses for MiniSearch —
    splits Plot into its own 240KB/84KB-gzipped chunk, fetched only once
    the chart step is actually reached, and brings the main chunk back to
    255.69KB gzipped (under budget). Re-verified after the fix that the
    scatter chunk is genuinely fetched only on reaching the chart step,
    not on page load.
  - **Chart**: Observable Plot scatter, log-scale sale price (x) vs.
    effective rate (y, capped/clamped at 8% -- the meaningful bulk of both
    classes sits under ~3%, per real-data exploration during this
    milestone; a few outliers near the 25% ceiling backstop would
    otherwise flatten the scale), color by tax class (validated
    blue/green categorical pair, `node scripts/validate_palette.js
    "#2a78d6,#008300" --mode light --pairs all` -- all checks pass).
    Griffin's own point gets a surface-color halo + ring (dataviz skill's
    ">=8px end-marker" spec) and a direct label anchored up-left (`dx:-12,
    textAnchor:"end"`) so it doesn't clip off the chart's right edge,
    since his sale price sits near the top of the citywide distribution.
  - Verified via headless-Chromium (Playwright) against both the
    Manhattan dev sample and the full citywide production build (`npm run
    build` + `npm run preview`): scrolled forward through all 4 steps and
    backward again (chart/camera effects both directions), clicked
    "Skip intro," clicked "Start exploring the map" and confirmed
    `body` class flips, the on-screen zoom control re-enables
    (`map.getZoom()` actually changes after a wheel event, not just that
    the handler was called), a building click still opens a popup
    post-handoff (milestone 4 regression check), and — against the real
    citywide build specifically — that the scatter chunk and
    `scatter-sample.json.gz` are fetched only once the chart step is
    reached, never on first paint.
- **Milestone 6 (performance gate): DONE, with a documented budget gap.**
  Tested against the citywide production build (`npm run build && npm run
  preview`): Lighthouse Performance **97** (target ≥90, pass), JS gzipped
  before interaction **381.5KB** (target <300KB), first tiles painted on a
  real (CDP, not Lighthouse-simulated) throttled connection **8.5s** on
  Lighthouse's own pessimistic "Slow 4G" profile / **3.1s** on a more
  typical regular-4G profile (target <1.5s in both cases). Full
  methodology, root-cause analysis, and a phased roadmap for actually
  closing the remaining gap: see `PERFORMANCE.md`.
  - **Two real fixes shipped, no tradeoffs.** (1) MapLibre still builds GL
    buckets/buffers for a layer with `visibility: "none"` — hiding is a
    render-time switch, not a tile-processing one — so the tier2 layers
    (hidden by default since Milestone 3, ~73% of all buildings) were
    paying full bucket-build cost on every load for something invisible on
    first paint. `main.ts`'s `ensureTier2Layers()` now defers adding those
    3 layers until the legend checkbox is actually switched on. Total
    Blocking Time: 2690ms → 20ms; **Lighthouse score: 63 → 97**. (2)
    `map.on('load')` → `map.on('style.load')` — `load` fires only after the
    basemap's own first visually-complete render, needlessly serializing
    our own buildings-tile fetch behind a live third-party basemap's full
    readiness instead of starting both in parallel; plus a `preconnect`
    hint to the basemap host. Together cut the Slow-4G first-tiles number
    from 10.1s → 8.5s.
  - **The other two budget misses are architectural, not bugs**, traced to
    two Milestone-3 decisions, discovered only now because this is the
    first time either number was measured against a real build: MapLibre GL
    JS's official bundle is ~380KB gzip minimum (main + worker chunk) before
    any of our own code, not tree-shakeable; and OpenFreeMap's live
    "positron" basemap pulls sprite+fonts+~900KB of shared vector-tile data
    (the tile bytes are fixed by OpenFreeMap's *shared* planet tileset, not
    the chosen style, so a lighter style wouldn't touch the dominant cost)
    from a third-party host on the same throttled pipe as everything else.
    At 1.6Mbps throttled bandwidth, ~1.4MB of combined payload before first
    paint is arithmetically incompatible with a 1.5s budget regardless of
    further code-level tuning. Per a user decision on 2026-07-31: don't
    force a rendering-stack rewrite now — ship with the measured numbers,
    documented in `PERFORMANCE.md`'s roadmap (self-host a minimal basemap
    style; self-hosted raster-tile basemap instead of the live vector one;
    replacing MapLibre GL JS with a lighter custom renderer, the only lever
    that actually attacks the JS-size floor) for a future revisit if the
    site gets real traffic.
  - Also found and fixed along the way: milestone 5's own bundle-size
    accounting (255.69KB gzip, recorded as "under budget" in that
    milestone's status) only counted the main entry chunk and missed the
    ~133KB `maplibre-gl-shared.mjs` worker chunk that also loads before
    interaction — the real total was always ~381KB, not caught until this
    milestone's explicit network-request tally.
- **Milestone 7 (polish + deploy + methodology): DONE.** Checked in with the
  user before starting (their stated preference) and again mid-milestone
  when a real bug turned up outside the original scope; both check-ins
  resolved before proceeding.
  - **Repo made public.** GitHub Pages requires either a public repo or a
    paid GitHub plan for private-repo Pages; confirmed no secrets were ever
    committed (`.env` always gitignored, only `.env.example` tracked) before
    flipping visibility. `gh repo edit --visibility public
    --accept-visibility-change-consequences`.
  - **Deploy mechanism: GitHub Actions build+deploy**
    (`.github/workflows/deploy.yml`), not a committed `dist/`/`gh-pages`
    branch — `npm ci && npm run build` in `site/` on every push to `main`,
    published via `actions/upload-pages-artifact` +
    `actions/deploy-pages`. Fits Vite's existing `dist/`-gitignored setup;
    no extra CI data-fetch step needed since `buildings.pmtiles`/
    `search-index.json.gz`/`scatter-sample.json.gz` are already committed
    source assets, not build outputs. Pages enabled via `gh api -X POST
    .../pages -f build_type=workflow` (had to run *after* the first push --
    the workflow's first run failed with `Get Pages site failed... Not
    Found` because Pages wasn't enabled yet when that push triggered it;
    re-ran via `gh workflow run deploy.yml` once Pages was on).
  - **`vite.config.ts` needed an explicit `base: "/nyc-tax-disparity-map/"`**
    for correct asset paths on a GitHub Pages *project* page (not a
    user/org root page) -- unset, it defaults to `/`, which breaks on
    `<username>.github.io/<repo>/`. The app's own asset-path code
    (`main.ts`/`search.ts`/`scatter.ts`) already read `import.meta.env.BASE_URL`
    rather than hardcoding `/`, so this one config line was the only
    change needed -- confirmed via `vite preview` that built HTML/JS/CSS
    paths and a ranged PMTiles request all resolved under the base path
    before deploying.
  - **The live URL is the custom domain, not `nlicalzi.github.io`.**
    The account's user-level Pages site (`nlicalzi.github.io` repo) already
    has `www.nlicalzi.com` configured as a custom domain (pre-existing,
    unrelated to this project) -- GitHub Pages automatically extends a
    user-site custom domain to every project site under that account, so
    `nlicalzi.github.io/nyc-tax-disparity-map/` 301-redirects to
    **`https://www.nlicalzi.com/nyc-tax-disparity-map/`**, confirmed as the
    canonical URL (`gh api .../pages` reports it as `html_url`). Both URLs
    work; the custom domain is what's linked from README.
  - **Verified against the real deployment, not just localhost**: PMTiles
    range requests (`HTTP/2 206` with correct `Content-Range`, confirmed on
    both the redirect-followed custom domain and the raw `.github.io` URL),
    full Playwright run against the live site (map renders, methodology
    panel expands, search → popup → filter chip all work, zero console
    errors). Also resolved two things only visible against the real CDN:
    GitHub Pages' Fastly origin does **not** serve Brotli even when the
    client advertises support (`Accept-Encoding: br, gzip` still comes back
    `content-encoding: gzip`) -- closes out PERFORMANCE.md's "unverified"
    Brotli question, no win available there. And the search index's
    known first-use latency (PLAN.md's existing ~10-20s local estimate)
    measured **~32s** over the real internet on first use -- slower than
    local, from the combination of a bigger real download + GitHub Pages
    not labeling the `.json.gz` response `content-encoding: gzip` (so the
    client's manual `DecompressionStream` fallback path runs, same
    known-limitation code path documented in Milestone 4, just slower over
    a real network than localhost). Still the same accepted v1 limitation,
    not a new bug -- not fixed here, per that milestone's existing framing.
    See PERFORMANCE.md for the full re-verification writeup and updated
    throttled-perf numbers against the live site (3.9s regular4g / 9.3s
    slow4g first-tiles-painted, vs. 3.1s/8.5s measured locally -- slightly
    worse from real internet RTT/DNS/TLS on top of the same architectural
    bottleneck, not a regression).
  - **New methodology footer** (`site/src/methodology.ts`, wired in
    `main.ts`): a collapsed-by-default `<details>` panel, bottom-right
    (symmetric with the legend's bottom-left), covering data vintage,
    the tax/rate formula, and a link back to the repo -- per
    PERFORMANCE.md's recommendation that this live in the site itself, not
    just the README. Plain `<details>`/`<summary>`, not hand-rolled toggle
    JS, since it's static content with no state anything else needs to
    react to.
  - **Real bug found and fixed mid-milestone, not just deploy plumbing**:
    while verifying the deploy didn't break existing interactivity,
    selecting a search result would sometimes never open a popup. Root
    cause: the search-select handler waited on MapLibre's map-wide `idle`
    event, which only fires once *every* source -- including the live,
    continuously-tile-fetching OpenFreeMap basemap -- has nothing pending,
    not just our own buildings source. Confirmed via timing trials this
    doesn't hang forever under normal conditions (an earlier, overstated
    read of the bug during initial investigation) but is measurably slower
    and coupled to third-party basemap load state for no reason. Fixed by
    scoping the wait to the buildings source specifically
    (`whenBuildingsSourceLoaded()` in `main.ts`, mirrors the existing
    `first-tiles-painted` perf-mark's `sourcedata`/`isSourceLoaded` check).
    Confirmed via repeated trials: ~3.2-3.3s consistently after the fix vs.
    ~4-4.7s before, and no longer coupled to basemap load state. Confirmed
    this reproduces identically on the pre-M7 `main` build too (not a
    regression from this milestone's other changes) by temporarily
    swapping in the old file and re-testing.
  - `site/public/.nojekyll` added (GitHub Pages runs Jekyll by default,
    which can interfere with dotfile-adjacent paths; harmless but standard
    to disable for a plain static build).
  - README updated: was still describing milestones 1-4 as the full state;
    now reflects all 7, adds the live URL, and documents the deploy
    mechanism.
- Work style: check in with the user after each milestone before proceeding
  to the next (their stated preference) -- held for all 7 milestones,
  including a genuine mid-milestone check-in in Milestone 7 when scope
  expanded beyond the original plan (fixing the search-popup bug).
- **Post-Milestone-7 feature additions (2026-07-31), from direct user
  feedback on the deployed site.** Four asks, not a formal milestone: local
  work only, verified via Playwright against both the dev sample and the
  full citywide production build, not yet pushed -- pending user review of
  the result before it goes live (deploys automatically on push to `main`,
  per Milestone 7's Actions workflow).
  - **Tax-class filter clarity**: the header's tax-class chips already had a
    native `title` tooltip, but per feedback it still wasn't obvious what
    "Class 2" means. Replaced with a custom `data-tip` + CSS tooltip
    (`filters.ts`/`style.css`) that appears instantly on hover/focus, no
    native-title delay; `aria-label` carries the same text for screen
    readers, which don't reliably read `title`.
  - **Divergence-axis filter**: a new filterable dimension on the same -2..+2
    over/under-taxed index `colors.ts` already colors tier-1 buildings by
    (factored the shared bucket math out into
    `divergenceIndexExpression`, reused by both the paint expression and the
    new filter). Five toggle chips in the legend, directly under the
    diverging ramp they filter (`legend.ts`), wired through a third
    dimension on `filters.ts`'s `createFilterController` alongside the
    existing borough/class filters -- same "omit the clause when everything
    selected" pattern. Applies only to `fill-tier1`/`circle-tier1` (tagged
    with a `divergence` expression per layer); tier2/nodata layers aren't
    colored by this axis and don't carry one.
  - **Scatter chart trend lines**: per-tax-class least-squares fit of
    effective rate against log10(sale price) (not raw price -- a fit against
    raw price would be dominated by the highest few points and wouldn't
    render straight on the chart's log-x scale), drawn as a dashed line per
    class reusing the existing color channel, plus a caption stating the
    fitted slope in "percentage points per 10x price" -- computed live from
    the actual rendered sample, not a hardcoded claim. **This surfaced a
    real, significant finding** -- see the new correction note in "The
    story" above -- that changed both the chart's caption and the
    surrounding story-card copy, checked with the user before shipping given
    it touches the site's headline claim, not just this feature.
  - **Griffin highlight + real popup on the story's Griffin step**: a red
    outline (soft glow + crisp line, matching the scatter chart's halo+ring
    treatment for the same building) around 220 Central Park South's
    polygon, shown only during that story step. Opens the *real* popup --
    queried from the loaded tile via `queryRenderedFeatures`, built with the
    same `buildPopupHtml` a genuine click uses -- rather than a hand-typed
    stand-in, so it can't drift out of sync with what clicking the building
    anywhere else shows. Threaded via a new `onGriffinFocus` callback on
    `StoryOptions` (`story.ts`), called from `applyStep`; waits on `moveend`
    + the buildings source being loaded before querying, the same pattern
    used for the Milestone 7 search-popup fix. `GRIFFIN_CENTER`/`GRIFFIN_BBL`
    now live as exports from `story.ts` (previously private) so `main.ts`
    shares the one validated coordinate/BBL instead of re-deriving it.
    Verified bidirectional (matches the existing story design): scrolling
    back up to the Griffin step re-shows the highlight and popup, not just
    scrolling forward past it.
- **Follow-up (2026-07-31): results-list panel**, from direct feedback that
  narrowing the divergence filter made matches hard to actually *find* on
  the map (color-coded dots are easy to miss at a glance). New
  `site/src/results.ts`: a "N buildings in view" panel (top-right, below the
  zoom control) listing whatever's currently rendered and passing the
  active filters, click an entry to fly to it and open its real popup.
  - **Client-side only, no pipeline/tileset change.** Built from
    `map.queryRenderedFeatures(CLICKABLE_LAYERS)` on every `moveend` and
    filter change, not a separate precomputed citywide dataset -- considered
    and rejected a pipeline-emitted "tier1 index" (address + coords + tax
    class + divergence bucket, ~230K rows) since it would mean touching the
    tileset build and re-verifying the performance budget for a feature
    that's really about *what's currently on screen*, not a citywide browse.
    Deduped by `bbl` (a building can span multiple query hits at tile
    boundaries), capped at 200 entries with a "200+" indicator, addr-first
    then BBL-only entries, both groups alphabetical.
  - **Only shown once something's actually filtered**
    (`filterController.isFiltered()`, a new getter alongside the existing
    borough/class/divergence state) -- hidden on the default unfiltered
    landing view where it would just be redundant clutter, appears the
    moment any filter (borough, class, or divergence bucket) is narrowed.
  - **Address availability is zoom-dependent, same constraint as
    everywhere else**: `addr` only exists in tile properties at the
    tileset's single highest detail zoom (Milestone 4's tile-schema size
    fight), so at citywide/borough zoom most entries show a `BBL ######`
    fallback instead of hiding those buildings from the list; verified both
    paths against the citywide production build (85 real addresses at a
    zoomed-in Manhattan view vs. `BBL` fallbacks at the citywide default).
  - **Refactor along the way**: the flyTo-then-popup sequence (wait for
    `moveend` + the buildings source to load, then query and show the real
    popup) existed three times with drift risk (search selection, the
    Griffin callout, now this) -- factored into two shared helpers
    (`waitForBuildingPopup`, `flyToBuildingAndPopup`) in `main.ts`, all
    three call sites now share one implementation.
  - **Two real bugs found by the user immediately after this shipped, both
    fixed same-day (2026-08-01):**
    1. **Wrong layers queried once the divergence axis was narrowed.**
       tier2/nodata layers carry no divergence classification at all -- only
       `fill-tier1`/`circle-tier1` do -- so their own MapLibre filter never
       excludes anything based on the divergence buckets. The results query
       unconditionally used `CLICKABLE_LAYERS` (all of them), so narrowing
       to e.g. "most overtaxed" correctly narrowed the *map's* colored
       tier-1 dots but the *panel* kept listing every uncolored tier-2/
       nodata building still sitting on screen alongside them -- reported by
       the user as "200 buildings" shown when the map visibly had ~0 colored
       matches. Fixed with a new `filterController.isDivergenceNarrowed()`
       getter: once true, the results query restricts to
       `["fill-tier1", "circle-tier1"]` only, dropping tier2/nodata from the
       list entirely rather than padding it with buildings that were never
       part of the selected slice.
    2. **`queryRenderedFeatures` right after `setFilter` can be stale.**
       Even after fixing (1), the *first* narrow-to-one-bucket interaction
       still showed a stale, much-larger count. Root cause, confirmed by
       directly comparing an immediate re-query against a delayed one in the
       browser: MapLibre's `setFilter` updates the layer's filter spec
       synchronously (`getFilter()` reflects it right away) but
       `queryRenderedFeatures` can still be querying against the
       *previously compiled* filter until a render pass actually runs --
       calling it in the same tick as `setFilter` (as the results-list
       refresh did, triggered synchronously from the filter-toggle
       handlers) can return results computed against the *old* filter.
       `map.once("render", ...)` wasn't a strong enough signal (still
       stale in testing); `map.once("idle", ...)` -- MapLibre's "no pending
       render or tile work at all" event -- was. `scheduleResultsRefresh()`
       in `main.ts` now defers every filter-triggered refresh through
       `idle` instead of calling the query synchronously; the `moveend`-
       triggered refresh (panning/zooming) was left as a direct call since
       it never showed this staleness in testing (a pure camera move
       doesn't recompile any layer filter, the specific thing that was
       stale). Verified via repeated trials, not a one-off: 134
       (unfiltered-equivalent, stale) before both fixes, 2 (correct, matches
       the visibly rendered polygons) after -- consistent across reruns.
  - **Follow-up (2026-08-02): effective rate added to each row.** User
    feedback: the BBL-only fallback (when zoomed out past the tileset's
    single detail zoom, see above) wasn't a very useful label on its own --
    asked for something like "Address | Effective Tax Rate" instead.
    `addr` is a detail-zoom-only field, but `r1`/`r2` are lean-schema fields
    present at *every* zoom (colors.ts), so the rate can always be shown
    regardless of how zoomed out the list was built at, unlike the address.
    New `rateLabelFor()` in `results.ts`: plain `formatRate(r1)` for
    tier-1 (sale-verified), `formatRate(r2) + " (est.)"` for tier-2 (DOF-
    value fallback), `"no data"` for nodata rows -- the `(est.)` suffix
    matters so a tier-2 estimate is never shown unlabeled next to a tier-1
    sale-verified number, matching the same distinction the map/legend/
    popup all make elsewhere (PLAN.md's Core metric: the two aren't
    directly comparable, and blending them was explicitly rejected back in
    Milestone 3). Rendered right-aligned on each row's second line, next to
    the borough.
  - **Bug found by the user right after this shipped (2026-08-02): "empty
    square" where the results panel should be, appearing even when nothing
    was filtered.** Root cause: a classic CSS specificity gotcha, not a JS
    bug. `#results`'s own rule sets `display: flex` -- an ID selector, which
    beats the browser's built-in `[hidden] { display: none }` rule (a lower-
    specificity attribute selector) -- so setting `resultsRoot.hidden = true`
    in `main.ts` stopped actually hiding the panel; it kept rendering as an
    empty flex box (no count text, no items, since `update()` never ran)
    sitting on screen. Confirmed directly: `el.hidden` read `true` in the
    DOM while `getBoundingClientRect()` still returned a real, non-zero box.
    Fixed with an explicit `#results[hidden] { display: none; }` rule (an
    ID+attribute selector, specific enough to win). Verified both states
    post-fix: a zero-size box when unfiltered, a real box with content once
    a filter is narrowed.
  - **Follow-up (2026-08-02): addresses only, sorted by decreasing rate.**
    User feedback: "I want it to list addresses, not BBLs. I also want it to
    sort by DECREASING effective rate." The BBL fallback from the prior
    entry is gone entirely -- `refreshResultsImpl` (`main.ts`) now skips any
    rendered feature with no `addr` (detail-zoom-only, see above) instead of
    labeling it `BBL ######`. Since `addr` requires being zoomed in to the
    tileset's single detail zoom, this means the list can legitimately go
    empty while zoomed out and filtered; rather than showing a generic "no
    buildings" message in that case (misleading -- buildings *are* there,
    just unaddressed at this zoom), a `sawUnaddressed` flag distinguishes it
    and shows "Zoom in to see building addresses." instead. New
    `rateValueFor()` in `results.ts` mirrors `rateLabelFor()`'s tier-1-then-
    tier-2 precedence but returns the raw number instead of a formatted
    string, so the sort key can never drift out of sync with what's printed
    next to it; `refreshResultsImpl` sorts by that value descending (most-
    overtaxed first), with `null` ("no data") rows always sorting last
    regardless of direction. `labelFor` was removed (no BBL case left to
    handle) in favor of a plain `addressLabel()`. Verified via Playwright
    against the full citywide production build (`vite preview`): searching
    to a dense Bed-Stuy block at z17 and filtering produced addresses only
    (no `BBL ` rows), rates strictly descending (21.63% -> 18.27% -> 8.80%
    -> ... -> 5.60%); zooming out to ~z11 while still filtered showed the
    new "Zoom in to see building addresses." hint with zero rows instead of
    stale/wrong content.

## The story
NYC's property tax system is famously regressive at the top: because co-ops and
condos are legally assessed as if they were rental buildings ("comparable
rental income" method) rather than on sale price, ultra-luxury condos are
often valued by DOF at a small fraction of what they actually sold for — while
modest single-family homes and co-ops are assessed much closer to market
value. Result: effective tax rates *fall* as property value rises at the very
top.

**Correction (2026-07-31, post-Milestone-7 feature work):** "modest
single-family homes... are assessed much closer to market value" overstates
how flat class 1 actually is across its own price range. A least-squares fit
of sale-verified effective rate against log10(sale price), run against the
full citywide sample while adding the scatter chart's trend lines (see
Status below), shows class 1's rate *also* falls as price rises -- and at
every price band tested, at least as steeply as class 2's. Not an artifact:
holds after excluding the two most extreme outliers, and gets *more*
pronounced (not less) when the top 1% by price is trimmed from both classes.
The likely mechanism is different from class 2's (income-approach
undervaluation): New York State's statutory cap on how fast a class 1
property's assessed value can rise year-over-year (6%/year, 20%/5-year)
means a home whose market value has appreciated quickly -- which correlates
with a high current sale price -- can have an assessed value lagging far
behind it at time of sale. This is a plausible, well-known feature of NYC
property tax policy, not something independently traced through this
pipeline's own assessment-history data the way the Griffin correction above
was -- flagged as a likely explanation, not a fully validated one. The
site's "It's not just one building" step and its scatter chart's trend
lines/caption were updated to state the finding directly rather than the
original "blue stays proportionate" framing; this doesn't change the
Griffin anchor or the class-2 income-approach story, which remain the
validated headline.

Concrete anchors to cite in the UI:
- Ken Griffin's Central Park South penthouse (BBL 1-01030-1082, "220 CENTRAL
  PARK SOUTH, 50"): sold 2019-01-23 for $239,958,219. Current (FY2026 final
  roll) DOF taxable value is $6,725,023 (tax class 2); at the FY2026 class 2
  rate (12.439%) that computes to ~$836,500 in tax — an effective rate of
  **~0.35% of the actual sale price**. (Note: the commonly-cited "~0.22%"
  figure was computed against an earlier, lower assessment year — DOF's own
  reported value for this unit has drifted from ~$9.4M up to ~$15.5M over
  FY2023–FY2027 even though nothing about the unit changed; the sale price is
  fixed. Verified directly against NYC Open Data on 2026-07-30 — see
  Data sources below.)
- NYU Furman Center, *State of the City 2025*: for co-op/condo units sold in
  2025, DOF market value undershot actual sale price by a median of
  ~$850K (co-ops) / ~$806K (condos), while modest condos are comparatively
  overtaxed.
- **Why this matters for the metric, not just the anecdote**: DOF's own
  "market value" for co-ops/condos is *already* the deflated income-approach
  number — dividing DOF's computed tax by DOF's own market value nets out to
  a nearly uniform ~5.6% for every class-2 property regardless of luxury
  level (45% assessment ratio × 12.4% rate), confirmed empirically on the
  Griffin unit (assessed value tracks DOF market value almost exactly, no
  meaningful cap suppression). The real disparity only shows up against the
  *actual sale price*. See "Core metric" and "Data sources" below — this
  changed the pipeline's data requirements from the original draft of this
  plan.

Site goal: let anyone search or click any NYC property and see, side by side,
its market value, DOF assessed value, computed property tax, and effective
tax rate — with a citywide map view that makes the "expensive = lower rate"
pattern visually obvious (e.g., color by effective rate, size/opacity by
market value).

## Data sources (all public, NYC Open Data / Socrata)
Verified directly against the live Socrata catalog/API on 2026-07-30 — the
original draft of this plan cited a dataset that turned out to be stale; the
IDs below are current.

- **Property Valuation and Assessment Data — Tax Classes 1,2,3,4**
  (dataset `8y4t-faws`, ~11.7M rows, actively updated — last updated
  2026-06-15) — the correct, current primary source table. **Not** `yjxr-fw8i`
  (a similarly-named dataset that stopped updating in 2020 and only covers
  FY2011–2019 — don't use it). Schema is the raw RPAD roll layout: for each
  BBL/unit-lot and roll `year`, there are parallel PY/TEN/CBN/FIN/CUR-prefixed
  blocks (prior-year, tentative, changed-by-notice, final, current) each with
  MKT (market value), ACT (actual assessed), TRN (transitional assessed), and
  TXB (taxable — post-cap, post-exemption; this is the base the class rate
  applies to) land/total fields, plus a per-stage tax class. **Use the
  `cur*` fields** (`curmkttot`, `curtxbtot`, `curtaxclass`) — `curtxbtot` is
  already exemption- and cap-adjusted, so no separate exemption subtraction
  is needed. Filter to `year='2026' AND period='3'` for the v1 snapshot (see
  Data vintage below). Key is `(boro, block, lot)` — for condos/co-ops, `lot`
  is the *individual unit's* tax lot (typically a 4-digit number in the
  1000s range), not the building's PLUTO lot.
- **PLUTO** (`64uk-42ks`, Dept. of City Planning + DOF, ~858,602 rows, updated
  2026-05-28) — parcel join key (`bbl`), lot/building attributes,
  `latitude`/`longitude` centroids. One row per physical tax lot/building.
  For condos, PLUTO's `bbl` is the building-level "billing lot" (e.g. block
  1030 lot 7501 for 220 Central Park South) — all of that building's
  individual unit-lots from `8y4t-faws` share this one PLUTO row for
  geometry/map-rendering purposes. See Core metric below for how
  building-level map values are derived from unit-level data. **Correction
  (2026-07-30, milestone 2): PLUTO does NOT have real polygon geometry.**
  The dataset's schema lists a `geom` field, but it is 100% null across all
  858,602 rows (verified directly against the live API) — PLUTO only ever
  provides `latitude`/`longitude` centroids. `03_fetch_pluto.py` already
  reflects this (it never selects `geom`). Real polygons come from the two
  datasets below instead.
- **TAX_LOT_POLYGON** (`i38t-6if2`, part of DOF's Digital Tax Map
  Collection, ~858,042 rows) — the actual parcel polygon source. One
  `MultiPolygon` per physical tax lot, keyed by `bbl`. Matches PLUTO's
  `bbl` directly for ~98.6% of buildings. Condo billing lots (synthetic
  BBLs like 220 CPS's 1010307501) are **not** physical parcels and never
  appear here directly — see the crosswalk below.
- **Digital Tax Map: Condominiums** (`p8u6-a6it`, ~12,165 rows) —
  crosswalk from a condo's PLUTO billing `bbl` (`condo_billing_bbl`) to the
  real physical tax lot(s) it's built on (`condo_base_bbl`). Required to
  resolve condo buildings' geometry via `TAX_LOT_POLYGON` (~1.2% of
  buildings, of which ~0.06% — 533 buildings — map to *multiple* base lots
  and need those polygons dissolved into one footprint). Validated against
  220 Central Park South: `condo_billing_bbl` 1010307501 resolves to base
  `bbl` 1010300019, confirmed geometrically correct (closest match to
  PLUTO's own centroid for that building; a second candidate lot on the
  same block was a smaller, wrong sliver). Combined, `TAX_LOT_POLYGON` +
  this crosswalk resolve **99.87%** of buildings to a real polygon; the
  remaining ~0.13% fall back to PLUTO's point centroid.
- **NYC Citywide Annualized Calendar Sales** (`w2pb-icbu`, ~845,607 rows,
  2016-01-01 through 2025-12-31, updated 2026-06-09) — **new data source,
  added after discovering DOF's own market value can't serve as the
  denominator for co-op/condo effective rate (see Core metric).** Has `bbl`
  (building-level, for geometry) plus `block`/`lot` (unit-level, for joining
  to `8y4t-faws`) and `sale_price`/`sale_date`. This is what makes the
  Furman-Center-style "true value vs. DOF value" comparison possible instead
  of just citing it anecdotally. Filter out $0/nominal transfers (family
  transfers, foreclosures) before treating a sale as "arms-length market
  value." Coverage is inherently partial — most parcels don't sell every
  year — so plan on a two-tier metric (see below), not full citywide
  coverage of the "true" rate.
- **DOF Digital Tax Map** / borough block-lot shapefiles — parcel polygons for
  true choropleth rendering (fallback: PLUTO centroids as points if polygon
  join is too heavy).
- **Annual property tax class rates** — **not a bulk Open Data dataset**;
  published as a small HTML table at
  `nyc.gov/site/finance/property/property-tax-rates.page`, four numbers per
  fiscal year, adopted by City Council resolution. As of 2026-07-30 the page
  shows adopted rates through **tax year 2026** (Class 1: 19.843%, Class 2:
  12.439%, Class 3: 11.108%, Class 4: 10.848%) — FY2027 rates are not yet
  posted even though FY2027 assessed values already exist, because NYC bills
  at the prior year's rate until Council adopts the new one (typically
  November, per DOF's own taxpayer-advocate reference card). This is exactly
  why the v1 snapshot uses FY2026 throughout (see Data vintage) rather than
  mixing FY2027 assessed values with a not-yet-final rate. Hardcode this
  4-number table in the pipeline with the source URL and verification date
  in a comment; it isn't worth scraping for a one-time snapshot (see
  Non-goals).
- Stretch: NYC DOF property tax bill lookup (per-BBL, not bulk) to spot-check
  a sample of computed values against real bills.

## Data vintage (v1 snapshot)
- **Assessment roll**: `8y4t-faws`, `year='2026'`, `period='3'` (FY2026 final
  roll — the most recent fiscal year that is both fully assessed *and* has a
  fully-adopted tax rate, avoiding the FY2027 provisional-rate issue above).
- **Tax rates**: FY2026 adopted rates, as listed above, sourced from
  `nyc.gov/site/finance/property/property-tax-rates.page`, verified
  2026-07-30.
- **Sales**: `w2pb-icbu`, full 2016–2025 window, for the sales-join layer.
- Document this exact combination in the site's methodology footer per the
  existing non-goals commitment to a single fixed vintage.

## Agent workflow: keep the build agent's own token cost down
Separate from *site* performance above: the source data (9.85M valuation
rows, 858K parcels) is also too big for an LLM agent to process by reading it
directly. The rule for every pipeline step is **write a script, run it, read
back a summary** — never "read the data" into the conversation.

- **Never load raw source files into context.** Don't `Read`/`cat` a
  multi-hundred-MB CSV, GeoJSON, or `.pmtiles` file. Every inspection goes
  through a script that prints schema, row counts, and a small sample
  (`DESCRIBE`, `.head()`, `wc -l`) — a few lines of output, not the dataset.
- **Prototype on a capped sample, then run full-scale unattended.** Build and
  debug each transform against a small slice first — one borough, one BBL
  prefix, or a SoQL/DuckDB `LIMIT 2000` — so iteration is cheap. Once the
  script is correct on the sample, run it once, non-interactively (background
  job), against the full dataset. The agent should never iterate on a
  9.85M-row run interactively.
- **Push filtering/aggregation to the data layer, not the agent.** Pull only
  what's needed via Socrata SoQL params (`$select`, `$where`, `$group`,
  `$limit`) instead of downloading the full table and filtering locally.
  For local joins/aggregation, use DuckDB to query CSV/Parquet directly
  with SQL — results stay in the database/file, not in anything the agent
  has to read token-by-token.
- **Pipeline is committed code, not a conversation.** Every step (fetch →
  join → compute effective rate → geojson → tippecanoe) lives as a script in
  `pipeline/`, runnable end-to-end with one command. The agent's job is to
  write/debug/run scripts, not manually reason over rows.
- **Validate with in-script assertions, not by eyeballing rows.** Bake known
  checks into the script (e.g., assert the Griffin penthouse unit-lot
  (boro=1, block=1030, lot=1082) computes to a sale-verified effective rate
  in the ~0.3%–0.4% range against its real $239,958,219 sale — see "The
  story" for the exact expected numbers) so it prints PASS/FAIL — the agent
  reads one line, not the underlying rows, to confirm correctness.
- **Geometry ops via CLI tools, never in-context parsing.** Use `ogr2ogr`,
  `mapshaper`, and `tippecanoe` for simplification/tiling — file-to-file CLI
  operations. The agent should never need to parse a coordinate array itself.
- **Long jobs report status, not logs.** Full-dataset downloads and tippecanoe
  builds run in the background; the agent reads back exit status plus a
  short stats block (rows in/out, file size, tile count) — not full stdout.
- **Cache every expensive intermediate, don't re-derive it.** Persist the raw
  Socrata pull, the joined PLUTO+valuation table, and the computed-rates
  table to disk (e.g. Parquet in a `data/cache/` dir) after each step. Later
  work — styling, UX, debugging a rendering bug — should read from cache, not
  re-trigger a 9.85M-row fetch or a full join. Only re-run an upstream step
  if its output is missing or the source is confirmed to have changed.
- **Build a small dev-scale tileset for the agent's own testing loop.** The
  agent should verify UI changes in a real browser before calling work done,
  but pointing that at full production tiles (858K parcels) every check-in
  wastes the same bandwidth/tokens this plan is trying to avoid — just moved
  to the verify step. Build a one-borough sample `.pmtiles` early and use it
  for all iterative dev/browser checks; switch to the full production tiles
  only for the final pre-deploy check.
- **Keep the repo itself small.** Raw and intermediate data (source CSVs,
  joined tables, unminified GeoJSON) stay out of git via `.gitignore`; only
  the final `.pmtiles` (or a pointer to where it's hosted) and the pipeline
  scripts get committed. A bloated repo makes every `git status`/`find`/clone
  the agent runs slower and noisier for no benefit. Document the exact
  re-fetch command in the README so cache misses are a one-liner, not a
  rediscovery.

## Core metric
`computed_annual_tax = curtxbtot × class_rate` per unit-lot (already
exemption/cap-adjusted, see Data sources). The denominator is **not**
uniformly DOF's own `curmkttot` — that was the original draft's assumption,
and it's wrong for co-ops/condos (see the callout in "The story" above).
Two-tier metric instead:

1. **Sale-verified effective rate** (`computed_annual_tax / sale_price`) —
   used wherever a qualifying recent arms-length sale exists in the
   2016–2025 sales join (`w2pb-icbu`). This is the "real" rate and the one
   that shows the disparity. For class 1 (1-3 family homes), DOF's own
   comps-based market value is already close to true value, so this and the
   DOF-relative rate mostly agree; for class 2, they diverge sharply — that
   divergence *is* the story.
2. **Assessed-value effective rate** (`computed_annual_tax / curmkttot`) —
   fallback for parcels/units with no qualifying recent sale. Must be
   visually distinguished on the map from tier 1 (e.g. muted/hatched
   styling), not blended into the same color scale, since it's a
   structurally different (and for class 2, much higher-looking) number —
   see the ~5.6%-uniform finding above. Label it clearly in the popup as
   "based on DOF's own valuation, no recent sale on record" vs. "based on
   actual sale price."

Building-level map dots (PLUTO granularity) aggregate their constituent
unit-lots: sum `computed_annual_tax` across all units sharing that PLUTO
`bbl`; for the numerator side of tier 1, use sale-verified units only where
available (e.g. median sale-verified effective rate among that building's
recently-sold units), falling back to tier 2 for buildings with zero
recently-sold units. Unit-level detail (individual apartment's own rate,
sale date, sale price) stays available in the popup/detail view, not just
the aggregate.

Bucket by tax class (1 = 1-3 family homes, 2 = co-ops/condos/rentals,
4 = commercial) since the disparity is mainly a class-1-vs-class-2 story.

## Tech stack (current state of the art for a static, no-backend site)
- **Hosting**: GitHub Pages, fully static — no server, no database.
- **Map rendering**: MapLibre GL JS (open-source, actively maintained,
  no API key) + **PMTiles** for vector tiles — single-file tile archives
  servable directly from GitHub Pages via HTTP range requests, no tile
  server needed. Build tiles offline with `tippecanoe`.
- **Heavy-lift aggregation** (optional): deck.gl `MVTLayer`/`H3HexagonLayer`
  as a MapLibre overlay if per-parcel point rendering (~800K+ points) needs
  binning at low zoom for performance.
- **Supplementary charts** (distribution of effective rate vs. market value,
  the "smoking gun" scatter): Observable Plot — lightweight, SVG-based, pairs
  well with a scrollytelling narrative.
- **Data prep pipeline** (offline, run once + refresh yearly): Python or
  DuckDB to pull Socrata CSV/OData exports, join PLUTO geometry, compute
  effective rates, emit GeoJSON → `tippecanoe` → `.pmtiles`. Commit the
  built `.pmtiles` (or publish via GitHub Release/LFS if size is large)
  alongside the static site.
- **Framework**: plain Vite + TypeScript (or Astro) — no need for React
  unless UI complexity grows; keep bundle small.

## Performance strategy
~858K NYC tax lots is too much to ship as one blob, so the plan bakes in a
"never send more than the current view needs" approach at three layers:

1. **Tile schema is the detail layer — no separate lookup fetch.** Once a
   MapLibre vector tile is loaded, `queryRenderedFeatures` already has every
   property on that feature client-side, so click-for-detail is free *if* the
   tile properties are kept lean. Design the tippecanoe schema accordingly:
   short field names, quantized values (effective rate as integer basis
   points, market value in $10K units, not raw floats/dollars), and drop
   rarely-used fields from low zooms via `tippecanoe --exclude`. Full address
   string and rarely-needed fields only need to exist at high zoom tiles.
2. **Zoom-dependent generalization, computed at build time, not runtime.**
   Nobody can perceive 858K parcels at a citywide zoom, so the initial
   landing view (the highest-traffic, first-paint path) should never load
   raw parcel geometry:
   - Low zoom (city/borough): pre-aggregated hex or grid bins (e.g. H3 res
     7–8) with a precomputed average/weighted effective rate — a few
     thousand features, not 858K.
   - Mid zoom: simplified/coalesced parcel polygons
     (`--coalesce-densest-as-needed`, `--drop-densest-as-needed`).
   - High zoom (z14+): full per-parcel polygons with full property set.
   This means the first thing a visitor sees is small and fast, and detail
   only loads as they zoom in on a neighborhood — which is also the more
   useful reading experience.
3. **Verify the host supports HTTP range requests before committing to
   this architecture. VERIFIED 2026-07-30.** Both GitHub Pages proper
   (bare `*.github.io`, Fastly-backed origin) and `raw.githubusercontent.com`
   correctly return `HTTP/2 206` with an accurate `Content-Range` header on
   a real `Range` GET request against live files (confirmed directly, not
   just via docs — PMTiles' own hosting docs mention GitHub Pages only as
   an untested "if it fits, it's easy" option, so this needed independent
   verification). No CDN fronting needed for v1; GitHub Pages alone is
   sufficient. Only caveat: GitHub Pages' 1GB-per-repo soft limit and
   individual file limits (~100MB before Git warns/blocks a plain push) —
   the citywide tileset built at 103MB (see Milestone 2), just over the
   50MB LFS-recommended threshold; watch this if the tileset grows.

Other budget items:
- **JS payload**: keep initial bundle lean (plain Vite/TS, no React unless
  needed); lazy-load Observable Plot and the search index only when the
  scrollytelling section or search box is actually engaged, not on first
  paint.
- **Search index**: don't ship one 858K-row searchable blob upfront — lazy
  fetch it on first focus of the search box, and keep it to compact
  fields only (address string + BBL + centroid), gzip/brotli compressed.
- **Styling**: rely on MapLibre's data-driven (GPU-side) paint expressions
  for color-by-rate rather than per-feature JS loops.
- **Explicit budget to test against before calling v1 done**: Lighthouse
  Performance ≥ 90, first tiles painted < 1.5s on a throttled 4G profile,
  < 300KB gzipped JS before any user interaction. Add this as a gate in
  the milestones below, not just an afterthought.

## Site UX
1. Landing view: full NYC map, parcels colored by effective tax rate
   (sequential/diverging scale), sized or filtered by market value tier.
   Sale-verified (tier 1) and assessed-value-fallback (tier 2) parcels are
   visually distinguished (see Core metric) with a legend explaining the
   difference, not silently blended.
2. Click/hover a parcel → popup: address, tax class, market/sale value,
   assessed value, computed tax, effective rate, which tier it's based on
   (recent sale vs. DOF's own valuation, with sale date if applicable), plus
   a one-line "for scale" comparison (e.g., "pays a lower rate than 90% of
   Brooklyn co-ops").
3. Search by address/BBL (client-side fuzzy match against a lightweight
   index, e.g., MiniSearch, since there's no backend).
4. Borough / tax-class filter toggles.
5. Short scrollytelling intro up top (2–3 screens) walking through the
   Griffin penthouse example before dropping into the free-roam map.
6. Methodology footer: data vintage, computation formula, link to sources.

## Non-goals / scope fence
This is a small static site, not a platform — worth stating outright so the
agent doesn't spend budget building things nobody asked for:
- **No backend, no database, no API server.** Everything is static files +
  client-side JS. If a feature seems to need a server, the answer is to
  precompute it at build time instead, not to add one.
- **No generic/reusable data pipeline framework.** The pipeline is hardcoded
  to these specific NYC DOF/PLUTO datasets and this specific join. Don't
  build a configurable "plug in any city's open data" system.
- **One-time data snapshot for v1, not a live-refreshing pipeline.** Ship
  against a single fixed data vintage (documented in the methodology
  footer). A yearly-refresh workflow is a real future improvement, not part
  of this build — don't build scheduling/automation for it now.
- **No user accounts, saved views, or server-side personalization.** Filters
  and search state can live in URL params if convenient, nothing heavier.
- **No polygon-perfect cartography.** Simplified/generalized geometry per the
  performance strategy is the goal, not survey-grade parcel boundaries.

## Milestones
1. ✅ **DONE** — Data pipeline: build and debug against a small sample (one
   borough or a capped SoQL query) per the agent-workflow rules above, then
   run full-scale as a background script → fetch + join + compute effective
   rates → validated sample CSV (spot check against known examples like the
   CPS penthouse). See Status above and `pipeline/README.md`.
2. ✅ **DONE** — Tile build: GeoJSON → PMTiles with zoom-dependent
   generalization (lean schema, low-zoom aggregation) per the performance
   strategy above; hosting choice (GitHub Pages) confirmed to serve range
   requests correctly (see Performance strategy item 3). Source data:
   `data/cache/building_effective_rates.parquet` — needed geometry joined
   in. **PLUTO itself has no polygon geometry** (see corrected PLUTO entry
   in Data sources above); geometry comes from `TAX_LOT_POLYGON` + the
   condo billing-lot crosswalk instead (`pipeline/06_fetch_geometry.py`,
   `pipeline/07_join_geometry.py`), resolving 99.91% of buildings to
   geometry (99.87% real polygon, 0.04% point fallback; 0.09% have none).
   Tiled with `tippecanoe` (`pipeline/08_build_tileset.py`): lean/quantized
   schema (bbl, boro, unit count, market value in $10K units, tax in $100
   units, tier-1/tier-2 effective rate in basis points), z9–z16,
   `--coalesce-densest-as-needed`/`--drop-densest-as-needed`/
   `--extend-zooms-if-still-dropping` for automatic low-zoom thinning with
   full per-parcel detail preserved at z14+. Citywide output: 856,471
   features → `site/public/tiles/buildings.pmtiles` (103MB). One-borough
   (Manhattan) dev-sample tileset also built at `data/cache/dev_sample.pmtiles`
   (gitignored) for the agent's own fast iteration loop, per the
   agent-workflow rules. **Not built for v1** (noted as optional/stretch in
   Tech stack): H3-hex-bin pre-aggregation at low zoom — tippecanoe's
   built-in feature-dropping/coalescing does the zoom-dependent
   generalization job instead; revisit only if low-zoom density still looks
   bad once rendered (Milestone 3).
3. ✅ **DONE** — Map MVP: static color-by-rate map, no interactivity. See
   Status above for detail and the two build gotchas hit along the way.
4. ✅ **DONE** — Interactivity: popups (from tile properties, no extra
   fetch), lazy-loaded search, filters. See Status above for detail,
   including the tile-schema size fight and the search-index main-thread
   latency flagged as a known v1 limitation.
5. ✅ **DONE** — Narrative layer: scrollytelling intro + Observable Plot
   scatter (lazy loaded). See Status above for the pinned-live-map
   mechanic, the unit-lot-grain scatter-data bug caught before shipping,
   and the bundle-size fix.
6. ✅ **DONE** — Performance gate: Lighthouse + throttled-network pass
   against the budget above. See Status above and `PERFORMANCE.md` for full
   results, root-cause analysis, and the documented budget gap (JS size and
   first-tiles-painted are architectural, not bugs; shipped with the
   measured numbers per an explicit user decision).
7. ✅ **DONE** — Polish + deploy to GitHub Pages + methodology footer. See
   Status above for the deploy mechanism, the custom-domain URL, the
   real-CDN verification, and the search-popup bug found and fixed along
   the way.

## Risks / open questions
- **Tax paid is computed, not scraped** — must be labeled clearly to avoid
  looking like leaked bill data.
- **Sale-verified coverage is inherently partial** — most parcels don't sell
  in any given 10-year window, so the "real" tier-1 metric (see Core metric)
  won't cover the whole city. The map must make the tier-1/tier-2 split
  visually obvious rather than implying uniform confidence. Sparse tier-1
  coverage in a given neighborhood/tier is a real result to show, not a bug
  to hide.
- **Unit-lot vs. billing-lot join is more involved than a flat BBL join** —
  DOF taxes individual condo/co-op units on their own unit-lot (`boro`,
  `block`, `lot` in `8y4t-faws`), which must be joined to sales at the same
  granularity, then aggregated *up* to PLUTO's building-level `bbl` for map
  rendering (see Core metric's aggregation rule). Verified this works with
  real data (220 Central Park South), but the aggregation logic needs
  broader validation once the pipeline runs at scale — treat milestone 1 as
  iterative on this point, not one-and-done.
- **Parcel count / tile size** — ~858K NYC tax lots; addressed by the
  performance strategy above (zoom-dependent aggregation + lean tile
  schema), but the aggregation logic and quantization choices need real
  data to tune, so treat milestone 2 as iterative, not one-and-done.
- **Tax rate timing**: FY2027 assessed values already exist but FY2027's
  rate isn't adopted yet (see Data vintage) — resolved by pinning v1 to
  FY2026 throughout, not mixing vintages.
- **Annual refresh**: resolved as a non-goal for v1 (see Non-goals section)
  — one-time snapshot, revisit only if the site gets traction.

## Success criteria
A visitor can, within one click, see that a Central Park megamansion pays a
lower effective property tax rate than an outer-borough two-family home —
backed by a labeled, sourced, reproducible computation.
