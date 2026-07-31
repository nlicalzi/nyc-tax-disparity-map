// Sequential single-hue ramp (blue, light -> dark), per dataviz skill's
// reference palette: light->dark blue for magnitude, applied to effective
// tax rate. r1/r2 tile fields are rate*10000 (basis points x100); the stops
// below are chosen in that same unit so no runtime division is needed.
//   0    -> 0.0%
//   100  -> 1.0%
//   200  -> 2.0%
//   300  -> 3.0%
//   450  -> 4.5%
//   600+ -> 6.0%+ (clamped)
export const RATE_STOPS: Array<[number, string]> = [
  [0, "#cde2fb"],
  [100, "#86b6ef"],
  [200, "#5598e7"],
  [300, "#2a78d6"],
  [450, "#1c5cab"],
  [600, "#0d366b"],
];

export const RATE_MIN = RATE_STOPS[0][0];
export const RATE_MAX = RATE_STOPS[RATE_STOPS.length - 1][0];

// Darker tone-on-tone step (matches the 700 ramp step) used for the tier-2
// hatch texture -- an "inked tone-on-tone" line per the dataviz skill's
// texture-fill guidance, used here as the primary tier1/tier2 distinguishing
// channel (a PLAN.md must-do), not just a CVD fallback.
export const HATCH_LINE_COLOR = "#0d366b";

// Neutral gray for the ~0.35% of buildings with no rate at all (exempt /
// missing valuation) -- distinct from both tiers, not part of the rate ramp.
export const NO_DATA_COLOR = "#c3c2b7";

// Tier-1 (sale-verified) buildings: rather than an independent rate x value
// bivariate grid (tried first -- a 3x3 grid with a muddy desaturated middle
// and a 9-box legend that's a puzzle to decode), encode the DIVERGENCE
// between rate and value directly. That's closer to the actual story: is
// this building's tax proportionate to its value, or do the two pull apart?
// Bucket each of rate/value into terciles (breaks below, from the real
// tier-1 citywide tercile split) and take valueTier - rateTier -> one
// diverging index from -2 (rate way exceeds value: overtaxed relative to
// worth) to +2 (value way exceeds rate: the "expensive = lower rate"
// headline case), 0 = proportionate. This is a real diverging palette --
// two hues + a neutral midpoint, the shape the dataviz skill's validator
// actually supports -- not an ad-hoc grid. The two arms are built by
// reusing the sequential blue ramp's exact OKLCH lightness/chroma at two
// steps and swapping in the categorical red hue, so both arms are
// perceptually symmetric by construction (equal step count per arm, per
// the skill's diverging-pair rule) rather than two independently-chosen
// colors. Adjacent-step CVD separation checked at 27.8-28.6 ΔE (well above
// the >=15 normal-vision floor) via validate_palette.js; the tool's
// chroma/single-hue FAILs are for checks that don't apply to a diverging
// shape (the neutral midpoint is deliberately low-chroma -- that's the
// point of a midpoint).
export const VALUE_BREAKS = [80, 120]; // mkt, $10K units: $800K, $1.2M
export const RATE_TIER_BREAKS = [90, 120]; // r1, rate x10000: 0.9%, 1.2%

// index -2..+2 -> hex. index 0 (proportionate) is the palette's own neutral.
export const DIVERGENCE_STEPS: Array<[number, string]> = [
  [-2, "#762221"],
  [-1, "#dd716a"],
  [0, "#f0efec"],
  [1, "#5598e7"],
  [2, "#104281"],
];

/** MapLibre expression: bucket mkt/r1 into terciles, then color by (valueTier - rateTier). */
export function divergenceColorExpression(mktField: unknown[], rateField: unknown[]): unknown[] {
  const valueTier = ["step", mktField, 0, VALUE_BREAKS[0], 1, VALUE_BREAKS[1], 2];
  const rateTier = ["step", rateField, 0, RATE_TIER_BREAKS[0], 1, RATE_TIER_BREAKS[1], 2];
  const index = ["-", valueTier, rateTier];
  const stops = DIVERGENCE_STEPS.flatMap(([step, color]) => [step, color]);
  return ["step", index, stops[1], ...stops.slice(2)];
}

/** Build a MapLibre `interpolate` color expression against a rate field, clamped to [RATE_MIN, RATE_MAX]. */
export function rateColorExpression(getField: unknown[]): unknown[] {
  const clamped = ["max", RATE_MIN, ["min", RATE_MAX, getField]];
  const stops = RATE_STOPS.flatMap(([stop, color]) => [stop, color]);
  return ["interpolate", ["linear"], clamped, ...stops];
}

/** Renders a 16x16 45-degree hatch pattern for use as a MapLibre fill-pattern image. */
export function makeHatchPattern(): ImageData {
  const size = 16;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  ctx.clearRect(0, 0, size, size);
  ctx.strokeStyle = HATCH_LINE_COLOR;
  ctx.globalAlpha = 0.55;
  ctx.lineWidth = 2;
  ctx.beginPath();
  // Two diagonal lines (plus wrapped corners) so the tile repeats seamlessly.
  for (const offset of [-size, 0, size]) {
    ctx.moveTo(offset, size);
    ctx.lineTo(offset + size, 0);
  }
  ctx.stroke();
  return ctx.getImageData(0, 0, size, size);
}
