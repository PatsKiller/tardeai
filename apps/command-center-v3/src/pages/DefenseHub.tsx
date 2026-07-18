import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { BB, T, TYPE, numStyle, heatRamp } from '../lib/watchTokens'
import { hubTitle, hubSubtitle } from '../lib/terminalHubChrome'
import { useTerminalUi } from '../lib/terminalUi'

// Defense Desk v1 (WS-E/F): sector momentum states as the page spine, would-have-fired
// credibility fold, net-exposure headline. Advisory-only — this page places NOTHING.
// Rows for Move-out (WS-C), Positioning (WS-B), Hedge/Short desks (WS-D2-D5) render
// honest-empty with their build status until those engines ship.

const FQDN = typeof window !== 'undefined' ? window.location.origin : ''
const STATE_COLOR: Record<string, string> = {
  LEADING: BB.green, WEAKENING: BB.amber, LAGGING: BB.red, IMPROVING: T.link,
}

const card: React.CSSProperties = { background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '10px 12px' }

function Head({ title, corpus, rail }: { title: string; corpus?: string; rail?: string }) {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 6, flexWrap: 'wrap', borderLeft: rail ? `3px solid ${rail}` : undefined, paddingLeft: rail ? 8 : 0 }}>
      <span style={{ fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.06em', color: BB.text2, textTransform: 'uppercase' }}>{title}</span>
      {corpus && <span style={{ fontSize: 8.5, fontWeight: 700, color: BB.text3, textTransform: 'uppercase' }}>· {corpus}</span>}
    </div>
  )
}

export default function DefenseHub() {
  const [terminalUi] = useTerminalUi()
  const { data } = useApi<any>('/api/v2/defense/posture', 300_000)
  const { data: regime } = useApi<any>('/api/v2/risk-regime/latest', 300_000)
  const { data: tradeAi } = useApi<any>('/api/v2/trade-ai/summary', 300_000)
  const [whfOpen, setWhfOpen] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  const rows: any[] = data?.momentum?.rows || []
  const transitions: any[] = data?.momentum?.transitions_today || []
  const whf: any[] = data?.would_have_fired?.transitions || []
  const net = data?.net_exposure
  const genAt = (data?.momentum?.generated_at || '').slice(0, 16)
  const weakLag = rows.filter(r => r.state === 'WEAKENING' || r.state === 'LAGGING')
  const bookLine = weakLag.filter(r => (r.book_pct ?? 0) > 0)
    .map(r => `${r.book_pct}% ${r.sector.toLowerCase()} (${r.state})`).join(' · ')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 1480, margin: '0 auto' }}>
      <div>
        <div style={hubTitle()}>Defense Desk</div>
        <div style={hubSubtitle(terminalUi)}>
          sector momentum transitions · positioning · hedge & short-side — advisory only, nothing here places orders
        </div>
      </div>

      {/* Row 1 — Market Posture (WS-E) */}
      <div style={{ ...card, borderLeft: `3px solid ${weakLag.length >= 3 ? BB.red : weakLag.length ? BB.amber : BB.green}` }}>
        <Head title="Market posture" corpus={`sector_momentum_state · nightly 17:25 · ${genAt}Z`} />
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'baseline', marginBottom: 8 }}>
          <span style={{ fontSize: TYPE.sm, color: BB.text2 }}>
            regime <b style={{ color: BB.amber }}>{regime?.regime_label?.replace(/_/g, ' ') ?? '—'}</b>
          </span>
          <span style={{ fontSize: TYPE.sm, color: BB.text2 }}>VIX <b style={{ ...numStyle }}>{tradeAi?.vix ?? '—'}</b></span>
          {net && (
            <span style={{ fontSize: TYPE.sm, color: BB.text2 }}>
              net equity exposure <b style={{ ...numStyle, color: BB.amber }}>{net.equity_pct}%</b>
              <span style={{ color: BB.text3 }}> ({net.cash_pct}% cash ≈ ${Math.round(net.cash_dollars / 1000)}K — already a hedge)</span>
            </span>
          )}
          {bookLine && <span style={{ fontSize: TYPE.sm, color: BB.text2 }}>your book: <b style={{ color: BB.amber }}>{bookLine}</b> · hedge coverage 0%</span>}
        </div>

        {/* transitions today */}
        {transitions.length > 0 ? transitions.map((t, i) => (
          <div key={i} style={{ fontSize: TYPE.sm, color: t.severity === 'urgent' ? BB.red : BB.amber, padding: '2px 0' }}>{t.line}</div>
        )) : <div style={{ fontSize: TYPE.xs, color: BB.text3, marginBottom: 6 }}>no confirmed transitions today (alerts fire only on 2-close-confirmed state changes, ≤4/day)</div>}

        {/* sector state table — the page spine */}
        <div style={{ overflowX: 'auto', marginTop: 6 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '170px 92px 64px 64px 64px 58px 70px 60px 70px', gap: 6, fontSize: 8.5, color: BB.text3, textTransform: 'uppercase', fontWeight: 800, padding: '2px 4px', borderBottom: `1px solid ${BB.border}` }}>
            <span>Sector</span><span>State</span><span>RS 5d</span><span>RS 20d</span><span>Slope</span><span>Breadth</span><span>Hermes Δ</span><span>News−</span><span>Your wt</span>
          </div>
          {rows.map((r: any) => {
            const c = STATE_COLOR[r.state] || BB.text3
            const open = expanded === r.etf
            return (
              <div key={r.etf}>
                <div onClick={() => setExpanded(open ? null : r.etf)} style={{ display: 'grid', gridTemplateColumns: '170px 92px 64px 64px 64px 58px 70px 60px 70px', gap: 6, fontSize: TYPE.xs, padding: '3px 4px', borderBottom: `1px solid ${BB.borderHair}`, borderLeft: `3px solid ${c}`, cursor: 'pointer', alignItems: 'baseline' }}>
                  <span style={{ color: BB.text1, fontWeight: 700 }}>{r.sector} <span style={{ ...numStyle, color: BB.text3 }}>{r.etf}</span></span>
                  <span style={{ fontSize: 9, fontWeight: 800, color: c }}>{r.state || r.note}</span>
                  <span style={{ ...numStyle, color: (r.rs5 ?? 0) >= 0 ? BB.green : BB.red, textAlign: 'right' }}>{r.rs5 != null ? `${r.rs5 >= 0 ? '+' : ''}${r.rs5}%` : '—'}</span>
                  <span style={{ ...numStyle, color: (r.rs20 ?? 0) >= 0 ? BB.green : BB.red, textAlign: 'right' }}>{r.rs20 != null ? `${r.rs20 >= 0 ? '+' : ''}${r.rs20}%` : '—'}</span>
                  <span style={{ ...numStyle, color: (r.slope ?? 0) >= 0 ? BB.green : BB.red, textAlign: 'right' }}>{r.slope != null ? `${r.slope >= 0 ? '+' : ''}${r.slope}` : '—'}</span>
                  <span style={{ ...numStyle, color: BB.text2, textAlign: 'right' }}>{r.breadth_pct != null ? `${r.breadth_pct}%` : '—'}</span>
                  <span style={{ ...numStyle, color: (r.hermes_delta ?? 0) >= 0 ? BB.green : BB.red, textAlign: 'right' }} title={`Hermes pulse ${r.hermes_pulse ?? '—'} (mean composite of tracked constituents)`}>{r.hermes_delta != null ? `${r.hermes_delta >= 0 ? '+' : ''}${r.hermes_delta}` : '—'}</span>
                  <span style={{ ...numStyle, color: r.news_negatives ? BB.red : BB.text3, textAlign: 'right' }}>{r.news_negatives ?? 0}</span>
                  <span style={{ ...numStyle, color: (r.book_pct ?? 0) >= 15 ? BB.amber : BB.text2, textAlign: 'right', fontWeight: 700 }}>{r.book_pct != null ? `${r.book_pct}%` : '—'}</span>
                </div>
                {open && (
                  <div style={{ padding: '6px 10px 8px 14px', fontSize: TYPE.xs, color: BB.text3, borderBottom: `1px solid ${BB.borderHair}`, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
                    <span>RS60 <b style={{ ...numStyle, color: BB.text2 }}>{r.rs60 ?? '—'}%</b></span>
                    <span>breadth n=<b style={{ ...numStyle, color: BB.text2 }}>{r.breadth_n ?? 0}</b> members</span>
                    <span>book <b style={{ ...numStyle, color: BB.text2 }}>${((r.book_dollars ?? 0) / 1000).toFixed(0)}K</b> (direct sector holdings — SCHG growth-fund lookthrough pending WS-D2)</span>
                    {r.top_negative && <span>loudest negative: {String(r.top_negative).slice(0, 80)}</span>}
                    <a href={`${FQDN}/v3/sectors?sector=${encodeURIComponent(r.sector)}`} style={{ color: T.link, textDecoration: 'none', fontWeight: 700 }}>Sectors tab ↗</a>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Credibility strip — would-have-fired */}
      <div style={card}>
        <Head title="Would-have-fired (hypothetical)" corpus="state machine over price history — threshold-tuning evidence, NOT a backtest" rail={BB.amber} />
        <button onClick={() => setWhfOpen(o => !o)} style={{ fontSize: TYPE.xs, fontWeight: 700, color: BB.text3, background: 'transparent', border: `1px solid ${BB.border}`, borderRadius: 2, padding: '3px 9px', cursor: 'pointer' }}>
          {whfOpen ? '▾' : '▸'} {whf.length} hypothetical transitions · last 40 sessions · un-debounced raw flips shown
        </button>
        {whfOpen && (
          <div style={{ marginTop: 6 }}>
            {whf.slice().reverse().map((t: any, i: number) => (
              <div key={i} style={{ display: 'flex', gap: 10, fontSize: TYPE.xs, padding: '2px 0', borderBottom: `1px solid ${BB.borderHair}`, alignItems: 'baseline' }}>
                <span style={{ ...numStyle, color: BB.text3, minWidth: 78 }}>{t.as_of}</span>
                <span style={{ color: BB.text1, minWidth: 150 }}>{t.sector}</span>
                <span style={{ fontWeight: 700, color: STATE_COLOR[t.to] || BB.text2 }}>{t.from}→{t.to}</span>
                <span style={{ ...numStyle, color: BB.text3 }}>rs20 {t.rs20}</span>
              </div>
            ))}
            <div style={{ fontSize: 8.5, color: BB.amber, marginTop: 4 }}>
              Technology → LAGGING on Jul 13: the debounced alert would have fired Jul 14 — three sessions before the operator asked why the system was silent. Hypothetical/backfilled; thresholds tune here before they earn trust.
            </div>
          </div>
        )}
      </div>

      {/* Rows 2-4 — honest build status for the deferred engines */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 12 }}>
        <div style={card}>
          <Head title="Move-out advisories" corpus="WS-C · not built yet" rail={BB.text3} />
          <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>
            Defensive-score join (sector state × position internals × Hermes divergence × catalyst clustering ×
            short-float trend) ships in the next Defense session — then runs 10 trading days SHADOW before Telegram.
            Rotation-alternatives "not_yet" root cause is documented in the diagnosis (verdict-clarity wait by design).
          </div>
        </div>
        <div style={card}>
          <Head title="Positioning intelligence" corpus="WS-B · verified viable, not built yet" rail={BB.text3} />
          <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>
            Phase 0 verified: Schwab option chains READABLE through the existing fence; short_float_pct captured by
            Finviz enrichment. Chain snapshots + OI-delta inference + short-float chips (as-of dated, bi-weekly
            cadence) ship next session. "Positioning inference", never "order flow".
          </div>
        </div>
        <div style={card}>
          <Head title="Hedge advisor" corpus="WS-D2 · capabilities matrix live" rail={BB.text3} />
          <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>
            config/account_capabilities.json is LIVE: Taxable short-stock VERIFIED (margin enabled);
            IRAs = inverse ETFs + covered calls{data?.account_capabilities ? '' : ' (config missing!)'} ·
            options_level awaits operator fill — menus degrade to inverse-ETF + CC until then.
            Venue-split sizing menus ship with WS-D2.
          </div>
        </div>
        <div style={card}>
          <Head title="Short-side desk" corpus="WS-D4/D5 · paper-first, not built yet" rail={BB.text3} />
          <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>
            defensive_short paper strategy (≤$2K, ≤3 concurrent, buy-stop ladder) + taxable advisories
            (mandatory stop, max-loss, ≤2% cap, anti-squeeze filter) ship next session; paper track earns
            the advisories credibility before anything real-money renders.
          </div>
        </div>
      </div>
    </div>
  )
}
