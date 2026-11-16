// Same-origin read client. It carries the browser's existing session (Tailscale identity via the
// existing serve listener). It never holds, reads or sends a token, and it issues GET only: the
// Wealth app has no write path, approval path or order path of its own.
//
// Shell guarantees (lead GO 2026-11-14T2313Z):
//  * single-flight: concurrent reads of one path share one request, aborted only when every caller has left;
//  * last good with age: a failed read keeps the last good body and says how old it is;
//  * per-reader timeout from the registry, so a slow 200 cannot stall the shell;
//  * heavy readers refuse a shell-originated read;
//  * no polling API: nothing here schedules a repeat. A page that refreshes owns its timer.
// `ok` below is HTTP-level only and is never a statement that the data is real: see renderState.
import type { ReaderSpec } from './readers.ts'
import { READERS, specFor } from './readers.ts'

export interface Envelope<T> {
  ok: boolean
  status: number
  data: T | null
  error: string | null
  fetchedAt: string
  lastGood: T | null
  lastGoodAt: string | null
  lastGoodAgeSeconds: number | null
  timedOut: boolean
  spec: ReaderSpec
}

export interface ReadOptions {
  signal?: AbortSignal
  /** 'shell' reads are refused for heavy readers. Pages pass 'page' (the default). */
  from?: 'shell' | 'page'
}

export interface ClientDeps {
  fetchImpl?: typeof fetch
  now?: () => number
  registry?: ReaderSpec[]
}

export class HeavyReaderFromShell extends Error {}

export function createClient(deps: ClientDeps = {}) {
  const doFetch: typeof fetch = deps.fetchImpl ?? ((input, init) => fetch(input, init))
  const now = deps.now ?? (() => Date.now())
  const registry = deps.registry ?? READERS
  // One shared request per path. It belongs to the client, not to its first caller: it is aborted only when
  // every subscriber has gone (each caller's signal releases its own hold), and an aborted flight is never
  // handed to a later caller. A caller without a signal holds the request until it settles.
  // Each flight carries a start sequence. Only a flight nobody abandoned may write last-good, and never over a
  // body from a flight that started later: a cancelled transport that resolves late cannot replace newer data.
  interface Flight { p: Promise<Envelope<unknown>>; ctl: AbortController; holders: number; seq: number }
  const inflight = new Map<string, Flight>()
  const lastGood = new Map<string, { data: unknown; at: number; seq: number }>()
  let flightSeq = 0

  function envelope<T>(path: string, spec: ReaderSpec, at: number, status: number, data: T | null, error: string | null, timedOut: boolean): Envelope<T> {
    const lg = lastGood.get(path)
    return {
      ok: data !== null, status, data, error,
      fetchedAt: new Date(at).toISOString(),
      lastGood: lg ? (lg.data as T) : null,
      lastGoodAt: lg ? new Date(lg.at).toISOString() : null,
      lastGoodAgeSeconds: lg ? Math.max(0, Math.round((now() - lg.at) / 1000)) : null,
      timedOut, spec,
    }
  }

  async function once<T>(path: string, spec: ReaderSpec, ctl: AbortController, seq: number): Promise<Envelope<T>> {
    const started = now()
    let timedOut = false
    const timer = setTimeout(() => { timedOut = true; ctl.abort() }, spec.timeoutMs)
    let status = 0
    let data: T | null = null
    let error: string | null = null
    try {
      const r = await doFetch(path, { method: 'GET', credentials: 'same-origin', signal: ctl.signal, headers: { Accept: 'application/json' } })
      status = r.status
      const body = r.headers.get('content-type')?.includes('json') ? await r.json() : null
      if (r.ok && body !== null) data = body as T
      else error = r.ok ? 'non-JSON body' : `HTTP ${r.status}`
    } catch (e) {
      error = timedOut ? `timed out after ${spec.timeoutMs} ms` : String(e)
    } finally {
      clearTimeout(timer)
    }
    if (data !== null && !ctl.signal.aborted) {
      const prev = lastGood.get(path)
      if (!prev || prev.seq < seq) lastGood.set(path, { data, at: started, seq })
    }
    return envelope<T>(path, spec, started, status, data, error, timedOut)
  }

  function get<T>(path: string, opts: ReadOptions = {}): Promise<Envelope<T>> {
    if (!path.startsWith('/api/')) throw new Error('wealth client reads canonical /api/ readers only')
    const spec = specFor(path, registry)
    if (spec.heavy && (opts.from ?? 'page') === 'shell') {
      throw new HeavyReaderFromShell(`${spec.path} is a heavy reader; only its own page may fetch it`)
    }
    const signal = opts.signal
    // A caller that has already left starts nothing and holds nothing; it gets the retained body, if any.
    if (signal?.aborted) return Promise.resolve(envelope<T>(path, spec, now(), 0, null, 'aborted before the read started', false))
    let f = inflight.get(path)
    if (!f || f.ctl.signal.aborted) {
      const ctl = new AbortController()
      const seq = ++flightSeq
      const flight: Flight = { ctl, holders: 0, seq, p: Promise.resolve(null as unknown as Envelope<unknown>) }
      flight.p = once<unknown>(path, spec, ctl, seq).finally(() => { if (inflight.get(path) === flight) inflight.delete(path) })
      inflight.set(path, flight)
      f = flight
    }
    const flight = f
    flight.holders += 1
    if (signal) {
      const leave = () => {
        flight.holders -= 1
        if (flight.holders <= 0 && inflight.get(path) === flight) { inflight.delete(path); flight.ctl.abort() }
      }
      signal.addEventListener('abort', leave, { once: true })
      // A settled read releases its listener, so a long-lived page signal does not accumulate one per poll.
      const detach = () => signal.removeEventListener('abort', leave)
      flight.p.then(detach, detach)
    }
    return flight.p as Promise<Envelope<T>>
  }

  return { get, inflightCount: () => inflight.size }
}

export const client = createClient()

/** Scaffold-compatible helper: a page read through the shared client. */
export function getJson<T>(path: string, signal?: AbortSignal): Promise<Envelope<T>> {
  return client.get<T>(path, { signal, from: 'page' })
}
