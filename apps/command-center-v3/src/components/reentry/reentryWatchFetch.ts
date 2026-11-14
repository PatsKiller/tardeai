// LQ-20261113-3062 (review 3051 A3): the Re-Entry rotation workspace's watchlist read.
//
// /api/v2/watchlist/items is a StaleServe route. Its first read after a night (or under a full admission) is
// HTTP 503 {ok:false, status:'UNKNOWN', error:'build_deferred', reason, retry_after_sec}. The old raw fetch read the
// body, found no `items`, wrote nothing and rendered an empty watch row with no retry: an UNKNOWN shown as empty.
// Here a non-OK answer (or a body that is not an items list, or a thrown fetch) marks every symbol of the chunk
// UNKNOWN with the HTTP status, the server's reason and its retry hint; the caller shows it and retries.
// Pure: fetch is injected, so the unit test needs no browser and no server.

export const WATCH_CHUNK = 80
export const WATCH_CONCURRENCY = 2
/** Used when the server gives no retry hint. */
export const DEFAULT_RETRY_SEC = 15
/** A server hint is clamped into [MIN, MAX] seconds. */
export const MIN_RETRY_SEC = 1
export const MAX_RETRY_SEC = 120
/** After this many failed retries the page stops retrying and says so. */
export const MAX_RETRIES = 6

export type WatchUnknown = {
  state: 'UNKNOWN'
  symbols: string[]
  /** HTTP status; null when fetch threw (network error) before any answer. */
  httpStatus: number | null
  error: string
  reason: string | null
  /** The server's retry hint in seconds, when it gave one. */
  retryAfterSec: number | null
}

export type WatchLoad = { items: Record<string, any>; unknown: WatchUnknown[] }

type FetchFn = (url: string, init?: RequestInit) => Promise<Response>

function unwrap(value: any): any {
  let result = value
  for (let i = 0; i < 3 && result?.data && typeof result.data === 'object'; i += 1) result = result.data
  return result ?? {}
}

function positive(value: unknown): number | null {
  const n = Number(value)
  return Number.isFinite(n) && n > 0 ? n : null
}

export function watchItemsUrl(chunk: string[]): string {
  return `/api/v2/watchlist/items?symbols=${encodeURIComponent(chunk.join(','))}`
}

function isAbort(error: unknown): boolean {
  return (error as any)?.name === 'AbortError'
}

/** One chunk. Never returns "nothing": either items, or an UNKNOWN naming every symbol of the chunk. */
export async function fetchWatchChunk(fetchFn: FetchFn, chunk: string[], signal?: AbortSignal): Promise<WatchLoad> {
  let response: Response
  try {
    response = await fetchFn(watchItemsUrl(chunk), { cache: 'no-store', signal })
  } catch (error) {
    if (isAbort(error)) throw error
    return { items: {}, unknown: [{ state: 'UNKNOWN', symbols: [...chunk], httpStatus: null, error: String((error as any)?.message || error || 'network error'), reason: null, retryAfterSec: null }] }
  }
  let body: any = null
  try { body = await response.json() } catch (error) { if (isAbort(error)) throw error }
  const payload = unwrap(body)
  const items = Array.isArray(payload?.items) ? payload.items : null
  if (!response.ok || payload?.ok === false || items === null) {
    const retryAfterSec = positive(payload?.retry_after_sec ?? body?.retry_after_sec) ?? positive(response.headers?.get?.('Retry-After'))
    return {
      items: {},
      unknown: [{
        state: 'UNKNOWN',
        symbols: [...chunk],
        httpStatus: response.status,
        error: String(payload?.error || body?.error || (response.ok ? 'no items list in the answer' : `HTTP ${response.status}`)),
        reason: payload?.reason ?? body?.reason ?? null,
        retryAfterSec,
      }],
    }
  }
  const out: Record<string, any> = {}
  for (const item of items) {
    const sym = String(item?.symbol || '').toUpperCase()
    if (sym) out[sym] = item
  }
  return { items: out, unknown: [] }
}

/** Every symbol, in chunks of WATCH_CHUNK, at most WATCH_CONCURRENCY in flight. */
export async function loadWatchMap(fetchFn: FetchFn, symbols: string[], signal?: AbortSignal): Promise<WatchLoad> {
  const items: Record<string, any> = {}
  const unknown: WatchUnknown[] = []
  let cursor = 0
  const worker = async () => {
    while (!signal?.aborted) {
      const index = cursor
      cursor += WATCH_CHUNK
      if (index >= symbols.length) return
      const got = await fetchWatchChunk(fetchFn, symbols.slice(index, index + WATCH_CHUNK), signal)
      Object.assign(items, got.items)
      unknown.push(...got.unknown)
    }
  }
  const lanes = Math.min(WATCH_CONCURRENCY, Math.ceil(symbols.length / WATCH_CHUNK) || 1)
  await Promise.all(Array.from({ length: lanes }, () => worker()))
  return { items, unknown }
}

/** Seconds until the next retry: the largest server hint, clamped; DEFAULT_RETRY_SEC when there is none. */
export function retryDelaySec(unknown: WatchUnknown[]): number {
  const hints = unknown.map(u => u.retryAfterSec).filter((n): n is number => n !== null)
  const sec = hints.length ? Math.max(...hints) : DEFAULT_RETRY_SEC
  return Math.min(MAX_RETRY_SEC, Math.max(MIN_RETRY_SEC, Math.ceil(sec)))
}

/** The symbols whose watch data is UNKNOWN, upper-cased. */
export function unknownSymbols(unknown: WatchUnknown[]): Set<string> {
  return new Set(unknown.flatMap(u => u.symbols.map(s => String(s).toUpperCase())))
}

/** The operator-facing line: state, cause, and when it retries (or that retries stopped). */
export function watchUnknownMessage(unknown: WatchUnknown[], retry: { inSec: number | null; attempt: number }): string {
  if (!unknown.length) return ''
  const count = unknownSymbols(unknown).size
  const causes = [...new Set(unknown.map(u => `${u.httpStatus === null ? 'network error' : `HTTP ${u.httpStatus}`} ${u.error}${u.reason ? ` (${u.reason})` : ''}`))].join('; ')
  const next = retry.inSec === null
    ? `retry stopped after ${retry.attempt} retr${retry.attempt === 1 ? 'y' : 'ies'} — reload the page to try again`
    : `retrying in ${retry.inSec} s (retry ${retry.attempt + 1} of ${MAX_RETRIES})`
  return `Watchlist data UNKNOWN for ${count} symbol${count === 1 ? '' : 's'}: ${causes} — ${next}. Price, RSI, resistance and trend for these symbols are not known, not empty.`
}
