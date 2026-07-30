# NYC Property Tax Disparity Map — 1-Pager

## The story
NYC's property tax system is famously regressive at the top: because co-ops and
condos are legally assessed as if they were rental buildings ("comparable
rental income" method) rather than on sale price, ultra-luxury condos are
often valued by DOF at a small fraction of what they actually sold for — while
modest single-family homes and co-ops are assessed much closer to market
value. Result: effective tax rates *fall* as property value rises at the very
top.

Concrete anchors to cite in the UI:
- Ken Griffin's $238M Central Park South penthouse: DOF market value ~$9.4M,
  effective rate ~0.22%.
- NYU Furman Center, *State of the City 2025*: for co-op/condo units sold in
  2025, DOF market value undershot actual sale price by a median of
  ~$850K (co-ops) / ~$806K (condos), while modest condos are comparatively
  overtaxed.

Site goal: let anyone search or click any NYC property and see, side by side,
its market value, DOF assessed value, computed property tax, and effective
tax rate — with a citywide map view that makes the "expensive = lower rate"
pattern visually obvious (e.g., color by effective rate, size/opacity by
market value).

## Data sources (all public, NYC Open Data / Socrata)
- **Property Valuation and Assessment Data** (dataset `yjxr-fw8i`, ~9.85M
  rows/40 cols, annual DOF roll) — market value, transitional/actual assessed
  value, exemption value, tax class, BBL. Primary source table.
- **PLUTO** (Dept. of City Planning + DOF) — parcel geometry join key (BBL),
  lot/building attributes, lat/lon centroids for geocoding.
- **DOF Digital Tax Map** / borough block-lot shapefiles — parcel polygons for
  true choropleth rendering (fallback: PLUTO centroids as points if polygon
  join is too heavy).
- **Annual property tax class rates** (published yearly by DOF/NYC Council,
  four numbers per fiscal year) — needed because *actual tax paid* is not
  bulk-published; it's computed as `(assessed value − exemptions) × class
  rate`. This is the same method ProPublica/NYT/Furman Center use. Flag
  this clearly in the site's methodology footer so it reads as "computed
  estimate," not scraped bill data.
- Stretch: NYC DOF property tax bill lookup (per-BBL, not bulk) to spot-check
  a sample of computed values against real bills.

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
  checks into the script (e.g., assert the Griffin penthouse BBL computes to
  ~0.22% effective rate) so it prints PASS/FAIL — the agent reads one line,
  not the underlying rows, to confirm correctness.
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
`effective_rate = computed_annual_tax / market_value` per BBL/year. Bucket by
tax class (1 = 1-3 family homes, 2 = co-ops/condos/rentals, 4 = commercial)
since the disparity is mainly a class-1-vs-class-2 story.

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
   this architecture.** PMTiles' entire performance story depends on the
   static host serving byte-range requests so the client only pulls the
   directory + relevant tile bytes, not the whole file. Confirm early
   whether GitHub Pages / raw.githubusercontent.com / GitHub Release assets
   honor `Range` headers reliably at the file sizes we'll produce; if not,
   front the `.pmtiles` file with a CDN that does (e.g. jsDelivr in front of
   a GitHub Release, or Cloudflare R2) rather than discovering this after
   the map ships slow.

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
2. Click/hover a parcel → popup: address, tax class, market value, assessed
   value, exemptions, computed tax, effective rate, plus a one-line
   "for scale" comparison (e.g., "pays a lower rate than 90% of Brooklyn
   co-ops").
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
1. Data pipeline: build and debug against a small sample (one borough or a
   capped SoQL query) per the agent-workflow rules above, then run full-scale
   as a background script → fetch + join + compute effective rates →
   validated sample CSV (spot check against known examples like the CPS
   penthouse).
2. Tile build: GeoJSON → PMTiles with zoom-dependent generalization (lean
   schema, low-zoom aggregation) per the performance strategy above; confirm
   the hosting choice actually serves range requests.
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
- **Parcel count / tile size** — ~858K NYC tax lots; addressed by the
  performance strategy above (zoom-dependent aggregation + lean tile
  schema), but the aggregation logic and quantization choices need real
  data to tune, so treat milestone 2 as iterative, not one-and-done.
- **Geometry join**: PLUTO BBL ↔ DOF valuation BBL join should be clean, but
  verify vintage-year alignment (roll year vs. PLUTO version).
- **Annual refresh**: resolved as a non-goal for v1 (see Non-goals section)
  — one-time snapshot, revisit only if the site gets traction.

## Success criteria
A visitor can, within one click, see that a Central Park megamansion pays a
lower effective property tax rate than an outer-borough two-family home —
backed by a labeled, sourced, reproducible computation.
