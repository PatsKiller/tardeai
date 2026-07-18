import { useState } from 'react'
import { BB, T, DASH, numStyle, heatRamp } from '../../lib/watchTokens'

// Defense v3 D3.3 Row 4 — everything below the fold. Collapsed by default: the
// operator opens what they need; the load view stays a dashboard, not a data dump.

const STATE_COLOR: Record<string, string> = {
  LEADING: BB.green, WEAKENING: BB.amber, LAGGING: BB.red, IMPROVING: T.link,
}

function Fold({ title, badge, children }: { title: string; badge?: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2 }}>
      <button onClick={() => setOpen(o => !o)} style={{
        width: '100%', textAlign: 'left', display: 'flex', gap: 8, alignItems: 'baseline',
        fontSize: DASH.section, fontWeight: 800, color: BB.text2, background: 'transparent',
        border: 'none', padding: '9px 12px', cursor: 'pointer',
      }}>
        <span style={{ color: BB.text3 }}>{open ? '▾' : '▸'}</span> {title}
        {badge && <span style={{ fontSize: DASH.chip, fontWeight: 800, color: BB.text3, textTransform: 'uppercase' }}>{badge}</span>}
      </button>
      {open && <div style={{ padding: '0 12px 10px' }}>{children}</div>}
    </div>
  )
}

function Heat({ v, scale = 1, suffix = '%' }: { v: number | null | undefined; scale?: number; suffix?: string }) {
  return (
    <span style={{ ...numStyle, textAlign: 'right', background: v != null ? heatRamp(v / scale) : 'transparent', color: BB.text0, borderRadius: 2, padding: '1px 4px', fontWeight: 700, fontSize: DASH.data }}>
      {v != null ? `${v >= 0 ? '+' : ''}${v}${suffix}` : '—'}
    </span>
  )
}

export default function DefenseDetails({ posture, industries, radar }: { posture: any; industries: any; radar: any }) {
  const [drill, setDrill] = useState<string | null>(null)
  const rows: any[] = posture?.momentum?.rows || []
  const whfC: any[] = posture?.would_have_fired?.confirmed || []
  const whfRaw: any[] = posture?.would_have_fired?.transitions || []
  const ind: any[] = industries?.industries || []
  const bySector: Record<string, any[]> = {}
  ind.forEach(g => { (bySector[g.sector || 'Other'] ||= []).push(g) })
  const drillList = (drill ? bySector[drill] || [] : []).sort((a, b) => (b.rel1w ?? -99) - (a.rel1w ?? -99))
  const radarRows: any[] = radar?.radar || []

  const th: React.CSSProperties = { fontSize: DASH.chip, color: BB.text3, textTransform: 'uppercase', fontWeight: 800, padding: '2px 4px', textAlign: 'left' }
  const td: React.CSSProperties = { fontSize: DASH.data, padding: '3px 4px', borderBottom: `1px solid ${BB.borderHair}` }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {(() => {
        // v4 WS-RADAR: honest emptiness — when NO row has a non-baseline signal the
        // radar is ONE summary line, not 20 rows of dashes
        const signal = radarRows.filter(r =>
          (r.put_oi_delta_pct ?? 0) > 5 || (r.skew25_delta ?? 0) > 1 || (r.pc_vol_vs_mean ?? 0) > 1.5)
        const histN = radarRows.length ? Math.max(...radarRows.map(r => r.pc_mean_n || 0)) : 0
        if (signal.length === 0) {
          return (
            <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '9px 12px', fontSize: DASH.data, color: BB.text2 }}>
              <b style={{ color: BB.text1 }}>Radar:</b> no unusual hedging across {radarRows.length} underlyings ·
              baselines set {(radar?.captured_at || '').slice(0, 10)} · history n={histN}/20d — deltas earn a table when they exist
            </div>
          )
        }
        return (
          <Fold title="Where the street is hedging" badge={`${signal.length} signals of ${radarRows.length} underlyings · inference, not order flow`}>
            <div style={{ fontSize: DASH.data, color: BB.text3, marginBottom: 6 }}>{radar?.coverage?.note} · {radar?.history_note}</div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                <thead><tr>
                  <th style={th}>Underlying</th><th style={th}>Put OI</th><th style={th}>P/C OI</th>
                  <th style={th}>ΔPut OI</th><th style={th}>ATM IV</th><th style={th}>Skew25</th><th style={th}>Read</th>
                </tr></thead>
                <tbody>
                  {signal.map(r => (
                    <tr key={r.symbol}>
                      <td style={{ ...td, fontWeight: 700, color: BB.text1 }}>{r.symbol}</td>
                      <td style={{ ...td, ...numStyle }}>{(r.put_oi / 1000).toFixed(0)}K</td>
                      <td style={{ ...td, ...numStyle }}>{r.pc_oi_ratio ?? ''}</td>
                      <td style={{ ...td, ...numStyle, color: (r.put_oi_delta_pct ?? 0) > 5 ? BB.red : BB.text2 }}>{r.put_oi_delta_pct != null ? `${r.put_oi_delta_pct >= 0 ? '+' : ''}${r.put_oi_delta_pct}%` : ''}</td>
                      <td style={{ ...td, ...numStyle }}>{r.atm_iv ?? ''}</td>
                      <td style={{ ...td, ...numStyle }}>{r.skew25 ?? ''}</td>
                      <td style={{ ...td, color: BB.text2 }}>{r.line.split('— ')[1] || r.line}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Fold>
        )
      })()}

      <Fold title="Sector spine" badge={`${rows.length} sectors · nightly 17:25`}>
        <div style={{ overflowX: 'auto' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '170px 92px 64px 64px 64px 60px 66px 92px', gap: 6, ...th, borderBottom: `1px solid ${BB.border}` } as any}>
            <span>Sector</span><span>State</span><span>RS 5d</span><span>RS 20d</span><span>Slope</span><span>Breadth</span><span>Hermes Δ</span><span>Your book</span>
          </div>
          {rows.map((r: any) => (
            <div key={r.etf} onClick={() => setDrill(d => d === r.sector ? null : r.sector)} style={{ display: 'grid', gridTemplateColumns: '170px 92px 64px 64px 64px 60px 66px 92px', gap: 6, padding: '3px 4px', borderBottom: `1px solid ${BB.borderHair}`, borderLeft: `3px solid ${STATE_COLOR[r.state] || BB.text3}`, cursor: 'pointer', alignItems: 'center', fontSize: DASH.data }}>
              <span style={{ color: BB.text1, fontWeight: 700 }}>{r.sector} <span style={{ ...numStyle, color: BB.text3 }}>{r.etf}</span></span>
              <span style={{ fontSize: DASH.chip, fontWeight: 800, color: STATE_COLOR[r.state] || BB.text3, textTransform: 'uppercase' }}>{r.state || r.note}</span>
              <Heat v={r.rs5} scale={1.5} />
              <Heat v={r.rs20} scale={2.5} />
              <Heat v={r.slope} scale={1.5} suffix="" />
              <span style={{ ...numStyle, textAlign: 'right', background: r.breadth_pct != null ? heatRamp((r.breadth_pct - 50) / 12) : 'transparent', color: BB.text0, borderRadius: 2, padding: '1px 4px', fontWeight: 700 }}>{r.breadth_pct != null ? `${r.breadth_pct}%` : '—'}</span>
              <Heat v={r.hermes_delta} scale={2} suffix="" />
              <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <span style={{ flex: 1, height: 7, background: BB.borderHair, borderRadius: 1, overflow: 'hidden' }}>
                  <span style={{ display: 'block', height: '100%', width: `${Math.min(100, (r.book_pct ?? 0) * 4)}%`, background: (r.book_pct ?? 0) >= 15 ? BB.amber : BB.green }} />
                </span>
                <span style={{ ...numStyle, fontWeight: 700, minWidth: 36, textAlign: 'right', color: BB.text2 }}>{r.book_pct != null ? `${r.book_pct}%` : '—'}</span>
              </span>
            </div>
          ))}
        </div>
        {drill && (
          <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: DASH.data, fontWeight: 700, color: BB.text2, marginBottom: 4 }}>{drill} industries ({drillList.length})</div>
            {drillList.map(g => (
              <div key={g.industry} style={{ display: 'grid', gridTemplateColumns: '240px 92px 64px 64px 1fr', gap: 6, padding: '2px 4px', borderBottom: `1px solid ${BB.borderHair}`, borderLeft: `3px solid ${STATE_COLOR[g.state] || BB.text3}`, alignItems: 'baseline', fontSize: DASH.data }}>
                <span style={{ color: BB.text1, fontWeight: 600 }}>{g.industry}</span>
                <span style={{ fontSize: DASH.chip, fontWeight: 800, color: STATE_COLOR[g.state] || BB.text3 }}>{g.state || '—'}</span>
                <Heat v={g.rel1w} scale={4} />
                <Heat v={g.rel1m} scale={4} />
                <span style={{ color: BB.text2 }}>
                  {g.held?.length ? <b style={{ color: BB.amber }}>holding {g.held.join(' ')}</b> : null}
                  {g.watched?.length ? <span style={{ color: T.link, marginLeft: 6 }}>★ {g.watched.join(' ')}</span> : null}
                </span>
              </div>
            ))}
          </div>
        )}
      </Fold>

      <Fold title="Confirmed transitions & would-have-fired" badge={`${whfC.length} debounced over 30 sessions · hypothetical before Jul 17`}>
        {whfC.slice().reverse().map((t: any, i: number) => (
          <div key={i} style={{ display: 'flex', gap: 10, fontSize: DASH.data, padding: '2px 0', borderBottom: `1px solid ${BB.borderHair}`, alignItems: 'baseline' }}>
            <span style={{ ...numStyle, color: BB.text3, minWidth: 80 }}>{t.as_of}</span>
            <span style={{ color: BB.text1, minWidth: 160 }}>{t.sector}</span>
            <span style={{ fontWeight: 700, color: STATE_COLOR[t.to] || BB.text2 }}>{t.from}→{t.to}</span>
            <span style={{ ...numStyle, color: BB.text3 }}>rs20 {t.rs20}</span>
          </div>
        ))}
        <div style={{ fontSize: DASH.data, color: BB.text3, marginTop: 4 }}>
          {whfRaw.length} raw un-debounced flips in the window — the debounce absorbed {Math.max(0, whfRaw.length - whfC.length)} single-day flickers.
          Technology → LAGGING was confirmed Jul 14, three sessions before the operator asked why the system was silent.
        </div>
      </Fold>

      <Fold title="Build status" badge="what's live vs accruing">
        <div style={{ fontSize: DASH.data, color: BB.text2, display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div><b style={{ color: BB.green }}>LIVE</b> — sector/industry state machines · market layer · hedging radar (chain snapshots nightly) · recommendations engine (all four groups, SHADOW)</div>
          <div><b style={{ color: BB.amber }}>ACCRUING</b> — OI deltas + P/C-vs-20d-mean (history builds nightly from first capture) · short-float TREND (single capture today, as-of dated) · paper-twin scoreboard (twins now enter the queue)</div>
          <div><b style={{ color: BB.text3 }}>GATED</b> — put-structure hedges await options_level in config/account_capabilities.json · move-out advisories in 10-day SHADOW before Telegram</div>
        </div>
      </Fold>
    </div>
  )
}
