"""Validate the effective-rate pipeline against known anchors + print summary
stats. The agent reads this script's PASS/FAIL output, not the underlying
rows -- see PLAN.md's agent-workflow rules.

Usage:
    .venv/bin/python pipeline/08_validate.py
"""
import os
import sys

import duckdb

CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "cache")

GRIFFIN_BORO = "1"
GRIFFIN_BLOCK = "1030"
GRIFFIN_LOT = "1082"
GRIFFIN_SALE_PRICE = 239958219
GRIFFIN_RATE_MIN = 0.0025
GRIFFIN_RATE_MAX = 0.0045


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}{' -- ' + detail if detail else ''}")
    return condition


def main():
    con = duckdb.connect()
    units = con.sql(f"SELECT * FROM read_parquet('{CACHE}/unit_effective_rates.parquet')")
    buildings = con.sql(f"SELECT * FROM read_parquet('{CACHE}/building_effective_rates.parquet')")

    all_pass = True

    # --- Griffin penthouse anchor ---
    griffin = con.sql(f"""
        SELECT * FROM units
        WHERE boro = '{GRIFFIN_BORO}' AND block = '{GRIFFIN_BLOCK}' AND lot = '{GRIFFIN_LOT}'
    """).df()

    all_pass &= check("Griffin unit-lot found in output", len(griffin) == 1, f"{len(griffin)} rows")
    if len(griffin) == 1:
        row = griffin.iloc[0]
        all_pass &= check(
            "Griffin sale price matches known sale ($239,958,219)",
            row["sale_price"] == GRIFFIN_SALE_PRICE,
            f"got {row['sale_price']}",
        )
        all_pass &= check("Griffin unit is tier 1 (sale-verified)", row["tier"] == 1, f"tier={row['tier']}")
        all_pass &= check(
            f"Griffin effective rate in [{GRIFFIN_RATE_MIN:.2%}, {GRIFFIN_RATE_MAX:.2%}]",
            GRIFFIN_RATE_MIN <= row["effective_rate"] <= GRIFFIN_RATE_MAX,
            f"got {row['effective_rate']:.4%}",
        )
        # Griffin's own dollar-gap-vs-class1-trend is expected to be exactly
        # 0, not a bug -- a same-priced class-1 sale's fitted rate is itself
        # lower than what he actually pays (07_compute_dollar_gap.py's module
        # docstring has the full explanation). A nonzero value here would
        # mean the benchmark fit or the join regressed.
        all_pass &= check(
            "Griffin's dollar_gap_vs_class1_trend is 0 (see 07_compute_dollar_gap.py docstring)",
            row["dollar_gap_vs_class1_trend"] == 0,
            f"got {row['dollar_gap_vs_class1_trend']}",
        )

    # --- Sanity/coverage stats ---
    total_units = con.sql("SELECT COUNT(*) FROM units").fetchone()[0]
    tier1_units = con.sql("SELECT COUNT(*) FROM units WHERE tier = 1").fetchone()[0]
    null_rate_units = con.sql("SELECT COUNT(*) FROM units WHERE effective_rate IS NULL").fetchone()[0]
    total_buildings = con.sql("SELECT COUNT(*) FROM buildings").fetchone()[0]

    print()
    print("--- Summary ---")
    print(f"unit rows:               {total_units:,}")
    print(f"  tier 1 (sale-verified): {tier1_units:,} ({tier1_units / total_units:.1%})")
    print(f"  tier 2 (DOF fallback):  {total_units - tier1_units:,} ({(total_units - tier1_units) / total_units:.1%})")
    print(f"  null effective_rate:    {null_rate_units:,}")
    print(f"building rows:            {total_buildings:,}")

    # A residual few percent null is expected -- genuinely $0-value exempt/utility
    # parcels (no market value, no sale) have no computable rate. R0 condo
    # billing-lot placeholders are filtered upstream in 06_build_effective_rates.py.
    all_pass &= check("No more than 3% of units have a null effective_rate", null_rate_units / total_units < 0.03)

    # Guard against nominal/non-arms-length sales slipping through the
    # sale-price sanity filter (see MIN_SALE_TO_VALUE_RATIO in
    # 06_build_effective_rates.py) -- a sale-verified effective rate over
    # 100% of sale price is never a real transaction; found via a $130K
    # "sale" matched to a $1.054B building (BBL 1011300001) that a flat
    # dollar floor alone didn't catch.
    tier1_outliers = con.sql("SELECT COUNT(*) FROM units WHERE tier = 1 AND effective_rate > 1.0").fetchone()[0]
    all_pass &= check(
        "Fewer than 0.1% of tier-1 units have effective_rate > 100% (nominal-sale check)",
        tier1_outliers / tier1_units < 0.001,
        f"{tier1_outliers:,} of {tier1_units:,} ({tier1_outliers / tier1_units:.2%})",
    )

    # class-2 vs class-1 DOF-relative rate sanity check (should be ~5.6% vs ~1.2% per PLAN.md)
    class_avg = con.sql("""
        SELECT class_prefix, AVG(curtxbtot * class_rate / NULLIF(curmkttot, 0)) AS avg_dof_relative_rate
        FROM units
        WHERE curmkttot > 0
        GROUP BY class_prefix
        ORDER BY class_prefix
    """).df()
    print()
    print("DOF-relative rate by class (sanity check vs PLAN.md's ~1.2%/~5.6% expectation):")
    print(class_avg.to_string(index=False))

    # --- Dollar-gap-vs-class1-trend sanity (07_compute_dollar_gap.py) ---
    # Bounded well below the rejected "sale_price x class_rate" counterfactual
    # ($38.6B, see PLAN.md's v2 roadmap item 1 pitfall note) -- a regression
    # guard in case a future edit accidentally reintroduces that comparison.
    gap_stats = con.sql("""
        SELECT SUM(dollar_gap_vs_class1_trend) AS total_gap,
               COUNT(*) FILTER (WHERE dollar_gap_vs_class1_trend > 0) AS n_underpaying,
               COUNT(*) FILTER (WHERE class_prefix = '2' AND tier = 1) AS n_class2_tier1
        FROM units
    """).df().iloc[0]
    print()
    print(f"dollar_gap_vs_class1_trend: ${gap_stats.total_gap:,.0f} total, "
          f"{gap_stats.n_underpaying:,.0f}/{gap_stats.n_class2_tier1:,.0f} class-2 tier-1 units with gap > 0")
    all_pass &= check(
        "Citywide dollar_gap_vs_class1_trend is well below the rejected full-value counterfactual ($38.6B)",
        1e6 < gap_stats.total_gap < 1e9,
        f"got ${gap_stats.total_gap:,.0f}",
    )
    # Not an exact match -- ~0.2% of class-2 tier-1 units don't resolve to any
    # PLUTO bbl (same known gap as 06_build_effective_rates.py's ~98.8%
    # unit->building match rate) and their gap dollars have nowhere to
    # aggregate to. Those units skew higher-value, so the dollar-weighted
    # shortfall (~5%) is bigger than the ~0.2% count-weighted one -- verified
    # directly (215 of 124,046 units, $3.34M of the $67.68M total). Bound
    # generously (10%) rather than exact-match, but still catch a real
    # aggregation bug (e.g. double-counting or dropping a whole borough).
    building_gap_total = con.sql(
        "SELECT SUM(building_dollar_gap_vs_class1_trend) FROM buildings"
    ).fetchone()[0]
    all_pass &= check(
        "Building-level dollar_gap within 10% of the unit-level total (some units never match a PLUTO bbl)",
        abs(building_gap_total - gap_stats.total_gap) / gap_stats.total_gap < 0.10,
        f"unit total ${gap_stats.total_gap:,.0f} vs building total ${building_gap_total:,.0f}",
    )

    print()
    if all_pass:
        print("ALL CHECKS PASSED")
    else:
        print("SOME CHECKS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
