import type MiniSearch from "minisearch";
import { fetchGzipJson } from "./gzip-fetch";
import { BOROUGH_NAMES, escapeHtml, titleCaseAddress } from "./format";

export interface SearchRecord {
  id: number;
  bbl: string;
  addr: string;
  boro: string;
  lon: number;
  lat: number;
}

// Matches pipeline/11_build_tileset.py's build_search_index -- array-of-arrays
// [bbl, addr, boro, lon, lat], gzip-compressed (see that script's docstring
// for why: array-of-objects repeats every key name 856K times, and the
// uncompressed file alone was ~80MB, too much to keep in the repo raw).
type RawRecord = [string, string, string, number, number];

const INDEX_URL = `${import.meta.env.BASE_URL}${
  import.meta.env.DEV ? "search-index-sample.json.gz" : "search-index.json.gz"
}`;

let indexPromise: Promise<MiniSearch<SearchRecord>> | null = null;

// Dynamic import, not a static one -- MiniSearch has no reason to be in the
// initial bundle when the search box (and its data) are already lazy per
// PLAN.md's Performance strategy; keeping the import static bundled the
// whole library into first paint for a feature most visitors never touch.
function loadIndex(): Promise<MiniSearch<SearchRecord>> {
  if (!indexPromise) {
    indexPromise = Promise.all([import("minisearch"), fetchGzipJson<RawRecord[]>(INDEX_URL)]).then(
      async ([{ default: MiniSearch }, rows]) => {
        const ms = new MiniSearch<SearchRecord>({
          fields: ["addr", "bbl"],
          storeFields: ["bbl", "addr", "boro", "lon", "lat"],
          searchOptions: { prefix: true, fuzzy: 0.2, boost: { addr: 2 } },
        });
        // Indexing 856K citywide records takes several seconds -- addAllAsync
        // (not addAll) chunks the work so the map stays interactive instead
        // of the whole page hanging for that whole stretch.
        await ms.addAllAsync(
          rows.map(([bbl, addr, boro, lon, lat], id) => ({ id, bbl, addr, boro, lon, lat })),
          { chunkSize: 5000 },
        );
        return ms;
      },
    );
  }
  return indexPromise;
}

export function setupSearch(root: HTMLElement, onSelect: (record: SearchRecord) => void): void {
  root.innerHTML = `
    <input id="search-input" class="search-input" type="text" placeholder="Search address or BBL…" autocomplete="off" />
    <div id="search-results" class="search-results" hidden></div>
  `;
  const input = root.querySelector<HTMLInputElement>("#search-input")!;
  const results = root.querySelector<HTMLDivElement>("#search-results")!;

  let debounceTimer: number | undefined;
  let currentHits: SearchRecord[] = [];

  input.addEventListener("focus", () => {
    void loadIndex();
  });

  function hideResults() {
    results.hidden = true;
    results.innerHTML = "";
  }

  function renderHits(hits: SearchRecord[]) {
    currentHits = hits;
    if (!hits.length) {
      results.innerHTML = `<div class="search-empty">No matches</div>`;
      results.hidden = false;
      return;
    }
    results.innerHTML = hits
      .map(
        (h, i) => `
          <button type="button" class="search-result" data-idx="${i}">
            <span class="search-result-addr">${escapeHtml(titleCaseAddress(h.addr))}</span>
            <span class="search-result-boro">${escapeHtml(BOROUGH_NAMES[h.boro] ?? h.boro)}</span>
          </button>
        `,
      )
      .join("");
    results.hidden = false;
    results.querySelectorAll<HTMLButtonElement>(".search-result").forEach((btn, i) => {
      btn.addEventListener("click", () => {
        const hit = currentHits[i];
        input.value = titleCaseAddress(hit.addr);
        hideResults();
        onSelect(hit);
      });
    });
  }

  let requestId = 0;

  input.addEventListener("input", () => {
    window.clearTimeout(debounceTimer);
    const query = input.value.trim();
    if (!query) {
      hideResults();
      return;
    }
    const thisRequest = ++requestId;
    debounceTimer = window.setTimeout(async () => {
      // Building the citywide index (856K addresses) takes several seconds
      // the first time -- give immediate feedback rather than leaving the
      // box looking unresponsive/broken while it warms up.
      results.innerHTML = `<div class="search-empty">Loading search index&hellip;</div>`;
      results.hidden = false;
      const ms = await loadIndex();
      if (thisRequest !== requestId) return; // input changed while we were loading
      const hits = ms.search(query).slice(0, 8) as unknown as SearchRecord[];
      renderHits(hits);
    }, 150);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && currentHits.length && !results.hidden) {
      const hit = currentHits[0];
      input.value = titleCaseAddress(hit.addr);
      hideResults();
      onSelect(hit);
    } else if (e.key === "Escape") {
      hideResults();
    }
  });

  document.addEventListener("click", (e) => {
    if (!root.contains(e.target as Node)) hideResults();
  });
}
