// One /api/v2/sectors/monitor read per page load (LQ-20261107-312).
//
// The sectors hub fetches this payload for its own table and also renders the actionable
// decision board, which used to fetch the same route itself: two identical requests, ~5 s
// each, on every /v3/sectors load (measured in a browser 2026-11-07 — one navigation, two
// requests with the same cache-buster). The hub now hands its payload to the board.
//
// `undefined` is the only "nobody supplied it" value. The hub's own payload is `null` while
// its first response is in flight, and a `null` that meant "fetch it yourself" would put the
// second request back on exactly the load that is slowest.

/** True only when the caller supplied no payload at all — then, and only then, fetch. */
export function shouldFetchSectorMonitor(supplied: unknown): boolean {
  return supplied === undefined
}

/** What the board renders: the supplied payload when there is one, else its own fetch. */
export function sectorMonitorPayload<T>(supplied: T | undefined, fetched: T | null): T | null {
  return supplied === undefined ? fetched : supplied
}
