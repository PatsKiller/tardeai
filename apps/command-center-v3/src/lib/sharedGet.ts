// One read per URL, shared by every component that mounts at the same time.
//
// Why (measured 2026-11-07 19:20 ET, /v3/intelligence/classic at 412 px): the page made 21 identical
// GET /api/v2/llm/oauth-lanes calls and 26 GET /api/v2/inference/ensemble calls in 27 s and never
// reached network idle. Neither endpoint is polled on this page: each mounted card reads it once. The
// card list is rebuilt every time one of ~13 feeds resolves, so the cards remounted and each remount
// re-read. One answer for the whole burst (and a short cache so a remount inside the same paint costs
// nothing) removes the duplicates; it does not hide a real state change, because the TTL is shorter
// than every caller's own poll interval.

type CacheEntry = { at: number; value: unknown }

const cache = new Map<string, CacheEntry>()
const inFlight = new Map<string, Promise<unknown>>()

/** Default window in which an identical read is answered from the last response. Shorter than the
 *  4 s ensemble poll and far shorter than the 90 s/120 s lane polls, so a caller's own poll cadence
 *  is unchanged. */
export const DEFAULT_TTL_MS = 1_500

export async function sharedGetJSON<T = unknown>(url: string, ttlMs: number = DEFAULT_TTL_MS): Promise<T> {
  const hit = cache.get(url)
  if (hit && Date.now() - hit.at < ttlMs) return hit.value as T
  const pending = inFlight.get(url)
  if (pending) return pending as Promise<T>
  const request = (async () => {
    try {
      const res = await fetch(url, { cache: 'no-store' })
      const json = (await res.json()) as T
      cache.set(url, { at: Date.now(), value: json })
      return json
    } finally {
      inFlight.delete(url)
    }
  })()
  inFlight.set(url, request)
  // A rejected read is never cached: the next caller must reach the server, not the failure.
  void request.catch(() => { cache.delete(url) })
  return request as Promise<T>
}

/** Test-only: drop both maps so a suite starts from a clean module. */
export function resetSharedGet(): void {
  cache.clear()
  inFlight.clear()
}
