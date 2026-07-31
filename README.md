# NYC Property Tax Disparity Map

A static, no-backend site showing how NYC's property tax system produces
lower *effective* tax rates for ultra-luxury condos/co-ops than for modest
homes — because co-ops and condos are assessed via the "comparable rental
income" method rather than sale price.

See [PLAN.md](./PLAN.md) for the full design doc.

## Status

Milestones 1 (data pipeline), 2 (tile build), 3 (static map MVP), and 4
(popups/search/filters) are done. See milestones in PLAN.md.

## Running the site

```
cd site
npm install
npm run dev      # http://localhost:5173, uses the Manhattan dev-sample tileset
npm run build && npm run preview   # full citywide tileset, as deployed
```

## Data vintage

- DOF assessment roll: FY2026 final roll (`year='2026'`, `period='3'`,
  dataset `8y4t-faws`).
- Tax class rates: FY2026 adopted rates (Class 1: 19.843%, Class 2: 12.439%,
  Class 3: 11.108%, Class 4: 10.848%), from
  nyc.gov/site/finance/property/property-tax-rates.page, verified 2026-07-30.
- Sales: NYC Citywide Annualized Calendar Sales, 2016-01-01 through
  2025-12-31 (dataset `w2pb-icbu`).
- Effective rate is two-tier: sale-verified (tax ÷ actual recent sale price)
  where a qualifying sale exists, DOF-value fallback (tax ÷ DOF's own market
  value) otherwise. See PLAN.md's "Core metric" section for why this split
  is necessary.

## Re-fetching data

See `pipeline/README.md`.
