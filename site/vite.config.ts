import { defineConfig } from "vite";

// GitHub Pages project-page base path -- https://nlicalzi.github.io/nyc-tax-disparity-map/,
// not a custom domain or user/org root page. App code reads asset paths via
// import.meta.env.BASE_URL (see main.ts/search.ts/scatter.ts), so this is
// the only place the path needs to be set.
export default defineConfig({
  base: "/nyc-tax-disparity-map/",
});
