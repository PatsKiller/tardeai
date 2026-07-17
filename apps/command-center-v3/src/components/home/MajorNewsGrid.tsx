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

function domain(u?: string): string {
  try { return new URL(u || '').hostname.replace(/^www\./, '') } catch { return '' }
}

export default function MajorNewsGrid() {
  const { data: book } = useApi<any>('/api/v2/portfolio/book-map', 120_000)
  const [sym, setSym] = useState<string | null>(null)
  const { data: news } = useApi<any>(sym ? `/api/v2/news/symbol-headlines?symbol=${sym}` : '', 0, { enabled: !!sym } as any)

  const rows: any[] = (book?.rows || [])
    .filter((r: any) => /^[A-Z]{1,6}$/.test(r.symbol))
    .sort((a: any, b: any) => Math.abs(b.day_change_pct ?? 0) - Math.abs(a.day_change_pct ?? 0))
    .slice(0, 24)
  const ingest = news?.ingest

  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderLeft: `3px solid ${BB.amber}`, borderRadius: 2, padding: '10px 12px' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 6, flexWrap: 'wrap' }}>
        <span style={{ fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.06em', color: BB.text2 }}>MAJOR NEWS</span>
        <span style={{ fontSize: 8.5, fontWeight: 700, color: BB.text3, textTransform: 'uppercase' }}>· your names by |day %| · guarded headlines on click</span>
        <span style={{ flex: 1 }} />
        <a href={`${FQDN}/v3/reports?mode=archive`} style={{ fontSize: TYPE.xs, fontWeight: 700, color: T.link, textDecoration: 'none' }}>All news →</a>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(86px, 1fr))', gap: 4 }}>
        {rows.map((r: any) => {
          const p = Number(r.day_change_pct ?? 0)
          const big = Math.abs(p) >= 2
          return (
            <button key={`${r.symbol}-${r.account}`} onClick={() => setSym(r.symbol)} style={{
              display: 'flex', justifyContent: 'space-between', gap: 4, alignItems: 'baseline',
              padding: '5px 7px', borderRadius: 2, cursor: 'pointer',
              background: heatRamp(p), border: big ? `1.5px solid ${p >= 0 ? BB.green : BB.red}` : `1px solid ${BB.borderHair}`,
            }}>
              <span style={{ ...numStyle, fontSize: TYPE.xs, fontWeight: 800, color: '#fff' }}>{r.symbol}</span>
              <span style={{ ...numStyle, fontSize: 9, fontWeight: 700, color: '#fff' }}>{p >= 0 ? '+' : ''}{p.toFixed(2)}%</span>
            </button>
          )
        })}
      </div>

      {sym && (
        <div onClick={() => setSym(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 300, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div onClick={e => e.stopPropagation()} style={{ width: 560, maxWidth: '92vw', maxHeight: '80vh', overflowY: 'auto', background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: 16 }}>
            {(() => {
              const row = rows.find((r: any) => r.symbol === sym)
              const p = Number(row?.day_change_pct ?? 0)
              return (
                <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', marginBottom: 10 }}>
                  <span style={{ ...numStyle, fontSize: TYPE.lg, fontWeight: 800, color: BB.text1 }}>{sym}</span>
                  <span style={{ ...numStyle, fontSize: TYPE.base, fontWeight: 700, color: p >= 0 ? BB.green : BB.red }}>{p >= 0 ? '+' : ''}{p.toFixed(2)}%</span>
                  {row && <span style={{ fontSize: 9, fontWeight: 800, color: BB.green }}>● HELD</span>}
                  <span style={{ flex: 1 }} />
                  <button onClick={() => setSym(null)} style={{ fontSize: TYPE.sm, color: BB.text3, background: 'transparent', border: 'none', cursor: 'pointer' }}>✕</button>
                </div>
              )
            })()}
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
                    no recent guarded headlines for {sym} (guard rejected {news.guard_rejected ?? 0}) — silence is stated, never padded
                  </div>
                )}
                <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                  <a href={`${FQDN}/v3/portfolio?symbol=${sym}`} style={{ fontSize: TYPE.xs, fontWeight: 700, padding: '3px 10px', borderRadius: 2, background: `${T.link}18`, color: T.link, textDecoration: 'none' }}>Open security card</a>
                  <a href={`${FQDN}/v3/watch?symbol=${sym}`} style={{ fontSize: TYPE.xs, fontWeight: 700, padding: '3px 10px', borderRadius: 2, background: `${BB.green}18`, color: BB.green, textDecoration: 'none' }}>Watch desk</a>
                  <a href={`${FQDN}/v3/risk?symbol=${sym}`} style={{ fontSize: TYPE.xs, fontWeight: 700, padding: '3px 10px', borderRadius: 2, background: `${BB.amber}18`, color: BB.amber, textDecoration: 'none' }}>Risk / stops</a>
                  <span style={{ flex: 1 }} />
                  {ingest && <span style={{ fontSize: 8.5, color: BB.text3 }}>{Number(ingest.guarded_72h).toLocaleString()} headlines · 72h · latest {rel(ingest.latest)}</span>}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
