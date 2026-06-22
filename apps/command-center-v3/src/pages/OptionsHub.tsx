import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import SynthesizedReportCard, { type ReportCardItem } from '../components/SynthesizedReportCard'
import { EnsembleValidationInline } from '../components/EnsembleValidationCard'
import { fmt$ } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'

interface Props { onDrill: (ctx: DrillContext) => void }

const TABS = ['Proposals', 'Open Positions', 'Strategy Overview'] as const
const panel = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }
const SEL: React.CSSProperties = { fontSize: 11, padding: '6px 9px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text0)' }

type Proposal = {
  id: string
  strategy: string
  symbol: string
  strike: number
  expiration?: string
  dte?: number
  premium?: number
  premium_total?: number
  pop_pct?: number
  edge_score?: number
  iv_rank?: number
  max_profit?: number | string
  max_loss?: number | string
  breakeven?: number
  risk_reward?: number
  expected_value?: number
  reasoning?: string
  recommended_action?: string
  action_buttons?: { action: string; label: string }[]
  severity?: string
  underlying_price?: number
  contracts?: number
}

type Position = {
  id: string
  underlying: string
  occ_symbol?: string
  strategy?: string
  strike?: number
  dte?: number
  moneyness?: string
  pop_otm_pct?: number
  pop_itm_pct?: number
  unrealized_pnl?: number
  edge_score?: number
  still_working?: boolean
  recommended_action?: string
  rationale?: string
  severity?: string
  action_buttons?: { action: string; label: string }[]
  mark?: number
  underlying_price?: number
}

function proposalToCard(p: Proposal): ReportCardItem {
  const stratLabel = p.strategy === 'covered_call' ? 'Covered Call'
    : p.strategy === 'cash_secured_put' ? 'Cash-Secured Put'
    : p.strategy === 'long_call' ? 'Long Call' : p.strategy
  return {
    id: p.id,
    type: stratLabel,
    symbol: p.symbol,
    title: `${p.symbol} $${p.strike} · ${p.dte ?? '—'} DTE`,
    synthesized_insight: p.reasoning,
    severity: p.severity || (p.edge_score && p.edge_score >= 75 ? 'positive' : 'info'),
    quality_score: p.edge_score,
    summary: [
      `POP ${p.pop_pct ?? '—'}% · Edge ${p.edge_score ?? '—'} · IV rank ${p.iv_rank ?? '—'}%`,
      `Premium ${fmt$(p.premium_total)} · Max profit ${typeof p.max_profit === 'number' ? fmt$(p.max_profit) : p.max_profit}`,
      `Breakeven $${p.breakeven ?? '—'} · R/R ${p.risk_reward ?? '—'} · EV ${fmt$(p.expected_value)}`,
    ].join('\n'),
    actions: (p.action_buttons || []).map(b => ({ label: b.label, url: `#${b.action}` })),
    has_actions: true,
  }
}

function positionToCard(p: Position): ReportCardItem {
  return {
    id: p.id,
    type: p.strategy?.replace(/_/g, ' ') || 'Option',
    symbol: p.underlying,
    title: `${p.underlying} $${p.strike ?? '—'} · ${p.moneyness ?? '—'} · ${p.dte ?? '—'} DTE`,
    synthesized_insight: p.rationale,
    severity: p.severity || (p.still_working ? 'positive' : 'warning'),
    quality_score: p.edge_score,
    summary: [
      `POP OTM ${p.pop_otm_pct ?? '—'}% · ITM ${p.pop_itm_pct ?? '—'}%`,
      `Mark $${p.mark ?? '—'} · Spot $${p.underlying_price ?? '—'} · P/L ${fmt$(p.unrealized_pnl)}`,
      `Action: ${p.recommended_action ?? 'Hold'}`,
    ].join('\n'),
    actions: (p.action_buttons || []).map(b => ({ label: b.label, url: `#${b.action}` })),
    has_actions: true,
  }
}

export default function OptionsHub({ onDrill }: Props) {
  const [searchParams, setSearchParams] = useSearchParams()
  const urlTab = searchParams.get('tab')
  const [tab, setTab] = useState<typeof TABS[number]>(
    (TABS as readonly string[]).includes(urlTab ?? '') ? urlTab as typeof TABS[number] : 'Proposals')

  const [symbolFilter, setSymbolFilter] = useState('')
  const [strategyFilter, setStrategyFilter] = useState('')
  const [minPop, setMinPop] = useState(0)
  const [minEdge, setMinEdge] = useState(0)
  const [expandedEnsemble, setExpandedEnsemble] = useState<string | null>(null)
  const [pendingIntent, setPendingIntent] = useState<string | null>(null)
  const [execMsg, setExecMsg] = useState<string | null>(null)

  const q = useMemo(() => {
    const p = new URLSearchParams()
    if (symbolFilter) p.set('symbol', symbolFilter.toUpperCase())
    if (strategyFilter) p.set('strategy', strategyFilter)
    if (minPop > 0) p.set('min_pop', String(minPop))
    if (minEdge > 0) p.set('min_edge', String(minEdge))
    const s = p.toString()
    return s ? `?${s}` : ''
  }, [symbolFilter, strategyFilter, minPop, minEdge])

  const { data: proposals, loading: propLoading, refetch: refetchProps } = useApi<any>(`/api/v2/options/proposals${q}`, 300_000)
  const { data: monitor, loading: monLoading, refetch: refetchMon } = useApi<any>('/api/v2/options/positions', 300_000)
  const { data: overview } = useApi<any>('/api/v2/options/overview', 300_000)
  const { data: execStatus } = useApi<any>('/api/v2/options/execution/status', 120_000)

  const propList: Proposal[] = proposals?.proposals ?? []
  const posList: Position[] = monitor?.positions ?? []
  const alerts = monitor?.alerts ?? []

  const selectTab = (t: typeof TABS[number]) => {
    setTab(t)
    setSearchParams({ tab: t }, { replace: true })
  }

  const execActions = new Set(['sell_covered_call', 'sell_put', 'buy_call', 'sell_credit_spread'])

  const handleAction = async (action: string, id: string, item: Proposal | Position) => {
    if (action === 'review_chain') {
      const sym = 'symbol' in item && item.symbol ? item.symbol : (item as Position).underlying
      onDrill({
        title: `${sym} Option Chain`,
        subtitle: 'Schwab read-only chain',
        endpoint: `/api/v2/schwab/option-chain?symbol=${sym}&strikes=12`,
        rows: [],
      })
      return
    }
    if (action === 'hold') return
    if (execActions.has(action) && 'id' in item) {
      const p = item as Proposal
      if (!execStatus?.armed_for_execution) {
        setExecMsg('Options execution locked — run options_pilot_arm.py --approve on server.')
        return
      }
      try {
        const r = await fetch('/api/v2/options/preflight', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ proposal_id: p.id, account_key: 'schwab_taxable' }),
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

  const chipBtn = (label: string, active: boolean, onClick: () => void, color = '#60a5fa') => (
    <button key={label} onClick={onClick} style={{
      padding: '4px 10px', fontSize: 10, borderRadius: 5, cursor: 'pointer',
      border: `1px solid ${active ? color : 'var(--border)'}`,
      background: active ? `${color}22` : 'var(--bg2)',
      color: active ? color : 'var(--text3)', fontWeight: active ? 700 : 500,
    }}>{label}</button>
  )

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)' }}>Options Desk</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>
            High-quality proposals only · {propList.length} ideas · {posList.length} open legs
            {alerts.length > 0 && <span style={{ color: '#f59e0b' }}> · {alerts.length} need action</span>}
            {execStatus && (
              <span style={{ color: execStatus.armed_for_execution ? '#22c55e' : '#f59e0b' }}>
                {' '}· execution {execStatus.armed_for_execution ? 'ARMED' : 'advisory'}
              </span>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {TABS.map(t => (
            <button key={t} onClick={() => selectTab(t)} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
              background: tab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
              color: tab === t ? '#60a5fa' : 'var(--text3)', fontWeight: tab === t ? 700 : 400,
            }}>{t}</button>
          ))}
        </div>
      </div>

      {execMsg && (
        <div style={{ ...panel, marginBottom: 12, borderLeft: '4px solid #60a5fa', fontSize: 11, color: 'var(--text2)' }}>
          {execMsg}
          {pendingIntent && <div style={{ marginTop: 6, fontSize: 10, color: 'var(--text3)' }}>Pending intent: {pendingIntent}</div>}
        </div>
      )}

      {tab === 'Proposals' && (
        <>
          <div style={{ ...panel, marginBottom: 14, display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
            <input
              placeholder="Ticker filter"
              value={symbolFilter}
              onChange={e => setSymbolFilter(e.target.value)}
              style={{ ...SEL, width: 90 }}
            />
            <label style={{ fontSize: 10, color: 'var(--text3)' }}>
              Strategy
              <select value={strategyFilter} onChange={e => setStrategyFilter(e.target.value)} style={{ ...SEL, marginLeft: 6 }}>
                <option value="">All</option>
                <option value="covered_call">Covered Call</option>
                <option value="cash_secured_put">Cash-Secured Put</option>
                <option value="long_call">Long Call</option>
                <option value="credit_spread">Credit Spread</option>
              </select>
            </label>
            <label style={{ fontSize: 10, color: 'var(--text3)' }}>
              Min POP %
              <select value={minPop} onChange={e => setMinPop(Number(e.target.value))} style={{ ...SEL, marginLeft: 6 }}>
                <option value={0}>Any</option>
                <option value={55}>55+</option>
                <option value={60}>60+</option>
                <option value={65}>65+</option>
              </select>
            </label>
            <label style={{ fontSize: 10, color: 'var(--text3)' }}>
              Min Edge
              <select value={minEdge} onChange={e => setMinEdge(Number(e.target.value))} style={{ ...SEL, marginLeft: 6 }}>
                <option value={0}>Any</option>
                <option value={65}>65+</option>
                <option value={70}>70+</option>
                <option value={75}>75+</option>
              </select>
            </label>
            <button onClick={() => { refetchProps(); refetchMon() }} style={{ ...SEL, cursor: 'pointer' }}>Refresh</button>
            {propLoading && <span style={{ fontSize: 10, color: 'var(--text3)' }}>Loading…</span>}
          </div>

          {propList.length === 0 && !propLoading && (
            <div style={panel}>
              <div style={{ fontSize: 12, color: 'var(--text3)' }}>
                No proposals passed quality gates (edge ≥62, POP ≥52%, IV rank). Adjust filters or wait for next scan.
              </div>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 12 }}>
            {propList.map(p => {
              const card = proposalToCard(p)
              return (
                <div key={p.id}>
                  <SynthesizedReportCard
                    item={card}
                    onAction={(a, id) => handleAction(a.replace('#', ''), id, p)}
                    footer={
                      <div style={{ marginTop: 8 }} onClick={e => e.stopPropagation()}>
                        <button
                          onClick={() => setExpandedEnsemble(expandedEnsemble === p.id ? null : p.id)}
                          style={{ fontSize: 9, color: '#a855f7', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                        >
                          {expandedEnsemble === p.id ? '▾ Hide ensemble' : '▸ Validate with ensemble'}
                        </button>
                        {expandedEnsemble === p.id && (
                          <EnsembleValidationInline
                            targetType="options_proposal"
                            targetId={p.id}
                            subject={`${p.symbol} ${p.strategy}`}
                            content={[p.reasoning, `POP ${p.pop_pct}%`, `Edge ${p.edge_score}`].join(' · ')}
                          />
                        )}
                      </div>
                    }
                  />
                </div>
              )
            })}
          </div>
        </>
      )}

      {tab === 'Open Positions' && (
        <>
          {alerts.length > 0 && (
            <div style={{ ...panel, marginBottom: 12, borderLeft: '4px solid #f59e0b' }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#f59e0b', marginBottom: 8 }}>Action Required</div>
              {alerts.map((a: any) => (
                <div key={a.id} style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 4 }}>
                  <b style={{ color: '#60a5fa' }}>{a.underlying}</b> — {a.message} → <span style={{ color: '#f59e0b' }}>{a.action}</span>
                </div>
              ))}
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
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 12 }}>
            {posList.map(p => (
              <SynthesizedReportCard
                key={p.id}
                item={positionToCard(p)}
                onAction={(a, id) => handleAction(a.replace('#', ''), id, p)}
              />
            ))}
          </div>
        </>
      )}

      {tab === 'Strategy Overview' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }}>
          {[
            { label: 'Proposal Count', value: overview?.proposal_count ?? propList.length, color: '#60a5fa' },
            { label: 'Avg Edge Score', value: overview?.proposals?.total_edge_avg ?? '—', color: '#22c55e' },
            { label: 'Avg POP', value: overview?.proposals?.avg_pop != null ? `${overview.proposals.avg_pop}%` : '—', color: '#a855f7' },
            { label: 'Income (CC)', value: overview?.proposals?.income_opportunities ?? 0, color: '#f59e0b' },
            { label: 'Open Positions', value: overview?.open_positions ?? posList.length, color: '#60a5fa' },
            { label: 'Needs Action', value: overview?.needs_action ?? alerts.length, color: '#ef4444' },
            { label: 'Unrealized P/L', value: fmt$(overview?.monitor?.total_unrealized_pnl), color: '#22c55e' },
            { label: 'ITM / OTM', value: `${overview?.monitor?.itm_count ?? 0} / ${overview?.monitor?.otm_count ?? 0}`, color: 'var(--text2)' },
          ].map(k => (
            <div key={k.label} style={{ ...panel, textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 6 }}>{k.label}</div>
              <div style={{ fontSize: 22, fontWeight: 800, color: k.color }}>{k.value}</div>
            </div>
          ))}
          <div style={{ ...panel, gridColumn: '1 / -1' }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Quality Philosophy</div>
            <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.5 }}>
              Proposals below edge {proposals?.quality_gate?.min_edge_score ?? 62}, POP {proposals?.quality_gate?.min_pop_pct ?? 52}%,
              or IV rank {proposals?.quality_gate?.min_iv_rank ?? 20}% are excluded. Monitoring refreshes every 5–15 minutes during market hours.
              Execution is advisory-only until Schwab options write path is operator-approved.
            </div>
          </div>
        </div>
      )}
    </div>
  )
}