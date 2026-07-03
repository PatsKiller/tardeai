import { useState } from 'react'
import FibChartModal, { type FibLevel } from './FibChartModal'

// Multi-timeframe swing + Fibonacci + cross-timeframe confluence for one symbol. Lazy-loaded (the
// analysis fetches 3 yfinance charts), so it only runs when the operator expands it on a card.
// Source: /api/v2/symbol/fib-confluence. Advisory/read-only — verify against your own charts.

const C = { card: { background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8 } as const }
const conf = (c?: string) => c === 'high' ? '#22c55e' : c === 'medium' ? '#f59e0b' : 'var(--text3)'
const trendC = (t?: string) => t === 'uptrend' ? '#22c55e' : t === 'downtrend' ? '#ef4444' : '#f59e0b'

export default function FibConfluencePanel({ symbol }: { symbol: string }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [chart, setChart] = useState<{ highlight?: number } | null>(null)

  // every analyzed level → a chart price line. Tagged by source for the legend; the clicked level is bold.
  const allLevels = (highlight?: number): FibLevel[] => {
    const out: FibLevel[] = []
    for (const t of (data?.timeframes ?? []).filter((x: any) => x.available)) {
      const tag = t.timeframe[0].toUpperCase()
      out.push({ price: t.swing_high, title: `${tag} swing hi`, color: '#ef4444' })
      out.push({ price: t.swing_low, title: `${tag} swing lo`, color: '#22c55e' })
      for (const r of t.retracements) out.push({ price: r.price, title: `${tag} ${r.label}`, color: '#60a5fa' })
      for (const e of t.extensions) out.push({ price: e.price, title: `${tag} ext ${e.label}`, color: '#a855f7' })
    }
    for (const z of (data?.confluence_zones ?? []).slice(0, 4)) out.push({ price: z.price_mid, title: `confluence (${z.confidence})`, color: '#eab308' })
    return out.map(l => ({ ...l, bold: highlight != null && Math.abs(l.price - highlight) < 0.01 }))
  }
  const openChart = (price?: number) => { if (data?.chart_bars?.length) setChart({ highlight: price }) }
  const lvlStyle = { cursor: 'pointer', textDecoration: 'underline dotted', textUnderlineOffset: 2 } as const

  const load = async () => {
    if (open) { setOpen(false); return }
    setOpen(true)
    if (data || loading) return
    setLoading(true); setErr('')
    try {
      const r = await fetch(`/api/v2/symbol/fib-confluence?symbol=${encodeURIComponent(symbol)}`)
      const j = await r.json()
      const d = j?.data ?? j
      if (d?.ok === false) setErr(d.error || 'unavailable')
      setData(d)
    } catch (e: any) { setErr(e?.message || 'failed') }
    finally { setLoading(false) }
  }

  const tfs = (data?.timeframes ?? []).filter((t: any) => t.available)
  const zones = data?.confluence_zones ?? []

  return (
    <div onClick={e => e.stopPropagation()} style={{ marginTop: 8 }}>
      <button onClick={load} style={{ fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 6, cursor: 'pointer', border: '1px solid var(--border)', background: open ? 'rgba(148,163,184,.10)' : 'transparent', color: 'var(--text2)' }}>
        Multi-TF Fib &amp; confluence {open ? '▴' : '▾'}
      </button>
      {open && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {loading && <div style={{ fontSize: 11, color: 'var(--text3)' }}>analyzing daily · weekly · monthly charts…</div>}
          {err && <div style={{ fontSize: 11, color: '#ef4444' }}>{err}</div>}

          {/* Per-timeframe swing + Fib table */}
          {tfs.length > 0 && (
            <div style={{ ...C.card, padding: 8, overflowX: 'auto' }}>
              <div style={{ fontSize: 10, fontWeight: 800, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: .3 }}>Swing structure &amp; Fibonacci · per timeframe</div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10.5 }}>
                <thead><tr style={{ color: 'var(--text3)', textAlign: 'right' }}>
                  <th style={{ textAlign: 'left', padding: '3px 6px' }}>TF</th><th style={{ textAlign: 'left', padding: '3px 6px' }}>Trend</th>
                  <th style={{ padding: '3px 6px' }}>Swing Lo</th><th style={{ padding: '3px 6px' }}>Swing Hi</th>
                  <th style={{ padding: '3px 6px' }}>38.2%</th><th style={{ padding: '3px 6px' }}>50%</th><th style={{ padding: '3px 6px' }}>61.8%</th>
                  <th style={{ padding: '3px 6px' }}>Ext 1.618</th>
                </tr></thead>
                <tbody>
                  {tfs.map((t: any) => {
                    const r = (x: number) => t.retracements.find((y: any) => y.ratio === x)?.price
                    const e618 = t.extensions.find((y: any) => y.ratio === 1.618)?.price
                    return (
                      <tr key={t.timeframe} style={{ borderTop: '1px solid var(--border)', textAlign: 'right' }}>
                        <td style={{ textAlign: 'left', padding: '3px 6px', fontWeight: 700, color: 'var(--text0)' }}>{t.timeframe}</td>
                        <td style={{ textAlign: 'left', padding: '3px 6px', color: trendC(t.trend), fontWeight: 700 }} title={t.structure}>{t.trend}</td>
                        <td onClick={() => openChart(t.swing_low)} style={{ padding: '3px 6px', color: 'var(--text2)', ...lvlStyle }} title={`${t.swing_low_date} — click to chart`}>${t.swing_low}</td>
                        <td onClick={() => openChart(t.swing_high)} style={{ padding: '3px 6px', color: 'var(--text2)', ...lvlStyle }} title={`${t.swing_high_date} — click to chart`}>${t.swing_high}</td>
                        <td onClick={() => openChart(r(0.382))} style={{ padding: '3px 6px', color: 'var(--text3)', ...lvlStyle }} title="click to chart">${r(0.382)}</td>
                        <td onClick={() => openChart(r(0.5))} style={{ padding: '3px 6px', color: 'var(--text3)', ...lvlStyle }} title="click to chart">${r(0.5)}</td>
                        <td onClick={() => openChart(r(0.618))} style={{ padding: '3px 6px', color: 'var(--text3)', ...lvlStyle }} title="click to chart">${r(0.618)}</td>
                        <td onClick={() => openChart(e618)} style={{ padding: '3px 6px', color: 'var(--text3)', ...lvlStyle }} title="click to chart">${e618}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <div style={{ fontSize: 8.5, color: 'var(--text3)', marginTop: 4 }}>Each timeframe analyzed independently (yfinance OHLC). Hover swing values for the date; trend for the structure read.</div>
            </div>
          )}

          {/* Confluence zones */}
          {zones.length > 0 && (
            <div style={{ ...C.card, padding: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <div style={{ fontSize: 10, fontWeight: 800, color: 'var(--text2)', textTransform: 'uppercase', letterSpacing: .3 }}>Confluence zones · ranked by strength · current ${data.current_price}</div>
                <span style={{ flex: 1 }} />
                {data?.chart_bars?.length > 0 && <button onClick={() => openChart()} style={{ fontSize: 9.5, fontWeight: 700, padding: '2px 8px', borderRadius: 5, cursor: 'pointer', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text2)' }}>Chart all levels</button>}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                {zones.slice(0, 6).map((z: any, i: number) => (
                  <div key={i} onClick={() => openChart(z.price_mid)} title="click to chart this zone" style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '5px 7px', borderRadius: 6, background: 'var(--bg1)', borderLeft: `3px solid ${conf(z.confidence)}`, cursor: 'pointer' }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 11.5, fontWeight: 800, color: 'var(--text0)' }}>${z.price_low}{z.price_high !== z.price_low ? `–$${z.price_high}` : ''}</span>
                      <span style={{ fontSize: 9.5, fontWeight: 700, color: z.zone === 'above' ? '#22c55e' : '#ef4444' }}>{z.dist_pct >= 0 ? '+' : ''}{z.dist_pct}% ({z.zone})</span>
                      <span style={{ flex: 1 }} />
                      <span style={{ fontSize: 9, fontWeight: 800, padding: '1px 6px', borderRadius: 4, background: `${conf(z.confidence)}22`, color: conf(z.confidence) }}>{z.confidence} · {z.signal_count} signals</span>
                    </div>
                    <div style={{ fontSize: 9, color: 'var(--text3)' }}>{z.timeframes.join(' · ')} → {z.levels.join(' · ')}</div>
                  </div>
                ))}
              </div>
              <div style={{ fontSize: 8.5, color: 'var(--text3)', marginTop: 5 }}>Zones where ≥2 levels (Fib / swing / S-R) align within 1.5% across timeframes. Strength = overlap count + timeframe diversity. Advisory — verify on your charts; never an order.</div>
            </div>
          )}
        </div>
      )}
      {chart && data?.chart_bars && <FibChartModal symbol={symbol} bars={data.chart_bars} barsMonthly={data.chart_bars_monthly} levels={allLevels(chart.highlight)} onClose={() => setChart(null)} />}
    </div>
  )
}
