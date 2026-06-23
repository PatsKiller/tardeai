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
  const [minPop, setMinPop] = useState(0)
  const [minEdge, setMinEdge] = useState(0)
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
    if (minPop > 0) p.set('min_pop', String(minPop))
    if (minEdge > 0) p.set('min_edge', String(minEdge))
    const s = p.toString()
    return s ? `?${s}` : ''
  }, [symbolFilter, strategyFilter, minPop, minEdge])

  const { data: proposals, loading: propLoading, error: propError, stale: propStale, refetch: refetchProps } =
    useApi<any>(`/api/v2/options/proposals${q}`, 300_000)
  const { data: monitor, loading: monLoading, error: monError, refetch: refetchMon } =
    useApi<any>('/api/v2/options/positions', 300_000)
  const { data: overview, refetch: refetchOverview } = useApi<any>('/api/v2/options/overview', 300_000)
  const { data: execStatus } = useApi<any>('/api/v2/options/execution/status', 120_000)

  const propList: Proposal[] = Array.isArray(proposals?.proposals) ? proposals.proposals : []
  const propCount = proposals?.count ?? propList.length
  const posList: Position[] = Array.isArray(monitor?.positions) ? monitor.positions : []
  const alerts = monitor?.alerts ?? []

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
            High-quality proposals only · {propCount} ideas · {posList.length} open legs
            {proposals?.quality_gate && (
              <span title="Intent sleeve (V/SCHD/LMT) uses edge floor 52; others need 62"> · gate {proposals.quality_gate.min_edge_score}+ / sleeve {proposals.quality_gate.relaxed_edge_floor}+</span>
            )}
            {proposals?.generated_at && (
              <span style={{ color: 'var(--text3)' }}> · updated {new Date(proposals.generated_at).toLocaleTimeString()}</span>
            )}
            {alerts.length > 0 && <span style={{ color: '#f59e0b' }}> · {alerts.length} need action</span>}
            {execStatus && (
              <span style={{ color: execStatus.armed_for_execution ? '#22c55e' : '#f59e0b' }}>
                {' '}· execution {execStatus.armed_for_execution ? 'ARMED' : 'advisory'}
              </span>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <NoviceToggle on={novice} onChange={setNovice} />
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
                <option value="protective_put">Protective Put</option>
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
            <button onClick={() => { refetchProps(); refetchMon(); refetchOverview() }} style={{ ...SEL, cursor: 'pointer' }}>Refresh</button>
            <button onClick={() => forceRefresh()} style={{ ...SEL, cursor: 'pointer', color: '#60a5fa' }}>Force scan</button>
            <button onClick={validateAllEnsemble} disabled={ensembleBusy} style={{ ...SEL, cursor: ensembleBusy ? 'default' : 'pointer', color: '#a855f7' }} title="Enqueue Grok + ChatGPT OAuth + local Gemma for every proposal">
              {ensembleBusy ? 'Queuing…' : 'Validate all (Grok+GPT)'}
            </button>
            {ensembleMsg && <span style={{ fontSize: 10, color: 'var(--text3)' }}>{ensembleMsg}</span>}
            {propLoading && <span style={{ fontSize: 10, color: 'var(--text3)' }}>Loading…</span>}
            {propStale && <span style={{ fontSize: 10, color: '#f59e0b' }}>Reconnecting…</span>}
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
          {posList.length > 0 && (
            <div style={{ ...panel, marginBottom: 14, display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1.2fr)', gap: 16 }}>
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
            { label: 'Proposal Count', value: overview?.proposal_count ?? propList.length, color: '#60a5fa' },
            { label: 'Avg Edge Score', value: overview?.proposals?.total_edge_avg ?? '—', color: '#22c55e' },
            { label: 'Avg POP', value: overview?.proposals?.avg_pop != null ? `${overview.proposals.avg_pop}%` : '—', color: '#a855f7' },
            { label: 'Income (CC)', value: overview?.proposals?.income_opportunities ?? 0, color: '#f59e0b' },
            { label: 'Put plays', value: overview?.proposals?.put_plays ?? proposals?.puts ?? 0, color: PURPLE },
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
          <div style={{ ...panel, gridColumn: '1 / -1' }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Quality Philosophy</div>
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