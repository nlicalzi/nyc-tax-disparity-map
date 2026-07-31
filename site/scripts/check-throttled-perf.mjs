// Milestone 6 (performance gate): measures "first tiles painted" against a
// real (CDP-throttled, not Lighthouse-simulated) network connection -- see
// PERFORMANCE.md for why the two measurement methods disagree enough to
// matter. Polls the performance.mark("first-tiles-painted") set in
// src/main.ts, fired once the buildings vector source finishes loading its
// initial-viewport tiles.
//
// Usage: node scripts/check-throttled-perf.mjs [--profile=slow4g|regular4g] [--trace] [--url=http://localhost:4173/]
import { chromium } from "playwright";

const PROFILES = {
  // Lighthouse's own default mobile throttle -- deliberately pessimistic,
  // commonly labeled "Slow 4G".
  slow4g: { rttMs: 150, downKbps: 1638.4, upKbps: 750 },
  // A more typical "regular 4G" connection.
  regular4g: { rttMs: 20, downKbps: 4000, upKbps: 3000 },
};

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, v] = a.replace(/^--/, "").split("=");
    return [k, v ?? true];
  }),
);
const profileName = args.profile ?? "slow4g";
const profile = PROFILES[profileName];
if (!profile) {
  console.error(`Unknown profile "${profileName}". Options: ${Object.keys(PROFILES).join(", ")}`);
  process.exit(1);
}
const url = args.url ?? "http://localhost:4173/";
const trace = Boolean(args.trace);

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 412, height: 823 } });
const client = await page.context().newCDPSession(page);

await client.send("Network.enable");
await client.send("Network.emulateNetworkConditions", {
  offline: false,
  latency: profile.rttMs,
  downloadThroughput: (profile.downKbps * 1024) / 8,
  uploadThroughput: (profile.upKbps * 1024) / 8,
});

const t0 = Date.now();
if (trace) {
  page.on("request", (req) => console.log(`${String(Date.now() - t0).padStart(6)}ms start ${req.url()}`));
  page.on("requestfinished", (req) => console.log(`${String(Date.now() - t0).padStart(6)}ms done  ${req.url()}`));
  page.on("requestfailed", (req) =>
    console.log(`${String(Date.now() - t0).padStart(6)}ms FAIL  ${req.url()} ${req.failure()?.errorText ?? ""}`),
  );
}

await page.goto(url, { waitUntil: "commit" });

let elapsedMs = null;
try {
  await page.waitForFunction(() => performance.getEntriesByName("first-tiles-painted").length > 0, {
    timeout: 30000,
  });
  elapsedMs = await page.evaluate(() => performance.getEntriesByName("first-tiles-painted")[0].startTime);
} catch {
  console.error("TIMEOUT waiting for first-tiles-painted mark (30s)");
}

console.log(JSON.stringify({ profile: profileName, url, firstTilesPaintedMs: elapsedMs }, null, 2));
await browser.close();
process.exit(elapsedMs === null ? 1 : 0);
