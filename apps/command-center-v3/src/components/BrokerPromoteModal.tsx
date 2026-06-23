import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import BrokerIntelPanel from './BrokerIntelPanel'
import BrokerDiligenceStrip from './BrokerDiligenceStrip'

const MUTED = '#94a3b8', TEXT0 = '#f8fafc', TEXT1 = '#dbeafe', GREEN = '#22c55e', AMBER = '#f59e0b', BLUE = '#60a5fa', PURPLE = '#a78bfa', RED = '#ef4444'
const overlay = { position: 'fixed' as const, inset: 0, background: 'rgba(2,6,23,.78)', zIndex: 9000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }
const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 16, padding: 22, width: 'min(640px, 96vw)', maxHeight: '92vh', overflow: 'auto', boxShadow: '0 24px 80px rgba(0,0,0,.45)' }
const inp = { fontSize: 12, padding: '8px 10px', borderRadius: 8, border: '1px solid rgba(148,163,184,.28)', background: 'rgba(15,23,42,.6)', color: TEXT0, width: '100%', fontFamily: 'monospace' } as const
const lbl = { fontSize: 10, color: MUTED, display: 'block', marginBottom: 5, textTransform: 'uppercase' as const, letterSpacing: '0.4px' }

export type BrokerPromoteSeed = { proposal_id: number; symbol: string; account?: string }

type Props = {
  seed: BrokerPromoteSeed
  mode?: 'promote' | 'adjust'
  onClose: () => void
  onPromoted?: (res: any) => void
}

function brokerOf(a: string) {
  const k = (a || '').toLowerCase()
  if (k.startsWith('fidelity')) return 'Fidelity'
  if (k.startsWith('schwab')) return 'Schwab'
  return '—'
}

function money(n: number | null | undefined, signed = false) {
  if (n == null || Number.isNaN(n)) return '—'
  const abs = Math.abs(n)
  const s = abs >= 1000 ? `$${(abs / 1000).toFixed(1)}k` : `$${abs.toFixed(0)}`
  if (signed && n < 0) return `-${s}`
  if (signed && n > 0) return `+${s}`
  return s
}

function computeEconomics(shares: number, entry: number, stop: number, target: number) {
  const riskPs = entry - stop
  const rewardPs = target - entry
  if (!shares || !entry || riskPs <= 0) return null
  return {
    investment: shares * entry,
    maxRisk: riskPs * shares,
    profitAtTarget: rewardPs > 0 ? rewardPs * shares : 0,
    riskPerShare: riskPs,
    rewardPerShare: rewardPs,
    rr: rewardPs > 0 ? rewardPs / riskPs : null,
    stopPct: (riskPs / entry) * 100,
    targetPct: rewardPs > 0 ? (rewardPs / entry) * 100 : 0,
  }
}

function statusColor(status: string) {
  if (status === 'PASS') return GREEN
  if (status === 'WARN') return AMBER
  return RED
}

function MetricBox({ label, value, sub, color = TEXT0 }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={{ padding: '10px 12px', borderRadius: 10, background: 'rgba(15,23,42,.55)', border: '1px solid rgba(148,163,184,.15)' }}>
      <div style={{ fontSize: 9, color: MUTED, textTransform: 'uppercase', letterSpacing: '0.35px', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 800, color, fontFamily: 'monospace' }}>{value}</div>
      {sub && <div style={{ fontSize: 9, color: MUTED, marginTop: 3 }}>{sub}</div>}
    </div>
  )
}

export default function BrokerPromoteModal({ seed, mode = 'promote', onClose, onPromoted }: Props) {
  const isAdjust = mode === 'adjust'
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [evalBusy, setEvalBusy] = useState(false)
  const [oversightBusy, setOversightBusy] = useState(false)
  const [cloudBusy, setCloudBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [data, setData] = useState<any>(null)
  const [evaluation, setEvaluation] = useState<any>(null)
  const [f, setF] = useState<any>({})
  const evalTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const prevAccount = useRef<string>('')
  const sharesTouched = useRef(false)

  const runEvaluate = useCallback(async (fields: any, strategyId?: string) => {
    if (!fields.account || !fields.shares || !fields.entry || !fields.stop || !fields.target) return
    setEvalBusy(true)
    try {
      const r = await fetch('/api/v2/broker-proposals/evaluate-promote', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          proposal_id: seed.proposal_id,
          strategy_id: strategyId || data?.strategy_id,
          account: fields.account,
          shares: Number(fields.shares),
          entry: Number(fields.entry),
          stop: Number(fields.stop),
          target: Number(fields.target),
        }),
      }).then(x => x.json())
      if (r.ok) {
        const ev = r.data ?? r
        setEvaluation(ev)
        if (ev.oversight) {
          setData((prev: any) => prev ? ({
            ...prev,
            oversight: ev.oversight,
            intel: { ...(prev.intel || {}), oversight: ev.oversight },
          }) : prev)
        }
        if (!sharesTouched.current && ev.recommended_shares != null) {
          setF((prev: any) => ({ ...prev, shares: String(ev.recommended_shares) }))
        }
      }
    } catch { /* keep last evaluation */ }
    finally { setEvalBusy(false) }
  }, [seed.proposal_id, data?.strategy_id])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const r = await fetch('/api/v2/broker-proposals/prepare-promote', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ proposal_id: seed.proposal_id, account: seed.account || undefined }),
        }).then(x => x.json())
        const d = r.data ?? r
        if (!cancelled) {
          if (!r.ok && !d.symbol) {
            setMsg(r.error || 'Failed to load proposal')
            return
          }
          const oversight = d.oversight || d.evaluation?.oversight
          setData({
            ...d,
            diligence_plan: d.diligence_plan,
            intel: d.intel ? { ...d.intel, oversight: oversight || d.intel.oversight } : d.intel,
          })
          setEvaluation(d.evaluation ?? null)
          const rec = d.recommended || {}
          const acct = seed.account || rec.account || d.current_broker || ''
          prevAccount.current = acct
          sharesTouched.current = false
          setF({
            account: acct,
            shares: rec.shares ?? '',
            entry: rec.entry ?? '',
            stop: rec.stop ?? '',
            target: rec.target ?? '',
            risk_reward: rec.risk_reward ?? '',
          })
        }
      } catch (e: any) {
        if (!cancelled) setMsg('Load failed: ' + String(e).slice(0, 80))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [seed.proposal_id, seed.account])

  useEffect(() => {
    if (loading || !data) return
    if (data.diligence_auto_queued) {
      setMsg('⏳ Due diligence auto-queued — agent + LLM reviews running (~1 min)')
    }
  }, [loading, data?.diligence_auto_queued])

  useEffect(() => {
    if (loading || !f.account || f.account === prevAccount.current) return
    prevAccount.current = f.account
    sharesTouched.current = false
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetch('/api/v2/broker-proposals/prepare-promote', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ proposal_id: seed.proposal_id, account: f.account }),
        }).then(x => x.json())
        const d = r.data ?? r
        if (!cancelled && r.ok) {
          setEvaluation(d.evaluation ?? null)
          const rec = d.recommended || {}
          setF((prev: any) => ({
            ...prev,
            shares: rec.shares ?? prev.shares,
            entry: rec.entry ?? prev.entry,
            stop: rec.stop ?? prev.stop,
            target: rec.target ?? prev.target,
          }))
        }
      } catch { /* keep current */ }
    })()
    return () => { cancelled = true }
  }, [f.account, loading, seed.proposal_id])

  useEffect(() => {
    if (loading) return
    if (evalTimer.current) clearTimeout(evalTimer.current)
    evalTimer.current = setTimeout(() => runEvaluate(f, data?.strategy_id), 400)
    return () => { if (evalTimer.current) clearTimeout(evalTimer.current) }
  }, [f.account, f.shares, f.entry, f.stop, f.target, loading, runEvaluate, data?.strategy_id])

  const econ = useMemo(() => {
    const sh = Number(f.shares), en = Number(f.entry), st = Number(f.stop), tg = Number(f.target)
    if (!sh || !en || !st || !tg) return null
    return computeEconomics(sh, en, st, tg)
  }, [f.shares, f.entry, f.stop, f.target])

  const computedRR = econ?.rr ?? null
  const quote = data?.quote || {}
  const sizing = evaluation?.sizing || data?.sizing || {}
  const activity = evaluation?.account_activity || sizing?.account_activity || {}
  const gateStatus = evaluation?.status || '—'
  const oversightStatus = evaluation?.oversight?.status || data?.oversight?.status
  const promoteReady = evaluation?.oversight?.promote_ready ?? data?.promote_ready
  const diligenceIncomplete = oversightStatus === 'BLOCK' || evaluation?.allowed === false || gateStatus === 'BLOCK'
  const blocked = diligenceIncomplete
  const oversightWarnings: string[] = evaluation?.oversight?.warnings || evaluation?.warnings || []
  const oversightViolations: string[] = [
    ...(evaluation?.oversight?.violations || []),
    ...(evaluation?.violations || []),
  ].filter((v, i, a) => a.indexOf(v) === i)
  const intelDiligence = evaluation?.oversight?.intel_diligence || data?.oversight?.intel_diligence

  const refreshOversight = useCallback(async () => {
    try {
      const r = await fetch('/api/v2/broker-proposals/oversight', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: seed.proposal_id }),
      }).then(x => x.json())
      const ov = r.data ?? r
      if (r.ok && ov) {
        setData((prev: any) => prev ? ({
          ...prev,
          oversight: ov,
          intel: { ...(prev.intel || {}), oversight: ov },
        }) : prev)
        setEvaluation((prev: any) => prev ? { ...prev, oversight: ov } : prev)
      }
    } catch { /* keep last */ }
  }, [seed.proposal_id])

  useEffect(() => {
    if (loading) return
    const pending = evaluation?.oversight?.agents?.pending?.length || data?.oversight?.agents?.pending?.length
    const localSt = evaluation?.oversight?.local_llm?.status || data?.oversight?.local_llm?.status
    if (!pending && localSt !== 'queued' && localSt !== 'missing') return
    const t = setInterval(() => {
      refreshOversight()
      runEvaluate(f, data?.strategy_id)
    }, 12_000)
    return () => clearInterval(t)
  }, [loading, evaluation?.oversight?.agents?.pending, evaluation?.oversight?.local_llm?.status, data?.oversight, f, data?.strategy_id, refreshOversight, runEvaluate])

  const queueOversight = async () => {
    setOversightBusy(true); setMsg('')
    try {
      const r = await fetch('/api/v2/broker-proposals/queue-oversight', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: seed.proposal_id }),
      }).then(x => x.json())
      setMsg(r.ok ? '✅ Local agent + LLM reviews queued — refresh in ~1 min' : '⛔ ' + (r.error || 'queue failed'))
      if (r.ok) setTimeout(refreshOversight, 3000)
    } catch (e: any) {
      setMsg('⛔ ' + String(e).slice(0, 80))
    } finally {
      setOversightBusy(false)
    }
  }

  const runCloudOversight = async () => {
    setCloudBusy(true); setMsg('')
    try {
      const r = await fetch('/api/v2/broker-proposals/run-cloud-oversight', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: seed.proposal_id, timeout: 120 }),
      }).then(x => x.json())
      const payload = r.data ?? r
      if (r.ok && payload.oversight) {
        const ov = payload.oversight
        setData((prev: any) => prev ? ({
          ...prev,
          oversight: ov,
          intel: { ...(prev.intel || {}), oversight: ov },
        }) : prev)
        setEvaluation((prev: any) => {
          if (!prev) return prev
          const merged = { ...prev, oversight: ov }
          if (ov.status === 'BLOCK') { merged.status = 'BLOCK'; merged.allowed = false }
          else if (ov.status === 'WARN' && prev.status === 'PASS') merged.status = 'WARN'
          merged.violations = [...(prev.violations || []), ...(ov.violations || [])]
          merged.warnings = [...(prev.warnings || []), ...(ov.warnings || [])]
          return merged
        })
        const verdict = payload.cloud?.consensus?.verdict || payload.cloud?.status
        setMsg(`✅ Cloud review: ${verdict || 'done'}`)
      } else {
        setMsg('⛔ ' + (r.error || payload.error || 'cloud review failed'))
      }
    } catch (e: any) {
      setMsg('⛔ ' + String(e).slice(0, 80))
    } finally {
      setCloudBusy(false)
    }
  }
  const paperOrig = data?.paper_original
  const accounts: any[] = data?.accounts || []
  const selAcct = accounts.find(a => a.account_key === f.account)
  const acctActivity = selAcct?.activity || activity

  const set = (k: string, v: any) => {
    if (k === 'shares') sharesTouched.current = true
    setF({ ...f, [k]: v })
  }

  const onAccountChange = (acct: string) => {
    sharesTouched.current = false
    setF({ ...f, account: acct })
  }

  const applyLiveAsk = () => {
    if (quote.ask != null) set('entry', String(Number(quote.ask).toFixed(2)))
  }

  const applyMaxShares = () => {
    const mx = evaluation?.max_shares ?? sizing?.shares
    if (mx != null) set('shares', String(mx))
  }

  const submit = async () => {
    if (blocked) {
      setMsg(oversightViolations.length
        ? '⛔ Due diligence incomplete — complete agent reviews, AI Review, and intel gates before promote'
        : '⛔ Trade blocked — fix sizing or market conditions before saving')
      return
    }
    if (!f.account) { setMsg('Select a destination account'); return }
    if (!f.shares || !f.entry || !f.stop || !f.target) { setMsg('Fill shares, entry, stop, and target'); return }
    if (Number(f.entry) <= Number(f.stop)) { setMsg('Entry must be above stop (long trade)'); return }
    setBusy(true); setMsg('')
    try {
      const r = await fetch('/api/v2/broker-proposals/promote-from-paper', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          proposal_id: seed.proposal_id,
          account: f.account,
          shares: Number(f.shares),
          entry: Number(f.entry),
          stop: Number(f.stop),
          target: Number(f.target),
          risk_reward: f.risk_reward ? Number(f.risk_reward) : computedRR,
        }),
      }).then(x => x.json())
      if (r.ok) {
        setMsg('✅ ' + (r.message || r.data?.message || 'Saved'))
        onPromoted?.(r)
        setTimeout(onClose, 1200)
      } else setMsg('⛔ ' + (r.error || r.message || 'failed'))
    } catch (e: any) {
      setMsg('⛔ ' + String(e).slice(0, 80))
    } finally {
      setBusy(false)
    }
  }

  const brokerBadge = selAcct?.execution_label || (brokerOf(f.account) === 'Fidelity' ? 'Manual · Fidelity' : 'Schwab · auto or manual')
  const sizingLabel = sizing.sizing_base_label === 'cash'
    ? `Sized on cash ($${Number(sizing.sizing_base || acctActivity.cash || 0).toLocaleString()})`
    : `Sized on equity ($${Number(sizing.sizing_base || sizing.equity || 0).toLocaleString()})`

  return (
    <div style={overlay} onClick={onClose}>
      <div style={card} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 900, color: TEXT0, letterSpacing: '-0.02em' }}>
              {isAdjust ? 'Edit broker trade' : 'Send to broker'} · <span style={{ fontFamily: 'monospace' }}>{seed.symbol}</span>
            </div>
            <div style={{ fontSize: 11, color: MUTED, marginTop: 5, lineHeight: 1.45 }}>
              Agent reviews, catalyst/analyst intel, sizing, and market gates must pass before promote.
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: MUTED, cursor: 'pointer', fontSize: 22, lineHeight: 1 }}>×</button>
        </div>

        {loading ? <div style={{ fontSize: 11, color: MUTED, padding: '24px 0' }}>Loading proposal & live quote…</div> : (
          <>
            {data?.diligence_plan?.stages?.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <BrokerDiligenceStrip
                  stages={data.diligence_plan.stages}
                  summary={{
                    status: data.diligence_plan.status,
                    promote_ready: data.diligence_plan.promote_ready,
                    next_action: data.diligence_plan.next_action,
                    current_step: data.diligence_plan.current_step,
                    total_steps: data.diligence_plan.total_steps,
                    completed_steps: data.diligence_plan.completed_steps,
                  }}
                />
              </div>
            )}

            <div style={{ marginBottom: 14, padding: '12px 14px', borderRadius: 10, background: 'rgba(15,23,42,.55)', border: '1px solid rgba(148,163,184,.18)' }}>
              <div style={{ fontSize: 10, fontWeight: 800, color: MUTED, textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 8 }}>Decision context</div>
              <BrokerIntelPanel
                intel={data?.intel}
                onQueueOversight={queueOversight}
                onRunCloudOversight={runCloudOversight}
                oversightBusy={oversightBusy}
                cloudBusy={cloudBusy}
              />
            </div>

            <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap', alignItems: 'center' }}>
              <span style={{ fontSize: 9, fontWeight: 800, padding: '4px 9px', borderRadius: 6, background: brokerOf(f.account) === 'Fidelity' ? 'rgba(167,139,250,.2)' : 'rgba(245,158,11,.2)', color: brokerOf(f.account) === 'Fidelity' ? PURPLE : AMBER }}>{brokerBadge}</span>
              {data?.strategy_id && (
                <span style={{ fontSize: 9, fontWeight: 700, padding: '4px 9px', borderRadius: 6, background: 'rgba(249,115,22,.15)', color: '#fb923c' }}>{data.strategy_id}</span>
              )}
              <span style={{
                fontSize: 9, fontWeight: 800, padding: '4px 9px', borderRadius: 6,
                background: gateStatus === 'PASS' ? 'rgba(34,197,94,.18)' : gateStatus === 'WARN' ? 'rgba(245,158,11,.18)' : 'rgba(239,68,68,.18)',
                color: statusColor(gateStatus),
              }}>
                {evalBusy ? 'CHECKING…' : gateStatus}
              </span>
              {oversightStatus && (
                <span style={{
                  fontSize: 9, fontWeight: 800, padding: '4px 9px', borderRadius: 6,
                  background: oversightStatus === 'PASS' ? 'rgba(168,85,247,.15)' : oversightStatus === 'WARN' ? 'rgba(245,158,11,.15)' : 'rgba(239,68,68,.15)',
                  color: oversightStatus === 'PASS' ? PURPLE : statusColor(oversightStatus),
                }}>
                  Diligence {oversightStatus}
                </span>
              )}
              {promoteReady === true && (
                <span style={{ fontSize: 9, fontWeight: 800, padding: '4px 9px', borderRadius: 6, background: 'rgba(34,197,94,.15)', color: GREEN }}>
                  PROMOTE READY
                </span>
              )}
              <span style={{ fontSize: 9, color: MUTED }}>Proposal #{seed.proposal_id}</span>
            </div>

            {paperOrig?.shares && Number(paperOrig.shares) !== Number(f.shares) && (
              <div style={{ fontSize: 10, color: AMBER, marginBottom: 12, padding: '8px 10px', borderRadius: 8, background: 'rgba(245,158,11,.1)', border: '1px solid rgba(245,158,11,.25)' }}>
                Paper had {Number(paperOrig.shares).toLocaleString()} sh ({money(paperOrig.dollar_size)}) — resized to broker cap {Number(f.shares).toLocaleString()} sh.
              </div>
            )}

            {f.account && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 14, padding: '10px 12px', borderRadius: 10, background: 'rgba(34,197,94,.06)', border: '1px solid rgba(34,197,94,.2)' }}>
                <MetricBox label="Cash (sizing base)" value={money(acctActivity.cash ?? sizing.cash_available)} sub={acctActivity.cash_source || sizing.cash_source || 'live'} color={GREEN} />
                <MetricBox label="Equity" value={money(acctActivity.equity ?? sizing.equity)} sub={acctActivity.equity_source || sizing.equity_source} />
                <MetricBox label="Open trades" value={String(acctActivity.open_trades ?? '—')} sub={acctActivity.max_concurrent_positions != null ? `max ${acctActivity.max_concurrent_positions} concurrent` : undefined} />
                <MetricBox label="New today" value={
                  acctActivity.max_new_positions_per_day != null
                    ? `${acctActivity.slots_used_today ?? acctActivity.new_trades_today ?? 0} / ${acctActivity.max_new_positions_per_day}`
                    : String(acctActivity.new_trades_today ?? acctActivity.slots_used_today ?? '—')
                } sub={acctActivity.remaining_new_today != null ? `${acctActivity.remaining_new_today} slots left` : undefined}
                  color={(acctActivity.daily_limit_reached) ? RED : TEXT0} />
              </div>
            )}

            {(sizing.shares != null || evaluation?.max_shares != null) && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 14 }}>
                <MetricBox label="Max shares" value={String(evaluation?.max_shares ?? sizing.shares ?? '—')} sub={`binding: ${sizing.binding || '—'}`} color={BLUE} />
                <MetricBox label="Sizing engine" value={sizing.engine || '—'} sub={sizingLabel} />
                <MetricBox label="Risk / pos %" value={sizing.risk_pct != null ? `${sizing.risk_pct}%` : '—'} sub={sizing.pos_pct != null ? `pos ${sizing.pos_pct}% of cash` : undefined} />
                <MetricBox label="Max risk $" value={money(sizing.max_dollar_risk)} sub={money(sizing.max_dollar_size) + ' position cap'} />
              </div>
            )}

            {oversightViolations.length > 0 && (
              <div style={{ fontSize: 10, color: RED, marginBottom: 12, padding: '8px 10px', borderRadius: 8, background: 'rgba(239,68,68,.1)' }}>
                <div style={{ fontWeight: 800, marginBottom: 4 }}>Due diligence blockers</div>
                {oversightViolations.map((v: string, i: number) => <div key={i}>⛔ {v}</div>)}
              </div>
            )}

            {intelDiligence?.catalyst_verdict && (
              <div style={{ fontSize: 9, color: MUTED, marginBottom: 10 }}>
                Catalyst critic: <b style={{ color: intelDiligence.catalyst_verdict === 'BLOCK' ? RED : intelDiligence.catalyst_verdict === 'DOWNGRADE' ? AMBER : GREEN }}>{intelDiligence.catalyst_verdict}</b>
                {intelDiligence.analyst_coverage ? ` · analyst coverage ${intelDiligence.analyst_coverage}` : ''}
                {intelDiligence.intel_readiness != null ? ` · intel ${intelDiligence.intel_readiness}%` : ''}
              </div>
            )}

            {(oversightWarnings.length > 0 || evaluation?.warnings?.length > 0) && (
              <div style={{ fontSize: 10, color: AMBER, marginBottom: 12, padding: '8px 10px', borderRadius: 8, background: 'rgba(245,158,11,.08)' }}>
                {[...new Set([...(evaluation?.warnings || []), ...oversightWarnings])].map((w: string, i: number) => <div key={i}>⚠ {w}</div>)}
              </div>
            )}

            {evaluation?.market?.warnings?.length > 0 && (
              <div style={{ fontSize: 10, color: AMBER, marginBottom: 12, padding: '8px 10px', borderRadius: 8, background: 'rgba(245,158,11,.1)' }}>
                {evaluation.market.warnings.map((w: string, i: number) => <div key={i}>⚠ {w}</div>)}
              </div>
            )}

            {(quote.bid != null || quote.ask != null) && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 14, padding: '10px 12px', borderRadius: 10, background: 'rgba(96,165,250,.08)', border: '1px solid rgba(96,165,250,.2)' }}>
                <div><div style={lbl}>Bid</div><div style={{ fontFamily: 'monospace', fontWeight: 700, color: TEXT1 }}>${Number(quote.bid).toFixed(2)}</div></div>
                <div><div style={lbl}>Ask</div><div style={{ fontFamily: 'monospace', fontWeight: 700, color: TEXT1 }}>${Number(quote.ask).toFixed(2)}</div></div>
                <div><div style={lbl}>Spread</div><div style={{ fontFamily: 'monospace', fontWeight: 700, color: quote.spread_pct != null && Number(quote.spread_pct) > 1 ? AMBER : GREEN }}>
                  {quote.spread != null ? `$${Number(quote.spread).toFixed(2)}` : '—'}
                  {quote.spread_pct != null ? ` (${Number(quote.spread_pct).toFixed(2)}%)` : ''}
                </div></div>
                <div style={{ display: 'flex', alignItems: 'flex-end' }}>
                  <button type="button" onClick={applyLiveAsk} style={{ fontSize: 10, fontWeight: 700, padding: '6px 10px', borderRadius: 6, border: `1px solid ${BLUE}`, background: 'rgba(96,165,250,.12)', color: BLUE, cursor: 'pointer', width: '100%' }}>
                    Use ask as entry
                  </button>
                </div>
              </div>
            )}

            {econ && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 16 }}>
                <MetricBox label="Investment" value={money(econ.investment)} sub={`${Number(f.shares).toLocaleString()} sh × $${Number(f.entry).toFixed(2)}`} color={BLUE} />
                <MetricBox label="Max risk" value={money(econ.maxRisk)} sub={`−${econ.stopPct.toFixed(1)}% to stop`} color={RED} />
                <MetricBox label="Profit @ target" value={money(econ.profitAtTarget, true)} sub={`+${econ.targetPct.toFixed(1)}% to target`} color={GREEN} />
                <MetricBox label="R : R" value={computedRR != null ? `${computedRR.toFixed(2)} : 1` : '—'} sub={econ.riskPerShare ? `$${econ.riskPerShare.toFixed(2)}/sh risk` : undefined} color={computedRR != null && computedRR >= 2 ? GREEN : AMBER} />
              </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <label style={{ gridColumn: '1 / -1' }}><span style={lbl}>Destination account</span>
                <select style={{ ...inp, fontFamily: 'inherit' }} value={f.account} onChange={e => onAccountChange(e.target.value)}>
                  <option value="">— select account —</option>
                  {accounts.map(a => {
                    const act = a.activity || {}
                    const cashLbl = act.cash != null ? ` · cash ${money(act.cash)}` : ''
                    const dayLbl = act.max_new_positions_per_day != null
                      ? ` · ${act.slots_used_today ?? 0}/${act.max_new_positions_per_day} today`
                      : (act.new_trades_today != null ? ` · ${act.new_trades_today} new today` : '')
                    return (
                      <option key={a.account_key} value={a.account_key}>
                        {brokerOf(a.account_key)} · {a.display_name || a.account_key}{cashLbl}{dayLbl}
                      </option>
                    )
                  })}
                </select>
              </label>
              <label><span style={lbl}>Shares {evaluation?.max_shares != null ? `(max ${evaluation.max_shares})` : ''}</span>
                <input style={inp} value={f.shares} onChange={e => set('shares', e.target.value.replace(/[^0-9]/g, ''))} />
              </label>
              <div style={{ display: 'flex', alignItems: 'flex-end' }}>
                <button type="button" onClick={applyMaxShares} disabled={!evaluation?.max_shares}
                  style={{ fontSize: 10, fontWeight: 700, padding: '8px 10px', borderRadius: 6, border: `1px solid ${GREEN}`, background: 'rgba(34,197,94,.1)', color: GREEN, cursor: 'pointer', width: '100%' }}>
                  Apply max shares
                </button>
              </div>
              <label><span style={lbl}>Entry ($)</span>
                <input style={inp} value={f.entry} onChange={e => set('entry', e.target.value)} />
              </label>
              <label><span style={lbl}>Stop ($)</span>
                <input style={inp} value={f.stop} onChange={e => set('stop', e.target.value)} />
              </label>
              <label><span style={lbl}>Target ($)</span>
                <input style={inp} value={f.target} onChange={e => set('target', e.target.value)} />
              </label>
              <label><span style={lbl}>R:R override {computedRR != null ? `(live ${computedRR}:1)` : ''}</span>
                <input style={inp} value={f.risk_reward} onChange={e => set('risk_reward', e.target.value)} placeholder={computedRR != null ? String(computedRR) : 'auto'} />
              </label>
            </div>
          </>
        )}

        {msg && <div style={{ fontSize: 11, marginTop: 14, padding: '8px 10px', borderRadius: 8, background: msg.startsWith('✅') ? 'rgba(34,197,94,.12)' : 'rgba(245,158,11,.12)', color: msg.startsWith('✅') ? GREEN : AMBER }}>{msg}</div>}

        <div style={{ display: 'flex', gap: 10, marginTop: 18, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ fontSize: 11, fontWeight: 700, padding: '9px 16px', borderRadius: 8, border: '1px solid var(--border)', background: 'transparent', color: MUTED, cursor: 'pointer' }}>Cancel</button>
          <button onClick={submit} disabled={busy || loading || blocked}
            style={{ fontSize: 12, fontWeight: 800, padding: '9px 20px', borderRadius: 8, border: 'none', background: blocked ? MUTED : AMBER, color: '#0f172a', cursor: busy || blocked ? 'not-allowed' : 'pointer', opacity: busy ? 0.7 : 1 }}>
            {busy ? 'Saving…' : blocked ? 'Diligence incomplete' : isAdjust ? 'Save trade plan' : 'Add to broker queue'}
          </button>
        </div>
      </div>
    </div>
  )
}