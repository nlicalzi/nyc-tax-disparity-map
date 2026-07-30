"""Join building_effective_rates.parquet to real parcel geometry, in three
priority tiers (see 06_fetch_geometry.py for why two extra datasets are
needed beyond PLUTO):

  1. direct         -- pluto_bbl matches TAX_LOT_POLYGON.bbl exactly (~98.6%)
  2. condo_crosswalk -- pluto_bbl is a condo billing bbl; resolved via the
                        condo crosswalk to one or more physical base bbls,
                        whose polygons are dissolved (ST_Union_Agg) into one
                        footprint if there's more than one (~1.2%, ~533 of
                        which are the multi-base-lot case)
  3. point_fallback  -- neither of the above resolved a polygon; use
                        PLUTO's lat/lon centroid as a Point (~0.13%)

Every building_effective_rates row ends up in exactly one tier (verified by
assertion below). Output keeps geometry + full attributes; tippecanoe schema
lean-ing (quantization, field drops per zoom) happens at tile-build time,
not here.

Usage:
    .venv/bin/python pipeline/07_join_geometry.py
(reads whatever is currently in data/cache/{building_effective_rates,
tax_lot_polygon,condo_crosswalk,pluto}.parquet)
"""
import os

import duckdb

CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "cache")

GRIFFIN_BUILDING_BBL = "1010307501"  # 220 Central Park South, condo billing bbl

SQL = f"""
WITH building AS (
    SELECT *, SPLIT_PART(pluto_bbl, '.', 1) AS bbl_norm
    FROM read_parquet('{CACHE}/building_effective_rates.parquet')
),
polygon AS (
    SELECT bbl, ST_GeomFromGeoJSON(the_geom_json) AS geom
    FROM read_parquet('{CACHE}/tax_lot_polygon.parquet')
    WHERE the_geom_json IS NOT NULL
),
pluto_point AS (
    SELECT
        SPLIT_PART(bbl, '.', 1) AS bbl_norm,
        TRY_CAST(latitude AS DOUBLE) AS latitude,
        TRY_CAST(longitude AS DOUBLE) AS longitude
    FROM read_parquet('{CACHE}/pluto.parquet')
),

direct AS (
    SELECT b.*, p.geom AS geom, 'direct' AS geom_source
    FROM building b
    JOIN polygon p ON p.bbl = b.bbl_norm
),

-- condo billing bbl -> one or more physical base bbls -> dissolve into one
-- footprint. ST_Union_Agg of a single geometry is just that geometry, so
-- this handles the single- and multi-base-lot cases uniformly.
condo_base_geom AS (
    SELECT cw.condo_billing_bbl AS bbl_norm, ST_Union_Agg(p.geom) AS geom
    FROM read_parquet('{CACHE}/condo_crosswalk.parquet') cw
    JOIN polygon p ON p.bbl = cw.condo_base_bbl
    GROUP BY cw.condo_billing_bbl
),
condo_crosswalk_tier AS (
    SELECT b.*, cg.geom AS geom, 'condo_crosswalk' AS geom_source
    FROM building b
    JOIN condo_base_geom cg ON cg.bbl_norm = b.bbl_norm
    WHERE b.bbl_norm NOT IN (SELECT bbl_norm FROM direct)
),

point_fallback AS (
    SELECT b.*, ST_Point(pt.longitude, pt.latitude) AS geom, 'point_fallback' AS geom_source
    FROM building b
    JOIN pluto_point pt ON pt.bbl_norm = b.bbl_norm
    WHERE b.bbl_norm NOT IN (SELECT bbl_norm FROM direct)
      AND b.bbl_norm NOT IN (SELECT bbl_norm FROM condo_crosswalk_tier)
      AND pt.latitude IS NOT NULL AND pt.longitude IS NOT NULL
)

SELECT * FROM direct
UNION ALL
SELECT * FROM condo_crosswalk_tier
UNION ALL
SELECT * FROM point_fallback
"""


def main():
    con = duckdb.connect()
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")

    print("Joining building_effective_rates to parcel geometry...")
    con.execute(f"CREATE TABLE buildings_geo AS {SQL}")

    total = con.sql("SELECT COUNT(*) FROM buildings_geo").fetchone()[0]
    by_source = con.sql(
        "SELECT geom_source, COUNT(*) n FROM buildings_geo GROUP BY geom_source ORDER BY n DESC"
    ).df()
    print(f"\n{total} rows resolved with geometry")
    for _, row in by_source.iterrows():
        print(f"  {row['geom_source']}: {row['n']} ({row['n'] / total:.2%})")

    src_total = con.sql(
        f"SELECT COUNT(*) FROM read_parquet('{CACHE}/building_effective_rates.parquet')"
    ).fetchone()[0]
    print(f"\nsource building_effective_rates.parquet rows: {src_total}")
    if total != src_total:
        print(f"  WARNING: {src_total - total} building rows have no geometry at all "
              f"(no polygon match AND no usable lat/lon)")

    griffin = con.sql(f"""
        SELECT geom_source, ST_GeometryType(geom) AS geom_type, ST_Area(geom) AS area
        FROM buildings_geo WHERE pluto_bbl LIKE '{GRIFFIN_BUILDING_BBL}%'
    """).df()
    print("\n--- Griffin building (220 Central Park South) geometry check ---")
    if len(griffin) != 1:
        print(f"[FAIL] expected 1 row for bbl {GRIFFIN_BUILDING_BBL}, got {len(griffin)}")
    else:
        row = griffin.iloc[0]
        ok_source = row["geom_source"] == "condo_crosswalk"
        ok_type = row["geom_type"] in ("POLYGON", "MULTIPOLYGON")
        ok_area = row["area"] > 0
        status = "PASS" if (ok_source and ok_type and ok_area) else "FAIL"
        print(f"[{status}] geom_source={row['geom_source']} geom_type={row['geom_type']} "
              f"area={row['area']:.8f} deg^2")

    # WKB (not GeoJSON) so downstream steps read it back via DuckDB's native
    # parquet reader -- re-reading a 600MB+ GeoJSON through the GDAL driver
    # for anything but the final tippecanoe input is too slow (a single
    # indexed point lookup took >15min in testing). GeoJSON for tippecanoe
    # itself gets generated once, directly from this parquet, at tile-build
    # time (pipeline/08_build_tileset.py).
    out_path = os.path.join(CACHE, "buildings_geom.parquet")
    con.execute(f"""
        COPY (
            SELECT
                pluto_bbl, boro, block, unit_count,
                building_tax, building_dof_market_value,
                tier1_tax, tier1_sale_basis, tier1_unit_count,
                building_effective_rate_tier1, building_effective_rate_tier2,
                pluto_borough_2letter, geom_source, ST_AsWKB(geom) AS geom_wkb
            FROM buildings_geo
        ) TO '{out_path}' (FORMAT PARQUET)
    """)
    size_mb = os.path.getsize(out_path) / 1e6
    print(f"\nWrote {out_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
