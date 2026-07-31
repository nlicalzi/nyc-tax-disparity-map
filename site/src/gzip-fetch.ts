/** Fetch + parse a gzip-compressed JSON asset (search index, scatter sample).
 * Some static hosts (Vite's dev server among them) recognize the .gz
 * extension and transparently decode it, setting Content-Encoding: gzip on
 * the response -- fetch() then hands back already-decompressed bytes.
 * Others (plain GitHub Pages, unconfirmed either way) serve the raw gzip
 * bytes as-is. `res.headers` reflects the header as sent regardless of
 * which happened, so it's a reliable signal for whether decoding already
 * happened -- decompressing twice throws, not a no-op. */
export async function fetchGzipJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok || !res.body) throw new Error(`gzip json fetch failed (${url}): ${res.status}`);
  if (res.headers.get("content-encoding") === "gzip") {
    return res.json() as Promise<T>;
  }
  const stream = res.body.pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).json() as Promise<T>;
}
