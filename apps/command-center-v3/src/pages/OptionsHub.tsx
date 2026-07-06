import { useMemo, useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { type OptionProposal } from '../components/OptionProposalCard'
import { type OptionPosition } from '../components/OptionPositionCard'
import OptionProposalCardV4, { type AlpacaLaneAction, type AlpacaActionResult } from '../components/OptionProposalCardV4'
import OptionPositionCardV4 from '../components/OptionPositionCardV4'
import OptionReviewBar from '../components/OptionReviewBar'
import ManualExecutionModal, { type ManualExecSeed } from '../components/ManualExecutionModal'
import ManualExecutionLog from '../components/ManualExecutionLog'
import { OpenOptionsIntroBanner, Options101Banner, NoviceToggle, PreflightConfirmModal } from '../components/OptionsNovicePanel'
import { isNoviceMode, setNoviceMode, strategyGuide, GLOSSARY } from '../lib/optionsNovice'
import { fmt$ } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'
import GreeksOverview from '../components/risk/GreeksOverview'
import OptionsPnLProfile from '../components/risk/OptionsPnLProfile'
import OptionsTrendsPanel from '../components/OptionsTrendsPanel'
import { Tip, TipChip, TipKpi, TipLabel, TipSection } from '../components/OptionsTip'
import { HEADER, TABS as TAB_TIPS, FILTERS, OVERVIEW, POSITION } from '../lib/optionsTooltips'

interface Props { onDrill: (ctx: DrillContext) => void }

const TABS = ['Proposals', 'Open Options', 'Strategy Overview', 'Options Trends'] as const
const LEGACY_TAB_ALIASES: Record<string, typeof TABS[number]> = {
  'Open Positions': 'Open Options',
}
const panel = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }
const SEL: React.CSSProperties = { fontSize: 11, padding: '6px 9px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text0)' }
const PURPLE = '#a855f7'

// Stage 3: Alpaca paper lane status filters (client-side over queue_status —
// these rows come from options_approval_queue, not the desk generator facets).
const ALPACA_LANE_FILTERS: { key: string; label: string; statuses: string[] }[] = [
  { key: 'queued', label: 'Queued', statuses: ['pending', 'approved'] },
  { key: 'ready', label: 'Ready', statuses: ['READY_FOR_ALPACA_PAPER'] },
  { key: 'submitted', label: 'Submitted', statuses: ['ALPACA_PAPER_SUBMITTED'] },
  { key: 'filled', label: 'Filled', statuses: ['ALPACA_PAPER_FILLED'] },
  { key: 'closed', label: 'Closed', statuses: ['ALPACA_PAPER_CLOSED', 'ALPACA_PAPER_REJECTED'] },
  { key: 'outcome', label: 'Outcome ✓', statuses: ['OUTCOME_RECORDED'] },
  { key: 'live_review', label: 'Live review', statuses: ['READY_FOR_LIVE_REVIEW'] },
]

type Proposal = OptionProposal
type Position = OptionPosition

export default function OptionsHub({ onDrill }: Props) {
  const [searchParams, setSearchParams] = useSearchParams()
  const urlTab = searchParams.get('tab')
  const resolveTab = (t: string | null): typeof TABS[number] => {
    if (!t) return 'Proposals'
    const mapped = LEGACY_TAB_ALIASES[t] || t
    return (TABS as readonly string[]).includes(mapped) ? mapped as typeof TABS[number] : 'Proposals'
  }
  const [tab, setTab] = useState<typeof TABS[number]>(resolveTab(urlTab))

  const [symbolFilter, setSymbolFilter] = useState('')
  const [strategyFilter, setStrategyFilter] = useState('')
  const [groupFilter, setGroupFilter] = useState('')
  const [optionTypeFilter, setOptionTypeFilter] = useState('')
  const [sideFilter, setSideFilter] = useState('')
  const [sleeveFilter, setSleeveFilter] = useState('')
  const [legStyleFilter, setLegStyleFilter] = useState('')
  const [tierFilter, setTierFilter] = useState('')
  const [alpacaLaneFilter, setAlpacaLaneFilter] = useState('')
  const [liveOnly, setLiveOnly] = useState(false)
  const [minPop, setMinPop] = useState(0)
  const [minEdge, setMinEdge] = useState(0)
  const [posSymbolFilter, setPosSymbolFilter] = useState('')
  const [posTypeFilter, setPosTypeFilter] = useState('')
  const [posSideFilter, setPosSideFilter] = useState('')
  const [posWorkingOnly, setPosWorkingOnly] = useState(false)
  const [posRouteFilter, setPosRouteFilter] = useState('')
  const [posSourceFilter, setPosSourceFilter] = useState('')
  const [posPaperOnly, setPosPaperOnly] = useState(false)
  const [ensembleBusy, setEnsembleBusy] = useState(false)
  const [ensembleMsg, setEnsembleMsg] = useState<string | null>(null)
  const [pendingIntent, setPendingIntent] = useState<string | null>(null)
  const [execMsg, setExecMsg] = useState<string | null>(null)
  const [novice, setNovice] = useState(isNoviceMode)
  const [guideCollapsed, setGuideCollapsed] = useState(false)
  const [preflightProposal, setPreflightProposal] = useState<Proposal | null>(null)
  const [manualSeed, setManualSeed] = useState<ManualExecSeed | null>(null)
  const ProposalCard = OptionProposalCardV4
  const PositionCard = OptionPositionCardV4

  useEffect(() => { setNoviceMode(novice) }, [novice])

  const q = useMemo(() => {
    const p = new URLSearchParams()
    if (symbolFilter) p.set('symbol', symbolFilter.toUpperCase())
    if (strategyFilter) p.set('strategy', strategyFilter)
    if (groupFilter) p.set('group', groupFilter)
    if (optionTypeFilter) p.set('option_type', optionTypeFilter)
    if (sideFilter) p.set('side', sideFilter)
    if (sleeveFilter) p.set('sleeve', sleeveFilter)
    if (legStyleFilter) p.set('leg_style', legStyleFilter)
    if (tierFilter) p.set('desk_tier', tierFilter)
    if (liveOnly) p.set('live_eligible', '1')
    if (minPop > 0) p.set('min_pop', String(minPop))
    if (minEdge > 0) p.set('min_edge', String(minEdge))
    const s = p.toString()
    return s ? `?${s}` : ''
  }, [symbolFilter, strategyFilter, groupFilter, optionTypeFilter, sideFilter, sleeveFilter, legStyleFilter, tierFilter, liveOnly, minPop, minEdge])

  const posQ = useMemo(() => {
    const p = new URLSearchParams()
    if (posSymbolFilter) p.set('symbol', posSymbolFilter.toUpperCase())
    if (posTypeFilter) p.set('option_type', posTypeFilter)
    if (posSideFilter) p.set('side', posSideFilter)
    if (posWorkingOnly) p.set('working_only', '1')
    if (posRouteFilter) p.set('route', posRouteFilter)
    if (posSourceFilter) p.set('source', posSourceFilter)
    if (posPaperOnly) p.set('paper_only', '1')
    const s = p.toString()
    return s ? `?${s}` : ''
  }, [posSymbolFilter, posTypeFilter, posSideFilter, posWorkingOnly, posRouteFilter, posSourceFilter, posPaperOnly])

  const { data: proposals, loading: propLoading, error: propError, stale: propStale, refetch: refetchProps } =
    useApi<any>(`/api/v2/options/proposals${q}`, 300_000)
  const { data: monitor, loading: monLoading, error: monError, refetch: refetchMon } =
    useApi<any>(`/api/v2/options/open-positions${posQ}`, 300_000)
  const { data: overview, refetch: refetchOverview } = useApi<any>('/api/v2/options/overview', 300_000)
  const { data: execStatus } = useApi<any>('/api/v2/options/execution/status', 120_000)
  // Stage B: advisory paper-validation gate progress (deep_itm_call) — header strip
  const { data: validation } = useApi<any>('/api/v2/options/validation', 300_000)
  const validationRows: any[] = Array.isArray(validation?.strategies)
    ? validation.strategies.filter((s: any) => s?.ok)
    : []

  const propList: Proposal[] = Array.isArray(proposals?.proposals) ? proposals.proposals : []
  const proposalSymbols = useMemo(
    () => [...new Set(propList.map(p => (p.symbol || '').toUpperCase()).filter(Boolean))].sort(),
    [propList],
  )
  // Stage 3: Alpaca-lane status filter (client-side — lane rows carry queue_status)
  const laneCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const f of ALPACA_LANE_FILTERS) {
      const n = propList.filter(p => p.educational_paper_model && f.statuses.includes(p.queue_status || '')).length
      if (n > 0) counts[f.key] = n
    }
    return counts
  }, [propList])
  const shownProps = useMemo(() => {
    if (!alpacaLaneFilter) return propList
    const f = ALPACA_LANE_FILTERS.find(x => x.key === alpacaLaneFilter)
    if (!f) return propList
    return propList.filter(p => p.educational_paper_model && f.statuses.includes(p.queue_status || ''))
  }, [propList, alpacaLaneFilter])
  const propCount = proposals?.filtered_count ?? proposals?.count ?? propList.length
  const propFacets = proposals?.filter_facets ?? {}
  const posList: Position[] = Array.isArray(monitor?.positions) ? monitor.positions : []
  const posFacets = monitor?.filter_facets ?? {}
  const monitoredCount = monitor?.monitored_count ?? 0
  const alerts = monitor?.alerts ?? []

  const clearPropFilters = () => {
    setSymbolFilter(''); setStrategyFilter(''); setGroupFilter('')
    setOptionTypeFilter(''); setSideFilter(''); setSleeveFilter('')
    setLegStyleFilter(''); setTierFilter(''); setLiveOnly(false)
    setMinPop(0); setMinEdge(0); setAlpacaLaneFilter('')
  }

  const facetChip = (tip: string, label: string, count: number | undefined, active: boolean, onClick: () => void, color = '#60a5fa') => (
    <TipChip
      key={label}
      tip={tip}
      label={count != null ? `${label} (${count})` : label}
      active={active}
      onClick={onClick}
      color={color}
    />
  )

  const forceRefresh = async () => {
    try {
      const r = await fetch(`/api/v2/options/proposals?force=1${q ? q.replace('?', '&') : ''}`)
      const j = await r.json()
      refetchProps()
      refetchMon()
      refetchOverview()
      return j
    } catch {
      refetchProps()
      refetchMon()
      refetchOverview()
    }
  }

  const selectTab = (t: typeof TABS[number]) => {
    setTab(t)
    setSearchParams({ tab: t }, { replace: true })
  }

  const execActions = new Set(['sell_covered_call', 'sell_put', 'buy_put', 'buy_call', 'sell_credit_spread'])

  const runPreflight = async (p: Proposal) => {
    if (!execStatus?.armed_for_execution) {
      setExecMsg('Options execution locked — run options_pilot_arm.py --approve on server.')
      return
    }
    try {
      const r = await fetch('/api/v2/options/preflight', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: p.id, account_key: p.account || undefined }),
      })
      const j = await r.json()
      const data = j.data ?? j
      if (!data.ok) {
        setExecMsg(data.error || 'Preflight blocked')
        return
      }
      setPendingIntent(data.intent_id)
      setExecMsg(`2FA requested for ${p.symbol} — approve via Telegram/email or confirm in Broker Orders (intent ${data.intent_id?.slice(0, 8)}…)`)
    } catch (e: any) {
      setExecMsg(String(e?.message || e))
    }
  }

  // ── Stage 3: Alpaca paper lane operator actions ────────────────────────────
  // 'send' is two-step server-side too: operator mark-ready (state machine,
  // actor operator:ui) then a confirm:true submit — the paper-endpoint hard
  // lock, LIMIT-only and 1-contract guards all live in the lane module. A
  // missing ALPACA_PAPER_BASE_URL comes back as an honest 4xx reason.
  const alpacaPost = async (path: string, body: any) => {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const j = await r.json().catch(() => ({}))
    return (j?.data ?? j) as any
  }

  const handleAlpacaAction = async (
    action: AlpacaLaneAction, proposalId: string, payload?: { exitPremium?: number },
  ): Promise<AlpacaActionResult> => {
    try {
      if (action === 'send') {
        const row = propList.find(p => p.id === proposalId) as any
        const qs = row?.queue_status
        if (qs === 'pending' || qs === 'approved') {
          const d1 = await alpacaPost('/api/v2/options/alpaca-paper/mark-ready', { proposal_id: proposalId })
          if (!d1.ok) return { ok: false, message: d1.reason || d1.error || 'mark-ready refused' }
        }
        const d2 = await alpacaPost('/api/v2/options/alpaca-paper/submit', { proposal_id: proposalId, confirm: true })
        refetchProps()
        return d2.ok
          ? { ok: true, message: `Paper LIMIT order submitted${d2.order_id ? ` — order ${d2.order_id}` : ''}` }
          : { ok: false, message: d2.reason || d2.error || 'submit refused' }
      }
      if (action === 'mark_outcome') {
        const d = await alpacaPost('/api/v2/options/alpaca-paper/record-outcome',
          { proposal_id: proposalId, exit_premium: payload?.exitPremium })
        refetchProps()
        return d.ok
          ? { ok: true, message: `Outcome recorded — ${d.outcome} (P/L ${fmt$(d.pnl)})` }
          : { ok: false, message: d.reason || d.error || 'record-outcome refused' }
      }
      // promote_live — review mark only; never places an order
      const d = await alpacaPost('/api/v2/options/alpaca-paper/promote-live-review',
        { proposal_id: proposalId, confirm: true })
      refetchProps()
      return d.ok
        ? { ok: true, message: 'Marked READY_FOR_LIVE_REVIEW — no order placed; 2FA + broker preview still required.' }
        : { ok: false, message: d.reason || d.error || 'promotion refused' }
    } catch (e: any) {
      return { ok: false, message: String(e?.message || e) }
    }
  }

  const handleAction = async (action: string, id: string, item: Proposal | Position) => {
    if (action === 'review_chain') {
      const sym = 'symbol' in item && item.symbol ? item.symbol : (item as Position).underlying
      const prop = 'strike' in item && 'symbol' in item ? (item as Proposal) : null
      onDrill({
        title: `${sym} Option Chain`,
        subtitle: prop
          ? `${prop.strategy?.replace(/_/g, ' ')} · $${prop.strike} · ${prop.expiration ?? ''} · verify live bid/ask`
          : 'Schwab read-only chain — pick expiration & strike',
        endpoint: `/api/v2/schwab/option-chain?symbol=${sym}&strikes=12`,
        rows: [],
        chainMode: true,
        highlightStrike: prop?.strike,
        highlightExpiration: prop?.expiration,
        // option_type wins when present (atm_put/protective_put render the put side)
        chainSide: prop?.option_type === 'put' || prop?.strategy === 'cash_secured_put' ? 'put' : 'call',
      })
      return
    }
    if (action === 'hold') {
      setExecMsg(`Passed on ${'symbol' in item ? item.symbol : (item as Position).underlying} — no action taken.`)
      return
    }
    if (action === 'review_block_reason' && 'symbol' in item) {
      const p = item as Proposal
      const blocks = p.enterprise?.blocks || []
      const reasons = [
        ...blocks,
        p.aegis_verdict ? `Aegis: ${p.aegis_verdict}` : '',
        (p as any).aegis_status ? `Aegis status: ${(p as any).aegis_status}` : '',
        (p as any).ensemble_verdict ? `Ensemble: ${(p as any).ensemble_verdict}` : '',
      ].filter(Boolean)
      setExecMsg(reasons.length
        ? `${p.symbol} blocked — ${reasons.join(' · ')}`
        : `${p.symbol} blocked — no detailed reason on card; check enterprise desk log.`)
      return
    }
    if (action === 'rerun_review' && 'symbol' in item) {
      const p = item as Proposal
      setEnsembleBusy(true)
      setEnsembleMsg(null)
      try {
        const r = await fetch('/api/v2/options/ensemble/enqueue', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ force: 1, fresh_hours: 0, proposal_id: p.id, symbol: p.symbol }),
        })
        const j = await r.json()
        const d = j.data ?? j
        setEnsembleMsg(`Re-queued review for ${p.symbol} · ${d.enqueued ?? 0} job(s)`)
        refetchProps()
      } catch (e: any) {
        setEnsembleMsg(String(e?.message || e))
      } finally {
        setEnsembleBusy(false)
      }
      return
    }
    if (execActions.has(action) && 'symbol' in item) {
      const p = item as Proposal
      const manualOnly = p.execution_mode === 'manual' || p.broker === 'fidelity' || p.auto_eligible === false
      if (manualOnly) {
        setManualSeed({ symbol: p.symbol, account: p.account, options_proposal_id: p.id, execution_type: 'option' })
        return
      }
      if (novice) {
        setPreflightProposal(p)
        return
      }
      await runPreflight(p)
      return
    }
    onDrill({
      title: `Options: ${action}`,
      subtitle: id,
      endpoint: `/api/v2/options/proposals`,
      rows: [],
      subjectType: 'options_action',
      subjectKey: id,
    })
  }

  const validateAllEnsemble = async () => {
    setEnsembleBusy(true)
    setEnsembleMsg(null)
    try {
      const r = await fetch('/api/v2/options/ensemble/enqueue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force: 0, fresh_hours: 12 }),
      })
      const j = await r.json()
      const d = j.data ?? j
      setEnsembleMsg(`Queued ${d.enqueued ?? 0} Grok+ChatGPT+Gemma reviews · ${d.skipped ?? 0} already warm`)
      refetchProps()
    } catch (e: any) {
      setEnsembleMsg(String(e?.message || e))
    } finally {
      setEnsembleBusy(false)
    }
  }

  return (
    <div>
      <div className="hub-title-row" style={{ marginBottom: 14 }}>
        <div>
          <Tip tip={HEADER.desk} style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)', display: 'inline-block' }}>
            Options Desk ⓘ
          </Tip>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>
            High-quality proposals only · {propCount} ideas · {posList.length} open legs
            {proposals?.quality_gate && (
              <Tip tip={HEADER.qualityGate}> · gate {proposals.quality_gate.min_edge_score}+ / sleeve {proposals.quality_gate.relaxed_edge_floor}+ ⓘ</Tip>
            )}
            {proposals?.generated_at && (
              <Tip tip={HEADER.updated} style={{ color: 'var(--text3)' }}> · updated {new Date(proposals.generated_at).toLocaleTimeString()} ⓘ</Tip>
            )}
            {alerts.length > 0 && (
              <Tip tip={HEADER.needAction} style={{ color: '#f59e0b' }}> · {alerts.length} need action ⓘ</Tip>
            )}
            {execStatus && (
              <Tip
                tip={execStatus.armed_for_execution ? HEADER.executionArmed : HEADER.executionAdvisory}
                style={{ color: execStatus.armed_for_execution ? '#22c55e' : '#f59e0b' }}
              >
                {' '}· execution {execStatus.armed_for_execution ? 'ARMED' : 'advisory'} ⓘ
              </Tip>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <Tip tip={HEADER.novice}><NoviceToggle on={novice} onChange={setNovice} /></Tip>
          <div className="hub-tabs">
          {TABS.map(t => (
            <button
              key={t}
              title={
                t === 'Proposals' ? TAB_TIPS.proposals
                  : t === 'Open Options' ? TAB_TIPS.positions
                    : t === 'Strategy Overview' ? TAB_TIPS.overview
                      : TAB_TIPS.trends
              }
              onClick={() => selectTab(t)}
              style={{
                padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'help',
                background: tab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
                color: tab === t ? '#60a5fa' : 'var(--text3)', fontWeight: tab === t ? 700 : 400,
              }}
            >{t}</button>
          ))}
          </div>
        </div>
      </div>

      {/* Stage B: Strategy Validation strip — advisory paper-gate progress for
          paper-model strategies (deep_itm_call). Amber only, never green; a met
          gate still reads "operator decision required" — nothing auto-enables. */}
      {validationRows.length > 0 && (
        <div style={{ ...panel, marginBottom: 12, padding: '8px 14px', borderLeft: '4px solid #f59e0b', display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'center' }}>
          <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.06em', color: '#f59e0b', textTransform: 'uppercase' }}>Strategy Validation</span>
          {validationRows.map((s: any) => {
            const m = s.metrics || {}
            const wr = m.win_rate != null ? `${(m.win_rate * 100).toFixed(0)}%` : '—'
            const pf = m.profit_factor != null ? Number(m.profit_factor).toFixed(2) : '—'
            return (
              <span key={s.strategy_id} title={s.message} style={{ fontSize: 10.5, color: 'var(--text2)', cursor: 'help' }}>
                <b style={{ color: 'var(--text0)' }}>{s.display_name || s.strategy_id}</b>
                {' · '}
                <span style={{ fontSize: 8.5, fontWeight: 800, padding: '1px 6px', borderRadius: 4, color: '#f59e0b', border: '1px solid rgba(245,158,11,.45)' }}>PAPER MODEL</span>
                {' '}{s.progress_label ?? '—'} · WR {wr} · PF {pf} · {m.calendar_months ?? 0} mo
                {' · '}
                <span style={{ color: s.gate_met ? '#f59e0b' : 'var(--text3)', fontWeight: 700 }}>
                  {s.gate_met ? 'gate met — operator decision required' : 'gate not met'}
                </span>
              </span>
            )
          })}
        </div>
      )}

      {novice && tab === 'Proposals' && (
        <Options101Banner collapsed={guideCollapsed} onToggle={() => setGuideCollapsed(c => !c)} />
      )}

      {preflightProposal && (
        <PreflightConfirmModal
          proposal={preflightProposal}
          onCancel={() => setPreflightProposal(null)}
          onConfirm={() => { const p = preflightProposal; setPreflightProposal(null); if (p) runPreflight(p) }}
        />
      )}

      {manualSeed && (
        <ManualExecutionModal seed={manualSeed} onClose={() => setManualSeed(null)} onLogged={() => refetchProps()} />
      )}

      {execMsg && (
        <div style={{ ...panel, marginBottom: 12, borderLeft: '4px solid #60a5fa', fontSize: 11, color: 'var(--text2)' }}>
          {execMsg}
          {pendingIntent && <div style={{ marginTop: 6, fontSize: 10, color: 'var(--text3)' }}>Pending intent: {pendingIntent}</div>}
        </div>
      )}

      {tab === 'Proposals' && (
        <>
          <div style={{ marginBottom: 14 }}>
            <ManualExecutionLog mode="option" borderColor="#a855f7" />
          </div>
          <div style={{ ...panel, marginBottom: 14 }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBottom: 10 }}>
              <input
                placeholder="Ticker"
                title={FILTERS.ticker}
                value={symbolFilter}
                onChange={e => setSymbolFilter(e.target.value)}
                style={{ ...SEL, width: 72, cursor: 'help' }}
              />
              <TipLabel tip={FILTERS.strategy}>
                Strategy
                <select value={strategyFilter} onChange={e => setStrategyFilter(e.target.value)} style={{ ...SEL, marginLeft: 4 }}>
                  <option value="">All</option>
                  <option value="covered_call">Covered Call</option>
                  <option value="cash_secured_put">Cash-Secured Put</option>
                  <option value="protective_put">Protective Put</option>
                  <option value="long_call">Long Call</option>
                  <option value="credit_spread">Credit Spread</option>
                  <option value="deep_itm_call">Deep ITM Call (paper)</option>
                  <option value="atm_call">ATM Call (paper)</option>
                  <option value="atm_put">ATM Put (paper)</option>
                  <option value="earnings_put_debit_spread">Earnings Put Debit Spread (paper)</option>
                </select>
              </TipLabel>
              <TipLabel tip={FILTERS.pop}>
                POP ≥
                <select value={minPop} onChange={e => setMinPop(Number(e.target.value))} style={{ ...SEL, marginLeft: 4 }}>
                  <option value={0}>Any</option>
                  <option value={55}>55</option>
                  <option value={60}>60</option>
                  <option value={65}>65</option>
                </select>
              </TipLabel>
              <TipLabel tip={FILTERS.edge}>
                Edge ≥
                <select value={minEdge} onChange={e => setMinEdge(Number(e.target.value))} style={{ ...SEL, marginLeft: 4 }}>
                  <option value={0}>Any</option>
                  <option value={65}>65</option>
                  <option value={70}>70</option>
                  <option value={75}>75</option>
                </select>
              </TipLabel>
              <button title={FILTERS.refresh} onClick={() => { refetchProps(); refetchMon(); refetchOverview() }} style={{ ...SEL, cursor: 'help' }}>Refresh</button>
              <button title={FILTERS.forceScan} onClick={() => forceRefresh()} style={{ ...SEL, cursor: 'help', color: '#60a5fa' }}>Force scan</button>
              <button title={FILTERS.validateAll} onClick={validateAllEnsemble} disabled={ensembleBusy} style={{ ...SEL, cursor: ensembleBusy ? 'default' : 'help', color: '#a855f7' }}>
                {ensembleBusy ? 'Queuing…' : 'Validate all'}
              </button>
              <button title={FILTERS.clear} onClick={clearPropFilters} style={{ ...SEL, cursor: 'help', color: 'var(--text3)' }}>Clear filters</button>
              {ensembleMsg && <span style={{ fontSize: 10, color: 'var(--text3)' }}>{ensembleMsg}</span>}
              {propLoading && <span style={{ fontSize: 10, color: 'var(--text3)' }}>Loading…</span>}
              {propStale && <span style={{ fontSize: 10, color: '#f59e0b' }}>Reconnecting…</span>}
            </div>
            <TipSection tip="Filter by strategy group, call/put, buy/sell side, and single-leg vs spread pairs.">TYPE &amp; PAIRS</TipSection>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
              {facetChip(FILTERS.all, 'All', propFacets.total, !groupFilter && !optionTypeFilter && !sideFilter && !legStyleFilter, () => {
                setGroupFilter(''); setOptionTypeFilter(''); setSideFilter(''); setLegStyleFilter('')
              })}
              {facetChip(FILTERS.income, 'Income', propFacets.by_group?.income, groupFilter === 'income', () => setGroupFilter(g => g === 'income' ? '' : 'income'), '#f59e0b')}
              {facetChip(FILTERS.hedge, 'Hedge', propFacets.by_group?.hedge, groupFilter === 'hedge', () => setGroupFilter(g => g === 'hedge' ? '' : 'hedge'), PURPLE)}
              {facetChip(FILTERS.directional, 'Directional', propFacets.by_group?.directional, groupFilter === 'directional', () => setGroupFilter(g => g === 'directional' ? '' : 'directional'), '#22c55e')}
              {facetChip(FILTERS.spreads, 'Spreads', propFacets.by_group?.spread, groupFilter === 'spread', () => setGroupFilter(g => g === 'spread' ? '' : 'spread'), '#ef4444')}
              {facetChip(FILTERS.calls, 'Calls', propFacets.by_option_type?.call, optionTypeFilter === 'call', () => setOptionTypeFilter(t => t === 'call' ? '' : 'call'))}
              {facetChip(FILTERS.puts, 'Puts', propFacets.by_option_type?.put, optionTypeFilter === 'put', () => setOptionTypeFilter(t => t === 'put' ? '' : 'put'))}
              {facetChip(FILTERS.sell, 'Sell', propFacets.by_side?.SELL, sideFilter === 'SELL', () => setSideFilter(s => s === 'SELL' ? '' : 'SELL'), '#f59e0b')}
              {facetChip(FILTERS.buy, 'Buy', propFacets.by_side?.BUY, sideFilter === 'BUY', () => setSideFilter(s => s === 'BUY' ? '' : 'BUY'), '#22c55e')}
              {facetChip(FILTERS.singleLeg, 'Single leg', propFacets.single_leg, legStyleFilter === 'single', () => setLegStyleFilter(l => l === 'single' ? '' : 'single'))}
              {facetChip(FILTERS.spreadPairs, 'Spread pairs', propFacets.spread_pairs, legStyleFilter === 'spread', () => setLegStyleFilter(l => l === 'spread' ? '' : 'spread'), '#ef4444')}
            </div>
            <TipSection tip="Portfolio sleeve = holdings-based. Conviction = watchlist names. Tiers from enterprise desk scoring.">SLEEVE &amp; DESK</TipSection>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {facetChip(FILTERS.portfolio, 'Portfolio', propFacets.by_sleeve?.portfolio, sleeveFilter === 'portfolio', () => setSleeveFilter(s => s === 'portfolio' ? '' : 'portfolio'))}
              {facetChip(FILTERS.conviction, 'Conviction', propFacets.by_sleeve?.conviction, sleeveFilter === 'conviction', () => setSleeveFilter(s => s === 'conviction' ? '' : 'conviction'), PURPLE)}
              {facetChip(FILTERS.tierA, 'Tier A', propFacets.by_tier?.A, tierFilter === 'A', () => setTierFilter(t => t === 'A' ? '' : 'A'), '#22c55e')}
              {facetChip(FILTERS.tierB, 'Tier B', propFacets.by_tier?.B, tierFilter === 'B', () => setTierFilter(t => t === 'B' ? '' : 'B'), '#60a5fa')}
              {facetChip(FILTERS.tierC, 'Tier C', propFacets.by_tier?.C, tierFilter === 'C', () => setTierFilter(t => t === 'C' ? '' : 'C'), 'var(--text3)')}
              {facetChip(FILTERS.liveEligible, 'Live eligible', propFacets.live_eligible, liveOnly, () => setLiveOnly(v => !v), '#22c55e')}
              <Tip tip={FILTERS.showing} style={{ fontSize: 10, color: 'var(--text3)', alignSelf: 'center', marginLeft: 4 }}>
                Showing {propCount}{propFacets.total != null && propCount !== propFacets.total ? ` of ${propFacets.total}` : ''} ⓘ
              </Tip>
            </div>
            {/* Stage 3: Alpaca paper lane — filter queue-backed paper-model rows by lane state */}
            {Object.keys(laneCounts).length > 0 && (
              <>
                <div style={{ marginTop: 8 }}>
                  <TipSection tip="Alpaca PAPER lane states for paper-model proposals: operator mark-ready → confirmed 1-contract LIMIT submit → fill/close → recorded outcome → operator-only live-review mark. Educational lane — never a live order path.">
                    ALPACA PAPER LANE
                  </TipSection>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {ALPACA_LANE_FILTERS.filter(f => laneCounts[f.key] != null).map(f =>
                    facetChip(
                      `Show only paper-model rows in the ${f.label} lane state.`,
                      f.label, laneCounts[f.key], alpacaLaneFilter === f.key,
                      () => setAlpacaLaneFilter(k => k === f.key ? '' : f.key), '#f59e0b',
                    ))}
                  {alpacaLaneFilter && (
                    <span style={{ fontSize: 10, color: 'var(--text3)', alignSelf: 'center' }}>
                      showing {shownProps.length} lane row{shownProps.length === 1 ? '' : 's'}
                    </span>
                  )}
                </div>
              </>
            )}
          </div>

          {propError && (
            <div style={{ ...panel, marginBottom: 12, borderLeft: '4px solid #ef4444', fontSize: 11, color: '#ef4444' }}>
              Options API: {propError} — try Force scan or check server on :7777
            </div>
          )}

          {propList.length === 0 && !propLoading && !propError && (
            <div style={panel}>
              <div style={{ fontSize: 12, color: 'var(--text3)' }}>
                No proposals passed quality gates (edge ≥62, POP ≥52%, IV rank). Use Force scan — fallback tier surfaces income-sleeve CCs when chain is thin.
              </div>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: 12 }}>
            {shownProps.map(p => (
              <ProposalCard
                key={p.id}
                proposal={p}
                armed={!!execStatus?.armed_for_execution}
                novice={novice}
                onAction={(a, id) => handleAction(a, id, p)}
                onAlpacaAction={p.educational_paper_model ? handleAlpacaAction : undefined}
                onManualLog={() => setManualSeed({ symbol: p.symbol, account: p.account, options_proposal_id: p.id, execution_type: 'option' })}
                onDrill={() => onDrill({
                  title: `${p.symbol} ${p.strategy.replace(/_/g, ' ')}`,
                  subtitle: `$${p.strike} · ${p.dte} DTE · ${p.expiration ?? ''}`,
                  endpoint: `/api/v2/options/proposals`,
                  rows: [p],
                  subjectType: 'options_proposal',
                  subjectKey: p.id,
                })}
                reviewBar={<OptionReviewBar proposal={p} autoRequest />}
              />
            ))}
          </div>
        </>
      )}

      {tab === 'Open Options' && (
        <>
          {novice && <OpenOptionsIntroBanner />}
          <div style={{ ...panel, marginBottom: 14 }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 8 }}>
              <input placeholder="Underlying" title={FILTERS.posTicker} value={posSymbolFilter} onChange={e => setPosSymbolFilter(e.target.value)} style={{ ...SEL, width: 80, cursor: 'help' }} />
              <button title={FILTERS.clear} onClick={() => {
                setPosSymbolFilter(''); setPosTypeFilter(''); setPosSideFilter('')
                setPosWorkingOnly(false); setPosRouteFilter(''); setPosSourceFilter(''); setPosPaperOnly(false)
              }} style={{ ...SEL, cursor: 'help', color: 'var(--text3)' }}>Clear</button>
              {monLoading && <span style={{ fontSize: 10, color: 'var(--text3)' }}>Loading…</span>}
              <span style={{ fontSize: 10, color: 'var(--text3)' }}>
                {posList.length}{monitor?.unified_count != null && posList.length !== monitor.unified_count ? ` of ${monitor.unified_count}` : ''} legs
                {monitoredCount > 0 ? ` · ${monitoredCount} monitored` : ''}
              </span>
            </div>
            <TipSection tip="Filter by leg type, route (Alpaca paper vs Schwab live), and lifecycle monitor source.">OPEN OPTIONS</TipSection>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 6 }}>
              {facetChip(FILTERS.posCalls, 'Calls', posFacets.by_option_type?.call, posTypeFilter === 'call', () => setPosTypeFilter(t => t === 'call' ? '' : 'call'))}
              {facetChip(FILTERS.posPuts, 'Puts', posFacets.by_option_type?.put, posTypeFilter === 'put', () => setPosTypeFilter(t => t === 'put' ? '' : 'put'))}
              {facetChip(FILTERS.posShort, 'Short / Sell', posFacets.by_side?.sell, posSideFilter === 'sell', () => setPosSideFilter(s => s === 'sell' ? '' : 'sell'), '#f59e0b')}
              {facetChip(FILTERS.posLong, 'Long / Buy', posFacets.by_side?.buy, posSideFilter === 'buy', () => setPosSideFilter(s => s === 'buy' ? '' : 'buy'), '#22c55e')}
              {facetChip(FILTERS.posWorking, 'Working', posFacets.working, posWorkingOnly, () => setPosWorkingOnly(w => !w), '#22c55e')}
              {facetChip('Alpaca paper lifecycle positions from options_monitored_positions.', 'Paper monitored', posFacets.paper_only, posPaperOnly, () => setPosPaperOnly(v => !v), '#f59e0b')}
              {facetChip('Schwab holdings legs from broker sync.', 'Broker', posFacets.by_source?.broker, posSourceFilter === 'broker', () => setPosSourceFilter(s => s === 'broker' ? '' : 'broker'), '#60a5fa')}
              {facetChip('Lifecycle monitor registry (hybrid ingest).', 'Monitored', posFacets.by_source?.monitored, posSourceFilter === 'monitored', () => setPosSourceFilter(s => s === 'monitored' ? '' : 'monitored'), '#a855f7')}
              {facetChip('Alpaca paper route only.', 'Alpaca paper', posFacets.by_route?.alpaca_paper, posRouteFilter === 'alpaca_paper', () => setPosRouteFilter(r => r === 'alpaca_paper' ? '' : 'alpaca_paper'), '#f59e0b')}
              {facetChip('Schwab live path (2FA when armed).', 'Schwab live', posFacets.by_route?.schwab_live, posRouteFilter === 'schwab_live', () => setPosRouteFilter(r => r === 'schwab_live' ? '' : 'schwab_live'), '#22c55e')}
            </div>
          </div>
          {alerts.length > 0 && (
            <div title={POSITION.actionRequired} style={{ ...panel, marginBottom: 12, borderLeft: '4px solid #f59e0b', cursor: 'help' }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#f59e0b', marginBottom: 8 }}>Action Required ⓘ</div>
              {alerts.map((a: any) => (
                <div key={a.id} style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 4 }}>
                  <b style={{ color: '#60a5fa' }}>{a.underlying}</b> — {a.message} → <span style={{ color: '#f59e0b' }}>{a.action}</span>
                </div>
              ))}
            </div>
          )}
          {posList.length > 0 && (
            <div title={POSITION.greeksPanel} style={{ ...panel, marginBottom: 14, display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1.2fr)', gap: 16, cursor: 'help' }}>
              <GreeksOverview positions={posList} />
              {posList[0] && (
                <OptionsPnLProfile
                  underlying={posList[0].underlying}
                  side={posList[0].side || posList[0].strategy}
                  optionType={posList[0].option_type || 'call'}
                  strike={Number(posList[0].strike)}
                  spot={Number(posList[0].underlying_price)}
                  qty={Number(posList[0].qty) || 1}
                  avgEntry={Number(posList[0].avg_entry)}
                  mark={Number(posList[0].mark)}
                  compact
                />
              )}
            </div>
          )}
          {monLoading && <div style={{ fontSize: 11, color: 'var(--text3)' }}>Loading positions…</div>}
          {posList.length === 0 && !monLoading && (
            <div style={panel}>
              <div style={{ fontSize: 12, color: 'var(--text3)' }}>
                No open options yet. Schwab legs sync from linked accounts; Alpaca paper fills appear here after reconcile via the lifecycle monitor.
              </div>
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: 12 }}>
            {posList.map(p => (
              <PositionCard
                key={p.id}
                position={p}
                novice={novice}
                onAction={(a, id) => handleAction(a, id, p)}
                onDrill={() => onDrill({
                  title: `${p.underlying} option leg`,
                  subtitle: p.occ_symbol || p.strategy || '',
                  endpoint: '/api/v2/options/open-positions',
                  rows: [p],
                  subjectType: 'options_position',
                  subjectKey: p.id,
                })}
              />
            ))}
          </div>
        </>
      )}

      {tab === 'Options Trends' && (
        <OptionsTrendsPanel
          defaultSymbol={symbolFilter ? symbolFilter.toUpperCase() : undefined}
          proposalSymbols={proposalSymbols}
        />
      )}

      {tab === 'Strategy Overview' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }}>
          {[
            { label: 'Proposal Count', tip: OVERVIEW.proposalCount, value: overview?.proposal_count ?? propList.length, color: '#60a5fa' },
            { label: 'Avg Edge Score', tip: OVERVIEW.avgEdge, value: overview?.proposals?.total_edge_avg ?? '—', color: '#22c55e' },
            { label: 'Avg POP', tip: OVERVIEW.avgPop, value: overview?.proposals?.avg_pop != null ? `${overview.proposals.avg_pop}%` : '—', color: '#a855f7' },
            { label: 'Income (CC)', tip: OVERVIEW.incomeCc, value: overview?.proposals?.income_opportunities ?? 0, color: '#f59e0b' },
            { label: 'Put plays', tip: OVERVIEW.putPlays, value: overview?.proposals?.put_plays ?? proposals?.puts ?? 0, color: PURPLE },
            { label: 'Open Positions', tip: OVERVIEW.openPositions, value: overview?.open_positions ?? posList.length, color: '#60a5fa' },
            { label: 'Needs Action', tip: OVERVIEW.needsAction, value: overview?.needs_action ?? alerts.length, color: '#ef4444' },
            { label: 'Unrealized P/L', tip: OVERVIEW.unrealizedPnl, value: fmt$(overview?.monitor?.total_unrealized_pnl), color: '#22c55e' },
            { label: 'ITM / OTM', tip: OVERVIEW.itmOtm, value: `${overview?.monitor?.itm_count ?? 0} / ${overview?.monitor?.otm_count ?? 0}`, color: 'var(--text2)' },
          ].map(k => (
            <TipKpi key={k.label} tip={k.tip} label={k.label} value={k.value} color={k.color} />
          ))}
          {novice && (
            <div style={{ ...panel, gridColumn: '1 / -1' }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Strategy cheat sheet</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 10 }}>
                {(['covered_call', 'cash_secured_put', 'long_call', 'credit_spread'] as const).map(s => {
                  const g = strategyGuide(s)
                  return (
                    <div key={s} style={{ background: 'var(--bg2)', borderRadius: 8, padding: 10, fontSize: 10, color: 'var(--text2)', lineHeight: 1.45 }}>
                      <div style={{ fontWeight: 800, color: '#60a5fa' }}>{g.emoji} {g.name}</div>
                      <div style={{ marginTop: 4 }}>{g.oneLiner}</div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
          <div title={OVERVIEW.philosophy} style={{ ...panel, gridColumn: '1 / -1', cursor: 'help' }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Quality Philosophy ⓘ</div>
            <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.5 }}>
              Proposals below edge {proposals?.quality_gate?.min_edge_score ?? 62}, POP {proposals?.quality_gate?.min_pop_pct ?? 52}%,
              or IV rank {proposals?.quality_gate?.min_iv_rank ?? 20}% are excluded (fallback floor {proposals?.quality_gate?.relaxed_edge_floor ?? 52}).
              Monitoring refreshes every 5–15 minutes during market hours.
              {execStatus?.armed_for_execution
                ? ' Execution ARMED — preflight + per-order 2FA required.'
                : ' Execution advisory until options_pilot_arm --approve.'}
            </div>
            {novice && (
              <details style={{ marginTop: 10 }}>
                <summary style={{ fontSize: 10, fontWeight: 700, color: 'var(--text3)', cursor: 'pointer' }}>Key terms ({GLOSSARY.length})</summary>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 6, marginTop: 8, fontSize: 10, color: 'var(--text2)' }}>
                  {GLOSSARY.map(g => <div key={g.term}><b>{g.term}</b> — {g.def}</div>)}
                </div>
              </details>
            )}
          </div>
        </div>
      )}
    </div>
  )
}