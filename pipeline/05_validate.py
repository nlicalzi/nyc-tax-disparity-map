"""Validate the effective-rate pipeline against known anchors + print summary
stats. The agent reads this script's PASS/FAIL output, not the underlying
rows -- see PLAN.md's agent-workflow rules.

Usage:
    .venv/bin/python pipeline/05_validate.py
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
    # billing-lot placeholders are filtered upstream in 04_build_effective_rates.py.
    all_pass &= check("No more than 3% of units have a null effective_rate", null_rate_units / total_units < 0.03)

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

    print()
    if all_pass:
        print("ALL CHECKS PASSED")
    else:
        print("SOME CHECKS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
