/** One-shot reads that share the page's polling hooks (combined Home, operator order 2026-11-13).
 *
 *  Why: the combined Home mounts the classic Home and the operational (v010) section on one page. The v010 section reads
 *  each source once per load; two of those paths are also polled by hooks on the same page or in the shell chrome
 *  (since-close by SinceCloseCard, approvals/summary by NavRail + MetricStrip). A second GET for the same path in the
 *  same interval is load the server does not need (portfolio-server was SIGKILLed under memory pressure on 2026-11-13).
 *
 *  Rule, in order:
 *    1. a body a useApi hook received for exactly this path within `maxAgeMs` is used as is — no request;
 *    2. otherwise the read joins the hook's in-flight GET for that path (lib/inflightGet.ts, same key useApi uses), or
 *       starts one that the hooks will join — one request either way;
 *    3. a joined read that came back 304 (the hook revalidated with an ETag) means "unchanged": the hook's last good body
 *       is that answer. With no recorded body it is UNKNOWN, never OK.
 *  Same result contract as lib/homeV010 readOnce: never throws; a failed read is UNKNOWN / TIMED OUT, never OK. */

import { coalesceInFlight } from './inflightGet.ts'
import { noteLastGood, peekLastGood } from '../hooks/useApi.ts'
import { HOME_V010_TIMEOUT_MS, type Read } from './homeV010.ts'

export interface SharedReadOptions {
  /** How old a hook's body may be and still count as this read (default: 60 s, the shortest Home poll). */
  maxAgeMs?: number
  timeoutMs?: number
  fetchImpl?: typeof fetch
  nowMs?: () => number
}

type Wire = { ok: boolean; status: number; headers: Headers | { get(k: string): string | null }; text: string }

/** The { ok, data } unwrap readOnce applies, on an already-parsed body. */
export function readFromBody<T>(source: string, body: unknown, at: string): Read<T> {
  if (body && typeof body === 'object' && !Array.isArray(body)) {
    const env = body as { ok?: unknown; data?: unknown; reason?: unknown; code?: unknown }
    if (env.ok === false) {
      const why = (typeof env.reason === 'string' && env.reason) || (typeof env.code === 'string' && env.code) || 'ok:false'
      return { state: 'UNKNOWN', data: null, error: why, at, source }
    }
    if (env.ok === true && env.data && typeof env.data === 'object' && !Array.isArray(env.data)) {
      return { state: 'OK', data: env.data as T, error: null, at, source }
    }
  }
  return { state: 'OK', data: body as T, error: null, at, source }
}

export async function readShared<T>(source: string, opts: SharedReadOptions = {}): Promise<Read<T>> {
  const now = opts.nowMs ?? Date.now
  const maxAgeMs = opts.maxAgeMs ?? 60_000
  const timeoutMs = opts.timeoutMs ?? HOME_V010_TIMEOUT_MS
  const fetchImpl = opts.fetchImpl ?? ((...a: Parameters<typeof fetch>) => fetch(...a))

  // 1. A hook on this page already holds a recent body for this exact path.
  const held = peekLastGood(source)
  if (held && now() - held.at <= maxAgeMs && now() >= held.at) {
    return readFromBody<T>(source, held.json, new Date(held.at).toISOString())
  }

  // 2. Join (or start) the one in-flight GET for this path.
  const at = new Date(now()).toISOString()
  let timedOut = false
  let timer: ReturnType<typeof setTimeout> | undefined
  const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null
  const run = async (): Promise<Wire> => {
    const sep = source.includes('?') ? '&' : '?'
    // No If-None-Match: a joined hook must get a full body from this read, never an empty 304.
    const res = await fetchImpl(`${source}${sep}_=${now()}`, { signal: ctl?.signal, cache: 'no-store', credentials: 'same-origin' })
    return { ok: res.ok, status: res.status, headers: res.headers, text: await res.text() }
  }
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => { timedOut = true; ctl?.abort(); reject(new Error('timeout')) }, timeoutMs)
  })
  try {
    const r = await Promise.race([coalesceInFlight<Wire>(source, run), timeout])
    if (r.status === 304) {
      const last = peekLastGood(source)
      return last ? readFromBody<T>(source, last.json, new Date(last.at).toISOString())
        : { state: 'UNKNOWN', data: null, error: 'HTTP 304 with no recorded body', at, source }
    }
    if (!r.ok) return { state: 'UNKNOWN', data: null, error: `HTTP ${r.status}`, at, source }
    let body: unknown
    try { body = JSON.parse(r.text) } catch { return { state: 'UNKNOWN', data: null, error: 'body is not JSON', at, source } }
    noteLastGood(source, body, Date.parse(at))
    return readFromBody<T>(source, body, at)
  } catch (e) {
    if (timedOut) return { state: 'TIMED OUT', data: null, error: `no answer after ${Math.round(timeoutMs / 1000)} s`, at, source }
    return { state: 'UNKNOWN', data: null, error: e instanceof Error ? e.message : String(e), at, source }
  } finally {
    if (timer) clearTimeout(timer)
  }
}
