import { useState } from 'react'
import { useApi } from '../../hooks/useApi'
import { BB, T, TYPE, numStyle, heatRamp } from '../../lib/watchTokens'

// Home v2 WS-C: Major News grid — held + top-watch symbols as heat cells; click pops a modal
// of GUARDED headlines (news_symbol_guard server-side; zero headlines = honest empty state).
// Every outbound link target=_blank rel=noopener noreferrer. Modal actions: security card /
// watch page — actionable, not a dead end.

const FQDN = typeof window !== 'undefined' ? window.location.origin : ''

function rel(ts?: string): string {
  if (!ts) return ''
  const ms = Date.now() - new Date(ts).getTime()
  const h = ms / 3.6e6
  if (h < 1) return `${Math.max(1, Math.round(h * 60))}m ago`
  if (h < 24) return `${Math.round(h)}h ago`
  return `${Math.round(h / 24)}d ago`
}

/** A day percent that was not reported is null — never zero. `+0.00%` is a measurement; "not reported" is not. */
function pctOf(v: any): number | null {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

function pctText(p: number | null): string {
  return p == null ? '—' : `${p >= 0 ? '+' : ''}${p.toFixed(2)}%`
}

function domain(u?: string): string {
  try { return new URL(u || '').hostname.replace(/^www\./, '') } catch { return '' }
}

/** The modal's body — extracted so the FQ-090 "not reported" sentence can be rendered and asserted directly. */
export function MajorNewsModalBody({ symbol, row, news, ingest, onClose }: {
  symbol: string
  row?: any
  news?: any
  ingest?: any
  onClose: () => void
}) {
  const p = pctOf(row?.day_change_pct)
  return (
    <>
      <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', marginBottom: 10 }}>
        <span style={{ ...numStyle, fontSize: TYPE.lg, fontWeight: 800, color: BB.text1 }}>{symbol}</span>
        <span data-day-pct={p == null ? 'not-reported' : p.toFixed(2)} style={{ ...numStyle, fontSize: TYPE.base, fontWeight: 700, color: p == null ? BB.text3 : p >= 0 ? BB.green : BB.red }}>{pctText(p)}</span>
        {p == null && <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>day change not reported</span>}
        {row && <span style={{ fontSize: 9, fontWeight: 800, color: BB.green }}>● HELD</span>}
        <span style={{ flex: 1 }} />
        <button onClick={onClose} style={{ fontSize: TYPE.sm, color: BB.text3, background: 'transparent', border: 'none', cursor: 'pointer' }}>✕</button>
      </div>
      {!news ? <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>loading headlines…</div> : (
        <>
          {(news.headlines || []).map((h: any, i: number) => (
            <a key={i} href={h.url || '#'} target="_blank" rel="noopener noreferrer" style={{
              display: 'flex', gap: 8, alignItems: 'baseline', padding: '6px 0', borderBottom: `1px solid ${BB.borderHair}`, textDecoration: 'none',
            }}>
              <span style={{ fontSize: 8.5, fontWeight: 700, color: BB.text3, border: `1px solid ${BB.borderHair}`, borderRadius: 2, padding: '0 5px', flexShrink: 0 }}>{domain(h.url) || h.source || 'source'}</span>
              <span style={{ fontSize: TYPE.sm, color: BB.text1, flex: 1 }}>{h.title}</span>
              <span style={{ ...numStyle, fontSize: 9, color: BB.text3, flexShrink: 0 }}>{rel(h.published_at)}</span>
            </a>
          ))}
          {(news.headlines || []).length === 0 && (
            <div style={{ fontSize: TYPE.sm, color: BB.text3, padding: '10px 0' }}>
              no recent guarded headlines for {symbol} (guard rejected {news.guard_rejected ?? 0}) — silence is stated, never padded
            </div>
          )}
          <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <a href={`${FQDN}/v3/portfolio?symbol=${symbol}`} style={{ fontSize: TYPE.xs, fontWeight: 700, padding: '3px 10px', borderRadius: 2, background: `${T.link}18`, color: T.link, textDecoration: 'none' }}>Open security card</a>
            <a href={`${FQDN}/v3/watch?symbol=${symbol}`} style={{ fontSize: TYPE.xs, fontWeight: 700, padding: '3px 10px', borderRadius: 2, background: `${BB.green}18`, color: BB.green, textDecoration: 'none' }}>Watch desk</a>
            <a href={`${FQDN}/v3/risk?symbol=${symbol}`} style={{ fontSize: TYPE.xs, fontWeight: 700, padding: '3px 10px', borderRadius: 2, background: `${BB.amber}18`, color: BB.amber, textDecoration: 'none' }}>Risk / stops</a>
            <span style={{ flex: 1 }} />
            {ingest && <span style={{ fontSize: 8.5, color: BB.text3 }}>{Number(ingest.guarded_72h).toLocaleString()} headlines · 72h · latest {rel(ingest.latest)}</span>}
          </div>
        </>
      )}
    </>
  )
}

export default function MajorNewsGrid() {
  // FQ-090: the read's own state travels with the numbers. `stale` is the hook's "showing
  // last-good data after a failed refetch"; `receivedAt` is when that read arrived; `transport`
  // names how it arrived (a 304 RETAINED is not a failure). An old read must never pass as fresh.
  const { data: book, stale: bookStale, transport: bookTransport, receivedAt: bookReceivedAt } = useApi<any>('/api/v2/portfolio/book-map', 120_000)
  const [sym, setSym] = useState<string | null>(null)
  const { data: news } = useApi<any>(sym ? `/api/v2/news/symbol-headlines?symbol=${sym}` : '', 0, { enabled: !!sym } as any)

  // dedupe by symbol (multi-account holdings rendered one cell per account — operator bug
  // 2026-07-17); same symbol has the same day % across accounts, day $ summed for tooltip
  const rows: any[] = (() => {
    const by = new Map<string, any>()
    for (const r of (book?.rows || [])) {
      if (!/^[A-Z]{1,6}$/.test(r.symbol)) continue
      const prev = by.get(r.symbol)
      if (prev) {
        // A sum is a measurement only when every account reported its dollar move; null + null
        // silently became 0 and the tooltip printed a fabricated +$0.
        const a = pctOf(prev.day_change)
        const b = pctOf(r.day_change)
        prev.day_change = a == null || b == null ? null : a + b
      } else by.set(r.symbol, { ...r })
    }
    return [...by.values()]
      .sort((a, b) => {
        const pa = pctOf(a.day_change_pct)
        const pb = pctOf(b.day_change_pct)
        if (pa == null && pb == null) return String(a.symbol).localeCompare(String(b.symbol))
        if (pa == null) return 1
        if (pb == null) return -1
        return Math.abs(pb) - Math.abs(pa)
      })
      .slice(0, 24)
  })()
  // which cells actually HAVE guarded headlines — marked BEFORE the click
  const symbolsKey = rows.map(r => r.symbol).join(',')
  const { data: hlCounts } = useApi<any>(symbolsKey ? `/api/v2/news/headline-counts?symbols=${symbolsKey}` : '', 300_000, { enabled: !!symbolsKey } as any)
  const counts: Record<string, number> = hlCounts?.counts || {}
  const ingest = news?.ingest

  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderLeft: `3px solid ${BB.amber}`, borderRadius: 2, padding: '10px 12px' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 6, flexWrap: 'wrap' }}>
        <span style={{ fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.06em', color: BB.text2 }}>MAJOR NEWS</span>
        <span style={{ fontSize: 8.5, fontWeight: 700, color: BB.text3, textTransform: 'uppercase' }}>· your names by |day %| · badge = guarded headlines · dim = none in 72h</span>
        {/* FQ-090: the book's own clock, said out loud. A date-only as_of is not an intraday quote time. */}
        <span data-testid="major-news-asof" title={[book?.as_of ? `book-map as_of ${book.as_of}` : 'book-map reported no as_of', `transport ${bookTransport ?? 'UNKNOWN'}`].join(' · ')}
          style={{ fontSize: 10, fontWeight: 700, color: BB.text3 }}>
          · {book?.as_of ? `as of ${String(book.as_of).slice(0, 10)}${String(book.as_of).length <= 10 ? ' · no intraday quote time' : ''}` : 'quote time not reported'}
          {/* A retained read after a failed refresh is not fresh; say which one it is and when it arrived. */}
          {bookStale && ` · quote read failed, showing the last good read${bookReceivedAt ? ` (${String(bookReceivedAt).slice(11, 19)}Z)` : ''}`}
        </span>
        <span style={{ flex: 1 }} />
        <a href={`${FQDN}/v3/reports?mode=archive`} style={{ fontSize: TYPE.xs, fontWeight: 700, color: T.link, textDecoration: 'none' }}>All news →</a>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(86px, 1fr))', gap: 4 }}>
        {rows.map((r: any) => {
          const p = pctOf(r.day_change_pct)
          const big = p != null && Math.abs(p) >= 2
          const n = counts[r.symbol] ?? null
          const hasNews = (n ?? 0) > 0
          // FQ-090: the dollar move is its own value with its own absence. `?? 0` printed a
          // fabricated `+$0` beside a real -2.50%, a sign that contradicted the percent.
          const d = pctOf(r.day_change)
          const dayTitle = p == null
            ? 'change not reported'
            : d == null
              ? `${pctText(p)} · dollar move not reported`
              : `${pctText(p)} · ${d >= 0 ? '+' : ''}$${Math.round(d).toLocaleString()}`
          return (
            <button key={r.symbol} onClick={() => setSym(r.symbol)}
              title={`${r.symbol} · day ${dayTitle}${n != null ? ` · ${n} guarded headline${n === 1 ? '' : 's'} 72h` : ''}`}
              style={{
                display: 'flex', justifyContent: 'space-between', gap: 4, alignItems: 'baseline',
                padding: '5px 7px', borderRadius: 2, cursor: 'pointer',
                background: heatRamp(p), border: big ? `1.5px solid ${(p as number) >= 0 ? BB.green : BB.red}` : `1px solid ${BB.borderHair}`,
                opacity: n != null && !hasNews ? 0.55 : 1,
              }}>
              <span style={{ ...numStyle, fontSize: TYPE.xs, fontWeight: 800, color: '#fff' }}>
                {r.symbol}{hasNews && <span style={{ fontSize: 8, fontWeight: 800, marginLeft: 3, color: '#fff', background: 'rgba(255,255,255,.25)', borderRadius: 2, padding: '0 3px' }}>{n}</span>}
              </span>
              <span data-day-pct={p == null ? 'not-reported' : p.toFixed(2)} style={{ ...numStyle, fontSize: 9, fontWeight: 700, color: p == null ? BB.text3 : '#fff' }}>{pctText(p)}</span>
            </button>
          )
        })}
      </div>

      {sym && (
        <div onClick={() => setSym(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 300, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div onClick={e => e.stopPropagation()} style={{ width: 560, maxWidth: '92vw', maxHeight: '80vh', overflowY: 'auto', background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: 16 }}>
            <MajorNewsModalBody symbol={sym} row={rows.find((r: any) => r.symbol === sym)} news={news} ingest={ingest} onClose={() => setSym(null)} />
          </div>
        </div>
      )}
    </div>
  )
}
