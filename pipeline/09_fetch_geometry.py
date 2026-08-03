"""Fetch real parcel polygon geometry -- NOT from PLUTO (64uk-42ks). That
dataset's `geom` field is present in its schema but 100% null across all
858,602 rows (verified directly against the live API); it only ever
provides `latitude`/`longitude` centroids, which is why 03_fetch_pluto.py
only pulls those. See PLAN.md's Data sources section (corrected 2026-07-30)
for the full story.

Real polygons live in two datasets from DOF's Digital Tax Map collection:

  - TAX_LOT_POLYGON (i38t-6if2): one MultiPolygon per physical tax lot,
    keyed by `bbl`. Matches ~98.6% of building_effective_rates.parquet's
    pluto_bbl directly.
  - Digital Tax Map: Condominiums (p8u6-a6it): crosswalk from a condo's
    synthetic PLUTO "billing" bbl (e.g. 220 Central Park South's
    1010307501) to the real physical bbl(s) it's built on
    (condo_base_bbl). Condo billing lots aren't physical parcels, so they
    never appear in TAX_LOT_POLYGON directly -- this crosswalk is required
    to resolve them. Covers another ~1.2% of buildings. A small subset of
    those (~533 buildings, ~0.06%) map to *multiple* base lots (merged
    parcels) and need their polygons dissolved into one footprint at join
    time -- see 10_join_geometry.py.

The remaining ~0.13% of buildings resolve to neither and fall back to
PLUTO's point centroid in 10_join_geometry.py.

Usage:
    .venv/bin/python pipeline/09_fetch_geometry.py --sample   # Manhattan only
    .venv/bin/python pipeline/09_fetch_geometry.py            # full citywide
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib.socrata import fetch_all  # noqa: E402

CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "cache")

TAX_LOT_POLYGON_ID = "i38t-6if2"
CONDO_CROSSWALK_ID = "p8u6-a6it"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="Manhattan only, for prototyping")
    args = parser.parse_args()

    where = "boro='1'" if args.sample else None
    poly_df = fetch_all(
        TAX_LOT_POLYGON_ID,
        select="bbl,boro,block,lot,the_geom",
        where=where,
        order="boro,block,lot",
        progress_label="tax_lot_polygon",
    )
    # the_geom comes back as a nested GeoJSON geometry dict per row (from the
    # Socrata JSON API) -- store as a JSON string so it round-trips through
    # parquet cleanly. Nobody parses the coordinates in Python; DuckDB's
    # spatial extension (ST_GeomFromGeoJSON) reads this string directly in
    # 10_join_geometry.py.
    poly_df["the_geom_json"] = poly_df["the_geom"].apply(
        lambda g: json.dumps(g) if isinstance(g, dict) else None
    )
    poly_df = poly_df.drop(columns=["the_geom"])
    poly_out = os.path.join(CACHE, "tax_lot_polygon.parquet")
    poly_df.to_parquet(poly_out, index=False)
    n_geom = poly_df["the_geom_json"].notna().sum()
    print(f"Wrote {len(poly_df)} rows ({n_geom} with geometry) to {poly_out}")

    cw_where = "condo_base_boro='1'" if args.sample else None
    cw_df = fetch_all(
        CONDO_CROSSWALK_ID,
        select="condo_billing_bbl,condo_base_bbl,condo_base_boro,condo_base_block,condo_base_lot,condo_name",
        where=cw_where,
        progress_label="condo_crosswalk",
    )
    cw_out = os.path.join(CACHE, "condo_crosswalk.parquet")
    cw_df.to_parquet(cw_out, index=False)
    print(f"Wrote {len(cw_df)} rows to {cw_out}")


if __name__ == "__main__":
    main()
