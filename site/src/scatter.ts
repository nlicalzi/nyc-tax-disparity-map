import * as Plot from "@observablehq/plot";
import { fetchGzipJson } from "./gzip-fetch";
import { formatMoney, formatRate } from "./format";

export interface ScatterRow {
  key: string;
  saleK: number; // sale price, $1000 units
  rateBp: number; // effective rate, basis points (rate * 10000)
  cls: "1" | "2";
  boro: string;
}

// Matches pipeline/08_build_tileset.py's build_scatter_sample -- array-of-arrays
// [unit_key, sale_k, rate_bp, cls, boro], gzip-compressed, same pattern as
// the search index (see gzip-fetch.ts).
type RawRow = [string, number, number, string, string];

const SCATTER_URL = `${import.meta.env.BASE_URL}${
  import.meta.env.DEV ? "scatter-sample-dev.json.gz" : "scatter-sample.json.gz"
}`;

// Griffin's individual unit-lot (boro-block-lot, not the PLUTO building bbl)
// -- see pipeline/08_build_tileset.py's GRIFFIN_UNIT_* constants and
// PLAN.md's "The story" section for the validated anchor figures this point
// must match ($239,958,219 sale, ~0.35% effective rate).
export const GRIFFIN_KEY = "1-1030-1082";

const CLASS_LABELS: Record<string, string> = {
  "1": "1–3 family home",
  "2": "co-op / condo / rental",
};

// Validated categorical pair (dataviz skill's slots 1/2, blue/green) --
// `node scripts/validate_palette.js "#2a78d6,#008300" --mode light --pairs all`
// passes every check (all-pairs CVD/normal-vision floors, contrast) for a
// 2-series scatter. Only two slots needed since the sample is restricted to
// tax classes 1/2 (see pipeline script's comment on why).
const CLASS_COLORS: Record<string, string> = {
  "1": "#2a78d6",
  "2": "#008300",
};

// Rates cluster under ~3% (see pipeline exploration: p90 is 1.4-2.3% for
// both classes) with a long thin tail up to the 25% ceiling backstop
// (pipeline/04's EFFECTIVE_RATE_CEILING -- itself flagged there as an
// imperfect backstop, not a clean signal). Capping the axis keeps the
// meaningful bulk of the pattern readable instead of a few outliers
// stretching the scale flat; `clamp: true` pins off-scale points to the top
// edge rather than silently dropping them.
const Y_DOMAIN_MAX_PCT = 8;

// Ordinary-least-squares fit of y on x. Used below to fit effective rate
// against log10(sale price), not raw sale price -- the x-axis is a log
// scale because price spans orders of magnitude, so a fit computed against
// the *raw* price would be dominated by the handful of highest-price points
// and wouldn't render as a straight line on a log-x chart anyway. Fitting
// against log10(price) instead means each unit of slope is directly
// interpretable as "rate change per 10x change in price", and (since the
// x-scale itself is log) the fitted line renders as a straight segment when
// plotted back in raw-price/log-scale coordinates.
function linearRegression(points: Array<[number, number]>): { slope: number; intercept: number } {
  const n = points.length;
  let sumX = 0;
  let sumY = 0;
  let sumXY = 0;
  let sumXX = 0;
  for (const [x, y] of points) {
    sumX += x;
    sumY += y;
    sumXY += x * y;
    sumXX += x * x;
  }
  const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX);
  const intercept = (sumY - slope * sumX) / n;
  return { slope, intercept };
}

interface FitPoint {
  saleK: number;
  y: number;
  cls: "1" | "2";
}

/** Per-class least-squares fit line (two endpoint points, spanning that
 * class's own observed price range) plus the slope in the interpretable
 * "percentage points of rate per 10x price" unit -- see linearRegression's
 * comment for why log10(price) is the fitted variable. */
function fitByClass(data: ScatterRow[]): { lines: FitPoint[]; slopes: Record<"1" | "2", number> } {
  const lines: FitPoint[] = [];
  const slopes = {} as Record<"1" | "2", number>;
  for (const cls of ["1", "2"] as const) {
    const rows = data.filter((d) => d.cls === cls);
    if (rows.length < 2) continue;
    const points: Array<[number, number]> = rows.map((d) => [Math.log10(d.saleK), d.rateBp / 100]);
    const { slope, intercept } = linearRegression(points);
    slopes[cls] = slope;
    const xs = points.map(([x]) => x);
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    lines.push(
      { saleK: 10 ** xMin, y: intercept + slope * xMin, cls },
      { saleK: 10 ** xMax, y: intercept + slope * xMax, cls },
    );
  }
  return { lines, slopes };
}

let dataPromise: Promise<ScatterRow[]> | null = null;

/** Dynamic import target for @observablehq/plot lives in main.ts/story.ts --
 * this module itself is only ever reached via a dynamic import, so a static
 * import here is fine (it never pulls Plot into the app's initial chunk). */
export function loadScatterData(): Promise<ScatterRow[]> {
  if (!dataPromise) {
    dataPromise = fetchGzipJson<RawRow[]>(SCATTER_URL).then((rows) =>
      rows.map(([key, saleK, rateBp, cls, boro]) => ({
        key,
        saleK,
        rateBp,
        cls: cls as "1" | "2",
        boro,
      })),
    );
  }
  return dataPromise;
}

export function renderScatterChart(container: HTMLElement, data: ScatterRow[]): void {
  const griffin = data.find((d) => d.key === GRIFFIN_KEY);
  const width = container.clientWidth || 640;
  // Leaves room below the plot for the caption appended after it -- height
  // is measured once, before that caption exists, so without this the plot
  // would claim the container's full height and push the caption off-screen.
  const CAPTION_HEIGHT = 34;
  const height = (container.clientHeight || 460) - CAPTION_HEIGHT;
  const { lines: fitLines, slopes } = fitByClass(data);

  const plot = Plot.plot({
    width,
    height,
    marginLeft: 56,
    marginBottom: 40,
    marginTop: 34,
    marginRight: 16,
    style: {
      background: "transparent",
      color: "var(--text-primary, #0b0b0b)",
      fontFamily: "inherit",
      fontSize: "12px",
    },
    x: {
      type: "log",
      label: "Sale price (verified, log scale) →",
      tickFormat: (d: number) => formatMoney(d * 1000),
    },
    y: {
      label: "↑ Effective tax rate",
      domain: [0, Y_DOMAIN_MAX_PCT],
      clamp: true,
      grid: true,
      tickFormat: (d: number) => `${d}%`,
    },
    color: {
      domain: ["1", "2"],
      range: [CLASS_COLORS["1"], CLASS_COLORS["2"]],
      legend: true,
      label: "Tax class",
      tickFormat: (d: string) => CLASS_LABELS[d] ?? d,
    },
    marks: [
      Plot.gridY({ stroke: "var(--border, #e1e0d9)" }),
      Plot.dot(data, {
        x: "saleK",
        y: (d: ScatterRow) => d.rateBp / 100,
        fill: "cls",
        fillOpacity: 0.35,
        r: 3,
        tip: true,
        channels: {
          Class: (d: ScatterRow) => CLASS_LABELS[d.cls] ?? d.cls,
          Borough: "boro",
        },
        title: (d: ScatterRow) => `${formatMoney(d.saleK * 1000)} sale · ${formatRate(d.rateBp)} effective rate`,
      }),
      // Per-class least-squares fit (see fitByClass) -- the visual answer to
      // "it's not just one building": co-op/condo's line trends down as
      // price rises, 1-3 family's stays close to flat. Dashed and drawn
      // above the dots (opaque, unlike the dots' 0.35 fillOpacity) so the
      // trend reads clearly through the scatter without a separate legend
      // entry -- it reuses the same `cls` color channel as the dots.
      Plot.line(fitLines, {
        x: "saleK",
        y: "y",
        stroke: "cls",
        strokeWidth: 2.5,
        strokeDasharray: "5,4",
      }),
      // Griffin's own point, called out per marks-and-anatomy's "label the
      // one series the story is about" -- a surface-color halo first so the
      // highlight ring stays legible against overlapping data dots, then
      // the ring itself (>=8px per the skill's end-marker spec) and a
      // direct label, never a value on every point.
      ...(griffin
        ? [
            Plot.dot([griffin], {
              x: "saleK",
              y: (d: ScatterRow) => d.rateBp / 100,
              r: 9,
              fill: "var(--surface-1, #fcfcfb)",
              fillOpacity: 0.9,
            }),
            Plot.dot([griffin], {
              x: "saleK",
              y: (d: ScatterRow) => d.rateBp / 100,
              r: 8,
              fill: "none",
              stroke: "var(--text-primary, #0b0b0b)",
              strokeWidth: 2,
            }),
            Plot.text([griffin], {
              x: "saleK",
              y: (d: ScatterRow) => d.rateBp / 100,
              text: () => "Ken Griffin's penthouse",
              // Anchored up-and-left of the ring rather than centered above
              // it -- Griffin's sale price sits near the top of the citywide
              // distribution, so a centered/right-leaning label would run
              // off the chart's right edge.
              dx: -12,
              dy: -12,
              textAnchor: "end",
              fontWeight: 600,
              fill: "var(--text-primary, #0b0b0b)",
            }),
          ]
        : []),
    ],
  });

  const caption = document.createElement("p");
  caption.className = "scatter-caption";
  caption.innerHTML = describeSlopes(slopes);

  container.replaceChildren(plot, caption);
}

/** Plain-language summary of the fitted slopes, computed from the same real
 * sample the chart plots -- not a hardcoded claim, so it can't drift out of
 * sync with the data. `slope` is pp of effective rate per 10x change in
 * price (see linearRegression's comment). */
function describeSlopes(slopes: Record<"1" | "2", number>): string {
  const fmt = (s: number) => `${s >= 0 ? "+" : ""}${s.toFixed(2)} pp`;
  const parts: string[] = [];
  if (slopes["2"] != null) {
    parts.push(`co-op/condo/rental: ${fmt(slopes["2"])} per 10&times; price`);
  }
  if (slopes["1"] != null) {
    parts.push(`1&ndash;3 family: ${fmt(slopes["1"])} per 10&times; price`);
  }
  return `Line of best fit, this sample &mdash; ${parts.join(" &middot; ")}.`;
}
