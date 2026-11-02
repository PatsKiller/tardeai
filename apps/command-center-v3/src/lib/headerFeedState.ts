// The five header situations that must never render alike.
//
// On a hard reload the Command Center header used to paint every one of these the
// same way — as em dashes that read like "no data":
//   (a) the requests are still in flight            -> loading
//   (b) a request failed                            -> error
//   (c) data is present but a refresh failed        -> stale (last good retained)
//   (d) no payload was ever returned                -> unknown / undated
//
// This module is presentation only. It derives one aggregate state from the
// per-feed receipts useApi already exposes; it does not fetch, reorder requests,
// recompute values or change any formatting. `ready` is the fifth state: the
// header has data and nothing failed.
//
// Precedence (2026-11-02 review): a failed feed outranks everything; a feed that
// settled with no payload and no error is UNKNOWN — never ready and never merely
// "loading" — because an empty settled source is not evidence that everything is
// fine. A stale feed (data retained after a failed refresh) is reported before a
// still-loading sibling, as it always has been, so the surface never claims it is
// still assembling while it is in fact showing last-good data.

export type HeaderFeedState = 'loading' | 'error' | 'stale' | 'unknown' | 'ready'

export interface HeaderFeed {
  key: string
  label: string
  hasData: boolean
  /** initial load in flight (useApi only sets this while it has no data) */
  loading: boolean
  /** the request failed; the message is the transport/HTTP outcome, never invented */
  error: string | null
  /** data present but the latest refresh failed and last-good is retained */
  stale: boolean
  refetch?: () => void
}

export interface HeaderState {
  state: HeaderFeedState
  /** one honest line for the header banner */
  message: string | null
  /** the underlying error text, when there is one */
  detail: string | null
  /** feeds that failed with no payload (why this is an error) */
  failed: string[]
  /**
   * feeds that settled with no payload, no error and no load still in flight.
   * An empty settled source is unknown, not absence of a problem: one healthy
   * sibling must never hide it. Named so the banner can say which source.
   */
  unavailable: string[]
  /** feeds still on their first load */
  pending: string[]
  /** feeds showing retained last-good data after a failed refresh */
  staleFeeds: string[]
  /** feeds that do have data */
  available: string[]
  retryable: boolean
}

function unique(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)))
}

export function deriveHeaderFeedState(feeds: HeaderFeed[]): HeaderState {
  const all = feeds ?? []
  const available = all.filter(f => f.hasData).map(f => f.label)
  const failedFeeds = all.filter(f => !f.hasData && !!f.error)
  // Settled and empty: the request is over, nothing failed, no payload arrived,
  // and no load is still in flight. This is the fourth situation, and it must be
  // named rather than folded into "ready" whenever another feed happens to have
  // data.
  const unavailableFeeds = all.filter(f => !f.hasData && !f.error && !f.loading)
  const pending = all.filter(f => !f.hasData && !f.error && f.loading).map(f => f.label)
  const staleFeeds = all.filter(f => f.hasData && (!!f.error || f.stale)).map(f => f.label)
  const failed = failedFeeds.map(f => f.label)
  const unavailable = unavailableFeeds.map(f => f.label)
  const detail = unique(failedFeeds.map(f => String(f.error))).join(' · ') || null

  // No feeds were supplied at all: that is not a healthy header. Never a false
  // ready (kept from 6bcaca7fc; regression-tested).
  if (!all.length) {
    return {
      state: 'unknown',
      message: 'Header data unavailable — no payload returned',
      detail: null,
      failed,
      unavailable,
      pending,
      staleFeeds,
      available,
      retryable: true,
    }
  }

  // 1. A request that failed with no payload is an ERROR. It is never "no data"
  //    (nothing was returned) and never "stale" (there is no last good to show).
  if (failed.length) {
    return {
      state: 'error',
      message: available.length ? 'Some header feeds are unavailable' : 'Header data unavailable',
      detail,
      failed,
      unavailable,
      pending,
      staleFeeds,
      available,
      retryable: true,
    }
  }

  // 2. A source that settled with no payload is UNKNOWN, and is retryable. This
  //    applies even when a sibling has data: one healthy feed cannot vouch for a
  //    source that returned nothing. It also outranks a still-loading sibling —
  //    the settled-empty source is a fact, the loading one is only a hope.
  if (unavailable.length) {
    return {
      state: 'unknown',
      message: available.length
        ? 'Some header feeds returned no payload'
        : 'Header data unavailable — no payload returned',
      detail: null,
      failed,
      unavailable,
      pending,
      staleFeeds,
      available,
      retryable: true,
    }
  }

  // 3. Data is on screen. A failed refresh keeps the last good payload: that is
  //    stale — honestly labelled as last-good — not an error and not UNDATED.
  if (staleFeeds.length) {
    return {
      state: 'stale',
      message: 'Header feeds failed to refresh — showing last good data',
      detail: unique(all.filter(f => f.hasData && !!f.error).map(f => String(f.error))).join(' · ') || null,
      failed,
      unavailable,
      pending,
      staleFeeds,
      available,
      retryable: true,
    }
  }

  // 4. Nothing failed and nothing settled empty; some sources are still on their
  //    first load.
  if (pending.length) {
    return {
      state: 'loading',
      message: available.length ? 'Loading remaining header metrics…' : 'Loading header metrics…',
      detail: null,
      failed,
      unavailable,
      pending,
      staleFeeds,
      available,
      retryable: false,
    }
  }

  // 5. Data is present, nothing failed, nothing is empty, nothing is pending.
  return {
    state: 'ready',
    message: null,
    detail: null,
    failed,
    unavailable,
    pending,
    staleFeeds,
    available,
    retryable: false,
  }
}
