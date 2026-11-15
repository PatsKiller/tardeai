// Stored news only: explicit user read, bounded concurrency, no producer or broker invocation.
import { useEffect, useRef, useState } from 'react'
import { getJson } from '../../../api/client'

type Wire = Record<string, unknown>
export interface StoredHeadline { title: string; source: string | null; url: string | null; publishedAt: string | null }
export interface StoredNewsRead { symbol: string; headlines: StoredHeadline[]; latest: string | null; rejected: number | null; error: string | null }
export interface StoredNewsProps { symbols: readonly string[] }
const object = (v: unknown): Wire => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Wire : {}
const text = (v: unknown): string | null => typeof v === 'string' && v.trim() ? v : null
export function headlineUrl(v: unknown): string | null {
  const raw = text(v)
  if (!raw) return null
  try { const u = new URL(raw); return (u.protocol === 'https:' || u.protocol === 'http:') && !u.username && !u.password ? u.href : null } catch { return null }
}
export function publishedClock(v: string | null): string {
  if (!v) return 'Publication time not served'
  if (!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(v)) return 'Published ' + v + ' · time zone not served'
  const at = Date.parse(v)
  return Number.isFinite(at) ? 'Published ' + new Date(at).toISOString() + ' (UTC)' : 'Publication time invalid · ' + v
}
export function decodeStoredNews(body: unknown, symbol: string): StoredNewsRead {
  const root = object(body), data = object(root.data)
  if (root.ok === false || data.ok !== true || data.symbol !== symbol || !Array.isArray(data.headlines))
    return {symbol, headlines: [], latest: null, rejected: null, error: 'Stored news response unavailable or incomplete'}
  const headlines: StoredHeadline[] = []
  for (const h of data.headlines) {
    const row = object(h), title = text(row.title)
    if (title) headlines.push({title, source: text(row.source), url: headlineUrl(row.url), publishedAt: text(row.published_at)})
  }
  return {symbol, headlines, latest: text(object(data.ingest).latest), rejected: typeof data.guard_rejected === 'number' ? data.guard_rejected : null, error: null}
}
export function StoredNews({symbols}: StoredNewsProps) {
  const names = [...new Set(symbols.map(s => s.toUpperCase().trim()).filter(Boolean))].sort()
  const key = names.join('|')
  const allowed = names.filter(s => /^[A-Z0-9]{1,8}$/.test(s))
  const rejected = names.length - allowed.length
  const controller = useRef<AbortController | null>(null)
  const generation = useRef(0)
  const [state, setState] = useState<{key: string; started: boolean; busy: boolean; reads: StoredNewsRead[]}>({key, started: false, busy: false, reads: []})
  useEffect(() => {
    generation.current++
    controller.current?.abort()
    setState({key, started: false, busy: false, reads: []})
    return () => { generation.current++; controller.current?.abort() }
  }, [key])
  const current = state.key === key ? state : {key, started: false, busy: false, reads: []}
  async function load() {
    controller.current?.abort()
    const ctl = new AbortController()
    controller.current = ctl
    const run = ++generation.current
    let cursor = 0
    const reads: StoredNewsRead[] = []
    setState({key, started: true, busy: true, reads: []})
    async function worker() {
      while (cursor < allowed.length && !ctl.signal.aborted) {
        const symbol = allowed[cursor++]
        let result: StoredNewsRead
        try {
          const env = await getJson<unknown>('/api/v2/news/symbol-headlines?symbol=' + encodeURIComponent(symbol) + '&hours=72', ctl.signal)
          result = env.ok && env.data !== null ? decodeStoredNews(env.data, symbol) : {symbol, headlines: [], latest: null, rejected: null, error: env.timedOut ? 'Stored news read timed out' : 'Stored news read failed'}
        } catch {
          result = {symbol, headlines: [], latest: null, rejected: null, error: 'Stored news read failed'}
        }
        if (ctl.signal.aborted || generation.current !== run) return
        reads.push(result)
        setState({key, started: true, busy: true, reads: [...reads]})
      }
    }
    await Promise.all(Array.from({length: Math.min(4, allowed.length)}, worker))
    if (!ctl.signal.aborted && generation.current === run) setState({key, started: true, busy: false, reads: [...reads]})
  }
  const successes = current.reads.filter(r => r.error === null)
  const failures = current.reads.filter(r => r.error !== null)
  const stories = successes.flatMap(r => r.headlines.map((h, index) => ({...h, symbol: r.symbol, index})))
  stories.sort((a,b) => (Date.parse(b.publishedAt || '') || 0) - (Date.parse(a.publishedAt || '') || 0))
  return <div aria-busy={current.busy}>
    <p>Stored headlines for {names.length} filtered holdings at or above the floor. Publication clocks belong to each source; news-ingest freshness is unverified.</p>
    <button type="button" className="hv-link" onClick={load} disabled={current.busy || !allowed.length}>{current.busy ? 'Reading stored news…' : current.started ? 'Refresh stored news' : 'Load stored news'}</button>
    {!names.length ? <p>No eligible holding in this slice. No news read requested.</p> : null}
    {rejected ? <p>{rejected} symbol{rejected === 1 ? '' : 's'} cannot be queried by this reader; coverage is partial.</p> : null}
    {current.started ? <p role="status">{successes.length} of {names.length} holdings read{failures.length || successes.length < names.length ? ' · partial' : ''}; {stories.length} stored headline{stories.length === 1 ? '' : 's'} returned. A zero return does not establish a current news feed.</p> : <p>News has not been read for this filter selection.</p>}
    {failures.map(r => <p key={r.symbol}>{r.symbol} · {r.error}; no empty-news verdict inferred.</p>)}
    {stories.map(h => <div key={h.symbol + '-' + h.index}><strong>{h.symbol}</strong> · {h.url ? <a href={h.url} target="_blank" rel="noopener noreferrer">{h.title}</a> : <span>{h.title} · source link not served</span>}<small>{h.source || 'Source not served'} · {publishedClock(h.publishedAt)}</small></div>)}
    {successes.filter(r => !r.headlines.length).map(r => <p key={r.symbol}>{r.symbol} · no matching stored headlines returned by the 72-hour query; ingest freshness unverified.</p>)}
  </div>
}
