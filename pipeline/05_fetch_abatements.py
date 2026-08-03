"""Fetch the FY2026 DOF Property Abatement Detail roll (dataset rgyu-ii48).

Per-parcel abatement type (`tccode`) + dollar amount actually taken off the
tax bill (`appliedabt`, distinct from an exemption -- this reduces the tax
itself, not the taxable value it's computed from). Co-op/condo abatement:
tccode CONDO/COOP. J-51 *abatement*: tccode J51 (a building can carry both a
J-51 exemption in exemptions_fy2026.parquet and a separate J-51 abatement
here -- see PLAN.md's v2 roadmap item 3).

This dataset has no boro/block/lot columns -- only a padded fixed-width
`parid` (verified live: same boro(1)+block(5)+lot(4) digit layout as
01_fetch_valuation.py's own `parid`, e.g. "1000010010" -> boro=1 block=1
lot=10). Left un-parsed here and handled in 06_build_effective_rates.py, same
"raw select, transform downstream" split every other fetch script in this
pipeline follows.

Also unlike exemptions_fy2026.parquet (roll stages 1/3), this dataset is
genuinely quarterly -- `appliedabt` is a per-quarter installment, not a
repeated annual snapshot (verified live: one parcel's CONDO abatement showed
$2042.82/$2024.10/$2014.22/$2014.22 across 1Q-4Q, summing to a plausible
~$8,095 annual figure). No period filter here; all 4 quarters are fetched
and summed downstream to get the annual dollar amount.

Usage:
    .venv/bin/python pipeline/05_fetch_abatements.py --sample   # Manhattan only, quick
    .venv/bin/python pipeline/05_fetch_abatements.py            # full citywide roll
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from lib.socrata import fetch_all  # noqa: E402

DATASET_ID = "rgyu-ii48"
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "abatements_fy2026.parquet")

SELECT = ",".join(["parid", "taxyr", "tccode", "appliedabt", "period"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", action="store_true", help="Manhattan only, for prototyping")
    args = parser.parse_args()

    where = "taxyr='2026'"
    if args.sample:
        where += " AND starts_with(parid, '1')"

    df = fetch_all(
        DATASET_ID,
        select=SELECT,
        where=where,
        order="parid",
        progress_label="abatements",
    )

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    print(f"Wrote {len(df)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
