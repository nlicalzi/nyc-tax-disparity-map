"""Class-1 trend-line benchmark + per-unit/citywide dollar-gap computation.

PLAN.md's v2 roadmap item 1: turn the rate-percentage disparity into a dollar
figure -- "how much would this class-2 (co-op/condo) unit have paid if it
were taxed like a same-priced class-1 (1-3 family) sale?" The naive
counterfactual (sale_price x class_rate) was already rejected during
research (it restates the whole assessment system's by-design discount as
if it were the finding, see PLAN.md). The fix: benchmark against class 1's
OWN price-vs-rate curve, not full value.

**Functional form matters more than the roadmap note anticipated.** A
straight-line OLS fit of `effective_rate ~ log10(sale_price)` (the form
`site/src/scatter.ts` already uses for its client-side VISUAL trend line,
which only ever draws between its own sample's min/max -- never
extrapolates) is fine for a chart. It is NOT fine as a benchmark FUNCTION
evaluated at arbitrary class-2 prices, because a raw linear fit crosses zero
around $2.4M and goes *negative* beyond it -- i.e. it claims a same-priced
class-1 sale above $2.4M should pay literally nothing, which is false (real
class-1 sales above $10M still show a ~0.4-0.5% median rate, never zero or
negative). That would floor ~23% of class-2 tier-1 units' gap at 0 for a
bad reason (a fit artifact), including Ken Griffin's own unit.

Fix: fit `ln(effective_rate) ~ log10(sale_price)` instead (a log-log / power
-law form) -- mathematically guaranteed positive everywhere, still a smooth
function defined at every price including the tail (per the roadmap's
requirement), and empirically closer to the real bucketed medians at the top
of class 1's own range than the raw linear fit.

**A second, more important finding survives the functional-form fix**:
matched-price-bucket comparison (no fitting at all) shows class-1 homes
already pay a LOWER median effective rate than class-2 units at every price
band from $300K up (e.g. at $5-10M: class 1 median 0.48% vs class 2 median
0.94%) -- this is real data, not a fitting artifact, and it's the same
mechanism PLAN.md's 2026-07-31 correction already documented (class 1's
own assessment-growth cap suppresses value at least as steeply as class 2's
income-approach method does). Consequence: **Ken Griffin's own unit computes
to a $0 gap under this specific benchmark** -- the fitted class-1 rate at his
$239,958,219 price (0.036%) is lower than what he actually pays (0.3486%),
so relative to a hypothetical same-priced class-1 sale, he's not
underpaying. This doesn't contradict the site's core Griffin anecdote (which
compares his rate to a MODEST home's rate, at a different, much lower price
-- a valid and different comparison); it means this specific "vs. trend
line" dollar figure is a separate, complementary metric, not a restatement
of the Griffin anecdote in dollar form. Checked with the user before
building the UI on top of this (2026-08-03) -- decision: report both,
clearly separated, not folded into one number.

Outputs (data/cache/, both rewritten in place -- see 06_build_effective_rates.py):
  - unit_effective_rates.parquet adds `class1_trend_rate`,
    `dollar_gap_vs_class1_trend` (class-2 tier-1 rows only, NULL elsewhere).
  - building_effective_rates.parquet adds `building_dollar_gap_vs_class1_trend`
    (SUM of the unit-level gap across each building's class-2 tier-1 units).

Usage:
    .venv/bin/python pipeline/07_compute_dollar_gap.py
(reads/rewrites data/cache/{unit_effective_rates,building_effective_rates}.parquet;
also reads pluto.parquet to re-derive the unit->PLUTO-bbl mapping for the
building-level aggregation -- duplicates the small condo-billing-lot join
block from 06_build_effective_rates.py's BUILDING_SQL, since each pipeline
step is a standalone script per PLAN.md's agent-workflow rules, same
BORO_CODE_TO_PLUTO duplication precedent as 11_build_tileset.py.)
"""
import os

import duckdb

CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "cache")

BORO_CODE_TO_PLUTO = {"1": "MN", "2": "BX", "3": "BK", "4": "QN", "5": "SI"}

# Vacant land (bldg_class starting with 'V') sells for wildly outlier prices
# (up to $869M citywide) at near-zero effective rates -- it isn't a "1-3
# family home" and its inclusion doesn't change the fitted slope much
# (-0.0207 with it vs -0.0220 without, in the linear form) but isn't
# conceptually part of the "modest home" comparison this site is about.
# Excluded from the class-1 fit population only.
EXCLUDE_VACANT_LAND = "bldg_class NOT LIKE 'V%'"

FIT_SQL = f"""
SELECT
    regr_slope(ln(effective_rate), log10(sale_price)) AS slope,
    regr_intercept(ln(effective_rate), log10(sale_price)) AS intercept,
    COUNT(*) AS n
FROM read_parquet('{CACHE}/unit_effective_rates.parquet')
WHERE class_prefix = '1' AND tier = 1 AND sale_price > 0
  AND effective_rate > 0 AND {EXCLUDE_VACANT_LAND}
"""

GAP_SQL = f"""
WITH fit AS ({FIT_SQL}),
gap_computed AS (
    SELECT
        u.*,
        CASE WHEN u.class_prefix = '2' AND u.tier = 1 AND u.sale_price > 0
             THEN exp(fit.intercept + fit.slope * log10(u.sale_price))
        END AS class1_trend_rate,
        -- Benchmark tax minus actual tax, floored at 0 -- only counts as a
        -- "gap" when this unit pays LESS than a same-priced class-1 sale's
        -- fitted rate would predict. See module docstring for why this is
        -- often 0, including for Griffin's own unit.
        CASE WHEN u.class_prefix = '2' AND u.tier = 1 AND u.sale_price > 0
             THEN GREATEST(
                 0,
                 exp(fit.intercept + fit.slope * log10(u.sale_price)) * u.sale_price - u.computed_tax
             )
        END AS dollar_gap_vs_class1_trend
    FROM read_parquet('{CACHE}/unit_effective_rates.parquet') u, fit
)
SELECT * FROM gap_computed
"""

# Re-derives the unit -> PLUTO bbl mapping, duplicated from
# 06_build_effective_rates.py's BUILDING_SQL (see module docstring for why).
BUILDING_GAP_SQL = f"""
WITH boro_map AS (
    SELECT * FROM (VALUES
        {', '.join(f"('{k}', '{v}')" for k, v in BORO_CODE_TO_PLUTO.items())}
    ) AS t(boro, pluto_borough)
),
pluto AS (
    SELECT
        SPLIT_PART(bbl, '.', 1) AS bbl,
        borough AS pluto_borough, block AS pluto_block, lot AS pluto_lot,
        TRY_CAST(condono AS BIGINT) AS condono
    FROM read_parquet('{CACHE}/pluto.parquet')
),
units_mapped AS (
    SELECT u.boro, u.block, u.lot, p.bbl AS pluto_bbl, u.dollar_gap_vs_class1_trend
    FROM gap_units u
    JOIN boro_map bm ON bm.boro = u.boro
    JOIN pluto p
      ON p.pluto_borough = bm.pluto_borough
     AND p.pluto_block = u.block
     AND p.condono = u.condo_number - CAST(u.boro AS BIGINT) * 100000
    WHERE u.condo_number IS NOT NULL

    UNION ALL

    SELECT u.boro, u.block, u.lot, p.bbl AS pluto_bbl, u.dollar_gap_vs_class1_trend
    FROM gap_units u
    JOIN boro_map bm ON bm.boro = u.boro
    JOIN pluto p
      ON p.pluto_borough = bm.pluto_borough
     AND p.pluto_block = u.block
     AND p.pluto_lot = u.lot
    WHERE u.condo_number IS NULL
),
building_gap AS (
    SELECT pluto_bbl, SUM(dollar_gap_vs_class1_trend) AS building_dollar_gap_vs_class1_trend
    FROM units_mapped
    GROUP BY pluto_bbl
)
SELECT b.*, COALESCE(bg.building_dollar_gap_vs_class1_trend, 0) AS building_dollar_gap_vs_class1_trend
FROM read_parquet('{CACHE}/building_effective_rates.parquet') b
LEFT JOIN building_gap bg ON bg.pluto_bbl = b.pluto_bbl
"""

GRIFFIN_BORO, GRIFFIN_BLOCK, GRIFFIN_LOT = "1", "1030", "1082"


def main():
    con = duckdb.connect()

    print("Fitting class-1 tier-1 trend line (ln(effective_rate) ~ log10(sale_price))...")
    fit = con.sql(FIT_SQL).df().iloc[0]
    print(f"  n={fit.n:,.0f}  slope={fit.slope:.6f}  intercept={fit.intercept:.6f}")

    print("Computing per-unit dollar gap for class-2 tier-1 units...")
    gap_df = con.sql(GAP_SQL).df()
    unit_out = os.path.join(CACHE, "unit_effective_rates.parquet")
    gap_df.to_parquet(unit_out, index=False)
    print(f"  rewrote {unit_out}")

    total_gap = gap_df["dollar_gap_vs_class1_trend"].sum()
    n_class2_tier1 = int(((gap_df["class_prefix"] == "2") & (gap_df["tier"] == 1)).sum())
    n_underpaying = int((gap_df["dollar_gap_vs_class1_trend"] > 0).sum())
    print(f"  citywide total: ${total_gap:,.0f} across {n_class2_tier1:,} class-2 tier-1 units "
          f"({n_underpaying:,} with gap > 0, {n_underpaying / n_class2_tier1:.1%})")

    griffin = gap_df[
        (gap_df.boro == GRIFFIN_BORO) & (gap_df.block == GRIFFIN_BLOCK) & (gap_df.lot == GRIFFIN_LOT)
    ]
    if len(griffin) == 1:
        g = griffin.iloc[0]
        print(f"  Griffin unit: sale_price=${g.sale_price:,.0f} actual_rate={g.effective_rate:.4%} "
              f"class1_trend_rate={g.class1_trend_rate:.4%} gap=${g.dollar_gap_vs_class1_trend:,.0f} "
              "(expected ~0 -- see module docstring)")
    else:
        print(f"  [WARN] Griffin unit-lot not found in gap output ({len(griffin)} rows)")

    con.register("gap_units", gap_df[["boro", "block", "lot", "condo_number", "dollar_gap_vs_class1_trend"]])
    print("\nAggregating dollar gap to building grain...")
    building_df = con.sql(BUILDING_GAP_SQL).df()
    building_out = os.path.join(CACHE, "building_effective_rates.parquet")
    building_df.to_parquet(building_out, index=False)
    print(f"  rewrote {building_out}")

    print("\n--- Stacking correlation check (v2 roadmap item 3, open question) ---")
    print("Does 421-a / co-op-condo abatement / LLC ownership concentrate among the")
    print("units this computation flags as most-underpaying (gap > 0) vs. the full")
    print("class-2 tier-1 population?")
    class2_tier1 = gap_df[(gap_df["class_prefix"] == "2") & (gap_df["tier"] == 1)]
    underpaying = class2_tier1[class2_tier1["dollar_gap_vs_class1_trend"] > 0]
    flags = ["has_421a_exemption", "has_j51_exemption", "has_coop_condo_abatement",
             "has_j51_abatement", "is_llc_or_lp"]
    print(f"{'flag':<28}{'all class-2 tier-1':>20}{'gap > 0 subset':>18}")
    for flag in flags:
        all_pct = class2_tier1[flag].mean()
        sub_pct = underpaying[flag].mean()
        print(f"{flag:<28}{all_pct:>19.1%}{sub_pct:>18.1%}")


if __name__ == "__main__":
    main()
