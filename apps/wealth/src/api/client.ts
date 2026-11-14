// Same-origin read client. It carries the browser's existing session (Tailscale identity via the
// existing serve listener). It never holds, reads or sends a token, and it issues GET only: the
// Wealth app has no write path, approval path or order path of its own.
//
// Shell guarantees (lead GO 2026-11-14T2313Z):
//  * single-flight: concurrent reads of one path share one request;
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
  const inflight = new Map<string, Promise<Envelope<unknown>>>()
  const lastGood = new Map<string, { data: unknown; at: number }>()

  async function once<T>(path: string, spec: ReaderSpec, signal?: AbortSignal): Promise<Envelope<T>> {
    const started = now()
    const ctl = new AbortController()
    let timedOut = false
    const timer = setTimeout(() => { timedOut = true; ctl.abort() }, spec.timeoutMs)
    const onOuterAbort = () => ctl.abort()
    signal?.addEventListener('abort', onOuterAbort)
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
      signal?.removeEventListener('abort', onOuterAbort)
    }
    if (data !== null) lastGood.set(path, { data, at: started })
    const lg = lastGood.get(path)
    return {
      ok: data !== null, status, data, error,
      fetchedAt: new Date(started).toISOString(),
      lastGood: lg ? (lg.data as T) : null,
      lastGoodAt: lg ? new Date(lg.at).toISOString() : null,
      lastGoodAgeSeconds: lg ? Math.max(0, Math.round((now() - lg.at) / 1000)) : null,
      timedOut, spec,
    }
  }

  function get<T>(path: string, opts: ReadOptions = {}): Promise<Envelope<T>> {
    if (!path.startsWith('/api/')) throw new Error('wealth client reads canonical /api/ readers only')
    const spec = specFor(path, registry)
    if (spec.heavy && (opts.from ?? 'page') === 'shell') {
      throw new HeavyReaderFromShell(`${spec.path} is a heavy reader; only its own page may fetch it`)
    }
    const pending = inflight.get(path)
    if (pending) return pending as Promise<Envelope<T>>
    const p = once<T>(path, spec, opts.signal).finally(() => inflight.delete(path))
    inflight.set(path, p as Promise<Envelope<unknown>>)
    return p
  }

  return { get, inflightCount: () => inflight.size }
}

export const client = createClient()

/** Scaffold-compatible helper: a page read through the shared client. */
export function getJson<T>(path: string, signal?: AbortSignal): Promise<Envelope<T>> {
  return client.get<T>(path, { signal, from: 'page' })
}
