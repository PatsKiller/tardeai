import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { BB, DASH, numStyle } from '../lib/watchTokens'
import { hubTitle, hubSubtitle } from '../lib/terminalHubChrome'
import { useTerminalUi } from '../lib/terminalUi'
import RotationBoards from '../components/defense/RotationBoards'
import DefenseDetails from '../components/defense/DefenseDetails'
import ExecutionPanel from '../components/defense/ExecutionPanel'
import ReviewConsole from '../components/defense/ReviewConsole'
import RotationPlanPanel from '../components/defense/RotationPlanPanel'
import OptionsLifecycleStrip from '../components/defense/OptionsLifecycleStrip'
import DefenseRedesign from '../components/defense/redesign/DefenseRedesign'

function ago(ts?: string | null): string {
  if (!ts) return 'never'
  const mins = Math.round((Date.now() - new Date(ts).getTime()) / 60000)
  if (mins < 60) return `${mins}m ago`
  if (mins < 60 * 36) return `${Math.round(mins / 60)}h ago`
  return `${Math.round(mins / 1440)}d ago`
}

// Defense Desk v3: deterministic posture and recommendations remain authoritative.
// Model seats critique the evidence and must never be presented as the source of market truth.

export default function DefenseHub() {
  const [terminalUi] = useTerminalUi()
  const { data: posture } = useApi<any>('/api/v2/defense/posture', 300_000)
  const { data: industries } = useApi<any>('/api/v2/defense/industries', 300_000)
  const { data: recsData, refetch: refetchRecs } = useApi<any>('/api/v2/defense/recommendations', 60_000)
  const { data: regime } = useApi<any>('/api/v2/risk-regime/latest', 300_000)
  const { data: tradeAi } = useApi<any>('/api/v2/trade-ai/summary', 300_000)
  const [queueing, setQueueing] = useState(false)
  const [deepSeekRefreshing, setDeepSeekRefreshing] = useState(false)

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

  const startDeepSeek = async () => {
    setDeepSeekRefreshing(true)
    try {
      const r = await (await fetch('/api/v2/defense/deepseek-refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })).json()
      if (!r.ok) { alert('DeepSeek refresh failed to start: ' + (r.error || 'unknown')); return }
      refetchRecs()
    } catch (e) { alert('DeepSeek refresh request failed: ' + String(e)) }
    finally { setDeepSeekRefreshing(false) }
  }

  // The redesigned desk — no feature flag. It shipped gated for one deploy and
  // the operator removed the gate; rollback is a git revert, not a runtime toggle.
  //
  // Section 6 (quadrant + ranked lists) is PRESERVED and passed through per
  // contract §5. Live components absent from the mockup are preserved unmodified
  // below section 9 per contract §2b.
  //
  // The superseded ARRANGEMENT is retired: the RESEARCH WATCH decision board, the
  // old stance strip, recommendations rail and stoplight rail each have a
  // redesigned section above. Those COMPONENTS are untouched and still in the
  // tree — only this page's old composition is gone.
  return (
    <div style={{ maxWidth: 1720, margin: '0 auto' }}>
      <DefenseRedesign
        posture={posture} recsData={recsData} tradeAi={tradeAi} regime={regime}
        industriesCapturedAt={industries?.captured_at}
        onRefresh={startRefresh} refreshing={queueing}
        onDeepSeek={startDeepSeek} deepSeekRefreshing={deepSeekRefreshing}
        quadrant={<RotationBoards sectors={rows} industries={ind} spyLong={spyLong} oversight={recsData?.oversight} />}
        preserved={
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <ExecutionPanel intents={recsData?.intents || []} execLog={recsData?.execution_log || []}
              capsCfg={recsData?.execution_caps} onChange={refetchRecs} />
            <OptionsLifecycleStrip />
            <RotationPlanPanel plan={recs?.rotation_plan || []} onConfirmed={refetchRecs} oversight={recsData?.oversight} />
            <ReviewConsole />
            <DefenseDetails posture={posture} industries={industries} radar={radar}
              operatorItems={recs?.operator_items} />
          </div>
        }
      />
    </div>
  )
}
