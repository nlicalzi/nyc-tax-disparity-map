# Pipeline

Run in order. Each step reads/writes `data/cache/*.parquet` (gitignored --
re-run to regenerate, don't hand-edit).

```
set -a; source .env; set +a   # loads SOCRATA_APP_TOKEN

.venv/bin/python pipeline/01_fetch_valuation.py   # DOF valuation roll, FY2026 final (8y4t-faws)
.venv/bin/python pipeline/02_fetch_sales.py        # NYC sales 2016-2025 (w2pb-icbu)
.venv/bin/python pipeline/03_fetch_pluto.py        # PLUTO parcel/geometry base (64uk-42ks)
.venv/bin/python pipeline/04_build_effective_rates.py  # join + compute two-tier effective rate
.venv/bin/python pipeline/05_validate.py           # PASS/FAIL checks + summary stats
.venv/bin/python pipeline/06_fetch_geometry.py     # real parcel polygons (i38t-6if2 + condo crosswalk p8u6-a6it)
.venv/bin/python pipeline/07_join_geometry.py      # join geometry onto building_effective_rates
.venv/bin/python pipeline/08_build_tileset.py      # lean-schema GeoJSON -> tippecanoe -> PMTiles
```

Add `--sample` to 01/02/03/06/08 to pull/build Manhattan only, for fast iteration.
`08 --sample` writes a dev-only tileset to `data/cache/dev_sample.pmtiles`
and a matching search index to `site/public/search-index-sample.json.gz`
(both gitignored) instead of the production path, for the agent's own
browser testing loop -- never point iterative dev checks at the full
citywide tileset. `npm run dev` serves the tileset from
`site/public/tiles/dev-sample.pmtiles`, a **separate copy** the build
script does not write directly -- after every `08 --sample` run, copy it
over by hand:
```
cp data/cache/dev_sample.pmtiles site/public/tiles/dev-sample.pmtiles
```
(Bit during milestone 4: the dev server silently kept serving a stale
tileset with the old schema for several rebuilds because this copy step is
easy to forget -- if a dev-loop check shows fields/behavior that don't
match a just-edited pipeline script, check this first.)

See PLAN.md's "Data sources" / "Core metric" sections for why the metric is
two-tier (sale-verified vs. DOF-value fallback) and how the condo unit-lot
to PLUTO building-lot aggregation works.

## Outputs

- `data/cache/unit_effective_rates.parquet` -- one row per DOF unit-lot, the
  validated core computation.
- `data/cache/building_effective_rates.parquet` -- aggregated to PLUTO `bbl`
  grain, for map rendering (milestone 2+).
- `data/cache/tax_lot_polygon.parquet` / `condo_crosswalk.parquet` -- real
  parcel geometry sources (PLUTO itself has none -- see PLAN.md's Data
  sources section).
- `data/cache/buildings_geom.parquet` -- `building_effective_rates` joined
  to real parcel geometry as WKB (99.87% real polygon, 0.04% point
  fallback, 0.09% missing). Kept as parquet (not GeoJSON) for fast
  re-reads -- GDAL-driver GeoJSON reads of a 600MB+ file were too slow for
  iterative debugging (a single indexed lookup took >15min).
- `site/public/tiles/buildings.pmtiles` -- the production citywide vector
  tileset (856,471 features, z9-z16, lean/quantized schema). Committed to
  the repo (103MB, under GitHub's 100MB hard limit but past the 50MB LFS
  warning threshold -- watch this if the tileset grows).
- `data/cache/dev_sample.pmtiles` -- Manhattan-only tileset for the agent's
  own dev-loop browser checks (gitignored, never committed).
- `site/public/scatter-sample.json.gz` -- milestone 5's narrative-layer
  scatter chart data: a deterministic, capped (4,000 per class) sample of
  tier-1 (sale-verified) tax class 1/2 unit-lots (sale price, effective
  rate), Ken Griffin's own unit-lot always force-included. Unit-lot grain,
  not building grain -- see `08_build_tileset.py`'s `build_scatter_sample`
  docstring for why. `-dev` variant (gitignored) is the Manhattan-only
  counterpart, same pattern as `search-index-sample.json.gz`.
