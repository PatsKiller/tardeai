import { useState } from 'react'
import TickerLinks from '../components/TickerLinks'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'
import { BB, T, TYPE, RAIL, numStyle, terminalButton } from '../lib/watchTokens'
import { Chip, StatePills } from '../components/TerminalChip'

// v3 Pullback/MACD Screener — S&P 500 names in an uptrend that have pulled back ~20% off their
// 52-week high and whose MACD is approaching a bullish cross. Two tiers: trigger / watch.
// Advisory only — auto-generated proposals require operator approval; nothing auto-executes.
// v4 (WS-A): watchTokens sweep — rails carry tier/conflict, chips replace ad-hoc pills.

interface Props { onDrill: (ctx: DrillContext) => void; embedded?: boolean }

const card = { background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: 14 }

const fmt = (v: any, d = 2) => (v === null || v === undefined ? '—' : Number(v).toFixed(d))

// The "pullback banner" — prominent amber highlight of how far off the 52-week high a name is,
// plus a green tag when the MACD cross is imminent (trigger tier).
function PullbackBanner({ c }: { c: any }) {
  const trigger = c.tier === 'trigger'
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
      background: BB.amberDim,
      border: `1px solid ${BB.amber}55`, borderRadius: 2, padding: '6px 10px', marginBottom: 8,
    }}>
      <span style={{ ...numStyle, fontSize: TYPE.base, fontWeight: 800, color: BB.amber }}>📉 PULLBACK {fmt(c.pullback_pct, 1)}%</span>
      <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>off 52-wk high · uptrend intact</span>
      {c.above_vwap === true && <span style={{ ...numStyle, fontSize: TYPE.xs, fontWeight: 800, color: BB.green }}>↑ VWAP {fmt(c.vwap)}</span>}
      {c.above_vwap === false && <span style={{ ...numStyle, fontSize: TYPE.xs, fontWeight: 700, color: BB.amber }}>↓ VWAP {fmt(c.vwap)}</span>}
      {trigger
        ? <span style={{ marginLeft: 'auto', fontSize: TYPE.xs, fontWeight: 800, color: BB.green }}>📈 RECOVERY CONFIRMED · MACD↑ + VWAP</span>
        : <span style={{ marginLeft: 'auto', fontSize: TYPE.xs, color: BB.text3 }}>watch · {c.why_not || 'not confirmed'}</span>}
    </div>
  )
}

function CandidateCard({ c, onDrill, onDismiss }: { c: any; onDrill: Props['onDrill']; onDismiss: (sym: string, cancel: boolean) => void }) {
  const trigger = c.tier === 'trigger'
  const rail = c.held_conflict ? RAIL.attention : trigger ? RAIL.favorable : RAIL.neutral
  const pills: Array<{ label: string; tone?: 'green' | 'amber' | 'red' | 'slate'; title?: string }> = [
    { label: trigger ? 'TRIGGER' : 'WATCH', tone: trigger ? 'green' : 'slate' },
  ]
  if (c.held) pills.push({
    label: `HELD · ${Math.round(c.held.shares)} sh${c.held.stop_price ? '' : ' · NO STOP'}`,
    tone: c.held.stop_price ? 'green' : 'amber',
    title: `Held ${Math.round(c.held.shares)} sh · $${Math.round(c.held.market_value).toLocaleString()}${c.held.stop_price ? ` · stop $${c.held.stop_price}${c.held.stop_distance_pct != null ? ` (${c.held.stop_distance_pct > 0 ? '+' : ''}${c.held.stop_distance_pct}%)` : ''}` : ' · NO STOP'}`,
  })
  return (
    <div style={{ ...card, borderLeft: `3px solid ${rail}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ ...numStyle, fontSize: TYPE.md, fontWeight: 800, cursor: 'pointer', color: BB.text0 }}
          onClick={() => onDrill({ kind: 'symbol', symbol: c.symbol } as any)}>{c.symbol}</span>
        <StatePills pills={pills} />
        <span style={{ marginLeft: 'auto' }}>
          <Chip kind="metric" title="composite screener score">score {fmt(c.score, 0)}</Chip>
        </span>
      </div>
      {c.held_conflict && (
        <div style={{ margin: '0 0 8px', padding: '6px 10px', borderRadius: 2, fontSize: TYPE.sm, fontWeight: 700,
          background: BB.amberDim, border: `1px solid ${BB.amber}66`, color: BB.amber }}>
          ⚠ Held position near stop — adding here averages down; review stop plan first
        </div>
      )}
      <PullbackBanner c={c} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, fontSize: TYPE.sm }}>
        <Metric label="Entry" value={fmt(c.entry)} />
        <Metric label="Stop" value={fmt(c.stop)} />
        <Metric label="Target1" value={fmt(c.target1)} />
        <Metric label="R:R" value={fmt(c.rr, 1)} />
        <Metric label="Trend (50/200)" value={`+${fmt(c.trend_pct, 1)}%`} />
        <Metric label="MACD prox" value={`${fmt(c.macd_prox_pct, 3)}%`} tip="|MACD − signal| as % of price — imminence to the cross (lower = closer)" />
        <Metric label="vs VWAP" value={c.vwap_dist_pct == null ? '—' : `${c.vwap_dist_pct > 0 ? '+' : ''}${fmt(c.vwap_dist_pct, 2)}%`} tip="Last price vs intraday session VWAP — entry-timing confirmation" />
        <Metric label="ATR" value={fmt(c.atr)} />
      </div>
      <div style={{ marginTop: 6 }}><TickerLinks symbol={c.symbol} /></div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8 }}>
        {c.proposal_id
          ? <span style={{ fontSize: TYPE.xs, color: T.link }}>Advisory proposal #{c.proposal_id} in approval queue</span>
          : <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>no proposal</span>}
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button style={terminalButton('ghost')} title="Hide for 10 trading days (re-shows early only if score improves ≥25%). Proposal untouched."
            onClick={() => onDismiss(c.symbol, false)}>Dismiss</button>
          {c.proposal_id
            ? <button style={terminalButton('danger')} title="Hide for 10 trading days AND reject the linked PENDING advisory proposal (no order surface involved)."
                onClick={() => onDismiss(c.symbol, true)}>Dismiss + cancel</button>
            : null}
        </span>
      </div>
    </div>
  )
}

const Metric = ({ label, value, tip }: any) => (
  <div title={tip} style={{ cursor: tip ? 'help' : 'inherit' }}>
    <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>{label}</div>
    <div style={{ ...numStyle, fontWeight: 700, color: BB.text1 }}>{value}</div>
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
            <h1 style={{ fontSize: TYPE.lg, fontWeight: 800, margin: 0, color: BB.text0 }}>Pullback / MACD Screener</h1>
            <div style={{ fontSize: TYPE.sm, color: BB.text3, marginTop: 2 }}>
              S&P 500 uptrends pulled back 12–28%, earliest recovery confirmed (MACD histogram turning up + above VWAP) ·
              advisory only, proposals require approval ·
              {run ? ` last scan ${run.scan_date} (${run.screened} screened — ${data?.scan_provenance?.universe || 'S&P 500 uptrend pullbacks'})` : ' no scan recorded yet'}{data?.hit_stats ? ` · last ${data.hit_stats.window_days}d: ${data.hit_stats.triggers} triggers${data.hit_stats.evaluated ? ` · ${data.hit_stats.target1_first}/${data.hit_stats.evaluated} reached T1 first${data.hit_stats.median_days ? ` · median ${Math.round(data.hit_stats.median_days)}d` : ''}` : ' · outcomes n/a until evaluations accrue'}` : ''}{data?.dismissed_in_cooldown ? ` · ${data.dismissed_in_cooldown} in dismiss-cooldown` : ''}
            </div>
            {msg && <div style={{ fontSize: TYPE.sm, color: BB.text2, marginTop: 4 }}>{msg}</div>}
          </div>
        ) : (
          <div style={{ flex: 1, fontSize: TYPE.sm, color: BB.text3 }}>
            <span title={data?.scan_provenance?.schedule || ''}>{run ? `Last scan ${run.scan_date} (${run.screened} screened — ${data?.scan_provenance?.universe || 'S&P 500 uptrend pullbacks'})` : 'No scan recorded yet'}{data?.hit_stats ? ` · last ${data.hit_stats.window_days}d: ${data.hit_stats.triggers} triggers${data.hit_stats.evaluated ? ` · ${data.hit_stats.target1_first}/${data.hit_stats.evaluated} reached T1 first${data.hit_stats.median_days ? ` · median ${Math.round(data.hit_stats.median_days)}d` : ''}` : ' · outcomes n/a until evaluations accrue'}` : ''}{data?.dismissed_in_cooldown ? ` · ${data.dismissed_in_cooldown} in dismiss-cooldown` : ''}</span>
            {msg && <span style={{ marginLeft: 8, color: BB.text2 }}>{msg}</span>}
          </div>
        )}
        <button style={{ ...terminalButton('primary'), opacity: busy ? 0.6 : 1 }}
          disabled={busy} onClick={runScan}>{busy ? 'Scanning…' : '↻ Run scan now'}</button>
      </div>

      {error && <div style={{ ...card, color: BB.red }}>API error: {String(error)}</div>}
      {loading && !cands.length && <div style={{ ...card, color: BB.text3 }}>Loading…</div>}

      <section>
        <div style={{ fontSize: TYPE.base, fontWeight: 800, marginBottom: 8, color: BB.text0 }}>
          🎯 Triggers <span style={{ color: BB.text3, fontWeight: 400 }}>({triggers.length}) — MACD turning up + above VWAP (earliest confirmed recovery)</span>
        </div>
        {triggers.length
          ? <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
              {triggers.map(c => <CandidateCard key={c.symbol} c={c} onDrill={onDrill} onDismiss={dismiss} />)}
            </div>
          : <div style={{ ...card, color: BB.text3, fontSize: TYPE.base }}>No triggers today — a deep pullback in a standing uptrend with the cross about to fire is rare (expected on most days).</div>}
      </section>

      <section>
        <div style={{ fontSize: TYPE.base, fontWeight: 800, marginBottom: 8, color: BB.text0 }}>
          👀 Watch <span style={{ color: BB.text3, fontWeight: 400 }}>({watch.length}) — in pullback, recovery not yet confirmed</span>
        </div>
        {watch.length
          ? <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
              {watch.map(c => <CandidateCard key={c.symbol} c={c} onDrill={onDrill} onDismiss={dismiss} />)}
            </div>
          : <div style={{ ...card, color: BB.text3, fontSize: TYPE.base }}>No watch candidates.</div>}
      </section>
    </div>
  )
}
