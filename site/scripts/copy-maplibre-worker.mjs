// maplibre-gl v6 resolves its worker script relative to its own bundle URL
// at runtime (`new URL('./maplibre-gl-worker.mjs', import.meta.url)`), which
// Vite's static asset analysis can't follow -- the worker (and the shared
// chunk it imports) end up missing from both the dev server's dep-optimized
// output and the production build. Self-hosting a verbatim copy in public/
// and pointing maplibre-gl at it via setWorkerUrl() (see src/main.ts)
// sidesteps that entirely. Re-run this (via postinstall) whenever
// maplibre-gl is upgraded.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..", "node_modules", "maplibre-gl", "dist");
const dest = join(here, "..", "public", "vendor", "maplibre");

mkdirSync(dest, { recursive: true });
for (const file of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
  copyFileSync(join(src, file), join(dest, file));
}
console.log(`Copied maplibre-gl worker files to ${dest}`);
