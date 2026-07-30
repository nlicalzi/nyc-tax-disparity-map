"""Fetch the FY2026 final DOF assessment roll (dataset 8y4t-faws).

Usage:
    .venv/bin/python pipeline/01_fetch_valuation.py --sample   # Manhattan only, quick
    .venv/bin/python pipeline/01_fetch_valuation.py            # full citywide roll
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib.socrata import fetch_all  # noqa: E402

DATASET_ID = "8y4t-faws"
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "valuation_fy2026.parquet")

SELECT = ",".join(
    [
        "parid",
        "boro",
        "block",
        "lot",
        "year",
        "period",
        "curmktland",
        "curmkttot",
        "curactland",
        "curacttot",
        "curtrnland",
        "curtrntot",
        "curtxbtot",
        "curtaxclass",
        "bldg_class",
        "owner",
        "housenum_lo",
        "housenum_hi",
        "street_name",
        "zip_code",
        "units",
        "aptno",
        "condo_number",
    ]
)


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
        progress_label="valuation",
    )

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    print(f"Wrote {len(df)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
