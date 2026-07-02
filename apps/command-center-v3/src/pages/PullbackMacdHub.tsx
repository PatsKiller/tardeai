import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'

// v3 Pullback/MACD Screener — S&P 500 names in an uptrend that have pulled back ~20% off their
// 52-week high and whose MACD is approaching a bullish cross. Two tiers: trigger / watch.
// Advisory only — auto-generated proposals require operator approval; nothing auto-executes.

interface Props { onDrill: (ctx: DrillContext) => void; embedded?: boolean }

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }

const Pill = ({ text, color, tip }: any) => (
  <span title={tip} style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 4, background: color + '22', color, border: `1px solid ${color}55`, whiteSpace: 'nowrap', cursor: tip ? 'help' : 'default' }}>{text}</span>
)

const fmt = (v: any, d = 2) => (v === null || v === undefined ? '—' : Number(v).toFixed(d))

// The "pullback banner" — prominent amber highlight of how far off the 52-week high a name is,
// plus a green tag when the MACD cross is imminent (trigger tier).
function PullbackBanner({ c }: { c: any }) {
  const trigger = c.tier === 'trigger'
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
      background: 'linear-gradient(90deg, rgba(245,158,11,.16), rgba(245,158,11,.04))',
      border: '1px solid rgba(245,158,11,.4)', borderRadius: 8, padding: '6px 10px', marginBottom: 8,
    }}>
      <span style={{ fontSize: 12, fontWeight: 800, color: '#f59e0b' }}>📉 PULLBACK {fmt(c.pullback_pct, 1)}%</span>
      <span style={{ fontSize: 10, color: 'var(--text3)' }}>off 52-wk high · uptrend intact</span>
      {c.above_vwap === true && <span style={{ fontSize: 10, fontWeight: 800, color: '#22c55e' }}>↑ VWAP {fmt(c.vwap)}</span>}
      {c.above_vwap === false && <span style={{ fontSize: 10, fontWeight: 700, color: '#f59e0b' }}>↓ VWAP {fmt(c.vwap)}</span>}
      {trigger
        ? <span style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 800, color: '#22c55e' }}>📈 RECOVERY CONFIRMED · MACD↑ + VWAP</span>
        : <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--text3)' }}>watch · {c.why_not || 'not confirmed'}</span>}
    </div>
  )
}

const btn = (bg: string) => ({ fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 5, border: '1px solid var(--border)', background: bg, color: 'var(--text0)', cursor: 'pointer' })

function CandidateCard({ c, onDrill, onDismiss }: { c: any; onDrill: Props['onDrill']; onDismiss: (sym: string, cancel: boolean) => void }) {
  const trigger = c.tier === 'trigger'
  return (
    <div style={{ ...card, borderColor: trigger ? 'rgba(34,197,94,.5)' : 'var(--border)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 16, fontWeight: 800, cursor: 'pointer' }}
          onClick={() => onDrill({ kind: 'symbol', symbol: c.symbol } as any)}>{c.symbol}</span>
        <Pill text={trigger ? 'TRIGGER' : 'WATCH'} color={trigger ? '#22c55e' : '#64748b'} />
        <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text3)' }}>score {fmt(c.score, 0)}</span>
      </div>
      <PullbackBanner c={c} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, fontSize: 11 }}>
        <Metric label="Entry" value={fmt(c.entry)} />
        <Metric label="Stop" value={fmt(c.stop)} />
        <Metric label="Target1" value={fmt(c.target1)} />
        <Metric label="R:R" value={fmt(c.rr, 1)} />
        <Metric label="Trend (50/200)" value={`+${fmt(c.trend_pct, 1)}%`} />
        <Metric label="MACD prox" value={`${fmt(c.macd_prox_pct, 3)}%`} tip="|MACD − signal| as % of price — imminence to the cross (lower = closer)" />
        <Metric label="vs VWAP" value={c.vwap_dist_pct == null ? '—' : `${c.vwap_dist_pct > 0 ? '+' : ''}${fmt(c.vwap_dist_pct, 2)}%`} tip="Last price vs intraday session VWAP — entry-timing confirmation" />
        <Metric label="ATR" value={fmt(c.atr)} />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8 }}>
        {c.proposal_id
          ? <span style={{ fontSize: 10, color: '#60a5fa' }}>Advisory proposal #{c.proposal_id} in approval queue</span>
          : <span style={{ fontSize: 10, color: 'var(--text3)' }}>no proposal</span>}
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button style={btn('var(--bg2)')} title="Dismiss until next scan"
            onClick={() => onDismiss(c.symbol, false)}>Dismiss</button>
          {c.proposal_id
            ? <button style={btn('rgba(239,68,68,.15)')} title="Dismiss and reject its advisory proposal"
                onClick={() => onDismiss(c.symbol, true)}>Dismiss + cancel</button>
            : null}
        </span>
      </div>
    </div>
  )
}

const Metric = ({ label, value, tip }: any) => (
  <div title={tip} style={{ cursor: tip ? 'help' : 'inherit' }}>
    <div style={{ fontSize: 9, color: 'var(--text3)' }}>{label}</div>
    <div style={{ fontWeight: 700 }}>{value}</div>
  </div>
)

export default function PullbackMacdHub({ onDrill, embedded }: Props) {
  const { data, loading, error, refetch } = useApi<any>('/api/v2/pullback-macd/candidates', 60_000)
  const cands: any[] = data?.candidates ?? []
  const triggers = cands.filter(c => c.tier === 'trigger')
  const watch = cands.filter(c => c.tier === 'watch')
  const run = data?.last_run
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const post = async (path: string, body?: any) => {
    const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
    return r.json()
  }
  const runScan = async () => {
    setBusy(true); setMsg('Scan started — refreshing in ~45s…')
    try { const j = await post('/api/v2/pullback-macd/scan'); setMsg(j.ok ? '✓ ' + (j.note || 'scan started') : 'Error: ' + j.error) }
    catch (e: any) { setMsg('Error: ' + e.message) }
    setTimeout(() => { refetch(); setBusy(false); setMsg(null) }, 45_000)
  }
  const dismiss = async (symbol: string, cancel: boolean) => {
    setMsg(`${symbol}: dismissing…`)
    try { const j = await post('/api/v2/pullback-macd/dismiss', { symbol, cancel_proposal: cancel }); setMsg(j.ok ? `✓ ${symbol} dismissed${j.proposal_cancelled ? ` · proposal #${j.proposal_cancelled} cancelled` : ''}` : 'Error: ' + j.error); refetch() }
    catch (e: any) { setMsg('Error: ' + e.message) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        {!embedded ? (
          <div style={{ flex: 1 }}>
            <h1 style={{ fontSize: 20, fontWeight: 800, margin: 0 }}>Pullback / MACD Screener</h1>
            <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 2 }}>
              S&P 500 uptrends pulled back 12–28%, earliest recovery confirmed (MACD histogram turning up + above VWAP) ·
              advisory only, proposals require approval ·
              {run ? ` last scan ${run.scan_date} (${run.screened} screened)` : ' no scan recorded yet'}
            </div>
            {msg && <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4 }}>{msg}</div>}
          </div>
        ) : (
          <div style={{ flex: 1, fontSize: 11, color: 'var(--text3)' }}>
            {run ? `Last scan ${run.scan_date} (${run.screened} screened)` : 'No scan recorded yet'}
            {msg && <span style={{ marginLeft: 8, color: 'var(--text2)' }}>{msg}</span>}
          </div>
        )}
        <button style={{ ...btn('var(--accent, #2563eb)'), fontSize: 12, padding: '7px 14px', opacity: busy ? 0.6 : 1 }}
          disabled={busy} onClick={runScan}>{busy ? 'Scanning…' : '↻ Run scan now'}</button>
      </div>

      {error && <div style={{ ...card, color: '#ef4444' }}>API error: {String(error)}</div>}
      {loading && !cands.length && <div style={{ ...card, color: 'var(--text3)' }}>Loading…</div>}

      <section>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>
          🎯 Triggers <span style={{ color: 'var(--text3)', fontWeight: 400 }}>({triggers.length}) — MACD turning up + above VWAP (earliest confirmed recovery)</span>
        </div>
        {triggers.length
          ? <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
              {triggers.map(c => <CandidateCard key={c.symbol} c={c} onDrill={onDrill} onDismiss={dismiss} />)}
            </div>
          : <div style={{ ...card, color: 'var(--text3)', fontSize: 12 }}>No triggers today — a deep pullback in a standing uptrend with the cross about to fire is rare (expected on most days).</div>}
      </section>

      <section>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>
          👀 Watch <span style={{ color: 'var(--text3)', fontWeight: 400 }}>({watch.length}) — in pullback, recovery not yet confirmed</span>
        </div>
        {watch.length
          ? <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
              {watch.map(c => <CandidateCard key={c.symbol} c={c} onDrill={onDrill} onDismiss={dismiss} />)}
            </div>
          : <div style={{ ...card, color: 'var(--text3)', fontSize: 12 }}>No watch candidates.</div>}
      </section>
    </div>
  )
}
