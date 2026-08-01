# Performance gate: results and gap analysis (Milestone 6)

Tested against the citywide production build (`npm run build && npm run
preview`) per PLAN.md's Performance strategy budget:

| Budget | Target | Measured | Status |
|---|---|---|---|
| Lighthouse Performance | ≥ 90 | **97** | ✅ Pass |
| JS gzipped before interaction | < 300 KB | **381.5 KB** | ❌ Over by ~82KB |
| First tiles painted, throttled 4G | < 1.5 s | **8.5 s** (Lighthouse's own Slow-4G profile, real CDP throttle) / **3.1 s** (a more typical regular-4G profile) | ❌ Over in both cases |

Methodology: Lighthouse run with `--only-categories=performance` against
`localhost:4173` (mobile emulation, its default "simulate" throttling
method). Separately, a Playwright/CDP script drives an *actual* throttled
connection (not simulated) and polls a `performance.mark("first-tiles-painted")`
set in `main.ts` the moment the buildings vector source finishes loading its
initial-viewport tiles — this is what "first tiles painted" means concretely
in this doc. Two network profiles were tested: Lighthouse's own default
mobile throttle (150ms RTT / 1.6Mbps down — deliberately pessimistic, often
called "Slow 4G"), and a more typical "regular 4G" (20ms RTT / 4Mbps down).
Script: `site/scripts/check-throttled-perf.mjs --profile=slow4g|regular4g
[--trace]` (against a running `npm run preview` server; `--trace` prints a
full per-request network timeline, useful for diagnosing what's actually
serializing).

## Fixes already shipped (real wins, no tradeoffs)

1. **Lazy-load the hidden tier2 layers.** MapLibre builds GL buckets/buffers
   for a layer regardless of `visibility: "none"` — hiding is a render-time
   switch, not a tile-processing one. `fill-tier2`/`fill-tier2-hatch`/
   `circle-tier2` (hidden by default since Milestone 3, covering ~73% of all
   buildings — the majority of the dataset) were paying full bucket-build
   cost on every load for something invisible on first paint. Deferred to
   `ensureTier2Layers()` in `main.ts`, called only when the legend checkbox
   is switched on. **Total Blocking Time: 2690ms → 20ms. Lighthouse score: 63
   → 97.**
2. **`map.on('load')` → `map.on('style.load')`.** `load` fires only after
   the basemap's own first visually-complete render — needlessly
   serializing our own buildings-tile fetch behind a live third-party
   basemap's full readiness instead of starting both in parallel.
3. **`<link rel="preconnect">` to `tiles.openfreemap.org`.** Removes one
   DNS+TCP+TLS round trip from the critical path. Cut the Slow-4G
   first-tiles-painted number from 10.1s → 8.5s.

These are committed and don't trade off against anything — safe to keep
regardless of what happens with the remaining gap.

4. **Decoupled the app's own interactivity from the basemap's network
   fetch.** The `Map` constructor was passed the OpenFreeMap style as a URL
   string, which forces MapLibre to fetch+parse that remote style JSON
   before `style.load` fires — and *every* `addLayer` call plus all
   click/search/filter/legend/story wiring lived inside that one
   `style.load` callback (see `main.ts`'s prior comment on `load` vs
   `style.load`, which addressed serialization against the basemap's own
   *tiles* but missed that the *style JSON itself* was still a blocking
   network dependency for a third-party host). A first-time visitor's
   entire app — not just the basemap — was gated behind that fetch, for no
   real reason: none of the interactivity code touches basemap state.
   Fixed by constructing the map with a minimal inline placeholder style
   (a flat background color, no network fetch), so `style.load` now fires
   on the next tick; the real OpenFreeMap style is fetched independently by
   a new `loadBasemap()` and its sources/layers are spliced in underneath
   the app's own layers once it resolves (via `beforeId`, since
   `fill-nodata` — the app's bottom layer — is guaranteed to already exist
   by the time that fetch's `.then()` runs). Purely additive: if the
   basemap fetch is slow or fails, the app is already fully usable against
   the plain background. Measured under the same throttled-4G CDP profile
   used elsewhere in this doc (`npm run build && npm run preview`, 3 runs
   each, median reported): time until the filter chips are interactive
   dropped from **~2020ms → ~1785ms** (removes the openfreemap style-JSON
   round trip from that critical path). Does **not** move the "first tiles
   painted" numbers in the table above — those are bandwidth-contention-
   bound against the basemap's ~900KB of tile data (see below), which this
   change doesn't touch; it fixes a real but separate blocking dependency
   (interactivity wiring), not the tile-payload race.

## Why the remaining two numbers are architectural, not bugs

Both trace back to two decisions made in Milestone 3, before either number
was measured against a real build:

**1. MapLibre GL JS as the rendering engine.** The official v6.1.0
distribution is ~380KB gzip minimum before any of our own code or data:
a ~252KB main-thread bundle plus a ~133KB worker-side "shared" chunk
(vector-tile parsing/bucket-building logic, vendored verbatim per
Milestone 3's notes since Vite can't resolve MapLibre's own
`import.meta.url`-relative worker loading). Both are required before the
map can render anything at all. It's not tree-shakeable — `dist/maplibre-gl.mjs`
ships as one pre-bundled file, so importing only `Map`/`Popup`/
`NavigationControl` still pulls in the whole library. Max-quality Brotli
only gets the pair down to ~316KB. Our own app code (`main.ts` +
`popup.ts`/`filters.ts`/`legend.ts`/`colors.ts`/`format.ts`/`search.ts`/
`story.ts`/`gzip-fetch.ts`, ~1200 lines) is a rounding error against this —
there's no realistic amount of *our* code to cut that closes an 82KB gap
whose source is the library itself.

**2. A live, un-self-hosted, full-featured basemap** (OpenFreeMap
"positron"). On a cold load this pulls in, from a third-party host, on the
same throttled connection as everything else:
- style JSON + a retina sprite atlas (~120KB) + font glyph ranges (~90KB
  combined for the two weights actually used)
- ~900KB of vector tile data for the ~6 tiles covering NYC at the initial
  citywide zoom

Critically, **OpenFreeMap serves one shared "planet" vector tileset across
all of its named styles** (positron/bright/liberty/dark/fiord/3D) — the
~900KB of tile bytes is fixed by the *data*, not the style, so switching to
a different named style or hand-editing one in Maputnik (their supported
customization path) would only trim the sprite/font portion (~210KB), not
the dominant 900KB of tile data. At 1.6Mbps throttled bandwidth, ~1.4MB of
combined basemap + our-own-JS payload before first paint is arithmetically
incompatible with a 1.5s budget — 300KB is roughly the ceiling of what *any*
transfer can move in 1.5s at that throughput, before our own JS payload
even starts downloading.

(Aside: Lighthouse's own FCP/LCP numbers looked fine — 2.1s — because its
default "simulate" throttling method mathematically estimates network delay
from an unthrottled trace rather than literally replaying a slow
connection. The CDP-throttled pass this milestone specifically asked for is
what surfaced the real gap; this is exactly why the milestone brief wanted
both checks, not just Lighthouse.)

## Roadmap to actually close the gap

Ordered by impact, with a rough honest effort/risk estimate for each. None
of these are scheduled — this is the reference for a future decision, not a
committed plan.

### Phase 1 — Self-host a minimal custom basemap style (moderate effort, some visual risk)
Use Maputnik to hand-build a stripped style against OpenFreeMap's tile
source: drop the sprite reference (no POI icons) and drop text-label layers
at low zoom (no font glyph fetch). Saves the ~210KB sprite+font chunk.
**Does not touch the ~900KB of vector tile bytes** (shared tileset, see
above) or the ~380KB MapLibre JS floor — closes maybe 15% of the total gap.
Visual risk: positron's labels were presumably chosen for legibility while
navigating; a label-free basemap changes that experience and would need a
design check-in, not a unilateral change.

### Phase 2 — Replace the live vector basemap with lightweight self-hosted raster tiles (larger effort)
The basemap here only needs to look reasonable as a backdrop under our own
building fills — it doesn't need to be independently interactive/stylable.
A small set of pre-rendered, low-zoom raster tiles (PNG/WebP, muted
grayscale) served from the same host as the rest of the site would likely
be well under 900KB total for the initial view, removes the third-party
dependency and its RTT entirely, and is cacheable indefinitely (no daily
planet-data refresh to track). Requires standing up a one-time raster tile
generation step in the pipeline (similar shape to the existing PMTiles
build) and losing basemap zoom/pan flexibility beyond whatever zoom range
gets pre-rendered.

### Phase 3 — Replace MapLibre GL JS with a lighter custom renderer for our own layer (largest effort, highest risk)
The ~380KB MapLibre floor is the single biggest lever and the only one of
these three that meaningfully attacks the JS-size budget specifically. Our
own data layer is comparatively simple (fills/circles by feature property,
filtered/colored via a handful of MapLibre expressions) — in principle
replaceable with a much smaller custom Canvas2D or minimal-WebGL renderer
reading PMTiles directly, at the cost of losing MapLibre's GPU-side
data-driven styling, hit-testing, and pan/zoom/projection handling for
free. This is effectively redoing the rendering core of Milestones 3-5, not
a performance-gate task — flagged here as the real ceiling-breaker, not a
recommendation to do it now.

### Lower-effort partial mitigations (don't close the gap alone, but stack with any of the above)
- ~~Preload/priority hints on our own `buildings.pmtiles` header request so
  it wins contention against basemap tiles under a shared throttled pipe.~~
  — **tried, measured a regression, reverted.** A `<link rel="preload"
  as="fetch">` can't carry a `Range` header (no HTML attribute for it), so
  it triggers a full, unranged GET of the whole 71MB file. The pmtiles JS
  library's own real request is always a targeted `Range: bytes=0-16383`
  (see `getBytes(0, 16384)` in `node_modules/pmtiles/dist/pmtiles.js`) —
  different request signature, so the browser doesn't coalesce the two; the
  preload's full-file download just runs alongside everything else,
  competing for bandwidth. Measured under the same throttled-4G CDP trace
  used elsewhere in this doc: the main JS bundle's own download time nearly
  doubled (**1617ms → 2820ms**) with the preload in place, and the
  `buildings.pmtiles` request it was meant to help ended up `ERR_ABORTED`.
  Reverted in `index.html`. A PMTiles source (single large file, accessed
  entirely via HTTP Range requests) isn't a good fit for static-HTML
  preload at all — there's no way to hint "just the header" without
  duplicating pmtiles-js's own Range-matching logic in an inline script,
  which is fragile enough (relies on the browser's HTTP cache reusing a
  partial-content response across two independently-issued requests) that
  it isn't worth the complexity for what's likely a small win.
- ~~Serve the vendored `maplibre-gl-shared.mjs` worker chunk with a long
  `Cache-Control`~~ — **checked, not achievable on GitHub Pages as chosen in
  PLAN.md's Hosting section.** Confirmed directly (`curl -I` against a live
  `*.github.io` file): GitHub Pages' Fastly-backed origin sends
  `Cache-Control: max-age=600` on every response — 10 minutes, not
  configurable per-file or per-repo. Unlike Netlify/Vercel, GitHub Pages has
  no `_headers`-file (or equivalent) convention, so there's no way to raise
  this from a repo change alone. The only real path to a long-lived cache
  here would be fronting GitHub Pages with a CDN that allows custom headers
  (e.g. Cloudflare), or moving hosts entirely — both are hosting-strategy
  decisions, not something to slip in as a drive-by fix; flagging here
  rather than implementing something that silently wouldn't work.
- ~~Re-test on GitHub Pages' actual Fastly-backed CDN once deployed
  (Milestone 7)~~ — **done, no win available.** `curl` against the live
  deployed main JS chunk with `Accept-Encoding: br, gzip` gets back
  `content-encoding: gzip` — GitHub Pages' Fastly origin does not serve
  Brotli even when the client advertises support, so the ~316KB
  max-quality-Brotli number cited above isn't achievable on this host. Also
  re-ran `check-throttled-perf.mjs --url=<live site>` against the real
  deployment: first-tiles-painted came back 3.9s (regular4g) / 9.3s
  (slow4g) — slightly worse than the localhost numbers in the table above
  (3.1s / 8.5s), consistent with added real-internet RTT/DNS/TLS on top of
  the same architectural bottleneck, not a new regression.

## Recommendation

Given the effort/risk of Phases 1-3 relative to where this project is
(pre-launch, v1 snapshot per PLAN.md's own non-goals), the pragmatic path is
to ship with the numbers in the table above, documented in the site's
methodology footer and here, rather than block launch on a rendering-stack
rewrite. Revisit if/when the site gets traffic and real-world performance
data (not just synthetic throttled tests) shows this is actually costing
users.
