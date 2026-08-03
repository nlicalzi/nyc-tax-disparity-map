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
    .venv/bin/python pipeline/06_build_effective_rates.py
(reads whatever is currently in data/cache/{valuation_fy2026,sales_2016_2025,
pluto,exemptions_fy2026,abatements_fy2026}.parquet)
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

# Owner-name heuristic for "held by an entity, not a person" -- word-boundary
# match so it doesn't false-positive on individual names that happen to
# contain "LP"/"LLC" as a substring (e.g. "PURCHIL PROPERTIES" doesn't
# match). Verified against the full citywide valuation roll: this regex
# gives 6.6% class 1 / 23.2% class "2" (not 2A/2B/2C) / 59.7% class 2B /
# 36.1% class 4 -- matches PLAN.md's v2-roadmap research numbers (6.4% /
# 23.1% / 59.2% / 35.8%) closely enough to confirm it's the same heuristic,
# small drift likely from that research being scoped to tier-1 units only.
LLC_LP_REGEX = r"\b(LLC|LLLP|LLP|LP)\b"

# muvi-b6kx (DOF Property Exemption Detail) exmp_code values for the 421-a
# family and J-51 *exemption* (distinct from the J-51 *abatement* below --
# verified live via myn9-hwsy, DOF's own code lookup table: 5110/5113/5114/
# 5116/5118/5121 are "421A ... YR ..." variants, 1920 is "J51").
EXEMPT_421A_CODES = ("5110", "5113", "5114", "5116", "5118", "5121")
EXEMPT_J51_CODE = "1920"

# rgyu-ii48 (DOF Property Abatement Detail) tccode values for co-op/condo
# abatement and the J-51 *abatement* (a building can carry both this and the
# J-51 exemption above simultaneously -- confirmed live, 138,416 FY2026 rows
# each).
ABATE_COOP_CONDO_CODES = ("COOP", "CONDO")
ABATE_J51_CODE = "J51"

MIN_ARMS_LENGTH_SALE = 10000  # filter $0/nominal family transfers, foreclosures, etc.

# A flat dollar floor alone isn't enough: it still let a $130,000 "sale"
# through against a building DOF values at $1.054B (BBL 1011300001, an
# obvious non-arms-length transfer -- easement, internal restructuring,
# whatever it actually was), producing a nonsense 39,586% effective rate.
# Found via milestone-3 map styling work, not milestone-1 validation --
# the ~1% of tier1 buildings this affected were concentrated almost
# exactly in the high-value Manhattan buildings the site's headline story
# is about, so it wasn't a negligible tail.
#
# Fix: also require the sale price be at least MIN_SALE_TO_VALUE_RATIO of
# the unit's own DOF market value (curmkttot). This is deliberately
# one-sided -- it only rejects sale_price << curmkttot, never sale_price >>
# curmkttot -- because sale price legitimately and substantially exceeding
# DOF's (already-deflated, income-approach) market value is exactly the
# disparity this site exists to show, not noise to filter out. The bad
# example above had a ratio of 0.0123%; 1% leaves ~80x margin below any
# plausible genuine distressed-sale ratio while still catching nominal
# transfers. Skip the check when curmkttot is missing/zero -- can't sanity
# check against a value we don't have.
MIN_SALE_TO_VALUE_RATIO = 0.01

# Final backstop, applied after the ratio filter -- see unit_computed below.
EFFECTIVE_RATE_CEILING = 0.25

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
-- `valuation` is NOT unique per (boro, block, lot) -- 4,133 keys citywide
-- have multiple rows (e.g. a real O6 office record alongside a zero-value
-- U9 placeholder sharing the same lot number; a handful of keys have
-- dozens+ rows for reasons not yet fully understood -- flagged separately,
-- out of scope for this fix). Joining the ratio check straight against
-- `valuation` let a sale get sanity-checked against whichever sibling row
-- the join fanned out to -- including a $0 placeholder, whose
-- "curmkttot <= 0 -> can't check, let it through" branch then waived the
-- check entirely for the REAL record's sake. Pre-aggregate to one
-- representative value per key (the max -- a $0 sibling should never
-- suppress a real one) so the ratio check can't be routed around this way.
valuation_keymax AS (
    SELECT boro, block, lot, MAX(curmkttot) AS curmkttot
    FROM valuation
    GROUP BY boro, block, lot
),
-- Join to valuation before picking the "latest" sale per unit-lot, so a
-- nominal transfer gets discarded in favor of an earlier genuine sale
-- (if any) rather than winning the dedup and silently killing tier-1
-- status for that unit.
sales_sane AS (
    SELECT s.borough AS boro, s.block, s.lot,
           TRY_CAST(s.sale_price AS DOUBLE) AS sale_price,
           s.sale_date
    FROM read_parquet('{CACHE}/sales_2016_2025.parquet') s
    JOIN valuation_keymax v ON v.boro = s.borough AND v.block = s.block AND v.lot = s.lot
    WHERE TRY_CAST(s.sale_price AS DOUBLE) > {MIN_ARMS_LENGTH_SALE}
      AND (
          v.curmkttot IS NULL OR v.curmkttot <= 0
          OR TRY_CAST(s.sale_price AS DOUBLE) >= {MIN_SALE_TO_VALUE_RATIO} * v.curmkttot
      )
),
latest_sale AS (
    SELECT boro, block, lot, sale_price, sale_date,
           ROW_NUMBER() OVER (
               PARTITION BY boro, block, lot ORDER BY sale_date DESC
           ) AS rn
    FROM sales_sane
),
sale_dedup AS (
    SELECT boro, block, lot, sale_price, sale_date
    FROM latest_sale WHERE rn = 1
),
exemptions_agg AS (
    SELECT
        boro, block, lot,
        SUM(TRY_CAST(curexmptot AS DOUBLE)) AS total_exemption_amt,
        SUM(CASE WHEN exmp_code IN {EXEMPT_421A_CODES} THEN TRY_CAST(curexmptot AS DOUBLE) ELSE 0 END)
            AS exemption_421a_amt,
        SUM(CASE WHEN exmp_code = '{EXEMPT_J51_CODE}' THEN TRY_CAST(curexmptot AS DOUBLE) ELSE 0 END)
            AS j51_exemption_amt
    FROM read_parquet('{CACHE}/exemptions_fy2026.parquet')
    GROUP BY boro, block, lot
),
-- rgyu-ii48 has no boro/block/lot columns -- only a padded fixed-width
-- `parid` in the same boro(1)+block(5)+lot(4) digit layout as valuation's
-- own parid (verified live, see 05_fetch_abatements.py). `appliedabt` is a
-- per-quarter installment (verified live: one parcel's amount differed
-- across 1Q-4Q, summing to a plausible annual total) -- sum all 4 quarters
-- per (boro,block,lot,tccode) to get the annual dollar figure before
-- pivoting into the two tccode groups this site reports.
abatements_parsed AS (
    SELECT
        SUBSTR(TRIM(parid), 1, 1) AS boro,
        CAST(CAST(SUBSTR(TRIM(parid), 2, 5) AS INT) AS VARCHAR) AS block,
        CAST(CAST(SUBSTR(TRIM(parid), 7, 4) AS INT) AS VARCHAR) AS lot,
        TRIM(tccode) AS tccode,
        TRY_CAST(appliedabt AS DOUBLE) AS appliedabt
    FROM read_parquet('{CACHE}/abatements_fy2026.parquet')
),
abatements_annual AS (
    SELECT boro, block, lot, tccode, SUM(appliedabt) AS annual_abatement
    FROM abatements_parsed
    GROUP BY boro, block, lot, tccode
),
abatements_agg AS (
    SELECT
        boro, block, lot,
        SUM(CASE WHEN tccode IN {ABATE_COOP_CONDO_CODES} THEN annual_abatement ELSE 0 END)
            AS coop_condo_abatement_amt,
        SUM(CASE WHEN tccode = '{ABATE_J51_CODE}' THEN annual_abatement ELSE 0 END) AS j51_abatement_amt
    FROM abatements_annual
    GROUP BY boro, block, lot
),
unit_computed AS (
    SELECT
        v.*,
        cr.rate AS class_rate,
        v.curtxbtot * cr.rate AS computed_tax,
        s.sale_price, s.sale_date,
        -- Owner-entity heuristic (see LLC_LP_REGEX above) -- reported
        -- separately from the core rate, same "never blended in" norm as
        -- the tier1/tier2 split.
        regexp_matches(v.owner, '{LLC_LP_REGEX}') AS is_llc_or_lp,
        -- Exemption (reduces taxable value, muvi-b6kx) and abatement
        -- (reduces the tax bill itself, rgyu-ii48) amounts/flags -- kept as
        -- separate labeled fields per PLAN.md's v2 roadmap item 3, never
        -- folded into computed_tax/effective_rate (those already reflect
        -- curtxbtot, which is post-exemption; the abatement figures here
        -- are informational, not re-applied to the rate).
        COALESCE(ex.exemption_421a_amt, 0) AS exemption_421a_amt,
        COALESCE(ex.exemption_421a_amt, 0) > 0 AS has_421a_exemption,
        COALESCE(ex.j51_exemption_amt, 0) AS j51_exemption_amt,
        COALESCE(ex.j51_exemption_amt, 0) > 0 AS has_j51_exemption,
        COALESCE(ab.coop_condo_abatement_amt, 0) AS coop_condo_abatement_amt,
        COALESCE(ab.coop_condo_abatement_amt, 0) > 0 AS has_coop_condo_abatement,
        COALESCE(ab.j51_abatement_amt, 0) AS j51_abatement_amt,
        COALESCE(ab.j51_abatement_amt, 0) > 0 AS has_j51_abatement,
        -- Backstop on top of the ratio filter above: even a sale that clears
        -- MIN_SALE_TO_VALUE_RATIO can still imply an impossible rate (e.g. a
        -- $960K "sale" against a $95.8M valuation clears 1% easily but still
        -- computes to 558% -- commercial/class-4 curtxbtot isn't cap-protected
        -- the way residential is, so the tax base alone can dwarf a barely-
        -- passing sale price). The >5% tail here has no clean natural break
        -- between "real distressed sale" and "nominal transfer" -- it's a
        -- smooth long tail, median 18% -- so EFFECTIVE_RATE_CEILING is a
        -- deliberately generous, documented cutoff (5x+ any real class
        -- average) rather than a precisely-derived one. Falls back to tier 2
        -- exactly like "no sale at all" when a sale trips it.
        CASE
            WHEN s.sale_price IS NOT NULL
                 AND v.curtxbtot * cr.rate / s.sale_price <= {EFFECTIVE_RATE_CEILING}
            THEN 1 ELSE 2
        END AS tier,
        CASE
            WHEN s.sale_price IS NOT NULL
                 AND v.curtxbtot * cr.rate / s.sale_price <= {EFFECTIVE_RATE_CEILING}
            THEN v.curtxbtot * cr.rate / s.sale_price
            WHEN v.curmkttot > 0 THEN v.curtxbtot * cr.rate / v.curmkttot
            ELSE NULL
        END AS effective_rate
    FROM valuation v
    LEFT JOIN class_rate cr ON cr.class_prefix = v.class_prefix
    LEFT JOIN sale_dedup s ON s.boro = v.boro AND s.block = v.block AND s.lot = v.lot
    LEFT JOIN exemptions_agg ex ON ex.boro = v.boro AND ex.block = v.block AND ex.lot = v.lot
    LEFT JOIN abatements_agg ab ON ab.boro = v.boro AND ab.block = v.block AND ab.lot = v.lot
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
        -- PLUTO's bbl comes back from Socrata as a decimal-formatted string
        -- (e.g. "1010307501.00000000") -- Socrata serializes its `number`
        -- column type this way. Normalize once, here, so every downstream
        -- consumer (join_geometry, the tile schema, search index) gets a
        -- clean id without repeating the fix.
        SPLIT_PART(bbl, '.', 1) AS bbl,
        borough AS pluto_borough, block AS pluto_block, lot AS pluto_lot,
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
    SELECT u.*, p.bbl AS pluto_bbl, p.pluto_borough AS pluto_borough, p.address AS pluto_address
    FROM units u
    JOIN boro_map bm ON bm.boro = u.boro
    JOIN pluto p
      ON p.pluto_borough = bm.pluto_borough
     AND p.pluto_block = u.block
     AND p.condono = u.condo_number - CAST(u.boro AS BIGINT) * 100000
    WHERE u.condo_number IS NOT NULL

    UNION ALL

    -- everything else: unit-lot IS the PLUTO lot
    SELECT u.*, p.bbl AS pluto_bbl, p.pluto_borough AS pluto_borough, p.address AS pluto_address
    FROM units u
    JOIN boro_map bm ON bm.boro = u.boro
    JOIN pluto p
      ON p.pluto_borough = bm.pluto_borough
     AND p.pluto_block = u.block
     AND p.pluto_lot = u.lot
    WHERE u.condo_number IS NULL
),
building_base AS (
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
        ANY_VALUE(units_mapped.pluto_borough) AS pluto_borough_2letter,
        -- ANY_VALUE, not an aggregate over unit addresses -- condo units
        -- share one PLUTO billing-lot row and thus one building address by
        -- construction (see units_mapped's join above); non-condo lots are
        -- already 1 unit = 1 building.
        ANY_VALUE(pluto_address) AS address,
        -- A building's units are overwhelmingly one tax class (mixed-class
        -- buildings are rare); mode() picks the class that best represents
        -- the building for the popup/filter UI rather than an arbitrary row.
        mode(class_prefix) AS tax_class,
        MAX(CASE WHEN tier = 1 THEN sale_date END) AS tier1_last_sale_date,
        -- Owner-entity flag, reported at the fraction-of-units grain, not a
        -- single "the building's owner" string -- a condo building is
        -- overwhelmingly many individually-owned units, so "mode(owner)"
        -- would just report whichever owner happens to hold the most units,
        -- not who owns the building. sample_owner is only a meaningful
        -- single name when unit_count = 1 (the class-1/single-unit case);
        -- the popup must gate on that, not display it unconditionally --
        -- see PLAN.md's v2 roadmap item 2.
        COUNT(*) FILTER (WHERE is_llc_or_lp) AS llc_unit_count,
        COUNT(*) FILTER (WHERE is_llc_or_lp) / COUNT(*)::DOUBLE AS llc_unit_pct,
        ANY_VALUE(owner) AS sample_owner,
        -- Exemption/abatement: reported as whether ANY unit in the building
        -- carries the flag, plus the summed dollar amount across all units
        -- -- never blended into building_tax/building_effective_rate_*,
        -- same labeling norm as tier1/tier2 (PLAN.md's v2 roadmap item 3).
        BOOL_OR(has_421a_exemption) AS has_421a_exemption,
        SUM(exemption_421a_amt) AS exemption_421a_amt,
        BOOL_OR(has_j51_exemption) AS has_j51_exemption,
        SUM(j51_exemption_amt) AS j51_exemption_amt,
        BOOL_OR(has_coop_condo_abatement) AS has_coop_condo_abatement,
        SUM(coop_condo_abatement_amt) AS coop_condo_abatement_amt,
        BOOL_OR(has_j51_abatement) AS has_j51_abatement,
        SUM(j51_abatement_amt) AS j51_abatement_amt
    FROM units_mapped
    GROUP BY pluto_bbl
)
SELECT
    building_base.*,
    -- "For scale" popup comparison: what fraction of this building's peers
    -- (same borough + tax class, among tier-1 sale-verified buildings only)
    -- pay a HIGHER effective rate. ORDER BY ... DESC means the
    -- highest-rate peer gets percent_rank 0 and the lowest-rate peer
    -- approaches 1, i.e. this value already reads as "fraction of peers
    -- with a higher rate than this building."
    CASE
        WHEN building_effective_rate_tier1 IS NOT NULL
        THEN ROUND(100 * PERCENT_RANK() OVER (
            PARTITION BY pluto_borough_2letter, tax_class
            ORDER BY building_effective_rate_tier1 DESC
        ))
        ELSE NULL
    END AS tier1_pctile_pays_less_than
FROM building_base
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
