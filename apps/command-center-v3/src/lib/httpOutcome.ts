/**
 * httpOutcome.ts — what a response actually means, and whether retrying it can help.
 *
 * The defect this replaces (found by the browser/state matrix,
 * cc-whole-site-residual-v1): `useApi` did `if (!r.ok) throw`, so a 401 or a 403
 * fell into the same catch as a socket timeout. The operator was told
 * "showing last-good data · live refresh paused" — a transport story — when the
 * real answer was "you are not allowed to see this", and the client then burned
 * its entire backoff ladder (8 retries plus a 30s slow-retry loop) against an
 * endpoint that was never going to say yes. In the matrix the `unauthorized` and
 * `forbidden` columns took roughly thirty times longer per route than any other
 * state, purely from retries that could not succeed.
 *
 * An authorization failure is not transient. Neither is a 404 or a validation
 * error. Retrying them is not resilience; it is noise that hides the real state.
 *
 * Pure functions. No network, no React, no side effects.
 */

export type OutcomeClass =
  | 'OK'
  | 'NOT_MODIFIED'
  | 'UNAUTHORIZED'
  | 'FORBIDDEN'
  | 'CLIENT_ERROR'
  | 'RATE_LIMITED'
  | 'TIMEOUT'
  | 'SERVER_BUSY'
  | 'SERVER_ERROR'
  | 'NETWORK'

export type Outcome = {
  kind: OutcomeClass
  status: number | null
  /** True when no amount of retrying can change the answer without operator action. */
  terminal: boolean
  /** True only when a later identical request could plausibly succeed. */
  retryable: boolean
  /** Server-directed delay in ms, when the response asked for one. */
  retryAfterMs: number | null
  /** Operator-facing sentence. Never "reconnecting" for an authorization failure. */
  message: string
  /**
   * Whether the surface may keep showing the last-good body. Authorization
   * failures keep it — losing the data would be a second lie — but they never
   * clear the stale flag, because the data did not just get any fresher.
   */
  keepLastGood: boolean
}

const MAX_RETRY_AFTER_MS = 5 * 60_000

/**
 * Parse `Retry-After`, which is either delta-seconds or an HTTP-date.
 * Returns null for anything unparseable rather than guessing a delay.
 */
export function parseRetryAfter(value: string | null | undefined, nowMs: number = Date.now()): number | null {
  if (value == null) return null
  const raw = String(value).trim()
  if (!raw) return null
  if (/^\d+$/.test(raw)) {
    const ms = Number(raw) * 1000
    return Number.isFinite(ms) ? Math.min(Math.max(ms, 0), MAX_RETRY_AFTER_MS) : null
  }
  const when = Date.parse(raw)
  if (Number.isNaN(when)) return null
  return Math.min(Math.max(when - nowMs, 0), MAX_RETRY_AFTER_MS)
}

/** Classify an HTTP status. `headers` is optional so this stays testable. */
export function classifyStatus(
  status: number,
  headers?: { get(name: string): string | null } | null,
  nowMs: number = Date.now(),
): Outcome {
  const retryAfterMs = parseRetryAfter(headers?.get('Retry-After') ?? null, nowMs)
  const base = { status, retryAfterMs }

  if (status === 304) {
    return { ...base, kind: 'NOT_MODIFIED', terminal: false, retryable: false,
      message: 'not modified', keepLastGood: true }
  }
  if (status >= 200 && status < 300) {
    return { ...base, kind: 'OK', terminal: false, retryable: false, message: 'ok', keepLastGood: true }
  }
  if (status === 401) {
    return { ...base, kind: 'UNAUTHORIZED', terminal: true, retryable: false,
      message: 'not authorized — sign in or supply a valid credential; this will not resolve by waiting',
      keepLastGood: true }
  }
  if (status === 403) {
    return { ...base, kind: 'FORBIDDEN', terminal: true, retryable: false,
      message: 'forbidden — this operator is not permitted this surface; this will not resolve by waiting',
      keepLastGood: true }
  }
  if (status === 408) {
    return { ...base, kind: 'TIMEOUT', terminal: false, retryable: true,
      message: 'the server timed out reading the request — retrying', keepLastGood: true }
  }
  if (status === 425) {
    return { ...base, kind: 'TIMEOUT', terminal: false, retryable: true,
      message: 'too early — retrying', keepLastGood: true }
  }
  if (status === 429) {
    return { ...base, kind: 'RATE_LIMITED', terminal: false, retryable: true,
      message: 'rate limited — backing off', keepLastGood: true }
  }
  if (status >= 400 && status < 500) {
    // 404, 400, 409, 422 … the request itself is wrong. Repeating it verbatim
    // cannot make it right, and pretending otherwise hides the real problem.
    return { ...base, kind: 'CLIENT_ERROR', terminal: true, retryable: false,
      message: `request rejected (HTTP ${status}) — retrying the same request cannot change this`,
      keepLastGood: true }
  }
  if (status === 503) {
    return { ...base, kind: 'SERVER_BUSY', terminal: false, retryable: true,
      message: 'server busy — retrying', keepLastGood: true }
  }
  if (status >= 500) {
    return { ...base, kind: 'SERVER_ERROR', terminal: false, retryable: true,
      message: `server error (HTTP ${status}) — retrying`, keepLastGood: true }
  }
  return { ...base, kind: 'SERVER_ERROR', terminal: false, retryable: true,
    message: `unexpected HTTP ${status}`, keepLastGood: true }
}

/** Classify a thrown fetch error (abort, DNS, connection reset). */
export function classifyError(err: unknown): Outcome {
  const name = (err as { name?: string } | null)?.name
  const msg = (err as { message?: string } | null)?.message || 'fetch failed'
  if (name === 'AbortError') {
    return { kind: 'TIMEOUT', status: null, terminal: false, retryable: true, retryAfterMs: null,
      message: 'request timed out — server busy, retrying', keepLastGood: true }
  }
  return { kind: 'NETWORK', status: null, terminal: false, retryable: true, retryAfterMs: null,
    message: msg, keepLastGood: true }
}

/**
 * Should this outcome count toward the global "feeds are failing" banner?
 *
 * Only connectivity does. An authorization failure is not a broken connection,
 * and painting the reconnect bar for one tells the operator to wait for a
 * recovery that will never come.
 */
export function countsAsConnectionFailure(o: Outcome): boolean {
  return o.kind === 'NETWORK' || o.kind === 'TIMEOUT' || o.kind === 'SERVER_ERROR'
}
