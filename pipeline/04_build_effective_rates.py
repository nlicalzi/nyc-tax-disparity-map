"""Join valuation + sales + PLUTO, compute the two-tier effective-rate metric.

FY2026 class rates, adopted by NYC Council, sourced from
nyc.gov/site/finance/property/property-tax-rates.page, verified 2026-07-30.
Hardcoded per PLAN.md's Non-goals section (not worth scraping for a
one-time v1 snapshot).

Outputs (data/cache/):
  - unit_effective_rates.parquet   one row per DOF unit-lot (the core,
                                    validated computation)
  - building_effective_rates.parquet  aggregated to PLUTO bbl grain, for
                                    map rendering

Usage:
    .venv/bin/python pipeline/04_build_effective_rates.py
(reads whatever is currently in data/cache/{valuation_fy2026,sales_2016_2025,pluto}.parquet)
"""
import os

import duckdb

CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "cache")

# tax_class prefix -> FY2026 adopted rate (percent of taxable value)
CLASS_RATES = {
    "1": 0.19843,
    "2": 0.12439,
    "3": 0.11108,
    "4": 0.10848,
}

# NYC boro code (as used by DOF valuation/sales) -> PLUTO 2-letter borough code
BORO_CODE_TO_PLUTO = {"1": "MN", "2": "BX", "3": "BK", "4": "QN", "5": "SI"}

MIN_ARMS_LENGTH_SALE = 10000  # filter $0/nominal family transfers, foreclosures, etc.

SQL = f"""
WITH class_rate AS (
    SELECT * FROM (VALUES
        {', '.join(f"('{k}', {v})" for k, v in CLASS_RATES.items())}
    ) AS t(class_prefix, rate)
),
boro_map AS (
    SELECT * FROM (VALUES
        {', '.join(f"('{k}', '{v}')" for k, v in BORO_CODE_TO_PLUTO.items())}
    ) AS t(boro, pluto_borough)
),
valuation AS (
    SELECT
        parid, boro, block, lot,
        TRY_CAST(curmkttot AS DOUBLE) AS curmkttot,
        TRY_CAST(curtxbtot AS DOUBLE) AS curtxbtot,
        curtaxclass,
        LEFT(curtaxclass, 1) AS class_prefix,
        bldg_class, owner, housenum_lo, housenum_hi, street_name, zip_code,
        TRY_CAST(units AS INT) AS units,
        aptno,
        TRY_CAST(condo_number AS BIGINT) AS condo_number
    FROM read_parquet('{CACHE}/valuation_fy2026.parquet')
    -- R0 = condo association billing-lot placeholder record (curmkttot/curtxbtot
    -- always 0, units=0) -- not a real taxed unit, the value lives in the
    -- individual unit-lot rows. Confirmed via block 1030 lot 7501 (220 CPS).
    WHERE bldg_class != 'R0'
),
latest_sale AS (
    SELECT borough AS boro, block, lot, sale_price, sale_date,
           ROW_NUMBER() OVER (
               PARTITION BY borough, block, lot ORDER BY sale_date DESC
           ) AS rn
    FROM read_parquet('{CACHE}/sales_2016_2025.parquet')
    WHERE TRY_CAST(sale_price AS DOUBLE) > {MIN_ARMS_LENGTH_SALE}
),
sale_dedup AS (
    SELECT boro, block, lot,
           TRY_CAST(sale_price AS DOUBLE) AS sale_price,
           sale_date
    FROM latest_sale WHERE rn = 1
),
unit_computed AS (
    SELECT
        v.*,
        cr.rate AS class_rate,
        v.curtxbtot * cr.rate AS computed_tax,
        s.sale_price, s.sale_date,
        CASE WHEN s.sale_price IS NOT NULL THEN 1 ELSE 2 END AS tier,
        CASE
            WHEN s.sale_price IS NOT NULL THEN v.curtxbtot * cr.rate / s.sale_price
            WHEN v.curmkttot > 0 THEN v.curtxbtot * cr.rate / v.curmkttot
            ELSE NULL
        END AS effective_rate
    FROM valuation v
    LEFT JOIN class_rate cr ON cr.class_prefix = v.class_prefix
    LEFT JOIN sale_dedup s ON s.boro = v.boro AND s.block = v.block AND s.lot = v.lot
)
SELECT * FROM unit_computed
"""

BUILDING_SQL = f"""
WITH units AS (
    SELECT * FROM unit_effective_rates
),
boro_map AS (
    SELECT * FROM (VALUES
        {', '.join(f"('{k}', '{v}')" for k, v in BORO_CODE_TO_PLUTO.items())}
    ) AS t(boro, pluto_borough)
),
pluto AS (
    SELECT
        bbl, borough AS pluto_borough, block AS pluto_block, lot AS pluto_lot,
        TRY_CAST(condono AS BIGINT) AS condono,
        address, zipcode,
        TRY_CAST(latitude AS DOUBLE) AS latitude,
        TRY_CAST(longitude AS DOUBLE) AS longitude,
        TRY_CAST(unitsres AS INT) AS unitsres,
        TRY_CAST(unitstotal AS INT) AS unitstotal,
        bldgclass, landuse
    FROM read_parquet('{CACHE}/pluto.parquet')
),
units_mapped AS (
    -- condo units: join to PLUTO's billing lot via condo_number (boro*100000 + condono).
    -- condono is only unique *within a block* in PLUTO (confirmed: e.g. QN condono=100
    -- collides across 10+ unrelated buildings on different blocks) -- block match is
    -- required, not optional, or this fans out into duplicate matches.
    SELECT u.*, p.bbl AS pluto_bbl, p.pluto_borough AS pluto_borough
    FROM units u
    JOIN boro_map bm ON bm.boro = u.boro
    JOIN pluto p
      ON p.pluto_borough = bm.pluto_borough
     AND p.pluto_block = u.block
     AND p.condono = u.condo_number - CAST(u.boro AS BIGINT) * 100000
    WHERE u.condo_number IS NOT NULL

    UNION ALL

    -- everything else: unit-lot IS the PLUTO lot
    SELECT u.*, p.bbl AS pluto_bbl, p.pluto_borough AS pluto_borough
    FROM units u
    JOIN boro_map bm ON bm.boro = u.boro
    JOIN pluto p
      ON p.pluto_borough = bm.pluto_borough
     AND p.pluto_block = u.block
     AND p.pluto_lot = u.lot
    WHERE u.condo_number IS NULL
)
SELECT
    pluto_bbl,
    ANY_VALUE(boro) AS boro,
    ANY_VALUE(block) AS block,
    COUNT(*) AS unit_count,
    SUM(computed_tax) AS building_tax,
    SUM(curmkttot) AS building_dof_market_value,
    SUM(CASE WHEN tier = 1 THEN computed_tax ELSE 0 END) AS tier1_tax,
    SUM(CASE WHEN tier = 1 THEN sale_price ELSE 0 END) AS tier1_sale_basis,
    COUNT(*) FILTER (WHERE tier = 1) AS tier1_unit_count,
    CASE
        WHEN SUM(CASE WHEN tier = 1 THEN sale_price ELSE 0 END) > 0
        THEN SUM(CASE WHEN tier = 1 THEN computed_tax ELSE 0 END)
             / SUM(CASE WHEN tier = 1 THEN sale_price ELSE 0 END)
        ELSE NULL
    END AS building_effective_rate_tier1,
    CASE
        WHEN SUM(curmkttot) > 0 THEN SUM(computed_tax) / SUM(curmkttot)
        ELSE NULL
    END AS building_effective_rate_tier2,
    ANY_VALUE(units_mapped.pluto_borough) AS pluto_borough_2letter
FROM units_mapped
GROUP BY pluto_bbl
"""


def main():
    con = duckdb.connect()

    print("Computing unit-level effective rates...")
    unit_df = con.sql(SQL).df()
    con.register("unit_effective_rates", unit_df)

    unit_out = os.path.join(CACHE, "unit_effective_rates.parquet")
    unit_df.to_parquet(unit_out, index=False)
    print(f"  wrote {len(unit_df)} unit rows -> {unit_out}")

    print("Aggregating to building (PLUTO bbl) level...")
    building_df = con.sql(BUILDING_SQL).df()
    building_out = os.path.join(CACHE, "building_effective_rates.parquet")
    building_df.to_parquet(building_out, index=False)
    print(f"  wrote {len(building_df)} building rows -> {building_out}")
    matched_units = int(building_df["unit_count"].sum())
    print(f"  {matched_units}/{len(unit_df)} unit rows matched to a PLUTO building "
          f"({matched_units / len(unit_df):.1%})")


if __name__ == "__main__":
    main()
