"""Build the PMTiles vector tileset from buildings_geom.parquet.

Per PLAN.md's Performance strategy:
  1. Lean tile schema -- short field names, quantized values (effective
     rate as integer basis points, market value in $10K units) so
     click-for-detail (queryRenderedFeatures) never needs an extra fetch.
     Per-building detail fields (address, sale price/date, "for scale"
     percentile) only ship at the single highest zoom level (DETAIL_ZOOM),
     not every zoom -- below that, tippecanoe's --coalesce-densest-as-needed
     merges multiple buildings into one representative feature anyway, so a
     single building's address/sale wouldn't mean anything there. Each zoom
     level of the pyramid stores its own near-full copy of the feature set,
     so shipping these fields at every "high" zoom is expensive multiplied
     by however many levels count as high -- confirmed empirically during
     milestone 4, where shipping them across 3 levels (z14-16) rather than
     1 pushed the citywide tileset from a 103MB baseline to 111-129MB
     depending on exactly which fields were spread across how many levels,
     over GitHub's 100MB hard push limit. Restricting detail fields (and
     the whole tileset's native max zoom) to one level -- MapLibre's own
     maxZoom in main.ts is higher and just overzooms past it -- brought
     the citywide build back under budget. Built as two tippecanoe passes
     (lean overview band + single full-detail zoom), merged with tile-join,
     since tippecanoe has no single-invocation per-zoom field filter.
  2. Zoom-dependent generalization computed at build time: tippecanoe's
     --coalesce-densest-as-needed / --drop-densest-as-needed /
     --extend-zooms-if-still-dropping automatically thin/merge dense areas
     at low zoom while preserving full per-parcel detail at high zoom.
     (H3-hex-bin pre-aggregation at low zoom, mentioned as an option in
     PLAN.md's Tech stack section, is explicitly called out there as
     optional/stretch -- not built here; tippecanoe's built-in feature
     dropping/coalescing is the v1 mechanism.)

Also emits the citywide search index (bbl, address, borough, centroid),
gzip-compressed per PLAN.md's Performance strategy search-index bullet --
site/public/search-index.json.gz, lazy-fetched + decompressed client-side
(DecompressionStream) on first search-box focus, never on first paint.

And (milestone 5) a scatter-sample dataset for the narrative layer's
Observable Plot "smoking gun" chart -- a deterministic, capped per-class
sample of tier-1 (sale-verified) class 1/2 buildings (sale price, effective
rate), Griffin's building force-included, gzip-compressed and lazy-fetched
the same way as the search index (site/src/scatter.ts), never on first
paint.

Two sets of outputs (tileset + search index + scatter sample):
  - Citywide production: site/public/tiles/buildings.pmtiles,
    site/public/search-index.json.gz, site/public/scatter-sample.json.gz
  - One-borough (Manhattan) dev-sample for the agent's own fast iteration
    loop, per the agent-workflow rules: data/cache/dev_sample.pmtiles,
    site/public/search-index-sample.json.gz,
    site/public/scatter-sample-dev.json.gz (all gitignored, never
    committed)

Usage:
    .venv/bin/python pipeline/08_build_tileset.py --sample   # Manhattan dev sample
    .venv/bin/python pipeline/08_build_tileset.py            # full citywide
"""
import argparse
import gzip
import json
import os
import subprocess

import duckdb

ROOT = os.path.join(os.path.dirname(__file__), "..")
CACHE = os.path.join(ROOT, "data", "cache")
SITE_PUBLIC_DIR = os.path.join(ROOT, "site", "public")
TILES_DIR = os.path.join(SITE_PUBLIC_DIR, "tiles")

MIN_ZOOM = 9
DETAIL_ZOOM = 15  # per-building popup detail (addr/sale/saledt/pctl) exists only at this single zoom
# MapLibre's own maxZoom (see main.ts) is 18, higher than this -- it just
# overzooms this tile past MAX_ZOOM rather than paying for a whole extra
# full-resolution pyramid level. See module docstring for the size math.
MAX_ZOOM = 15

# Griffin's individual unit-lot (not the building's PLUTO billing bbl) --
# see pipeline/05_validate.py. Deliberately unit-level, not building-level:
# building_effective_rate_tier1 (buildings_geom.parquet) aggregates a
# building's tier1_sale_basis as the SUM of every unit that sold 2016-2025 --
# for 220 Central Park South that's a combined $4.1B across 116 units (see
# popup.ts's nsale handling), not Griffin's own $239,958,219 sale. Plotting
# that aggregate would misrepresent the exact anchor numbers PLAN.md's "The
# story" section validates and cites. Unit-level also matches the Furman
# Center methodology PLAN.md itself cites ("for co-op/condo UNITS sold in
# 2025, DOF market value undershot...").
GRIFFIN_UNIT_BORO = "1"
GRIFFIN_UNIT_BLOCK = "1030"
GRIFFIN_UNIT_LOT = "1082"

# Milestone 5 scatter (site/src/scatter.ts): a deterministic per-class sample
# of tier-1 (sale-verified) unit-lots, capped well below the ~349K full
# tier-1 population so an SVG scatter renders smoothly client-side. Only
# tax classes 1 and 2, per PLAN.md's Core metric ("the disparity is mainly a
# class-1-vs-class-2 story") -- also keeps the chart's categorical legend to
# two validated slots (blue/green) instead of needing a 3rd/4th "other"
# bucket. hash() ordering (not TABLESAMPLE) keeps the sample reproducible
# across re-runs without needing to persist a seed anywhere.
SCATTER_SAMPLE_CAP_PER_CLASS = 4000

# unit_effective_rates.parquet's own boro is the DOF numeric code ("1".."5"),
# not PLUTO's 2-letter code -- same mapping as 04_build_effective_rates.py's
# BORO_CODE_TO_PLUTO, duplicated here since this script never reads that
# module (each pipeline step is a standalone script per PLAN.md's workflow
# rules).
UNIT_BORO_CASE_SQL = """
    CASE boro
        WHEN '1' THEN 'MN' WHEN '2' THEN 'BX' WHEN '3' THEN 'BK'
        WHEN '4' THEN 'QN' WHEN '5' THEN 'SI' ELSE NULL END
"""


def build_scatter_sample(con: duckdb.DuckDBPyConnection, out_path: str, sample: bool) -> int:
    """Compact scatter-plot dataset for the narrative layer's "smoking gun"
    chart: sale-verified value vs. effective rate, tax class 1 vs. 2,
    unit-lot grain (see GRIFFIN_UNIT_* comment above for why). Same
    array-of-arrays + gzip approach as build_search_index -- lazy-fetched by
    site/src/scatter.ts only once the story's chart step is reached, never
    part of the initial JS payload. Reads unit_effective_rates.parquet
    directly (pipeline/04's output), not buildings_geom.parquet -- this is
    the one dataset build step in 08 that doesn't need geometry."""
    unit_parquet = os.path.join(CACHE, "unit_effective_rates.parquet")
    boro_where = "AND boro = '1'" if sample else ""
    rows = []
    for cls in ("1", "2"):
        rows.extend(
            con.sql(f"""
                SELECT
                    boro || '-' || block || '-' || lot AS unit_key,
                    CAST(ROUND(sale_price / 1000) AS INTEGER) AS sale_k,
                    CAST(ROUND(effective_rate * 10000) AS INTEGER) AS rate_bp,
                    class_prefix AS cls,
                    {UNIT_BORO_CASE_SQL} AS boro_2letter
                FROM read_parquet('{unit_parquet}')
                WHERE class_prefix = '{cls}' AND tier = 1
                  {boro_where}
                ORDER BY hash(boro || block || lot)
                LIMIT {SCATTER_SAMPLE_CAP_PER_CLASS}
            """).fetchall()
        )
    # Force-include Griffin's unit regardless of the hash sample -- the
    # narrative's anchor anecdote must always be plottable, not left to luck.
    if not any(r[0] == f"{GRIFFIN_UNIT_BORO}-{GRIFFIN_UNIT_BLOCK}-{GRIFFIN_UNIT_LOT}" for r in rows):
        griffin = con.sql(f"""
            SELECT
                boro || '-' || block || '-' || lot AS unit_key,
                CAST(ROUND(sale_price / 1000) AS INTEGER) AS sale_k,
                CAST(ROUND(effective_rate * 10000) AS INTEGER) AS rate_bp,
                class_prefix AS cls,
                {UNIT_BORO_CASE_SQL} AS boro_2letter
            FROM read_parquet('{unit_parquet}')
            WHERE boro = '{GRIFFIN_UNIT_BORO}' AND block = '{GRIFFIN_UNIT_BLOCK}' AND lot = '{GRIFFIN_UNIT_LOT}'
        """).fetchall()
        rows.extend(griffin)
    with gzip.open(out_path, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump([list(row) for row in rows], f, separators=(",", ":"))
    return len(rows)


# Per-building fields that only mean something for a single, uncoalesced
# building (see module docstring): a coalesced multi-building blob has no
# one address or sale to report. Restricted to a single top zoom, not a
# multi-level band -- each level of the zoom pyramid stores its own
# near-full copy of the feature set, and these fields (address especially:
# a unique string per building, none of which dedupe against each other)
# don't get cheaper just because they're "detail." Confirmed empirically
# during milestone 4: shipping this set across 3 zoom levels rather than 1
# alone pushed the citywide tileset from 103MB to 111-129MB depending on
# which fields were included, uncomfortably close to (or over) GitHub's
# 100MB push limit; restricting to z16 only brought it back under.
DETAIL_FIELDS = ["addr", "sale", "saledt", "pctl", "nsale"]


def build_lean_geojson(con: duckdb.DuckDBPyConnection, out_path: str, sample: bool) -> int:
    where = "WHERE boro = '1'" if sample else ""
    sql = f"""
        COPY (
            SELECT
                pluto_bbl AS bbl,
                pluto_borough_2letter AS boro,
                unit_count AS units,
                CAST(ROUND(building_dof_market_value / 10000) AS INTEGER) AS mkt,
                CAST(ROUND(building_tax / 100) AS INTEGER) AS tax,
                CASE WHEN building_effective_rate_tier1 IS NOT NULL
                     THEN CAST(ROUND(building_effective_rate_tier1 * 10000) AS INTEGER)
                     ELSE NULL END AS r1,
                CASE WHEN building_effective_rate_tier2 IS NOT NULL
                     THEN CAST(ROUND(building_effective_rate_tier2 * 10000) AS INTEGER)
                     ELSE NULL END AS r2,
                CASE WHEN building_effective_rate_tier1 IS NOT NULL THEN 1 ELSE 0 END AS t1,
                tax_class AS cls,
                address AS addr,
                CASE WHEN building_effective_rate_tier1 IS NOT NULL
                     THEN CAST(ROUND(tier1_sale_basis / 10000) AS INTEGER)
                     ELSE NULL END AS sale,
                CASE WHEN building_effective_rate_tier1 IS NOT NULL
                     THEN LEFT(tier1_last_sale_date, 10)
                     ELSE NULL END AS saledt,
                CAST(tier1_pctile_pays_less_than AS INTEGER) AS pctl,
                CASE WHEN building_effective_rate_tier1 IS NOT NULL
                     THEN tier1_unit_count
                     ELSE NULL END AS nsale,
                ST_GeomFromWKB(geom_wkb) AS geom
            FROM read_parquet('{CACHE}/buildings_geom.parquet')
            {where}
        ) TO '{out_path}' WITH (FORMAT GDAL, DRIVER 'GeoJSON')
    """
    con.execute(sql)
    n = con.sql(f"""
        SELECT COUNT(*) FROM read_parquet('{CACHE}/buildings_geom.parquet') {where}
    """).fetchone()[0]
    return n


def build_search_index(con: duckdb.DuckDBPyConnection, out_path: str, sample: bool) -> int:
    """Compact citywide search index (bbl, address, borough, centroid) --
    lazy-fetched + gunzipped client-side on first search-box focus, never
    bundled into the initial JS payload (see PLAN.md Performance strategy's
    search-index item, which explicitly calls for gzip/brotli compression).
    Array-of-arrays, not array-of-objects -- skips repeating "bbl"/"addr"/
    etc. as a JSON key on every one of 856K rows. Buildings without an
    address aren't searchable by anything useful, so they're skipped."""
    where = "WHERE boro = '1' AND address IS NOT NULL" if sample else "WHERE address IS NOT NULL"
    rows = con.sql(f"""
        SELECT
            pluto_bbl AS bbl,
            address AS addr,
            pluto_borough_2letter AS boro,
            ROUND(ST_X(ST_Centroid(ST_GeomFromWKB(geom_wkb))), 5) AS lon,
            ROUND(ST_Y(ST_Centroid(ST_GeomFromWKB(geom_wkb))), 5) AS lat
        FROM read_parquet('{CACHE}/buildings_geom.parquet')
        {where}
    """).fetchall()
    with gzip.open(out_path, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump([list(row) for row in rows], f, separators=(",", ":"))
    return len(rows)


def run(cmd: list[str]):
    print("  $ " + " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-4000:])
        print(result.stderr[-4000:])
        raise SystemExit(f"command failed (exit {result.returncode}): {' '.join(cmd)}")
    # tail of stderr only -- tippecanoe prints its summary stats there
    tail = "\n".join(result.stderr.strip().splitlines()[-15:])
    if tail:
        print(tail)


def tippecanoe_pass(
    geojson_path: str,
    out_mbtiles: str,
    layer_name: str,
    min_zoom: int,
    max_zoom: int,
    exclude_fields: list[str],
    extend_zooms: bool,
):
    cmd = [
        "tippecanoe",
        f"--output={out_mbtiles}",
        f"--layer={layer_name}",
        f"--minimum-zoom={min_zoom}",
        f"--maximum-zoom={max_zoom}",
        "--coalesce-densest-as-needed",
        "--drop-densest-as-needed",
        "--name=NYC building effective tax rates",
        "--description=Per-building computed effective property tax rate, PLUTO/DOF join",
        "--force",
        "--no-progress-indicator",
    ]
    if extend_zooms:
        cmd.append("--extend-zooms-if-still-dropping")
    for field in exclude_fields:
        cmd.append(f"--exclude={field}")
    cmd.append(geojson_path)
    run(cmd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="Manhattan-only dev-sample tileset")
    args = parser.parse_args()

    con = duckdb.connect()
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")

    prefix = "dev_sample" if args.sample else "buildings"
    if args.sample:
        geojson_path = os.path.join(CACHE, "tileset_source_sample.geojson")
        mbtiles_path = os.path.join(CACHE, "dev_sample.mbtiles")
        pmtiles_path = os.path.join(CACHE, "dev_sample.pmtiles")
        search_index_path = os.path.join(SITE_PUBLIC_DIR, "search-index-sample.json.gz")
        scatter_sample_path = os.path.join(SITE_PUBLIC_DIR, "scatter-sample-dev.json.gz")
    else:
        geojson_path = os.path.join(CACHE, "tileset_source.geojson")
        mbtiles_path = os.path.join(CACHE, "buildings.mbtiles")
        os.makedirs(TILES_DIR, exist_ok=True)
        pmtiles_path = os.path.join(TILES_DIR, "buildings.pmtiles")
        search_index_path = os.path.join(SITE_PUBLIC_DIR, "search-index.json.gz")
        scatter_sample_path = os.path.join(SITE_PUBLIC_DIR, "scatter-sample.json.gz")
    layer_name = "buildings"

    # Two zoom bands, each its own tippecanoe pass, merged with tile-join --
    # see DETAIL_FIELDS above for why the split sits at a single top zoom.
    bands = [
        ("overview", MIN_ZOOM, DETAIL_ZOOM - 1, DETAIL_FIELDS, False),
        ("detail", DETAIL_ZOOM, MAX_ZOOM, [], True),
    ]
    band_mbtiles = [os.path.join(CACHE, f"{prefix}_{name}.mbtiles") for name, *_ in bands]

    for p in (geojson_path, mbtiles_path, pmtiles_path, search_index_path, scatter_sample_path, *band_mbtiles):
        if os.path.exists(p):
            os.remove(p)

    print(f"Building lean-schema GeoJSON ({'Manhattan sample' if args.sample else 'citywide'})...")
    n = build_lean_geojson(con, geojson_path, args.sample)
    geojson_mb = os.path.getsize(geojson_path) / 1e6
    print(f"  {n} features -> {geojson_path} ({geojson_mb:.1f} MB)")

    for (name, zmin, zmax, exclude_fields, extend_zooms), out_mbtiles in zip(bands, band_mbtiles):
        if zmin > zmax:
            continue
        print(f"Running tippecanoe ({name} pass, z{zmin}-{zmax}, exclude={exclude_fields or 'none'})...")
        tippecanoe_pass(geojson_path, out_mbtiles, layer_name, zmin, zmax, exclude_fields, extend_zooms)

    print("Merging zoom-band passes...")
    run(["tile-join", "-f", f"--output={mbtiles_path}", *[m for m in band_mbtiles if os.path.exists(m)]])

    print("Converting to PMTiles...")
    run(["pmtiles", "convert", mbtiles_path, pmtiles_path])

    pmtiles_mb = os.path.getsize(pmtiles_path) / 1e6
    print(f"\nWrote {pmtiles_path} ({pmtiles_mb:.1f} MB)")

    print("\ntileset info:")
    subprocess.run(["pmtiles", "show", pmtiles_path])

    print("\nBuilding search index...")
    n_idx = build_search_index(con, search_index_path, args.sample)
    idx_mb = os.path.getsize(search_index_path) / 1e6
    print(f"  {n_idx} addresses -> {search_index_path} ({idx_mb:.1f} MB gzipped)")

    print("\nBuilding scatter sample...")
    n_scatter = build_scatter_sample(con, scatter_sample_path, args.sample)
    scatter_mb = os.path.getsize(scatter_sample_path) / 1e6
    print(f"  {n_scatter} buildings -> {scatter_sample_path} ({scatter_mb:.2f} MB gzipped)")


if __name__ == "__main__":
    main()
