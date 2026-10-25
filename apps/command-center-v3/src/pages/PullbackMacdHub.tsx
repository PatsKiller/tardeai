import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { MobileDetailSheet, useMobilePageDetail } from '../components/MobileDetailSheet'
import TickerLinks from '../components/TickerLinks'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'
import { BB, T, TYPE, RAIL, numStyle, terminalButton } from '../lib/watchTokens'
import { Chip, StatePills } from '../components/TerminalChip'
import { accountName } from '../lib/accountLabels'

// v3 Pullback/MACD Screener — S&P 500 names in an uptrend that have pulled back ~20% off their
// 52-week high and whose MACD is approaching a bullish cross. Two tiers: trigger / watch.
// Advisory only — auto-generated proposals require operator approval; nothing auto-executes.
// v4 (WS-A): watchTokens sweep — rails carry tier/conflict, chips replace ad-hoc pills.

interface Props { onDrill: (ctx: DrillContext) => void; embedded?: boolean }

const card = { background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: 14 }

const fmt = (v: any, d = 2) => (v === null || v === undefined ? '—' : Number(v).toFixed(d))
const heldStopState = (held: any) => String(held?.stop_state || 'unknown').toLowerCase()
const heldStopLabel = (held: any) => ({ active: 'Active stop', pending_activation: 'Pending activation', filled: 'Filled', none: 'No stop', unknown: 'Stop state unavailable' } as Record<string, string>)[heldStopState(held)] || 'Stop state unavailable'
function HeldEvidence({ held }: { held: any }) {
  return <div style={{ color: BB.text3, fontSize: TYPE.xs, marginBottom: 8 }}>
    <div>{heldAccounts(held)}</div>
    <div>{heldStopLabel(held)}{held.stop_price != null ? ` · observed $${fmt(held.stop_price)}` : ''}</div>
  </div>
}
const heldAccounts = (held: any) => Array.isArray(held?.account_labels) && held.account_labels.length
  ? held.account_labels.map((label: string) => accountName(label)).join(' · ')
  : 'Held account names unavailable'

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

// Format the server's score and formula; no client-side score recomputation.
function scoreBreakdown(c: any, f: any): string {
  return [
    `Screen score: ${fmt(c.score, 0)}`,
    f?.formula ? `Screen formula: ${f.formula}` : 'Formula explanation unavailable',
    'CIO conviction is supplied separately.',
  ].join('\n')
}

function CandidateCard({ c, onDrill, onDismiss, riskOff, scoreFormula }: { c: any; onDrill: Props['onDrill']; onDismiss: (sym: string, cancel: boolean) => void; riskOff?: boolean; scoreFormula?: any }) {
  const trigger = c.tier === 'trigger'
  const queued = trigger && c.proposal_live === true
  const rail = c.held_conflict ? RAIL.attention : trigger ? RAIL.favorable : RAIL.neutral
  const pills: Array<{ label: string; tone?: 'green' | 'amber' | 'red' | 'slate'; title?: string }> = [
    { label: trigger ? 'TRIGGER' : 'WATCH', tone: trigger ? 'green' : 'slate' },
  ]
  if (c.held) pills.push({
    label: `HELD · ${Math.round(c.held.shares)} sh`,
    tone: heldStopState(c.held) === 'active' ? 'green' : heldStopState(c.held) === 'filled' ? 'slate' : 'amber',
    title: heldStopLabel(c.held),
  })
  return (
    <div data-testid={`pullback-${c.symbol}`} style={{ ...card, borderLeft: `3px solid ${rail}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <button aria-label={`View ${c.symbol}`} style={{ ...terminalButton('ghost'), ...numStyle, fontSize: TYPE.md, fontWeight: 800, color: BB.text0 }}
          onClick={() => onDrill({ kind: 'symbol', symbol: c.symbol } as any)}>{c.symbol}</button>
        <StatePills pills={pills} />
        <span style={{ marginLeft: 'auto' }}>
          <Chip kind="metric" title={scoreBreakdown(c, scoreFormula)}>score {fmt(c.score, 0)}</Chip>
        </span>
      </div>
      {/* v4 (F1): regime disclosure on TRIGGER cards — no suppression until the outcome
          ledger can prove suppression is warranted; disclosure only */}
      {trigger && riskOff && (
        <div style={{ margin: '0 0 8px', padding: '4px 10px', borderRadius: 2, fontSize: TYPE.xs, fontWeight: 700,
          borderLeft: `3px solid ${RAIL.attention}`, background: BB.amberDim, color: BB.amber }}>
          Regime risk-off · review the trigger evidence and plan
        </div>
      )}
      {c.held_conflict && (
        <div style={{ margin: '0 0 8px', padding: '6px 10px', borderRadius: 2, fontSize: TYPE.sm, fontWeight: 700,
          background: BB.amberDim, border: `1px solid ${BB.amber}66`, color: BB.amber }}>
          ⚠ Held position near stop — adding here averages down; review stop plan first
        </div>
      )}
      {c.held && <HeldEvidence held={c.held} />}
      <PullbackBanner c={c} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, fontSize: TYPE.sm }}>
        <Metric tip="Advisory entry from the latest screen. Review the setup before acting." label="Entry" value={fmt(c.entry)} />
        <Metric tip="Advisory technical invalidation level. Observed protection is shown separately." label="Plan stop" value={fmt(c.stop)} />
        <Metric tip="First recovery target supplied by the screen." label="Target1" value={fmt(c.target1)} />
        <Metric tip="Potential gain to the first target per unit of planned risk; a screening estimate." label="R:R" value={fmt(c.rr, 1)} />
        <Metric tip="Moving-average spread used by the uptrend screen." label="Trend (50/200)" value={`+${fmt(c.trend_pct, 1)}%`} />
        <Metric tip="|MACD − signal| as % of price — imminence to the cross (lower = closer)" label="MACD prox" value={`${fmt(c.macd_prox_pct, 3)}%`} />
        <Metric tip="Last price vs intraday session VWAP — entry-timing confirmation" label="vs VWAP" value={c.vwap_dist_pct == null ? '—' : `${c.vwap_dist_pct > 0 ? '+' : ''}${fmt(c.vwap_dist_pct, 2)}%`} />
        <Metric tip="Typical daily range used by the technical plan." label="ATR" value={fmt(c.atr)} />
      </div>
      <div style={{ marginTop: 6 }}><TickerLinks symbol={c.symbol} /></div>
      <div className="w3-pullback-actions" style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
        {queued
          ? <span style={{ fontSize: TYPE.xs, color: T.link }}>Advisory proposal in approval queue</span>
          : <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>{trigger ? 'No active proposal' : 'Watching · trigger confirmation required'}</span>}
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button style={terminalButton('ghost')} title="Hide for 10 trading days (re-shows early only if score improves ≥25%). Proposal untouched."
            onClick={() => onDismiss(c.symbol, false)}>Dismiss</button>
          {queued
            ? <button style={terminalButton('danger')} title="Hide for 10 trading days AND reject the linked PENDING advisory proposal (no order surface involved)."
                onClick={() => onDismiss(c.symbol, true)}>Dismiss + cancel</button>
            : null}
        </span>
      </div>
      <button aria-label={`View ${c.symbol} setup`} style={{ ...terminalButton('primary'), width: '100%', minHeight: 44, marginTop: 12 }} onClick={() => onDrill({ kind: 'symbol', symbol: c.symbol } as any)}>View setup</button>
    </div>
  )
}

const Metric = ({ label, value, tip }: any) => (
  <details style={{ minWidth: 0 }}>
    <summary title={tip} style={{ cursor: 'pointer', minHeight: 44, listStyle: 'none', padding: '4px 0' }}>
      <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>{label} ⓘ</div>
      <div style={{ ...numStyle, fontWeight: 700, color: BB.text1 }}>{value}</div>
    </summary>
    <div style={{ color: BB.text3, fontSize: TYPE.xs, overflowWrap: 'anywhere' }}>{tip || 'Explanation unavailable'}</div>
  </details>
)

export default function PullbackMacdHub({ onDrill, embedded }: Props) {
  const { data, loading, error, refetch } = useApi<any>('/api/v2/pullback-macd/candidates', 60_000)
  // v4 (F1): same regime read as the tab-level WatchRegimeStrip — one source of truth
  const { data: regime } = useApi<any>('/api/v2/risk-regime/latest', 300_000)
  const riskOff = /off/i.test(String(regime?.regime_label || ''))
  const cands: any[] = data?.candidates ?? []
  const triggers = cands.filter(c => c.tier === 'trigger')
  const watch = cands.filter(c => c.tier === 'watch')
  const [params, setParams] = useSearchParams()
  const setupDetail = useMobilePageDetail('setup')
  const selected = cands.find(c => c.symbol === setupDetail.id)
  const filter = params.get('setupTier') || 'all'
  const openSetup = (ctx: DrillContext) => { setMsg(null); setupDetail.open(String((ctx as any).symbol)) }
  const closeSetup = setupDetail.close
  const [research, setResearch] = useState<DrillContext | null>(null)
  useEffect(() => {
    if (research && !selected) { onDrill(research); setResearch(null) }
  }, [research, selected, onDrill])
  const run = data?.last_run
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [actionBusy, setActionBusy] = useState<string | null>(null)

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
    setActionBusy(symbol); setMsg(`${symbol}: dismissing…`)
    try {
      const j = await post('/api/v2/pullback-macd/dismiss', { symbol, cancel_proposal: cancel })
      setMsg(j.ok ? `✓ ${symbol} dismissed${j.proposal_cancelled ? ' · advisory proposal cancelled' : ''}` : 'Error: ' + j.error)
      if (j.ok) refetch()
      return Boolean(j.ok)
    } catch (e: any) { setMsg('Error: ' + e.message); return false }
    finally { setActionBusy(null) }
  }

  return (
    <div className="w3-pullback" style={{ display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}>
      <style>{`
        .w3-pullback button,.w3-pullback select,.w3-pullback a { min-height:44px; }
        .w3-pullback a { display:inline-flex; align-items:center; }
        @media(max-width:820px) { .w3-pullback-actions { align-items:stretch; flex-direction:column; } .w3-pullback-primary { width:100%; margin-top:auto; min-height:44px; } }
      `}</style>
      {msg && !selected && <div data-testid="pullback-action-notice" role="status" style={{ position: 'fixed', left: 12, right: 12, bottom: 'calc(88px + env(safe-area-inset-bottom))', zIndex: 1300, padding: 12, background: BB.bg, color: msg.startsWith('Error') ? BB.red : BB.text1, border: `1px solid ${BB.border}`, fontSize: TYPE.sm, pointerEvents: 'none' }}>{msg}</div>}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        {!embedded ? (
          <div style={{ flex: 1 }}>
            <h1 style={{ fontSize: TYPE.lg, fontWeight: 800, margin: 0, color: BB.text0 }}>Pullback / MACD Screener</h1>
            <div style={{ fontSize: TYPE.sm, color: BB.text3, marginTop: 2 }}>
              S&P 500 uptrends pulled back 12–28%, earliest recovery confirmed (MACD histogram turning up + above VWAP) ·
              advisory only, proposals require approval ·
              {run ? ` last scan ${run.scan_date} (${run.screened} screened — ${data?.scan_provenance?.universe || 'S&P 500 uptrend pullbacks'})` : ' no scan recorded yet'}{data?.hit_stats ? ` · last ${data.hit_stats.window_days}d: ${data.hit_stats.triggers} triggers${data.hit_stats.evaluated ? ` · ${data.hit_stats.target1_first}/${data.hit_stats.evaluated} reached T1 first${data.hit_stats.median_days ? ` · median ${Math.round(data.hit_stats.median_days)}d` : ''}` : ' · outcomes n/a until evaluations accrue'}` : ''}{data?.dismissed_in_cooldown ? ` · ${data.dismissed_in_cooldown} in dismiss-cooldown` : ''}
            </div>
          </div>
        ) : (
          <div style={{ flex: 1, fontSize: TYPE.sm, color: BB.text3 }}>
            <span title={data?.scan_provenance?.schedule || ''}>{run ? `Last scan ${run.scan_date} (${run.screened} screened — ${data?.scan_provenance?.universe || 'S&P 500 uptrend pullbacks'})` : 'No scan recorded yet'}{data?.hit_stats ? ` · last ${data.hit_stats.window_days}d: ${data.hit_stats.triggers} triggers${data.hit_stats.evaluated ? ` · ${data.hit_stats.target1_first}/${data.hit_stats.evaluated} reached T1 first${data.hit_stats.median_days ? ` · median ${Math.round(data.hit_stats.median_days)}d` : ''}` : ' · outcomes n/a until evaluations accrue'}` : ''}{data?.dismissed_in_cooldown ? ` · ${data.dismissed_in_cooldown} in dismiss-cooldown` : ''}</span>
          </div>
        )}
        <button style={{ ...terminalButton('primary'), opacity: busy ? 0.6 : 1 }}
          disabled={busy} onClick={runScan}>{busy ? 'Scanning…' : '↻ Run scan now'}</button>
      </div>

      {error && <div style={{ ...card, color: BB.red }}>API error: {String(error)}</div>}
      {loading && !cands.length && <div style={{ ...card, color: BB.text3 }}>Loading…</div>}

      <label style={{ color: BB.text2, fontSize: TYPE.sm }}>Filter setups{' '}
        <select aria-label="Filter setup tier" value={filter} style={terminalButton('secondary')} onChange={e => { const next = new URLSearchParams(params); next.set('setupTier', e.target.value); setParams(next, { replace: true }) }}>
          <option value="all">All setups</option><option value="trigger">Triggers</option><option value="watch">Watching</option>
        </select>
      </label>
      {filter !== 'watch' && <section>
        <div style={{ fontSize: TYPE.base, fontWeight: 800, marginBottom: 8, color: BB.text0 }}>
          🎯 Triggers <span style={{ color: BB.text3, fontWeight: 400 }}>({data?.trigger_count ?? '—'}) — MACD turning up + above VWAP (earliest confirmed recovery){riskOff ? ' · regime risk-off' : ''}</span>
        </div>
        {triggers.length
          ? <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 320px), 1fr))', gap: 12 }}>
              {triggers.map(c => <CandidateCard key={c.symbol} c={c} onDrill={openSetup} onDismiss={dismiss} riskOff={riskOff} scoreFormula={data?.score_formula} />)}
            </div>
          : <div style={{ ...card, color: BB.text3, fontSize: TYPE.base }}>No confirmed triggers in the latest screen.</div>}
      </section>}

      {filter !== 'trigger' && <section>
        <div style={{ fontSize: TYPE.base, fontWeight: 800, marginBottom: 8, color: BB.text0 }}>
          👀 Watch <span style={{ color: BB.text3, fontWeight: 400 }}>({data?.watch_count ?? '—'}) — in pullback, recovery not yet confirmed</span>
        </div>
        {watch.length
          ? <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 320px), 1fr))', gap: 12 }}>
              {watch.map(c => <CandidateCard key={c.symbol} c={c} onDrill={openSetup} onDismiss={dismiss} scoreFormula={data?.score_formula} />)}
            </div>
          : <div style={{ ...card, color: BB.text3, fontSize: TYPE.base }}>No watch candidates.</div>}
      </section>}
      {selected && <MobileDetailSheet title={`${selected.symbol} setup detail`} onBack={closeSetup}>
        <h2 style={{ margin: 0, color: BB.text0 }}>{selected.symbol} · {selected.tier === 'trigger' ? 'Triggered' : 'Watching'}</h2>
        {selected.held && <HeldEvidence held={selected.held} />}
        <PullbackBanner c={selected} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,minmax(0,1fr))', gap: 12 }}>
          <Metric tip="Advisory entry from the latest screen. Review the setup before acting." label="Entry" value={fmt(selected.entry)} /><Metric tip="Advisory technical invalidation level. Observed protection is shown separately." label="Plan stop" value={fmt(selected.stop)} />
          <Metric tip="First recovery target supplied by the screen." label="Target" value={fmt(selected.target1)} /><Metric tip="Potential gain to the first target per unit of planned risk; a screening estimate." label="R:R" value={fmt(selected.rr, 1)} />
          <Metric tip="Volume-weighted average price used for trigger confirmation." label="VWAP" value={fmt(selected.vwap)} /><Metric tip="Composite screen score. CIO conviction is supplied separately." label="Score" value={fmt(selected.score, 0)} />
        </div>
        <p style={{ color: BB.text2 }}>{selected.tier === 'trigger' && selected.proposal_live === true ? 'Advisory proposal in approval queue' : selected.tier === 'watch' ? 'Watching · trigger confirmation required' : 'No active proposal'}</p>
        <div style={{ color: BB.text3, fontSize: TYPE.sm }}>{scoreBreakdown(selected, data?.score_formula)}</div>
        <button style={terminalButton('secondary')} onClick={() => { setResearch({ title: selected.symbol, endpoint: `/api/v2/watch/provenance/${selected.symbol}`, rows: [selected], subjectType: 'security', subjectKey: selected.symbol }); closeSetup() }}>Full research and provenance</button>
        {msg && <p role="status" style={{ color: msg.startsWith('Error') ? BB.red : BB.text2 }}>{msg}</p>}
        <button className="w3-pullback-primary mobile-detail-primary" disabled={actionBusy === selected.symbol} style={terminalButton('primary')} onClick={async () => { if (await dismiss(selected.symbol, false)) closeSetup() }}>{actionBusy === selected.symbol ? 'Dismissing…' : 'Dismiss from this screen'}</button>
      </MobileDetailSheet>}
    </div>
  )
}
