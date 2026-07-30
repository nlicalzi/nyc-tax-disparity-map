# Pipeline

Run in order. Each step reads/writes `data/cache/*.parquet` (gitignored --
re-run to regenerate, don't hand-edit).

```
set -a; source .env; set +a   # loads SOCRATA_APP_TOKEN

.venv/bin/python pipeline/01_fetch_valuation.py   # DOF valuation roll, FY2026 final (8y4t-faws)
.venv/bin/python pipeline/02_fetch_sales.py        # NYC sales 2016-2025 (w2pb-icbu)
.venv/bin/python pipeline/03_fetch_pluto.py        # PLUTO parcel/geometry base (64uk-42ks)
.venv/bin/python pipeline/04_build_effective_rates.py  # join + compute two-tier effective rate
.venv/bin/python pipeline/05_validate.py           # PASS/FAIL checks + summary stats
```

Add `--sample` to 01/02/03 to pull Manhattan only, for fast iteration.

See PLAN.md's "Data sources" / "Core metric" sections for why the metric is
two-tier (sale-verified vs. DOF-value fallback) and how the condo unit-lot
to PLUTO building-lot aggregation works.

## Outputs

- `data/cache/unit_effective_rates.parquet` -- one row per DOF unit-lot, the
  validated core computation.
- `data/cache/building_effective_rates.parquet` -- aggregated to PLUTO `bbl`
  grain, for map rendering (milestone 2+).
