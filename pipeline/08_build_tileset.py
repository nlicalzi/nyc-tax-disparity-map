"""Build the PMTiles vector tileset from buildings_geom.parquet.

Per PLAN.md's Performance strategy:
  1. Lean tile schema -- short field names, quantized values (effective
     rate as integer basis points, market value in $10K units) so
     click-for-detail (queryRenderedFeatures) never needs an extra fetch.
  2. Zoom-dependent generalization computed at build time: tippecanoe's
     --coalesce-densest-as-needed / --drop-densest-as-needed /
     --extend-zooms-if-still-dropping automatically thin/merge dense areas
     at low zoom while preserving full per-parcel detail at high zoom.
     (H3-hex-bin pre-aggregation at low zoom, mentioned as an option in
     PLAN.md's Tech stack section, is explicitly called out there as
     optional/stretch -- not built here; tippecanoe's built-in feature
     dropping/coalescing is the v1 mechanism.)

Two outputs:
  - Citywide production tileset: site/public/tiles/buildings.pmtiles
  - One-borough (Manhattan) dev-sample tileset for the agent's own fast
    iteration loop, per the agent-workflow rules: data/cache/dev_sample.pmtiles
    (gitignored, never committed)

Usage:
    .venv/bin/python pipeline/08_build_tileset.py --sample   # Manhattan dev sample
    .venv/bin/python pipeline/08_build_tileset.py            # full citywide
"""
import argparse
import os
import subprocess
import sys

import duckdb

ROOT = os.path.join(os.path.dirname(__file__), "..")
CACHE = os.path.join(ROOT, "data", "cache")
TILES_DIR = os.path.join(ROOT, "site", "public", "tiles")

MIN_ZOOM = 9
MAX_ZOOM = 16


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
                geom_source AS gsrc,
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="Manhattan-only dev-sample tileset")
    args = parser.parse_args()

    con = duckdb.connect()
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")

    if args.sample:
        geojson_path = os.path.join(CACHE, "tileset_source_sample.geojson")
        mbtiles_path = os.path.join(CACHE, "dev_sample.mbtiles")
        pmtiles_path = os.path.join(CACHE, "dev_sample.pmtiles")
        layer_name = "buildings"
    else:
        geojson_path = os.path.join(CACHE, "tileset_source.geojson")
        mbtiles_path = os.path.join(CACHE, "buildings.mbtiles")
        os.makedirs(TILES_DIR, exist_ok=True)
        pmtiles_path = os.path.join(TILES_DIR, "buildings.pmtiles")
        layer_name = "buildings"

    for p in (geojson_path, mbtiles_path, pmtiles_path):
        if os.path.exists(p):
            os.remove(p)

    print(f"Building lean-schema GeoJSON ({'Manhattan sample' if args.sample else 'citywide'})...")
    n = build_lean_geojson(con, geojson_path, args.sample)
    geojson_mb = os.path.getsize(geojson_path) / 1e6
    print(f"  {n} features -> {geojson_path} ({geojson_mb:.1f} MB)")

    print("Running tippecanoe...")
    run([
        "tippecanoe",
        f"--output={mbtiles_path}",
        f"--layer={layer_name}",
        f"--minimum-zoom={MIN_ZOOM}",
        f"--maximum-zoom={MAX_ZOOM}",
        "--coalesce-densest-as-needed",
        "--drop-densest-as-needed",
        "--extend-zooms-if-still-dropping",
        "--name=NYC building effective tax rates",
        "--description=Per-building computed effective property tax rate, PLUTO/DOF join",
        "--force",
        "--no-progress-indicator",
        geojson_path,
    ])

    print("Converting to PMTiles...")
    run(["pmtiles", "convert", mbtiles_path, pmtiles_path])

    pmtiles_mb = os.path.getsize(pmtiles_path) / 1e6
    print(f"\nWrote {pmtiles_path} ({pmtiles_mb:.1f} MB)")

    print("\ntileset info:")
    subprocess.run(["pmtiles", "show", pmtiles_path])


if __name__ == "__main__":
    main()
