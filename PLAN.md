# NYC Property Tax Disparity Map — 1-Pager

## Status (updated 2026-07-30)
- **Repo**: `nlicalzi/nyc-tax-disparity-map` (private), pushed to `main`.
- **Environment**: Python venv at `.venv/` (duckdb, pandas, pyarrow, requests,
  python-dotenv installed). `duckdb`, `tippecanoe`, `ogr2ogr` installed via
  Homebrew. Socrata app token in `.env` as `SOCRATA_APP_TOKEN` (gitignored;
  `set -a; source .env; set +a` before running fetch scripts).
- **Milestone 1 (data pipeline): DONE.** `pipeline/01`–`05` run end-to-end,
  full citywide scale (1,164,670 unit rows, 857,253 building rows), see
  `pipeline/README.md` for the run order. Validated: Griffin penthouse
  computes to 0.35% effective rate against its real sale (script-asserted),
  and the "expensive = lower rate" pattern holds citywide by sale-price
  decile for class 1 and class 2, not just as an anecdote. Outputs live in
  `data/cache/*.parquet` (gitignored — re-run pipeline to regenerate, ~15 min
  full citywide fetch + a few min compute).
- **Milestone 2 (tile build): DONE.** `pipeline/06`–`08` fetch real parcel
  geometry (PLUTO has none — see corrected Data sources), join it to
  `building_effective_rates.parquet`, and build the PMTiles tileset. Output:
  `site/public/tiles/buildings.pmtiles` (856,471 features, 103MB, z9–z16).
  GitHub Pages verified to correctly serve HTTP range requests. See
  Milestones below for full detail and what's explicitly deferred (H3
  low-zoom binning).
- **Next up: Milestone 3** (map MVP — static color-by-rate map, no
  interactivity). Not started.
- Work style: check in with the user after each milestone before proceeding
  to the next (their stated preference) — don't auto-continue through
  milestones 3–7 without a pause.

## The story
NYC's property tax system is famously regressive at the top: because co-ops and
condos are legally assessed as if they were rental buildings ("comparable
rental income" method) rather than on sale price, ultra-luxury condos are
often valued by DOF at a small fraction of what they actually sold for — while
modest single-family homes and co-ops are assessed much closer to market
value. Result: effective tax rates *fall* as property value rises at the very
top.

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
3. Map MVP: static color-by-rate map, no interactivity.
4. Interactivity: popups (from tile properties, no extra fetch), lazy-loaded
   search, filters.
5. Narrative layer: scrollytelling intro + Observable Plot scatter (lazy
   loaded).
6. Performance gate: Lighthouse + throttled-network pass against the budget
   above; fix before calling it done, not after.
7. Polish + deploy to GitHub Pages + README with methodology.

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
