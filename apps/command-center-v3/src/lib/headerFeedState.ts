// The four header situations that must never render alike.
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
  const pending = all.filter(f => !f.hasData && !f.error && f.loading).map(f => f.label)
  const staleFeeds = all.filter(f => f.hasData && (!!f.error || f.stale)).map(f => f.label)
  const failed = failedFeeds.map(f => f.label)
  const detail = unique(failedFeeds.map(f => String(f.error))).join(' · ') || null

  // A request that failed with no payload is an ERROR. It is never "no data"
  // (nothing was returned) and never "stale" (there is no last good to show).
  if (failed.length) {
    return {
      state: 'error',
      message: available.length ? 'Some header feeds are unavailable' : 'Header data unavailable',
      detail,
      failed,
      pending,
      staleFeeds,
      available,
      retryable: true,
    }
  }

  // Nothing has ever loaded: distinguish "still trying" from "finished empty".
  if (!available.length) {
    if (pending.length) {
      return {
        state: 'loading',
        message: 'Loading header metrics…',
        detail: null,
        failed,
        pending,
        staleFeeds,
        available,
        retryable: false,
      }
    }
    return {
      state: 'unknown',
      message: 'Header data unavailable — no payload returned',
      detail: null,
      failed,
      pending,
      staleFeeds,
      available,
      retryable: true,
    }
  }

  // Data is on screen. A failed refresh keeps the last good payload: that is
  // stale — honestly labelled as last-good — not an error and not UNDATED.
  if (staleFeeds.length) {
    return {
      state: 'stale',
      message: 'Header feeds failed to refresh — showing last good data',
      detail: unique(all.filter(f => f.hasData && !!f.error).map(f => String(f.error))).join(' · ') || null,
      failed,
      pending,
      staleFeeds,
      available,
      retryable: true,
    }
  }

  if (pending.length) {
    return {
      state: 'loading',
      message: 'Loading remaining header metrics…',
      detail: null,
      failed,
      pending,
      staleFeeds,
      available,
      retryable: false,
    }
  }

  return {
    state: 'ready',
    message: null,
    detail: null,
    failed,
    pending,
    staleFeeds,
    available,
    retryable: false,
  }
}
