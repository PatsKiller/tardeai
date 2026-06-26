import { useMemo, useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import OptionProposalCard, { type OptionProposal } from '../components/OptionProposalCard'
import OptionPositionCard, { type OptionPosition } from '../components/OptionPositionCard'
import OptionReviewBar from '../components/OptionReviewBar'
import ManualExecutionModal, { type ManualExecSeed } from '../components/ManualExecutionModal'
import ManualExecutionLog from '../components/ManualExecutionLog'
import { Options101Banner, NoviceToggle, PreflightConfirmModal } from '../components/OptionsNovicePanel'
import { isNoviceMode, setNoviceMode, strategyGuide, GLOSSARY } from '../lib/optionsNovice'
import { fmt$ } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'
import GreeksOverview from '../components/risk/GreeksOverview'
import OptionsPnLProfile from '../components/risk/OptionsPnLProfile'
import { Tip, TipChip, TipKpi, TipLabel, TipSection } from '../components/OptionsTip'
import { HEADER, TABS as TAB_TIPS, FILTERS, OVERVIEW, POSITION } from '../lib/optionsTooltips'

interface Props { onDrill: (ctx: DrillContext) => void }

const TABS = ['Proposals', 'Open Positions', 'Strategy Overview'] as const
const panel = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }
const SEL: React.CSSProperties = { fontSize: 11, padding: '6px 9px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text0)' }
const PURPLE = '#a855f7'

type Proposal = OptionProposal
type Position = OptionPosition

export default function OptionsHub({ onDrill }: Props) {
  const [searchParams, setSearchParams] = useSearchParams()
  const urlTab = searchParams.get('tab')
  const [tab, setTab] = useState<typeof TABS[number]>(
    (TABS as readonly string[]).includes(urlTab ?? '') ? urlTab as typeof TABS[number] : 'Proposals')

  const [symbolFilter, setSymbolFilter] = useState('')
  const [strategyFilter, setStrategyFilter] = useState('')
  const [groupFilter, setGroupFilter] = useState('')
  const [optionTypeFilter, setOptionTypeFilter] = useState('')
  const [sideFilter, setSideFilter] = useState('')
  const [sleeveFilter, setSleeveFilter] = useState('')
  const [legStyleFilter, setLegStyleFilter] = useState('')
  const [tierFilter, setTierFilter] = useState('')
  const [liveOnly, setLiveOnly] = useState(false)
  const [minPop, setMinPop] = useState(0)
  const [minEdge, setMinEdge] = useState(0)
  const [posSymbolFilter, setPosSymbolFilter] = useState('')
  const [posTypeFilter, setPosTypeFilter] = useState('')
  const [posSideFilter, setPosSideFilter] = useState('')
  const [posWorkingOnly, setPosWorkingOnly] = useState(false)
  const [ensembleBusy, setEnsembleBusy] = useState(false)
  const [ensembleMsg, setEnsembleMsg] = useState<string | null>(null)
  const [pendingIntent, setPendingIntent] = useState<string | null>(null)
  const [execMsg, setExecMsg] = useState<string | null>(null)
  const [novice, setNovice] = useState(isNoviceMode)
  const [guideCollapsed, setGuideCollapsed] = useState(false)
  const [preflightProposal, setPreflightProposal] = useState<Proposal | null>(null)
  const [manualSeed, setManualSeed] = useState<ManualExecSeed | null>(null)

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
    const s = p.toString()
    return s ? `?${s}` : ''
  }, [posSymbolFilter, posTypeFilter, posSideFilter, posWorkingOnly])

  const { data: proposals, loading: propLoading, error: propError, stale: propStale, refetch: refetchProps } =
    useApi<any>(`/api/v2/options/proposals${q}`, 300_000)
  const { data: monitor, loading: monLoading, error: monError, refetch: refetchMon } =
    useApi<any>(`/api/v2/options/positions${posQ}`, 300_000)
  const { data: overview, refetch: refetchOverview } = useApi<any>('/api/v2/options/overview', 300_000)
  const { data: execStatus } = useApi<any>('/api/v2/options/execution/status', 120_000)

  const propList: Proposal[] = Array.isArray(proposals?.proposals) ? proposals.proposals : []
  const propCount = proposals?.filtered_count ?? proposals?.count ?? propList.length
  const propFacets = proposals?.filter_facets ?? {}
  const posList: Position[] = Array.isArray(monitor?.positions) ? monitor.positions : []
  const posFacets = monitor?.filter_facets ?? {}
  const alerts = monitor?.alerts ?? []

  const clearPropFilters = () => {
    setSymbolFilter(''); setStrategyFilter(''); setGroupFilter('')
    setOptionTypeFilter(''); setSideFilter(''); setSleeveFilter('')
    setLegStyleFilter(''); setTierFilter(''); setLiveOnly(false)
    setMinPop(0); setMinEdge(0)
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
        chainSide: prop?.strategy === 'cash_secured_put' ? 'put' : 'call',
      })
      return
    }
    if (action === 'hold') {
      setExecMsg(`Passed on ${'symbol' in item ? item.symbol : (item as Position).underlying} — no action taken.`)
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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14 }}>
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
          <div style={{ display: 'flex', gap: 4 }}>
          {TABS.map(t => (
            <button
              key={t}
              title={t === 'Proposals' ? TAB_TIPS.proposals : t === 'Open Positions' ? TAB_TIPS.positions : TAB_TIPS.overview}
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
            {propList.map(p => (
              <OptionProposalCard
                key={p.id}
                proposal={p}
                armed={!!execStatus?.armed_for_execution}
                novice={novice}
                onAction={(a, id) => handleAction(a, id, p)}
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

      {tab === 'Open Positions' && (
        <>
          <div style={{ ...panel, marginBottom: 14 }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 8 }}>
              <input placeholder="Underlying" title={FILTERS.posTicker} value={posSymbolFilter} onChange={e => setPosSymbolFilter(e.target.value)} style={{ ...SEL, width: 80, cursor: 'help' }} />
              <button title={FILTERS.clear} onClick={() => { setPosSymbolFilter(''); setPosTypeFilter(''); setPosSideFilter(''); setPosWorkingOnly(false) }} style={{ ...SEL, cursor: 'help', color: 'var(--text3)' }}>Clear</button>
              {monLoading && <span style={{ fontSize: 10, color: 'var(--text3)' }}>Loading…</span>}
              <span style={{ fontSize: 10, color: 'var(--text3)' }}>
                {posList.length}{posFacets.total != null && posList.length !== posFacets.total ? ` of ${posFacets.total}` : ''} legs
              </span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {facetChip(FILTERS.posCalls, 'Calls', posFacets.by_option_type?.call, posTypeFilter === 'call', () => setPosTypeFilter(t => t === 'call' ? '' : 'call'))}
              {facetChip(FILTERS.posPuts, 'Puts', posFacets.by_option_type?.put, posTypeFilter === 'put', () => setPosTypeFilter(t => t === 'put' ? '' : 'put'))}
              {facetChip(FILTERS.posShort, 'Short / Sell', posFacets.by_side?.sell, posSideFilter === 'sell', () => setPosSideFilter(s => s === 'sell' ? '' : 'sell'), '#f59e0b')}
              {facetChip(FILTERS.posLong, 'Long / Buy', posFacets.by_side?.buy, posSideFilter === 'buy', () => setPosSideFilter(s => s === 'buy' ? '' : 'buy'), '#22c55e')}
              {facetChip(FILTERS.posWorking, 'Working', posFacets.working, posWorkingOnly, () => setPosWorkingOnly(w => !w), '#22c55e')}
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
                No open option legs detected on linked Schwab accounts. Short calls / puts appear here automatically when held.
              </div>
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: 12 }}>
            {posList.map(p => (
              <OptionPositionCard
                key={p.id}
                position={p}
                novice={novice}
                onAction={(a, id) => handleAction(a, id, p)}
                onDrill={() => onDrill({
                  title: `${p.underlying} option leg`,
                  subtitle: p.occ_symbol || p.strategy || '',
                  endpoint: '/api/v2/options/positions',
                  rows: [p],
                  subjectType: 'options_position',
                  subjectKey: p.id,
                })}
              />
            ))}
          </div>
        </>
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