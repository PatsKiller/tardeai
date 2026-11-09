// One network read per path while a read for that path is already in flight.
//
// Why (LQ-20261107-1305, measured 2026-11-08 20:52 ET at 412 px on live beb570f97): NavRail and
// MetricStrip both mount in the shell and both called useApi(`${HOME_APPROVALS}/summary`, 60_000), so
// the page issued that GET twice on load and twice on every 60 s poll — two cache-busters, two
// responses (server log: paired 200s in the same second; an unauthenticated browser logs the identical
// 403 twice). The two surfaces are meant to read ONE number; one answer is enough for both.
//
// This is coalescing, not a cache. Nothing is reused after a request settles, so the next poll still
// reaches the server and a state change is never hidden behind a stale body. Different paths never
// share, and a rejected read is never handed to a later caller.
//
// The body is read by the caller's `run` function, not here: a Response body can be consumed once, so
// whatever is shared must already be a plain value (useApi shares `{ status, headers, text }`).

const inflight = new Map<string, Promise<unknown>>()

/** Join the in-flight read for `key`, or start one. Settles exactly like the read it wraps. */
export function coalesceInFlight<T>(key: string, run: () => Promise<T>): Promise<T> {
  const pending = inflight.get(key)
  if (pending) return pending as Promise<T>
  const request = run()
  inflight.set(key, request as Promise<unknown>)
  // A settled read stops being shareable — resolved OR rejected. (A later caller must reach the
  // server, never a finished answer.)
  const forget = () => { inflight.delete(key) }
  void request.then(forget, forget)
  return request
}

/** Test-only: forget every in-flight read so a suite starts from a clean module. */
export function resetInFlight(): void {
  inflight.clear()
}
