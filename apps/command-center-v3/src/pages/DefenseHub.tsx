import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { BB, DASH, numStyle } from '../lib/watchTokens'
import { hubTitle, hubSubtitle } from '../lib/terminalHubChrome'
import { useTerminalUi } from '../lib/terminalUi'
import RecommendationsRail from '../components/defense/RecommendationsRail'
import RotationBoards from '../components/defense/RotationBoards'
import DefenseDetails from '../components/defense/DefenseDetails'
import BookStanceStrip from '../components/defense/BookStanceStrip'
import RotationPlanPanel from '../components/defense/RotationPlanPanel'

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
        <span key={k}>
          {k.replace('_', ' ')} <b style={{ ...numStyle, color: stale(ts) ? BB.amber : BB.text2 }}>{ago(ts)}</b>
        </span>
      ))}
      {running ? (
        <span style={{ color: BB.amber, fontWeight: 700 }}>
          ⟳ refresh running: {job.step || '…'} ({(job.steps || []).filter((s: any) => s.state === 'done').length}/{(job.steps || []).length})
        </span>
      ) : (
        <button onClick={onRefresh} disabled={refreshing} style={{
          fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', cursor: 'pointer',
          color: BB.text2, background: 'transparent', border: `1px solid ${BB.border}`, borderRadius: 2, padding: '2px 9px',
        }}>{refreshing ? 'queueing…' : '⟳ refresh all'}</button>
      )}
      {job?.state === 'error' && <span style={{ color: BB.red }}>last refresh failed at {job.step || job.error}</span>}
      {job?.state === 'done' && !running && <span>last manual refresh {ago(job.finished_at)}</span>}
    </div>
  )
}

// Defense Desk v3 (WS-D3): a dashboard, not a data dump. Row 1 verdict + four big
// numbers · Row 2 recommendations (the reason the desk exists) · Row 3 rotation
// picture · Row 4 collapsed detail folds. House scale = DASH tokens; the design
// guard (scripts/check_design_tokens.sh) blocks raw hex and sub-10px regressions.

function Big({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div style={{ minWidth: 130 }}>
      <div style={{ fontSize: DASH.chip, fontWeight: 800, color: BB.text3, textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 2 }}>{label}</div>
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
            recommendations · rotation · hedging — advisory only, nothing here places orders
          </div>
        </div>
        <FreshnessStrip
          sources={{ ...(recs?.sources || {}), recommendations: recs?.generated_at }}
          job={job} onRefresh={startRefresh} refreshing={queueing}
        />
      </div>

      {/* Row 1 — verdict */}
      <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderLeft: `3px solid ${weakLag.length >= 3 ? BB.red : weakLag.length ? BB.amber : BB.green}`, borderRadius: 2, padding: '14px 16px' }}>
        <div style={{ fontSize: DASH.verdict, fontWeight: 800, color: BB.text1, lineHeight: 1.35, marginBottom: 12 }}>
          {market?.state_line || 'market engine warming up'}
        </div>
        <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <Big label="Net equity exposure" value={net ? `${net.equity_pct}%` : '—'} tone={BB.amber} />
          <Big label="Effective tech (LAGGING)" value={techRow?.book_pct != null ? `${techRow.book_pct}%` : '—'}
            tone={(techRow?.book_pct ?? 0) > 15 ? BB.red : BB.text1} />
          <Big label="Hedges · active / advised" value={`0 / ${shortAdvised}`} tone={shortAdvised ? BB.red : BB.text1} />
          <Big label="Transitions today" value={String(transitions.length)} tone={transitions.length ? BB.amber : BB.text1} />
          <Big label="VIX · regime" value={`${tradeAi?.vix ?? '—'}`} />
          <div style={{ fontSize: DASH.data, color: BB.text3, paddingBottom: 4 }}>
            {regime?.regime_label?.replace(/_/g, ' ') ?? ''}
            {net && <span> · {net.cash_pct}% cash ≈ ${Math.round(net.cash_dollars / 1000)}K is already a hedge</span>}
            {techRow?.book_pct != null && (
              <span> · tech {techRow.book_pct}% effective ({techRow.book_direct_pct}% direct + fund lookthrough)</span>
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

      {/* Row 2a — your book: every ≥$10K position has a stance (L3), ladder progress inline */}
      <BookStanceStrip stances={recs?.stances || []} notDecomposed={recs?.not_decomposed}
        ladders={recs?.ladders || []} />

      {/* Row 2b — THE ROTATION PLAN (v5): trims, ladders, re-entry watches — the page's memory */}
      <RotationPlanPanel plan={recs?.rotation_plan || []} onConfirmed={refetchRecs} />

      {/* Row 2c — the recommendations rail */}
      <RecommendationsRail recs={recs} />

      {/* Row 3 — the rotation picture */}
      <RotationBoards sectors={rows} industries={ind} spyLong={spyLong} />

      {/* Row 4 — detail folds, collapsed by default */}
      <DefenseDetails posture={posture} industries={industries} radar={radar} />
    </div>
  )
}
