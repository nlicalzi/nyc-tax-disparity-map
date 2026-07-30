"""Fetch NYC Citywide Annualized Calendar Sales, 2016-2025 (dataset w2pb-icbu).

Usage:
    .venv/bin/python pipeline/02_fetch_sales.py --sample   # Manhattan only, quick
    .venv/bin/python pipeline/02_fetch_sales.py            # full citywide sales history
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib.socrata import fetch_all  # noqa: E402

DATASET_ID = "w2pb-icbu"
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "sales_2016_2025.parquet")

SELECT = ",".join(
    [
        "borough",
        "block",
        "lot",
        "bbl",
        "address",
        "apartment_number",
        "sale_price",
        "sale_date",
        "tax_class_at_time_of_sale",
        "building_class_at_time_of",
    ]
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="Manhattan only, for prototyping")
    args = parser.parse_args()

    where = "borough='1'" if args.sample else None

    df = fetch_all(
        DATASET_ID,
        select=SELECT,
        where=where,
        order="borough,block,lot,sale_date",
        progress_label="sales",
    )

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    print(f"Wrote {len(df)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
