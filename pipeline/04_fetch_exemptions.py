"""Fetch the FY2026 DOF Property Exemption Detail roll (dataset muvi-b6kx).

Per-parcel exemption codes + dollar amount removed from taxable value (421-a,
J-51, senior/veteran/clergy, etc.) -- see PLAN.md's v2 roadmap item 3
("stacked benefits"). Filtered to period='3' (final roll), matching
01_fetch_valuation.py's vintage -- unlike the abatement dataset (quarterly
installments, see 05_fetch_abatements.py), this one carries the same
tentative/changed/final roll-stage periods as the valuation table itself
(verified live: periods 1 and 3 both present for year=2026, with different
exmp_code rows between them for the same parcel -- period 3 is the final
stage, not a duplicate).

Usage:
    .venv/bin/python pipeline/04_fetch_exemptions.py --sample   # Manhattan only, quick
    .venv/bin/python pipeline/04_fetch_exemptions.py            # full citywide roll
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib.socrata import fetch_all  # noqa: E402

DATASET_ID = "muvi-b6kx"
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "exemptions_fy2026.parquet")

SELECT = ",".join(["boro", "block", "lot", "year", "period", "exmp_code", "curexmptot"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="Manhattan only, for prototyping")
    args = parser.parse_args()

    where = "year='2026' AND period='3'"
    if args.sample:
        where += " AND boro='1'"

    df = fetch_all(
        DATASET_ID,
        select=SELECT,
        where=where,
        order="boro,block,lot",
        progress_label="exemptions",
    )

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    print(f"Wrote {len(df)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
