# NYC Property Tax Disparity Map

A static, no-backend site showing how NYC's property tax system produces
lower *effective* tax rates for ultra-luxury condos/co-ops than for modest
homes — because co-ops and condos are assessed via the "comparable rental
income" method rather than sale price.

**Live site**: https://www.nlicalzi.com/nyc-tax-disparity-map/
(`nlicalzi.github.io/nyc-tax-disparity-map/` also works — it 301-redirects
here, since the account's root Pages site already has this custom domain
configured, which GitHub extends to all project sites under the account)

See [PLAN.md](./PLAN.md) for the full design doc and [PERFORMANCE.md](./PERFORMANCE.md)
for the performance-gate results and roadmap.

## Status

All 7 milestones are done: data pipeline, tile build, static map MVP,
interactivity (popups/search/filters), narrative/scrollytelling layer,
performance gate, and deploy to GitHub Pages. See milestones in PLAN.md.

## Running the site

```
cd site
npm install
npm run dev      # http://localhost:5173, uses the Manhattan dev-sample tileset
npm run build && npm run preview   # full citywide tileset, as deployed
```

## Deployment

Pushes to `main` build and deploy automatically via
`.github/workflows/deploy.yml` (GitHub Actions → GitHub Pages): `npm ci &&
npm run build` in `site/`, then publish `site/dist/`. No manual build step
or committed `dist/` needed. `site/vite.config.ts`'s `base` is set to the
repo's project-page path (`/nyc-tax-disparity-map/`) — update it if the repo
is ever renamed or moved to a custom domain.

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
