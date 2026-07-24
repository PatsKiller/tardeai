import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { BB, DASH, numStyle } from '../lib/watchTokens'
import { hubTitle, hubSubtitle } from '../lib/terminalHubChrome'
import { useTerminalUi } from '../lib/terminalUi'
import RecommendationsRail from '../components/defense/RecommendationsRail'
import RotationBoards from '../components/defense/RotationBoards'
import DefenseDetails from '../components/defense/DefenseDetails'
import BookStanceStrip from '../components/defense/BookStanceStrip'
import ExecutionPanel from '../components/defense/ExecutionPanel'
import ReviewConsole from '../components/defense/ReviewConsole'
import RotationPlanPanel from '../components/defense/RotationPlanPanel'
import OptionsLifecycleStrip from '../components/defense/OptionsLifecycleStrip'
import InverseStoplightRail from '../components/defense/InverseStoplightRail'
import InstitutionalRotationBrief from '../components/rotation/InstitutionalRotationBrief'

function ago(ts?: string | null): string {
  if (!ts) return 'never'
  const mins = Math.round((Date.now() - new Date(ts).getTime()) / 60000)
  if (mins < 60) return `${mins}m ago`
  if (mins < 60 * 36) return `${Math.round(mins / 60)}h ago`
  return `${Math.round(mins / 1440)}d ago`
}

function FreshnessStrip({ sources, job, onRefresh, refreshing }: {
  sources: Record<string, string | null>; job: any; onRefresh: () => void; refreshing: boolean
}) {
  const running = job?.state === 'running'
  const stale = (ts?: string | null) => !ts || (Date.now() - new Date(ts).getTime()) > 24 * 3600e3
  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', fontSize: DASH.data, color: BB.text3 }}>
      {Object.entries(sources || {}).map(([k, ts]) => (
        <span key={k} title={`last time the ${k.replace('_', ' ')} producer wrote its snapshot (${ts || 'never'}) — amber = older than 24h`} style={{ cursor: 'help' }}>
          {k.replace('_', ' ')} <b style={{ ...numStyle, color: stale(ts) ? BB.amber : BB.text2 }}>{ago(ts)}</b>
        </span>
      ))}
      {running ? (
        <span style={{ color: BB.amber, fontWeight: 700 }}>
          ⟳ refresh running: {job.step || '…'} ({(job.steps || []).filter((s: any) => s.state === 'done').length}/{(job.steps || []).length})
        </span>
      ) : (
        <button onClick={onRefresh} disabled={refreshing} title="queues a detached 4-step refresh (sectors → industries → radar → recommendations); the page polls per-step status — no waiting. Industry STATES stay owned by the 16:18 close cron." style={{
          fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', cursor: 'pointer',
          color: BB.text2, background: 'transparent', border: `1px solid ${BB.border}`, borderRadius: 2, padding: '2px 9px',
        }}>{refreshing ? 'queueing…' : '⟳ refresh all'}</button>
      )}
      {job?.state === 'error' && <span style={{ color: BB.red }}>last refresh failed at {job.step || job.error}</span>}
      {job?.state === 'done' && !running && <span>last manual refresh {ago(job.finished_at)}</span>}
    </div>
  )
}

// Defense Desk v3: deterministic posture and recommendations remain authoritative.
// Model seats critique the evidence and must never be presented as the source of market truth.

function Big({ label, value, tone, tip }: { label: string; value: string; tone?: string; tip?: string }) {
  return (
    <div style={{ minWidth: 130 }} title={tip}>
      <div style={{ fontSize: DASH.chip, fontWeight: 800, color: BB.text3, textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 2, cursor: tip ? 'help' : 'default' }}>{label}</div>
      <div style={{ ...numStyle, fontSize: DASH.verdict, fontWeight: 800, color: tone || BB.text1 }}>{value}</div>
    </div>
  )
}

export default function DefenseHub() {
  const [terminalUi] = useTerminalUi()
  const { data: posture } = useApi<any>('/api/v2/defense/posture', 300_000)
  const { data: industries } = useApi<any>('/api/v2/defense/industries', 300_000)
  const { data: recsData, refetch: refetchRecs } = useApi<any>('/api/v2/defense/recommendations', 60_000)
  const { data: regime } = useApi<any>('/api/v2/risk-regime/latest', 300_000)
  const { data: tradeAi } = useApi<any>('/api/v2/trade-ai/summary', 300_000)
  const [queueing, setQueueing] = useState(false)

  const rows: any[] = posture?.momentum?.rows || []
  const market = posture?.momentum?.market
  const transitions: any[] = posture?.momentum?.transitions_today || []
  const net = posture?.net_exposure
  const recs = recsData?.recommendations
  const radar = recsData?.hedging_radar
  const job = recsData?.refresh_job
  const ind: any[] = industries?.industries || []
  const weakLag = rows.filter(r => r.state === 'WEAKENING' || r.state === 'LAGGING')
  const shortAdvised = (recs?.groups?.short_side || []).length
  const spyLong = (market?.indices || []).find((i: any) => i.symbol === 'SPY')?.long ?? null
  const techRow = rows.find(r => r.sector === 'Technology')

  const [paidBusy, setPaidBusy] = useState(false)
  const runPaid = async () => {
    setPaidBusy(true)
    try {
      const pv = await (await fetch('/api/v2/defense/oversight/paid', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })).json()
      if (!pv.ok) { alert(pv.error || 'preview failed'); return }
      const seatLines = Object.entries(pv.seats).map(([k, v]: any) => `  ${k}: ${v.model} — $${v.cost_est_usd}`).join('\n')
      const pick = window.prompt(
        `⚖ Model critique — brief ~${pv.input_tokens_est.toLocaleString()} tokens\n${seatLines}\n\nBudget remaining: $${pv.budget_remaining_usd} of $${pv.monthly_budget_usd}\n\nSeats to run (comma list or 'panel' for all):`, 'paid')
      if (!pick) return
      const seats = pick.trim() === 'panel' ? Object.keys(pv.seats) : pick.split(',').map(x => x.trim()).filter(Boolean)
      const r = await (await fetch('/api/v2/defense/oversight/paid', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm: true, seats }) })).json()
      const lines = Object.entries(r.results || {}).map(([k, v]: any) => `${k}: ${v.status}${v.error ? ' — ' + v.error.slice(0, 60) : ''}`).join('\n')
      alert(`Model critique — spent $${r.spent_usd}\n${lines}\n\nCritique pills and memo updated where available. Deterministic facts and permission gates are unchanged.`)
      refetchRecs()
    } finally { setPaidBusy(false) }
  }

  const startRefresh = async () => {
    setQueueing(true)
    try {
      await fetch('/api/v2/defense/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      refetchRecs()
    } finally { setQueueing(false) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 1480, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={hubTitle()}>Defense Desk</div>
          <div style={hubSubtitle(terminalUi)}>
            institutional rotation · portfolio defense · governed recommendations — nothing here places orders
          </div>
        </div>
        <button onClick={runPaid} disabled={paidBusy}
          title="Runs a bounded critique of the current evidence packet. Models can concur, qualify or object; they do not create market facts, change recommendations, approve orders or widen permissions."
          style={{ fontSize: DASH.data, fontWeight: 800, cursor: 'pointer', color: BB.text1, background: 'transparent', border: `1px solid ${BB.amber}`, borderRadius: 2, padding: '4px 12px' }}>
          {paidBusy ? 'reviewing…' : '⚖ Run model critique (paid)'}
        </button>
        <FreshnessStrip
          sources={{ ...(recs?.sources || {}), recommendations: recs?.generated_at }}
          job={job} onRefresh={startRefresh} refreshing={queueing}
        />
      </div>

      <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderLeft: `3px solid ${weakLag.length >= 3 ? BB.red : weakLag.length ? BB.amber : BB.green}`, borderRadius: 2, padding: '14px 16px' }}>
        <div style={{ fontSize: DASH.verdict, fontWeight: 800, color: BB.text1, lineHeight: 1.35, marginBottom: 12 }}>
          {market?.state_line || 'market engine warming up'}
        </div>
        <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <Big label="Net equity exposure" value={net ? `${net.equity_pct}%` : '—'} tone={BB.amber}
            tip="equity ÷ (equity + cash) across all accounts — the cash remainder already acts as a hedge" />
          <Big label="Effective tech (LAGGING)" value={techRow?.book_pct != null ? `${techRow.book_pct}%` : '—'}
            tone={(techRow?.book_pct ?? 0) > 15 ? BB.red : BB.text1}
            tip={`direct tech holdings (${techRow?.book_direct_pct ?? '—'}%) + configured fund look-through; verify factsheet dates before treating this as precision exposure`} />
          <Big label="Hedges · active / advised" value={`0 / ${shortAdvised}`} tone={shortAdvised ? BB.red : BB.text1}
            tip="active = open hedge positions detected · advised = complete short-side cards passing current recommendation fields and rails" />
          <Big label="Transitions today" value={String(transitions.length)} tone={transitions.length ? BB.amber : BB.text1}
            tip="sector/style state changes confirmed by two consecutive closes in the new state" />
          <Big label="VIX · regime" value={`${tradeAi?.vix ?? '—'}`}
            tip="CBOE VIX plus the risk-regime engine; verify each source timestamp in the freshness ledger" />
          <div style={{ fontSize: DASH.data, color: BB.text3, paddingBottom: 4 }}>
            {regime?.regime_label?.replace(/_/g, ' ') ?? ''}
            {net && <span> · {net.cash_pct}% cash ≈ ${Math.round(net.cash_dollars / 1000)}K is already a hedge</span>}
            {techRow?.book_pct != null && (
              <span> · tech {techRow.book_pct}% effective ({techRow.book_direct_pct}% direct + configured fund look-through)</span>
            )}
          </div>
        </div>
        {transitions.length > 0 && (
          <div style={{ marginTop: 10 }}>
            {transitions.map((t: any, i: number) => (
              <div key={i} style={{ fontSize: DASH.section, fontWeight: 700, color: t.severity === 'urgent' ? BB.red : BB.amber, padding: '2px 0' }}>{t.line}</div>
            ))}
          </div>
        )}
      </div>

      <InstitutionalRotationBrief
        sectors={rows}
        industries={ind}
        recommendations={recs}
        generatedAt={posture?.momentum?.generated_at}
        industryCapturedAt={industries?.captured_at}
      />

      <BookStanceStrip stances={recs?.stances || []} notDecomposed={recs?.not_decomposed}
        ladders={recs?.ladders || []} oversight={recsData?.oversight} />

      <ExecutionPanel intents={recsData?.intents || []} execLog={recsData?.execution_log || []}
        capsCfg={recsData?.execution_caps} onChange={refetchRecs} />

      <OptionsLifecycleStrip />
      <InverseStoplightRail />

      <RotationPlanPanel plan={recs?.rotation_plan || []} onConfirmed={refetchRecs} oversight={recsData?.oversight} />
      <RecommendationsRail recs={recs} oversight={recsData?.oversight} />
      <RotationBoards sectors={rows} industries={ind} spyLong={spyLong} oversight={recsData?.oversight} />
      <ReviewConsole />
      <DefenseDetails posture={posture} industries={industries} radar={radar}
        operatorItems={recs?.operator_items} />
    </div>
  )
}
