"""Fetch PLUTO tabular fields (dataset 64uk-42ks) -- geometry pull happens
separately in the milestone-2 tile build, not here.

Usage:
    .venv/bin/python pipeline/03_fetch_pluto.py --sample   # Manhattan only, quick
    .venv/bin/python pipeline/03_fetch_pluto.py            # full citywide PLUTO
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib.socrata import fetch_all  # noqa: E402

DATASET_ID = "64uk-42ks"
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "pluto.parquet")

SELECT = ",".join(
    [
        "bbl",
        "borough",
        "block",
        "lot",
        "address",
        "zipcode",
        "latitude",
        "longitude",
        "unitsres",
        "unitstotal",
        "bldgclass",
        "landuse",
        "assessland",
        "assesstot",
        "numfloors",
        "yearbuilt",
        "condono",
    ]
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="Manhattan only, for prototyping")
    args = parser.parse_args()

    where = "borough='MN'" if args.sample else None

    df = fetch_all(
        DATASET_ID,
        select=SELECT,
        where=where,
        order="borough,block,lot",
        progress_label="pluto",
    )

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    print(f"Wrote {len(df)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
