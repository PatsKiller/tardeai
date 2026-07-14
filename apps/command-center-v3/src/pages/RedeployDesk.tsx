/**
 * RedeployDesk — full-page institutional capital-allocation workstation.
 *
 * Replaces the 780px RedeployEventModal drawer (rejected at operator review
 * 2026-07-13: unreadable 9–10px type, label-level plans, no pro-forma).
 * Typography floor: body 14px / tables 13px / labels 12px / headings 18px /
 * title 26px, with a compact|comfortable density toggle that never goes
 * below the floor. Advisory only — no execution controls exist on this page.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { BB } from '../lib/holdingsTerminalTokens'
import { fmt$ } from '../lib/format'

// ── workstation typography (Part F floor) ───────────────────────────────────
const DENSITY_KEY = 'cc-v3-redeploy-density'
type Density = 'comfortable' | 'compact'
const T = (d: Density) => ({
  title: 26,
  heading: 18,
  subheading: 16,
  body: 14,
  table: 13,
  label: 12,
  cellPadY: d === 'compact' ? 4 : 8,
  cellPadX: d === 'compact' ? 8 : 12,
  gap: d === 'compact' ? 10 : 16,
})

// Decision-first ordering (Phase 17): the operator lands on DECISION, then
// comparison, then the lab. CAPITAL BOOK remains the no-event landing.
const TABS = [
  'CAPITAL BOOK', 'DECISION', 'PLAN COMPARISON', 'PLAN LAB', 'EVENT OVERVIEW', 'PRO-FORMA', 'LOOK-THROUGH',
  'PERFORMANCE', 'ENTRIES', 'MONITORING', 'REJECTED', 'PM MEMO', 'AUDIT',
] as const
type Tab = (typeof TABS)[number]

// PM memo (defect 21) — structured 18-section memo rendered as prose, never JSON.
const MEMO_SECTIONS: [string, string][] = [
  ['executive_recommendation', 'Executive recommendation'],
  ['sale_summary', 'Sale summary'],
  ['exposure_removed', 'Exposure removed'],
  ['portfolio_context', 'Portfolio context'],
  ['regime_context', 'Regime context'],
  ['alternatives_considered', 'Alternatives considered'],
  ['recommended_allocation', 'Recommended allocation'],
  ['reserve', 'Reserve'],
  ['entry_stages', 'Entry stages'],
  ['expected_impact', 'Expected impact'],
  ['income_and_fees', 'Income and fees'],
  ['risk_analysis', 'Risk analysis'],
  ['remaining_gaps', 'Remaining gaps'],
  ['change_conditions', 'Change conditions'],
  ['next_operator_action', 'Next operator action'],
  ['sources_and_timestamps', 'Sources and timestamps'],
  ['oversight_conclusion', 'Oversight conclusion'],
  ['advisory_statement', 'Advisory statement'],
]
// Plain-language coercion for memo values — objects become "key: value" lines, never JSON.
const memoLines = (v: any): string[] => {
  if (v == null) return []
  if (typeof v === 'string') return [v]
  if (Array.isArray(v)) return v.flatMap(memoLines)
  if (typeof v === 'object') return Object.entries(v).map(([k, x]) => `${k.replace(/_/g, ' ')}: ${memoLines(x).join('; ')}`)
  return [String(v)]
}

// ── data hook (self-contained; refreshable; null url = idle) ─────────────────
function useJson<T = any>(url: string | null) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (!url) { setData(null); return }
    let dead = false
    setLoading(true); setError('')
    fetch(url)
      .then(r => r.json())
      .then(j => { if (!dead) setData((j?.data && typeof j.data === 'object' && !Array.isArray(j.data) && (j.plans === undefined && j.rows === undefined)) ? j.data : j) })
      .catch(e => { if (!dead) setError(String(e)) })
      .finally(() => { if (!dead) setLoading(false) })
    return () => { dead = true }
  }, [url, tick])
  return { data, loading, error, refetch: () => setTick(t => t + 1) }
}

const pct = (v: any, dp = 2) => (v === null || v === undefined ? '—' : `${Number(v).toFixed(dp)}%`)
const num = (v: any, dp = 2) => (v === null || v === undefined ? '—' : Number(v).toFixed(dp))
const ago = (iso?: string | null) => {
  if (!iso) return '—'
  const ms = Date.now() - new Date(iso).getTime()
  if (!isFinite(ms)) return String(iso).slice(0, 16)
  const m = Math.round(ms / 60000)
  if (m < 60) return `${m}m ago`
  if (m < 60 * 36) return `${Math.round(m / 60)}h ago`
  return `${Math.round(m / 1440)}d ago`
}
const toneFor = (v: number | null | undefined) =>
  v === null || v === undefined ? BB.text3 : v > 0 ? BB.green : v < 0 ? BB.red : BB.text2

// ── shared UI atoms ──────────────────────────────────────────────────────────
function Pill({ text, color, title }: { text: string; color: string; title?: string }) {
  return (
    <span title={title} style={{
      display: 'inline-block', padding: '2px 10px', borderRadius: 4, fontSize: 12,
      fontWeight: 700, letterSpacing: 0.4, color, border: `1px solid ${color}55`,
      background: `${color}18`, whiteSpace: 'nowrap',
    }}>{text}</span>
  )
}

function Section({ title, t, children, right }: any) {
  return (
    <div style={{ marginBottom: t.gap * 1.5 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ fontSize: t.heading, fontWeight: 700, color: BB.text0 }}>{title}</div>
        {right}
      </div>
      {children}
    </div>
  )
}

function DataTable({ t, cols, rows, empty }: {
  t: ReturnType<typeof T>
  cols: { key: string; label: string; align?: 'right' | 'left'; render?: (row: any) => any; width?: string }[]
  rows: any[]
  empty?: string
}) {
  if (!rows?.length) return <div style={{ fontSize: t.body, color: BB.text3, padding: 12 }}>{empty || 'No rows.'}</div>
  return (
    <div style={{ overflowX: 'auto', border: `1px solid ${BB.border}`, borderRadius: 6 }}>
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: t.table, fontFamily: BB.mono }}>
        <thead>
          <tr style={{ background: BB.bgRowAlt }}>
            {cols.map(c => (
              <th key={c.key} style={{
                padding: `${t.cellPadY + 2}px ${t.cellPadX}px`, textAlign: c.align || 'left',
                color: BB.text3, fontSize: t.label, fontWeight: 700, letterSpacing: 0.5,
                borderBottom: `1px solid ${BB.border}`, whiteSpace: 'nowrap', width: c.width,
              }}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} style={{ background: i % 2 ? BB.bgRowAlt : BB.bgRow }}>
              {cols.map(c => (
                <td key={c.key} style={{
                  padding: `${t.cellPadY}px ${t.cellPadX}px`, textAlign: c.align || 'left',
                  color: BB.text1, borderBottom: `1px solid ${BB.borderSubtle}`, whiteSpace: 'nowrap',
                }}>{c.render ? c.render(r) : (r[c.key] ?? '—')}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ═════════════════════════════════════════════════════════════════════════════
export default function RedeployDesk() {
  const [params, setParams] = useSearchParams()
  const [density, setDensity] = useState<Density>(() =>
    (localStorage.getItem(DENSITY_KEY) as Density) || 'comfortable')
  const t = T(density)
  const [tab, setTab] = useState<Tab>(() => {
    const raw = params.get('tab')
    if (raw === 'PLANS') return 'PLAN LAB'  // legacy deep-links
    if ((TABS as readonly string[]).includes(raw || '')) return raw as Tab
    // No explicit ?tab= deep-link: an event deep-link lands decision-first.
    return params.get('event') ? 'DECISION' : 'CAPITAL BOOK'
  })
  const eventId = params.get('event') ? Number(params.get('event')) : null

  const setEvent = useCallback((id: number | null, nextTab?: Tab) => {
    const p = new URLSearchParams(params)
    if (id) p.set('event', String(id)); else p.delete('event')
    const goto = nextTab ?? (id ? 'DECISION' as Tab : undefined) // selecting an event defaults to DECISION
    if (goto) { p.set('tab', goto); setTab(goto) }
    setParams(p, { replace: true })
  }, [params, setParams])

  useEffect(() => { localStorage.setItem(DENSITY_KEY, density) }, [density])
  useEffect(() => {
    const p = new URLSearchParams(params)
    if (p.get('tab') !== tab) { p.set('tab', tab); setParams(p, { replace: true }) }
  }, [tab]) // eslint-disable-line

  // core data
  const book = useJson<any>('/api/v2/redeploy/book?limit=300')
  const pools = useJson<any>('/api/v2/redeploy/capital-pools')
  const plansRes = useJson<any>(eventId ? `/api/v2/deploy/plans?event_id=${eventId}` : null)
  const monitoring = useJson<any>(eventId ? `/api/v2/deploy/monitoring?event_id=${eventId}` : null)
  const analysis = useJson<any>(eventId ? `/api/v2/deploy/analysis?event_id=${eventId}` : null)
  const exportRes = useJson<any>(eventId ? `/api/v2/deploy/export?event_id=${eventId}` : null)
  const candidates = useJson<any>(eventId ? `/api/v2/redeploy/candidates?event_id=${eventId}` : null)
  const audit = useJson<any>(eventId ? `/api/v2/redeploy/audit?event_id=${eventId}` : null)

  const bookRows: any[] = book.data?.rows ?? []
  const eventRow = useMemo(() => bookRows.find(r => r.event_id === eventId) || null, [bookRows, eventId])
  const plans: any[] = plansRes.data?.plans ?? []

  // Phase 17 decision contract (all optional — backend agents land concurrently)
  const rec = plansRes.data?.recommendation ?? null
  const memoStruct = plansRes.data?.pm_memo_structured ?? null
  const lockedPlanId = plansRes.data?.locked_plan_id ?? eventRow?.locked_plan_id ?? null
  const primaryPlan = useMemo(() =>
    (rec?.primary?.archetype ? plans.find((p: any) => p.plan_archetype === rec.primary.archetype) : null) ?? null,
    [plans, rec])
  const topQuantPlanId = useMemo(() => {
    let best: any = null
    for (const p of plans) {
      const s = p?.decision_score?.total_score
      if (s != null && (best == null || s > best.s)) best = { id: p.id, s }
    }
    return best?.id ?? null
  }, [plans])

  // selected plan persists per event across tabs (Part F requirement)
  const planKey = `cc-v3-redeploy-plan-${eventId ?? 'none'}`
  const [selectedPlanId, setSelectedPlanId] = useState<number | null>(null)
  useEffect(() => {
    const saved = eventId ? Number(localStorage.getItem(planKey) || 0) : 0
    const lockedId = eventRow?.locked_plan_id ?? null
    const fallback = plans.length ? plans[0].id : null
    const pick = [saved, lockedId, fallback].find(v => v && plans.some(p => p.id === v)) ?? fallback
    setSelectedPlanId(pick ?? null)
  }, [eventId, plans.length, eventRow?.locked_plan_id]) // eslint-disable-line
  const selectPlan = (id: number) => { setSelectedPlanId(id); if (eventId) localStorage.setItem(planKey, String(id)) }
  const selectedPlan = plans.find(p => p.id === selectedPlanId) || null
  const planLabel = selectedPlan ? `Plan ${selectedPlan.plan_archetype} v${selectedPlan.version} · ${selectedPlan.objective || selectedPlan.plan_type || ''}` : null

  const proForma = useJson<any>(eventId && selectedPlanId
    ? `/api/v2/redeploy/portfolio-pro-forma?event_id=${eventId}&plan_id=${selectedPlanId}` : null)
  const performance = useJson<any>(eventId && selectedPlanId
    ? `/api/v2/redeploy/performance?event_id=${eventId}&plan_id=${selectedPlanId}` : null)

  const [compareIds, setCompareIds] = useState<number[]>([])
  const [actionMsg, setActionMsg] = useState('')

  // Defect 22: comparison never opens empty. Reset stale ids on event change,
  // then preload system primary + strategic (A) + income (C) + staged (F).
  useEffect(() => { setCompareIds([]) }, [eventId])
  useEffect(() => {
    if (!plans.length) return
    setCompareIds(prev => {
      if (prev.length) return prev // never fight manual toggling
      const ids: number[] = []
      for (const arch of [rec?.primary?.archetype, 'A', 'C', 'F']) {
        const p = arch ? plans.find((x: any) => x.plan_archetype === arch) : null
        if (p && !ids.includes(p.id)) ids.push(p.id)
      }
      return ids.slice(0, 4)
    })
  }, [eventId, plans.length, rec?.primary?.archetype]) // eslint-disable-line

  const refreshQuotes = async () => {
    setActionMsg('Refreshing quotes + recomputing plans…')
    try {
      const r = await fetch('/api/v2/deploy/recompute', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_id: eventId }),
      })
      const j = await r.json()
      setActionMsg(j?.ok === false ? `Refresh failed: ${j.error}` : 'Quotes refreshed — replans generated.')
      plansRes.refetch(); exportRes.refetch(); book.refetch()
    } catch (e) { setActionMsg(`Refresh failed: ${e}`) }
  }
  const refreshOneQuote = async (sym: string) => {
    setActionMsg(`Refreshing ${sym}…`)
    try {
      const r = await fetch(`/api/v2/watchlist/${sym}/refresh`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      setActionMsg(r.ok ? `${sym} quote refreshed. Recompute plans to reprice entries.` : `${sym} refresh failed`)
    } catch (e) { setActionMsg(`${sym} refresh failed: ${e}`) }
  }

  // Part G — plan-quality gate: composite score alone is never enough.
  // Legacy fallback only — the server readiness state machine is authoritative.
  const planReadiness = (p: any) => {
    const missing: string[] = []
    if (!(p.legs?.length)) missing.push('legs')
    // Per-plan staleness: one stale leg in ANOTHER archetype must not gate this plan.
    if ((p.legs || []).some((l: any) => l.price_stale && !l.is_reserve)) missing.push('fresh quotes')
    if (!p.hermes_narrative && !p.advantages?.length) missing.push('PM memo')
    if (p.oversight_status !== 'pass' && p.oversight_status !== 'pending') missing.push('oversight (failed)')
    if ((eventRow?.warnings || []).some((w: string) => w.startsWith('quarantined_test_fills'))) missing.push('P0 cleanup pending')
    if (!eventRow?.settled) missing.push('settlement verification')
    return missing
  }

  // Server readiness first (defect 1/23) — the UI never upgrades a plan the
  // server holds back. Fallback for old rows keeps the legacy checks PLUS an
  // oversight-pending gate on major events (> $25k proceeds).
  const readinessOf = (p: any): { state: string; reasons: string[]; operator_ready: boolean; display: string } => {
    if (p?.readiness?.state) {
      return {
        state: p.readiness.state,
        reasons: p.readiness.reasons || [],
        operator_ready: !!p.readiness.operator_ready,
        display: p.readiness.display || String(p.readiness.state).replace(/_/g, ' '),
      }
    }
    const missing = planReadiness(p)
    const majorEvent = (eventRow?.proceeds_usd ?? 0) > 25_000
    const oversightPassed = p?.oversight_status === 'pass' || p?.oversight_status === 'passed'
    if (majorEvent && !oversightPassed && !missing.includes('oversight (failed)')) missing.push('oversight pending')
    return missing.length
      ? { state: missing.includes('oversight pending') ? 'OVERSIGHT_PENDING' : 'DATA_INCOMPLETE',
          reasons: missing, operator_ready: false,
          display: missing.includes('oversight pending') && missing.length === 1
            ? 'ANALYTICS READY — OVERSIGHT PENDING'
            : `NOT OPERATOR-READY: needs ${missing.join(', ')}` }
      : { state: 'OPERATOR_READY', reasons: [], operator_ready: true, display: 'OPERATOR-READY' }
  }
  const readinessTone = (state: string) =>
    ['OPERATOR_READY', 'OPERATOR_SELECTED', 'OPERATOR_LOCKED'].includes(state) ? BB.green
      : ['ANALYTICS_READY', 'OVERSIGHT_PENDING'].includes(state) ? BB.amberAlt
        : BB.red // OVERSIGHT_FAILED / QUOTES_STALE / DATA_INCOMPLETE / unknown
  const nextActionFor = (p: any): string => {
    const r = readinessOf(p)
    if (r.state === 'QUOTES_STALE' || r.reasons.some(x => /stale|fresh quotes/i.test(x))) return 'Refresh quotes'
    if (r.state === 'OVERSIGHT_PENDING' || r.reasons.some(x => /oversight pending/i.test(x))) return 'Run oversight'
    if (r.state === 'OVERSIGHT_FAILED') return 'Review oversight findings'
    if (r.operator_ready) return 'Review comparison, approve plan for operator implementation review'
    return r.reasons.length ? `Resolve: ${r.reasons.join(', ')}` : 'Review plan readiness'
  }
  // Four capital fields (OVR-P0-TARGET-VS-CURRENT-ACTION). NEVER sum
  // executable_at_current_quote_usd with staged_limit_order_usd — they are two
  // valuations of the SAME legs (the old addition double-counted proceeds).
  const planUltimateTarget = (p: any): number | null =>
    p?.financials?.executable_at_current_quote_usd ?? null
  const planImplementNow = (p: any): number | null =>
    p?.financials?.implement_now_usd ?? null
  const planPendingStages = (p: any): number | null =>
    p?.financials?.pending_future_stages_usd ?? null
  const planUncommittedCash = (p: any): number | null =>
    p?.financials?.uncommitted_cash_usd ?? null
  const meaningOf = (p: any, key: string): string | undefined =>
    p?.financials?.amount_meanings?.[key]
  // Sign-aware dollar delta (income baselines, OVR-P0-INCOME-DELTA-BASELINE)
  const signed$ = (v: number | null | undefined): string =>
    v == null ? '—' : v < 0 ? `−${fmt$(Math.abs(v))}` : `+${fmt$(v)}`
  // Two-axis plan labels: implementation cadence vs destination portfolio.
  const policyPill = (p: any) => {
    const pol = p?.implementation_policy
    if (pol === 'staged') return <Pill text={`STAGED → destination Plan ${p?.destination_archetype ?? '?'}`} color={BB.blue} title="Implementation cadence is staged; the destination portfolio is another archetype" />
    if (pol === 'hold') return <Pill text="HOLD" color={BB.text3} title="No purchases — capital stays parked" />
    if (pol) return <Pill text="IMMEDIATE" color={BB.green} title="Single-pass implementation at current quotes" />
    return null
  }
  const policyText = (p: any): string => {
    const pol = p?.implementation_policy
    if (pol === 'staged') return `STAGED → destination Plan ${p?.destination_archetype ?? '?'}`
    if (pol === 'hold') return 'HOLD'
    return pol ? 'IMMEDIATE' : '—'
  }
  const planIncomeOf = (p: any): number | null =>
    p?.plan_income?.expected_annual_income_usd
      ?? ((p?.legs || []).reduce((s: number, l: any) =>
        s + ((l.target_dollars && l.expected_yield_pct) ? l.target_dollars * l.expected_yield_pct / 100 : 0), 0) || null)

  // Tie banner (recommendation.decisive === false) — DECISION + PLAN COMPARISON.
  const tieBanner = rec && rec.decisive === false ? (
    <div style={{
      border: `1px solid ${BB.amberAlt}`, background: BB.amberDim, borderRadius: 6,
      padding: '10px 14px', fontSize: t.body, color: BB.amberAlt, fontWeight: 700, marginBottom: t.gap,
    }}>
      NO DECISIVE WINNER — {rec.tie_policy || 'plans are within the tie band; operator judgment decides.'}
    </div>
  ) : null

  // Capital ledger banner (OVR-P0-CAPITAL-POOL-OVERCLAIM) — the selected event
  // is claiming capital that older open events already claim.
  const awaitingCapital = eventRow?.capital_status === 'awaiting_capital'
  const awaitingCapitalBanner = awaitingCapital ? (
    <div style={{
      border: `1px solid ${BB.red}`, background: BB.redDim, borderRadius: 6,
      padding: '10px 14px', fontSize: t.body, color: BB.red, fontWeight: 700, marginBottom: t.gap,
    }}>
      AWAITING CAPITAL — open events claim more than account cash; resolve older events or pool capital.
    </div>
  ) : null

  // Reserve-leg detail (Plan Lab + Entries RESERVE): vehicle, shares, ER, sweep cash.
  const reserveDetail = (p: any) => {
    const legs = (p?.legs || []).filter((l: any) => l.is_reserve
      && (l.reserve_vehicle_dollars != null || l.reserve_cash_unswept_usd != null || l.target_shares != null || l.implementation_required || l.note))
    if (!legs.length) return null
    return legs.map((l: any, i: number) => (
      <div key={l.ticker || i} style={{ fontSize: t.body, color: BB.text2, marginTop: 6, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <b style={{ color: BB.blue, fontSize: t.label }}>RESERVE</b>
        <span style={{ fontFamily: BB.mono, color: BB.text0 }}>
          {l.ticker || '—'} {l.target_shares ?? '—'} sh @ {l.current_price != null ? `$${num(l.current_price)}` : '—'}
          {' '}(ER {l.expense_ratio_pct != null ? num(l.expense_ratio_pct, 2) : '—'}%)
          {' '}+ {fmt$(l.reserve_cash_unswept_usd ?? 0)} sweep cash
        </span>
        {l.implementation_required && <Pill text="RESERVE REQUIRES PURCHASE" color={BB.amberAlt} title="The reserve vehicle is not held yet — parking the reserve is itself a purchase" />}
        {l.note && <span style={{ fontSize: t.label, color: BB.text3 }}>{l.note}</span>}
      </div>
    ))
  }

  // ── sticky context bar ─────────────────────────────────────────────────────
  const contextBar = (
    <div style={{
      position: 'sticky', top: 0, zIndex: 30, background: BB.bg,
      borderBottom: `1px solid ${BB.border}`, padding: `10px 0`, marginBottom: t.gap,
      display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center',
    }}>
      <span style={{ fontSize: t.title, fontWeight: 800, color: BB.amber, letterSpacing: 0.5 }}>REDEPLOY DESK</span>
      <Pill text="ADVISORY ONLY — NO BROKER EXECUTION" color={BB.blue} />
      <select
        value={eventId ?? ''}
        onChange={e => setEvent(e.target.value ? Number(e.target.value) : null)}
        style={{
          background: BB.bgRowAlt, color: BB.text0, border: `1px solid ${BB.border}`,
          borderRadius: 4, padding: '6px 10px', fontSize: t.body, fontFamily: BB.mono, maxWidth: 420,
        }}>
        <option value="">— select sale event —</option>
        {bookRows.filter(r => r.completion_status !== 'dismissed').map(r => (
          <option key={r.event_id} value={r.event_id}>
            #{r.event_id} {r.symbol} {fmt$(r.proceeds_usd)} · {r.sold_at} · {r.completion_status}
          </option>
        ))}
      </select>
      {planLabel && <Pill text={planLabel} color={BB.amber} title="Selected plan — carried across every tab" />}
      {eventRow && (
        <>
          <Pill text={eventRow.settled ? 'SETTLED' : eventRow.reconciliation_status.toUpperCase()}
                color={eventRow.settled ? BB.green : BB.amberAlt} />
          {eventRow.quote_age_minutes != null && (
            <Pill text={`quotes ${Math.round(eventRow.quote_age_minutes)}m old`}
                  color={eventRow.quote_age_minutes > 30 ? BB.red : BB.green} />
          )}
          {(eventRow.warnings || []).map((w: string) => (
            <Pill key={w} text={w.replace(/_/g, ' ')} color={w.startsWith('quarantined') ? BB.red : BB.amberAlt} />
          ))}
        </>
      )}
      <span style={{ flex: 1 }} />
      <button onClick={() => setDensity(d => d === 'compact' ? 'comfortable' : 'compact')}
        style={{ background: BB.bgRowAlt, color: BB.text2, border: `1px solid ${BB.border}`, borderRadius: 4, padding: '5px 12px', fontSize: t.label, cursor: 'pointer' }}>
        density: {density}
      </button>
      <span style={{ fontSize: t.label, color: BB.text3 }}>book as of {ago(book.data?.as_of)}</span>
      {eventId && plans.length > 0 && (() => {
        // Persistent decision header (Phase 17) — the operator's standing answer
        // to "what is the system's lean and what do I do next", on every tab.
        const focus = selectedPlan ?? primaryPlan ?? plans[0]
        const fr = readinessOf(focus)
        const isFocusPrimary = focus === primaryPlan
        const ultimate = planUltimateTarget(focus) ?? (isFocusPrimary ? rec?.primary?.ultimate_target_usd : null)
        const implementNow = planImplementNow(focus) ?? (isFocusPrimary ? rec?.primary?.implement_now_usd : null)
        const pendingStages = planPendingStages(focus) ?? (isFocusPrimary ? rec?.primary?.pending_future_stages_usd : null)
        const uncommitted = planUncommittedCash(focus) ?? (isFocusPrimary ? rec?.primary?.uncommitted_cash_usd : null)
        const reserve = focus?.financials?.reserve_usd ?? focus?.reserve_usd
          ?? (isFocusPrimary ? rec?.primary?.reserve_usd : null)
        const residual = focus?.financials?.whole_share_residual_usd
        const income = planIncomeOf(focus)
        const pi = focus?.plan_income
        const kv = (k: string, v: any, color: string = BB.text0, title?: string) => (
          <span key={k} title={title} style={{ fontSize: t.label, color: BB.text3, whiteSpace: 'nowrap', borderBottom: title ? `1px dotted ${BB.text3}` : undefined }}>
            {k} <b style={{ color, fontFamily: BB.mono }}>{v}</b>
          </span>
        )
        return (
          <div style={{
            flexBasis: '100%', display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'center',
            borderTop: `1px solid ${BB.borderSubtle}`, paddingTop: 6, marginTop: 2,
          }}>
            {kv('SYSTEM LEAN', rec?.primary?.archetype ? `Plan ${rec.primary.archetype}` : '—', BB.amber)}
            {kv('OPERATOR', selectedPlan ? `Plan ${selectedPlan.plan_archetype}` : 'none')}
            <Pill text={fr.display} color={readinessTone(fr.state)} title={(fr.reasons || []).join('; ') || undefined} />
            {kv('ULTIMATE TARGET', fmt$(ultimate), BB.text0, meaningOf(focus, 'executable_at_current_quote_usd'))}
            {kv('IMPLEMENT NOW', fmt$(implementNow), BB.green, meaningOf(focus, 'implement_now_usd'))}
            {kv('PENDING STAGES', fmt$(pendingStages), BB.amberAlt, meaningOf(focus, 'pending_future_stages_usd'))}
            {kv('UNCOMMITTED CASH', fmt$(uncommitted), BB.text0, meaningOf(focus, 'uncommitted_cash_usd'))}
            {kv('RESERVE', fmt$(reserve), BB.text0, residual != null ? `whole-share residual ${fmt$(residual)}` : meaningOf(focus, 'reserve_usd'))}
            {kv('PLAN INCOME', income == null ? '—' : `${fmt$(income)}/yr`, BB.green)}
            {kv('VS POST-SALE', signed$(pi?.income_vs_post_sale_usd), toneFor(pi?.income_vs_post_sale_usd), pi?.income_vs_post_sale_note)}
            {pi?.income_vs_pre_sale_usd != null
              ? kv('VS PRE-SALE', signed$(pi.income_vs_pre_sale_usd), toneFor(pi.income_vs_pre_sale_usd), pi?.income_vs_pre_sale_note)
              : kv('VS PRE-SALE', '—', BB.text3, 'basis unavailable')}
            {kv('NEXT', nextActionFor(focus), BB.text1)}
            {awaitingCapital && <div style={{ flexBasis: '100%' }}>{awaitingCapitalBanner}</div>}
          </div>
        )
      })()}
    </div>
  )

  const tabBar = (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: t.gap }}>
      {TABS.map(name => {
        const needsEvent = name !== 'CAPITAL BOOK'
        const disabled = needsEvent && !eventId
        return (
          <button key={name} disabled={disabled} onClick={() => setTab(name)}
            style={{
              padding: '8px 14px', fontSize: t.label, fontWeight: 700, letterSpacing: 0.6,
              fontFamily: BB.mono, cursor: disabled ? 'not-allowed' : 'pointer', borderRadius: 4,
              border: `1px solid ${tab === name ? BB.amber : BB.border}`,
              background: tab === name ? BB.amberDim : BB.bgRowAlt,
              color: disabled ? BB.text3 : tab === name ? BB.amber : BB.text2, opacity: disabled ? 0.45 : 1,
            }}>{name}</button>
        )
      })}
    </div>
  )

  // ── TAB: CAPITAL BOOK ──────────────────────────────────────────────────────
  const capitalBook = (
    <>
      <Section title="Portfolio capital-allocation book" t={t}
        right={<span style={{ fontSize: t.label, color: BB.text3 }}>{book.data?.row_count ?? '…'} historical sale events · production evidence only</span>}>
        <div style={{ display: 'flex', gap: t.gap, flexWrap: 'wrap', marginBottom: t.gap }}>
          {[
            ['Historical proceeds', fmt$(book.data?.totals?.proceeds)],
            ['Deployed (recorded fills)', fmt$(book.data?.totals?.deployed)],
            ['Unallocated (open events)', fmt$(book.data?.totals?.unallocated)],
            ['Open events', String(book.data?.totals?.open_events ?? '—')],
          ].map(([k, v]) => (
            <div key={k as string} style={{ border: `1px solid ${BB.border}`, borderRadius: 6, padding: 14, minWidth: 200 }}>
              <div style={{ fontSize: t.label, color: BB.text3, marginBottom: 4 }}>{k}</div>
              <div style={{ fontSize: 22, fontWeight: 800, color: BB.text0, fontFamily: BB.mono }}>{v}</div>
            </div>
          ))}
        </div>
        {book.data?.account_capital && Object.keys(book.data.account_capital).length > 0 && (
          <div style={{ marginBottom: t.gap }}>
            <div style={{ fontSize: t.label, color: BB.text3, fontWeight: 700, letterSpacing: 0.5, marginBottom: 6 }}>Account capital</div>
            <div style={{ display: 'flex', gap: t.gap, flexWrap: 'wrap' }}>
              {Object.entries(book.data.account_capital).map(([acct, c]: [string, any]) => (
                <div key={acct} style={{ border: `1px solid ${c.overclaimed ? BB.red : BB.border}`, borderRadius: 6, padding: 12, minWidth: 280 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 4 }}>
                    <span style={{ fontSize: t.body, fontWeight: 700, color: BB.text0 }}>{acct.replace(/_/g, ' ')}</span>
                    {c.overclaimed && <Pill text={`OVERCLAIMED ${fmt$(c.overclaim_usd)}`} color={BB.red} title="Open events claim more than this account's visible cash" />}
                  </div>
                  <div style={{ fontSize: t.body, color: BB.text2 }}>
                    visible cash <b style={{ color: BB.text0, fontFamily: BB.mono }}>{fmt$(c.visible_cash_usd)}</b>
                    {' '}· open claims <b style={{ color: BB.amberAlt, fontFamily: BB.mono }}>{fmt$(c.open_claims_usd)}</b>
                    {' '}· allocatable <b style={{ color: (c.currently_allocatable_usd ?? 0) > 0 ? BB.green : BB.amberAlt, fontFamily: BB.mono }}>{fmt$(c.currently_allocatable_usd)}</b>
                  </div>
                </div>
              ))}
            </div>
            {book.data?.capital_note && (
              <div style={{ fontSize: t.label, color: BB.text3, marginTop: 6 }}>{book.data.capital_note}</div>
            )}
          </div>
        )}
        <DataTable t={t} rows={bookRows} empty={book.loading ? 'Loading…' : 'No events.'} cols={[
          { key: 'event_id', label: '#', render: r => (
            <button onClick={() => setEvent(r.event_id, 'DECISION')}
              style={{ background: 'none', border: 'none', color: BB.amber, cursor: 'pointer', fontFamily: BB.mono, fontSize: t.table, textDecoration: 'underline' }}>
              {r.event_id}
            </button>) },
          { key: 'symbol', label: 'SOLD' },
          { key: 'account', label: 'ACCOUNT', render: r => (r.account || '—').replace(/_/g, ' ') },
          { key: 'sold_at', label: 'DATE' },
          { key: 'proceeds_usd', label: 'PROCEEDS', align: 'right', render: r => fmt$(r.proceeds_usd) },
          { key: 'deployable_usd', label: 'DEPLOYABLE', align: 'right', render: r => fmt$(r.deployable_usd) },
          { key: 'deployed_usd', label: 'DEPLOYED', align: 'right', render: r => fmt$(r.deployed_usd) },
          { key: 'remaining_usd', label: 'REMAINING', align: 'right', render: r => (
            <span style={{ color: r.remaining_usd > 0 && r.completion_status !== 'dismissed' ? BB.amberAlt : BB.text2 }}>{fmt$(r.remaining_usd)}</span>) },
          { key: 'restoration_pct', label: 'RESTORED', align: 'right', render: r => pct(r.restoration_pct, 1) },
          { key: 'redeployed_pl_usd', label: 'P/L', align: 'right', render: r => (
            <span style={{ color: toneFor(r.redeployed_pl_usd) }}>{r.redeployed_pl_usd == null ? '—' : fmt$(r.redeployed_pl_usd)}</span>) },
          { key: 'plan_selected', label: 'PLAN', render: r => r.plan_selected || (r.plan_count ? `${r.plan_count} drafts` : '—') },
          { key: 'plan_age_days', label: 'PLAN AGE', align: 'right', render: r => r.plan_age_days == null ? '—' : `${r.plan_age_days}d` },
          { key: 'capital_status', label: 'CAPITAL', render: r => r.capital_status
            ? <Pill text={String(r.capital_status).replace(/_/g, ' ').toUpperCase()} color={
                r.capital_status === 'awaiting_capital' ? BB.red
                  : r.capital_status === 'reserved_locked' ? BB.green
                    : r.capital_status === 'reserved_selected' ? BB.blue : BB.text2} />
            : <span style={{ color: BB.text3 }}>—</span> },
          { key: 'completion_status', label: 'STATUS', render: r => (
            <Pill text={r.completion_status.toUpperCase()} color={
              r.completion_status === 'completed' ? BB.green : r.completion_status === 'partial' ? BB.blue
              : r.completion_status === 'dismissed' ? BB.text3 : BB.amberAlt} />) },
          { key: 'warnings', label: 'WARNINGS', render: r => (r.warnings || []).length
            ? <span style={{ color: BB.amberAlt, fontSize: t.label }}>{r.warnings.join(' · ').replace(/_/g, ' ')}</span>
            : <span style={{ color: BB.text3 }}>—</span> },
        ]} />
      </Section>
      <Section title="Capital pools by account" t={t}>
        <div style={{ display: 'flex', gap: t.gap, flexWrap: 'wrap' }}>
          {(pools.data?.pools ?? []).map((p: any) => (
            <div key={p.account} style={{ border: `1px solid ${BB.border}`, borderRadius: 6, padding: 14, minWidth: 280 }}>
              <div style={{ fontSize: t.body, fontWeight: 700, color: BB.text0, marginBottom: 6 }}>{p.account.replace(/_/g, ' ')}</div>
              <div style={{ fontSize: t.body, color: BB.text2 }}>visible cash <b style={{ color: BB.text0 }}>{fmt$(p.visible_cash_usd)}</b></div>
              <div style={{ fontSize: t.body, color: BB.text2 }}>open-event remaining <b style={{ color: BB.amberAlt }}>{fmt$(p.open_event_remaining_usd)}</b></div>
              {(p.open_events || []).map((e: any) => (
                <div key={e.event_id} style={{ fontSize: t.label, color: BB.text3, marginTop: 4 }}>
                  #{e.event_id} {e.symbol} · {fmt$(e.remaining_usd)} · {e.sold_at}
                </div>
              ))}
            </div>
          ))}
        </div>
      </Section>
    </>
  )

  // ── TAB: EVENT OVERVIEW ────────────────────────────────────────────────────
  const exposure = analysis.data?.analysis?.exposure_loss || analysis.data?.exposure_loss
  const eventOverview = eventRow && (
    <>
      <Section title={`${eventRow.symbol} sale — ${fmt$(eventRow.proceeds_usd)} · ${eventRow.sold_at}`} t={t}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(230px,1fr))', gap: t.gap }}>
          {[
            ['Account', (eventRow.account || '—').replace(/_/g, ' ')],
            ['Net proceeds', fmt$(eventRow.net_proceeds_usd ?? eventRow.proceeds_usd)],
            ['Deployable', fmt$(eventRow.deployable_usd)],
            ['Reconciliation', eventRow.reconciliation_status],
            ['Operator status', eventRow.operator_status],
            ['Instrument', eventRow.instrument_type || '—'],
            ['Deployed so far', fmt$(eventRow.deployed_usd)],
            ['Remaining', fmt$(eventRow.remaining_usd)],
          ].map(([k, v]) => (
            <div key={k as string} style={{ border: `1px solid ${BB.border}`, borderRadius: 6, padding: 12 }}>
              <div style={{ fontSize: t.label, color: BB.text3 }}>{k}</div>
              <div style={{ fontSize: t.body + 1, color: BB.text0, fontFamily: BB.mono, marginTop: 3 }}>{v}</div>
            </div>
          ))}
        </div>
      </Section>
      {exposure?.sectors?.length ? (
        <Section title="Exposure removed by the sale (look-through)" t={t}>
          <DataTable t={t} rows={exposure.sectors.slice(0, 12)} cols={[
            { key: 'sector', label: 'SECTOR' },
            { key: 'usd_removed', label: 'REMOVED', align: 'right', render: r => fmt$(r.usd_removed) },
            { key: 'pct_of_sale', label: '% OF SALE', align: 'right', render: r => pct(r.pct_of_sale ?? r.weight_pct, 1) },
          ]} />
        </Section>
      ) : null}
      {(monitoring.data?.reeval_flags?.length ?? 0) > 0 && (
        <Section title="Status flags" t={t}>
          {monitoring.data.reeval_flags.map((f: any) => (
            <div key={f.code} style={{ fontSize: t.body, color: BB.text1, padding: '6px 0' }}>
              <b style={{ color: BB.amber }}>{f.code}</b> — {f.message}
            </div>
          ))}
        </Section>
      )}
    </>
  )

  // ── TAB: DECISION (Phase 17 — decision-first landing) ─────────────────────
  const decisionTab = (() => {
    if (!eventId) return <div style={{ fontSize: t.body, color: BB.text3 }}>Select a sale event.</div>
    if (plansRes.loading && !plans.length) return <div style={{ fontSize: t.body, color: BB.text3 }}>Loading plans…</div>
    if (!plans.length) return <div style={{ fontSize: t.body, color: BB.text3 }}>No plans generated for this event yet — use REFRESH QUOTES + RECOMPUTE in PLAN LAB.</div>
    if (!rec?.primary) {
      return (
        <Section title="Decision" t={t}>
          <div style={{ fontSize: t.body, color: BB.text3 }}>
            No system recommendation is persisted for this event yet (plans predate the decision engine).
            Recompute plans in PLAN LAB to generate a scored recommendation, or compare plans manually in PLAN COMPARISON.
          </div>
        </Section>
      )
    }
    const prim = rec.primary
    const primHoldings = (primaryPlan?.legs || []).filter((l: any) => !l.is_reserve)
    // Scorecard: primary first, then next-best by total decision score (top 3)
    const scored = plans.filter((p: any) => p.decision_score?.dimensions)
    const scorePlans = [
      ...(primaryPlan && scored.includes(primaryPlan) ? [primaryPlan] : []),
      ...scored.filter((p: any) => p !== primaryPlan)
        .sort((a: any, b: any) => (b.decision_score?.total_score ?? 0) - (a.decision_score?.total_score ?? 0)),
    ].slice(0, 3)
    const dimKeys: string[] = Object.keys(scorePlans[0]?.decision_score?.dimensions || {})
    const changeTriggers: string[] = primaryPlan?.tranche_triggers?.length ? primaryPlan.tranche_triggers
      : primaryPlan?.entry_triggers?.length ? primaryPlan.entry_triggers
        : (memoStruct?.sections?.change_conditions || [])
    const nextAction = memoStruct?.sections?.next_operator_action
      || nextActionFor(selectedPlan ?? primaryPlan ?? plans[0])
    const primPolicy = prim.implementation_policy ?? primaryPlan?.implementation_policy
    const primDest = prim.destination_archetype ?? primaryPlan?.destination_archetype
    const primPi = primaryPlan?.plan_income
    return (
      <>
        {tieBanner}
        {awaitingCapitalBanner}
        <Section title="Recommended lean" t={t}
          right={primaryPlan && <Pill text={readinessOf(primaryPlan).display} color={readinessTone(readinessOf(primaryPlan).state)} />}>
          <div style={{ fontSize: t.title - 4, fontWeight: 800, color: BB.amber, marginBottom: 10 }}>
            {primPolicy === 'staged' && primDest
              ? `Plan ${primDest} destination · staged implementation (Plan ${prim.archetype} cadence)`
              : `Plan ${prim.archetype}`} — {prim.objective || primaryPlan?.objective || ''}
          </div>
          <div style={{ display: 'flex', gap: t.gap, flexWrap: 'wrap', marginBottom: t.gap }}>
            {([
              ['Ultimate target', fmt$(prim.ultimate_target_usd ?? planUltimateTarget(primaryPlan)), BB.text0, meaningOf(primaryPlan, 'executable_at_current_quote_usd')],
              ['Implement now', fmt$(prim.implement_now_usd ?? planImplementNow(primaryPlan)), BB.green, meaningOf(primaryPlan, 'implement_now_usd')],
              ['Pending stages', fmt$(prim.pending_future_stages_usd ?? planPendingStages(primaryPlan)), BB.amberAlt, meaningOf(primaryPlan, 'pending_future_stages_usd')],
              ['Uncommitted cash', fmt$(prim.uncommitted_cash_usd ?? planUncommittedCash(primaryPlan)), BB.text0, meaningOf(primaryPlan, 'uncommitted_cash_usd')],
              ['Reserve', fmt$(prim.reserve_usd), BB.text0, `whole-share residual ${fmt$(prim.residual_usd ?? primaryPlan?.financials?.whole_share_residual_usd)}`],
              ['Quant score', prim.total_score != null ? num(prim.total_score, 1) : '—', BB.blue, undefined],
            ] as [string, string, string, string | undefined][]).map(([k, v, c, tip]) => (
              <div key={k} title={tip} style={{ border: `1px solid ${BB.border}`, borderRadius: 6, padding: 14, minWidth: 190, cursor: tip ? 'help' : undefined }}>
                <div style={{ fontSize: t.label, color: BB.text3, marginBottom: 4, borderBottom: tip ? `1px dotted ${BB.text3}` : undefined, display: 'inline-block' }}>{k}</div>
                <div style={{ fontSize: 22, fontWeight: 800, color: c, fontFamily: BB.mono }}>{v}</div>
              </div>
            ))}
          </div>
          {primPi && (
            <div style={{ fontSize: t.body, color: BB.text2, marginBottom: t.gap }}>
              plan income <b style={{ color: BB.green, fontFamily: BB.mono }}>{fmt$(primPi.expected_annual_income_usd)}/yr</b>
              {' '}· vs post-sale <b title={primPi.income_vs_post_sale_note} style={{ color: toneFor(primPi.income_vs_post_sale_usd), fontFamily: BB.mono }}>{signed$(primPi.income_vs_post_sale_usd)}</b>
              {' '}· vs pre-sale {primPi.income_vs_pre_sale_usd != null
                ? <b title={primPi.income_vs_pre_sale_note} style={{ color: toneFor(primPi.income_vs_pre_sale_usd), fontFamily: BB.mono }}>{signed$(primPi.income_vs_pre_sale_usd)}</b>
                : <span title="basis unavailable" style={{ color: BB.text3, borderBottom: `1px dotted ${BB.text3}`, cursor: 'help' }}>—</span>}
            </div>
          )}
          {primHoldings.length > 0 && (
            <DataTable t={t} rows={primHoldings} cols={[
              { key: 'ticker', label: 'TICKER', render: (l: any) => <b style={{ color: BB.text0 }}>{l.ticker}</b> },
              { key: 'role', label: 'ROLE', render: (l: any) => String(l.role || l.dual_label || '—').replace(/_/g, ' ') },
              { key: 'target_dollars', label: 'DOLLARS', align: 'right', render: (l: any) => fmt$(l.target_dollars) },
              { key: 'target_shares', label: 'SHARES', align: 'right', render: (l: any) => l.target_shares ?? '—' },
            ]} />
          )}
        </Section>
        {(prim.reasons || []).length > 0 && (
          <Section title="Why this is recommended" t={t}>
            {prim.reasons.map((r: string, i: number) => (
              <div key={i} style={{ fontSize: t.body, color: BB.text1, padding: '4px 0' }}>• {r}</div>
            ))}
            {prim.strongest && <div style={{ fontSize: t.body, color: BB.green, marginTop: 6 }}>Strongest dimension: {String(prim.strongest?.note ?? prim.strongest).replace(/_/g, ' ')}</div>}
            {prim.weakest && <div style={{ fontSize: t.body, color: BB.amberAlt }}>Weakest dimension: {String(prim.weakest?.note ?? prim.weakest).replace(/_/g, ' ')}</div>}
          </Section>
        )}
        {((rec.alternatives || []).length > 0 || (rec.do_not_choose || []).length > 0) && (
          <Section title="Why not the other plans" t={t}>
            {(rec.alternatives || []).map((a: any) => (
              <div key={a.archetype} style={{ fontSize: t.body, color: BB.text2, padding: '5px 0' }}>
                <b style={{ color: BB.text0 }}>Plan {a.archetype}</b>{a.objective ? ` — ${a.objective}` : ''}
                {a.total_score != null && <span style={{ color: BB.blue }}> · score {num(a.total_score, 1)}</span>}
                {a.gap_to_primary != null && <span style={{ color: BB.text3 }}> ({num(a.gap_to_primary, 1)} behind primary)</span>}
                {a.choose_when && <div style={{ color: BB.text3, marginLeft: 14 }}>choose when: {a.choose_when}</div>}
              </div>
            ))}
            {(rec.do_not_choose || []).map((d: any) => (
              <div key={d.archetype} style={{ fontSize: t.body, color: BB.text2, padding: '5px 0' }}>
                <b style={{ color: BB.red }}>Do not choose Plan {d.archetype}</b> — {d.reason}
              </div>
            ))}
          </Section>
        )}
        {dimKeys.length > 0 && (
          <Section title="Decision scorecard" t={t}
            right={<span style={{ fontSize: t.label, color: BB.text3 }}>weighted composite — weights shown; score is one input, never the sole selector</span>}>
            <DataTable t={t} rows={[
              ...dimKeys.map(k => {
                const w = scorePlans[0]?.decision_score?.dimensions?.[k]?.weight ?? rec.weights?.[k]
                const row: any = {
                  dim: k.replace(/_/g, ' '),
                  weight: w == null ? '—' : pct(w <= 1 ? w * 100 : w, 0), // tolerate fraction or percent scale
                }
                scorePlans.forEach((p: any) => {
                  const d = p.decision_score?.dimensions?.[k]
                  row[`p${p.id}`] = d ? { text: `${num(d.raw, 1)} → ${num(d.weighted, 1)}`, note: d.note } : { text: '—' }
                })
                return row
              }),
              {
                dim: 'TOTAL', weight: '',
                ...Object.fromEntries(scorePlans.map((p: any) =>
                  [`p${p.id}`, { text: num(p.decision_score?.total_score, 1), total: true }])),
              },
            ]} cols={[
              { key: 'dim', label: 'DIMENSION' },
              { key: 'weight', label: 'WEIGHT', align: 'right' },
              ...scorePlans.map((p: any) => ({
                key: `p${p.id}`, label: `PLAN ${p.plan_archetype}${p === primaryPlan ? ' ★' : ''} (raw → wtd)`, align: 'right' as const,
                render: (r: any) => {
                  const c = r[`p${p.id}`] || {}
                  return <span title={c.note} style={{ fontFamily: BB.mono, fontWeight: c.total ? 800 : 400, color: c.total ? BB.amber : BB.text1, borderBottom: c.note ? `1px dotted ${BB.text3}` : undefined }}>{c.text ?? '—'}</span>
                },
              })),
              { key: 'note', label: 'NOTE (PRIMARY)', render: (r: any) => (
                <span style={{ fontSize: t.label, color: BB.text3, whiteSpace: 'normal' }}>{r[`p${scorePlans[0]?.id}`]?.note || ''}</span>) },
            ]} />
          </Section>
        )}
        {changeTriggers.length > 0 && (
          <Section title="What could change the decision" t={t}>
            {changeTriggers.map((c: string, i: number) => (
              <div key={i} style={{ fontSize: t.body, color: BB.text2, padding: '4px 0' }}>• {c}</div>
            ))}
          </Section>
        )}
        <Section title="Next operator action" t={t}>
          <div style={{ fontSize: t.body + 1, color: BB.text0 }}>{nextAction}</div>
          <div style={{ fontSize: t.label, color: BB.text3, marginTop: 6 }}>
            Advisory only — the operator approves a plan for operator implementation review, never execution approval.
          </div>
        </Section>
      </>
    )
  })()

  // ── TAB: PLANS ─────────────────────────────────────────────────────────────
  // Selection evidence (defects 15/20): why this ticker won its role, and who lost.
  const evidenceText = (l: any) => {
    const ev = l.selection_evidence
    if (!ev) return ''
    const alts = (ev.alternatives || [])
      .map((a: any) => `${a.symbol}${a.score != null ? ` (${num(a.score, 1)})` : ''}${a.why_lost ? ` — ${a.why_lost}` : ''}`)
      .join('\n  ')
    return [
      `role: ${ev.role ?? l.role ?? '—'}`,
      `method: ${ev.method ?? '—'}`,
      `score: ${ev.score != null ? num(ev.score, 1) : '—'} · margin: ${ev.selection_margin != null ? num(ev.selection_margin, 1) : '—'}`,
      ev.eligible_pool != null ? `eligible pool: ${ev.eligible_pool}` : '',
      alts ? `alternatives:\n  ${alts}` : 'alternatives: none recorded',
    ].filter(Boolean).join('\n')
  }
  const legCols = (p: any) => [
    { key: 'ticker', label: 'TICKER', render: (l: any) => <b style={{ color: BB.text0 }}>{l.is_reserve ? 'RESERVE' : l.ticker}</b> },
    { key: 'role', label: 'ROLE', render: (l: any) => (l.role || l.dual_label || (l.is_reserve ? 'cash reserve' : '—')).replace(/_/g, ' ') },
    { key: 'allocation_pct_of_net', label: 'ALLOC %', align: 'right' as const, render: (l: any) => pct(l.allocation_pct_of_net ?? l.allocation_pct, 1) },
    { key: 'target_dollars', label: 'TARGET $', align: 'right' as const, render: (l: any) => fmt$(l.target_dollars) },
    { key: 'target_shares', label: 'SHARES', align: 'right' as const, render: (l: any) => l.target_shares ?? '—' },
    { key: 'expected_yield_pct', label: 'YIELD', align: 'right' as const, render: (l: any) => pct(l.expected_yield_pct, 2) },
    { key: 'income', label: 'INCOME/YR', align: 'right' as const, render: (l: any) =>
      l.expected_yield_pct != null && l.target_dollars ? fmt$(l.target_dollars * l.expected_yield_pct / 100) : '—' },
    { key: 'current_price', label: 'PRICE', align: 'right' as const, render: (l: any) => l.current_price ? `$${num(l.current_price)}` : '—' },
    { key: 'price_as_of', label: 'QUOTE AGE', render: (l: any) => (
      <span style={{ color: l.price_stale ? BB.red : BB.text3, fontSize: t.label }}>{l.price_stale ? 'STALE · ' : ''}{ago(l.price_as_of)}</span>) },
    { key: 'why', label: 'WHY', render: (l: any) => l.selection_evidence
      ? <span title={evidenceText(l)} style={{ fontSize: t.label, color: BB.blue, borderBottom: `1px dotted ${BB.blue}`, cursor: 'help' }}>why {l.ticker}</span>
      : <span style={{ color: BB.text3 }}>—</span> },
  ]

  // Financials reconciliation line (defect 2 / OVR-P0-DEPLOY-NOW-DOUBLE-COUNT):
  // executable + reserve + residual = total, matching financials fields directly.
  // executable_at_current_quote_usd and staged_limit_order_usd are two valuations
  // of the SAME legs — they are NEVER summed.
  const reconLine = (p: any) => {
    const f = p?.financials
    if (!f) return null
    const meaning = (k: string) => f.amount_meanings?.[k]
    const term = (label: string, v: any, key: string) => (
      <span title={meaning(key)} style={{ borderBottom: meaning(key) ? `1px dotted ${BB.text3}` : undefined, cursor: meaning(key) ? 'help' : undefined }}>
        {label} <b style={{ color: BB.text0, fontFamily: BB.mono }}>{fmt$(v)}</b>
      </span>
    )
    return (
      <>
        <div style={{ fontSize: t.body, color: BB.text2, marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
          {term('Executable', f.executable_at_current_quote_usd, 'executable_at_current_quote_usd')} +
          {term('Reserve', f.reserve_usd, 'reserve_usd')} +
          {term('Residual', f.whole_share_residual_usd, 'whole_share_residual_usd')} =
          {term('Deployable', f.deployable_cash_usd, 'deployable_cash_usd')}
          {f.reconciles
            ? <b style={{ color: BB.green }}>✓ reconciles</b>
            : <b style={{ color: BB.red }}>✗ gap {fmt$(f.reconciliation_gap_usd)}</b>}
        </div>
        {(f.implement_now_usd != null || f.pending_future_stages_usd != null || f.uncommitted_cash_usd != null) && (
          <div style={{ fontSize: t.body, color: BB.text2, marginTop: 4, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
            {term('Implement now', f.implement_now_usd, 'implement_now_usd')} ·
            {term('pending stages', f.pending_future_stages_usd, 'pending_future_stages_usd')} ·
            {term('uncommitted', f.uncommitted_cash_usd, 'uncommitted_cash_usd')}
          </div>
        )}
      </>
    )
  }

  const plansTab = (
    <>
      <Section title={`Institutional plans — ${plans.length} archetypes (latest version)`} t={t}
        right={<div style={{ display: 'flex', gap: 8 }}>
          <button onClick={refreshQuotes} style={{ background: BB.blueDim, color: BB.blue, border: `1px solid ${BB.blue}55`, borderRadius: 4, padding: '6px 12px', fontSize: t.label, fontWeight: 700, cursor: 'pointer' }}>
            REFRESH QUOTES + RECOMPUTE
          </button>
          {compareIds.length >= 2 && <Pill text={`comparing ${compareIds.length}`} color={BB.blue} />}
        </div>}>
        {actionMsg && <div style={{ fontSize: t.body, color: BB.amberAlt, marginBottom: 8 }}>{actionMsg}</div>}
        {plans.map((p: any) => {
          const ready = readinessOf(p)
          const isSel = p.id === selectedPlanId
          return (
            <div key={p.id} style={{
              border: `1px solid ${isSel ? BB.amber : BB.border}`, borderRadius: 8,
              padding: t.gap, marginBottom: t.gap, background: isSel ? 'rgba(255,176,0,0.04)' : BB.bgRow,
            }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBottom: 8 }}>
                <span style={{ fontSize: t.subheading, fontWeight: 800, color: BB.text0 }}>
                  Plan {p.plan_archetype} v{p.version} — {p.objective || p.plan_type}
                </span>
                {/* Distinct governance chips (defect 23) — primary/selected/locked never conflated */}
                {rec?.primary?.archetype === p.plan_archetype && <Pill text="SYSTEM PRIMARY" color={BB.amber} title="The system's recommended lean" />}
                {p.id === selectedPlanId && <Pill text="OPERATOR SELECTED" color={BB.blue} title="Your working selection — carried across tabs" />}
                {p.id === lockedPlanId && <Pill text="OPERATOR LOCKED" color={BB.green} title="Locked by the operator" />}
                {p.id === topQuantPlanId && <Pill text="HIGHEST QUANT RANK" color={BB.text3} title="Top decision score — one input, never the sole selector" />}
                {p.decision_score?.total_score != null
                  ? <Pill text={`score ${num(p.decision_score.total_score, 1)}`} color={BB.blue} title="Weighted decision score — one component, never the sole selector" />
                  : <Pill text={`confidence ${num(p.confidence, 1)}`} color={BB.blue} title="One decision component — never the sole selector" />}
                {policyPill(p)}
                {(p.concentration_violations || []).length > 0 && (
                  <Pill text="CONCENTRATION CAPS VIOLATED" color={BB.red} title={(p.concentration_violations || []).join('; ')} />
                )}
                {p.oversight_status && <Pill text={`oversight: ${p.oversight_status}`}
                  color={p.oversight_status === 'pass' || p.oversight_status === 'passed' ? BB.green : p.oversight_status === 'failed' ? BB.red : BB.text3} />}
                <Pill text={ready.display} color={readinessTone(ready.state)} title={(ready.reasons || []).join('; ') || undefined} />
                <span style={{ flex: 1 }} />
                <label style={{ fontSize: t.label, color: BB.text2, display: 'flex', gap: 6, alignItems: 'center' }}>
                  <input type="checkbox" checked={compareIds.includes(p.id)}
                    onChange={e => setCompareIds(ids => e.target.checked ? [...ids, p.id].slice(-4) : ids.filter(i => i !== p.id))} />
                  compare
                </label>
                <button onClick={() => selectPlan(p.id)} style={{
                  background: isSel ? BB.amber : BB.bgRowAlt, color: isSel ? '#000' : BB.amber,
                  border: `1px solid ${BB.amber}`, borderRadius: 4, padding: '6px 14px',
                  fontSize: t.label, fontWeight: 800, cursor: 'pointer',
                }}>{isSel ? 'SELECTED' : 'SELECT PLAN'}</button>
              </div>
              {(p.concentration_violations || []).length > 0 && (
                <div style={{ fontSize: t.body, color: BB.red, marginBottom: 6 }}>
                  {(p.concentration_violations || []).map((v: string, i: number) => (
                    <div key={i}>• {v}</div>
                  ))}
                </div>
              )}
              <DataTable t={t} rows={p.legs || []} empty="No legs — plan is not operator-ready." cols={legCols(p)} />
              {reconLine(p)}
              {reserveDetail(p)}
              {p.plan_income && (
                <div style={{ fontSize: t.body, color: BB.text2, marginTop: 4 }}>
                  expected income <b style={{ color: BB.green, fontFamily: BB.mono }}>{fmt$(p.plan_income.expected_annual_income_usd)}/yr</b>
                  {' '}· vs post-sale <b title={p.plan_income.income_vs_post_sale_note} style={{ color: toneFor(p.plan_income.income_vs_post_sale_usd), fontFamily: BB.mono }}>{signed$(p.plan_income.income_vs_post_sale_usd)}</b>
                  {' '}· vs pre-sale {p.plan_income.income_vs_pre_sale_usd != null
                    ? <b title={p.plan_income.income_vs_pre_sale_note} style={{ color: toneFor(p.plan_income.income_vs_pre_sale_usd), fontFamily: BB.mono }}>{signed$(p.plan_income.income_vs_pre_sale_usd)}</b>
                    : <span title="basis unavailable" style={{ color: BB.text3, borderBottom: `1px dotted ${BB.text3}`, cursor: 'help' }}>—</span>}
                  {' '}· whole-plan yield <b style={{ color: BB.text0 }}>{pct(p.plan_income.whole_plan_yield_pct)}</b>
                  {p.plan_income.invested_sleeve_yield_pct != null && <> · invested-sleeve yield <b style={{ color: BB.text0 }}>{pct(p.plan_income.invested_sleeve_yield_pct)}</b></>}
                  {p.plan_income.calculation_as_of && <span style={{ fontSize: t.label, color: BB.text3 }}> · as of {String(p.plan_income.calculation_as_of).slice(0, 10)}</span>}
                </div>
              )}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: t.gap, marginTop: 10 }}>
                {p.advantages?.length ? <div>
                  <div style={{ fontSize: t.label, color: BB.green, fontWeight: 700, marginBottom: 4 }}>ADVANTAGES</div>
                  {p.advantages.slice(0, 4).map((a: string, i: number) => <div key={i} style={{ fontSize: t.body, color: BB.text2 }}>• {a}</div>)}
                </div> : null}
                {p.compromises?.length ? <div>
                  <div style={{ fontSize: t.label, color: BB.amberAlt, fontWeight: 700, marginBottom: 4 }}>COMPROMISES</div>
                  {p.compromises.slice(0, 4).map((a: string, i: number) => <div key={i} style={{ fontSize: t.body, color: BB.text2 }}>• {a}</div>)}
                </div> : null}
                {p.risks?.length ? <div>
                  <div style={{ fontSize: t.label, color: BB.red, fontWeight: 700, marginBottom: 4 }}>RISKS</div>
                  {p.risks.slice(0, 4).map((a: string, i: number) => <div key={i} style={{ fontSize: t.body, color: BB.text2 }}>• {a}</div>)}
                </div> : null}
              </div>
            </div>
          )
        })}
      </Section>
    </>
  )

  // ── TAB: PLAN COMPARISON ───────────────────────────────────────────────────
  const staleLegs = (p: any) => (p?.legs || []).filter((l: any) => l.price_stale && !l.is_reserve).length
  const cmpCell = (fn: (p: any) => string) =>
    Object.fromEntries(compareIds.map(id => [String(id), fn(plans.find(p => p.id === id) || {})]))
  const comparisonTab = compareIds.length >= 2 ? (
    <Section title={`Plan comparison — ${compareIds.length} plans (differences, not merely winners)`} t={t}>
      {tieBanner}
      {awaitingCapitalBanner}
      {rec?.primary && (
        <div style={{ border: `1px solid ${BB.border}`, borderRadius: 8, padding: t.gap, marginBottom: t.gap }}>
          <div style={{ fontSize: t.subheading, fontWeight: 800, color: BB.amber, marginBottom: 6 }}>
            SYSTEM LEAN: {(rec.primary.implementation_policy ?? primaryPlan?.implementation_policy) === 'staged' && (rec.primary.destination_archetype ?? primaryPlan?.destination_archetype)
              ? `Plan ${rec.primary.destination_archetype ?? primaryPlan?.destination_archetype} destination · staged implementation (Plan ${rec.primary.archetype} cadence)`
              : `Plan ${rec.primary.archetype}`}{rec.primary.objective ? ` — ${rec.primary.objective}` : ''}
          </div>
          {(rec.primary.reasons || []).slice(0, 3).map((r: string, i: number) => (
            <div key={i} style={{ fontSize: t.body, color: BB.text1, padding: '2px 0' }}>• {r}</div>
          ))}
          {(rec.alternatives || []).slice(0, 1).map((a: any) => (
            <div key={a.archetype} style={{ fontSize: t.body, color: BB.text2, marginTop: 8 }}>
              <b style={{ color: BB.blue }}>RUNNER-UP:</b> Plan {a.archetype}
              {a.total_score != null && <span style={{ color: BB.text3 }}> (score {num(a.total_score, 1)})</span>}
              {a.choose_when && <> — choose when: {a.choose_when}</>}
            </div>
          ))}
          {(rec.do_not_choose || []).length > 0 && (
            <div style={{ fontSize: t.body, color: BB.text2, marginTop: 6 }}>
              <b style={{ color: BB.red }}>DO NOT USE:</b>{' '}
              {rec.do_not_choose.map((d: any) => `Plan ${d.archetype} — ${d.reason}`).join(' · ')}
            </div>
          )}
        </div>
      )}
      <DataTable t={t} rows={[
        { k: 'Objective', ...cmpCell(p => p.objective || '—') },
        { k: 'Readiness', ...cmpCell(p => readinessOf(p).display) },
        { k: 'Decision score', ...cmpCell(p => p.decision_score?.total_score != null ? num(p.decision_score.total_score, 1) : '—') },
        { k: 'Implementation', ...cmpCell(p => policyText(p)) },
        { k: 'Ultimate target $', ...cmpCell(p => fmt$(planUltimateTarget(p) ?? p.total_deployable_usd)) },
        { k: 'Implement now $', ...cmpCell(p => fmt$(planImplementNow(p))) },
        { k: 'Pending stages $', ...cmpCell(p => fmt$(planPendingStages(p))) },
        { k: 'Uncommitted cash $', ...cmpCell(p => fmt$(planUncommittedCash(p))) },
        { k: 'Reserve $', ...cmpCell(p => fmt$(p.financials?.reserve_usd ?? p.reserve_usd)) },
        { k: 'Whole-share residual $', ...cmpCell(p => fmt$(p.financials?.whole_share_residual_usd)) },
        { k: 'Deployment % of net', ...cmpCell(p => pct(p.deploy_pct_of_net, 1)) },
        { k: 'Deployable $', ...cmpCell(p => fmt$(p.financials?.deployable_cash_usd ?? p.total_deployable_usd)) },
        { k: 'Legs', ...cmpCell(p => (p.legs || []).map((l: any) => l.is_reserve ? 'RSV' : l.ticker).join(' + ') || '—') },
        { k: 'Leg count', ...cmpCell(p => String((p.legs || []).filter((l: any) => !l.is_reserve).length)) },
        { k: 'Whole-plan yield', ...cmpCell(p => pct(p.plan_income?.whole_plan_yield_pct)) },
        { k: 'Expected income /yr', ...cmpCell(p => planIncomeOf(p) ? fmt$(planIncomeOf(p)) : '—') },
        { k: 'Income vs post-sale', ...cmpCell(p => signed$(p.plan_income?.income_vs_post_sale_usd)) },
        { k: 'Income vs pre-sale', ...cmpCell(p => p.plan_income?.income_vs_pre_sale_usd != null ? signed$(p.plan_income.income_vs_pre_sale_usd) : 'basis unavailable') },
        { k: 'Concentration', ...cmpCell(p => (p.concentration_violations || []).length
          ? `CAPS VIOLATED: ${(p.concentration_violations || []).join('; ')}` : 'within caps') },
        { k: 'Oversight', ...cmpCell(p => p.oversight_status || '—') },
        { k: 'Stale-quote legs', ...cmpCell(p => String(staleLegs(p))) },
        { k: 'Principal advantage', ...cmpCell(p => p.advantages?.[0] || '—') },
        { k: 'Principal compromise', ...cmpCell(p => p.compromises?.[0] || '—') },
        { k: 'Principal risk', ...cmpCell(p => p.risks?.[0] || '—') },
      ]} cols={[
        { key: 'k', label: '' },
        ...compareIds.map(id => {
          const p = plans.find(x => x.id === id)
          return { key: String(id), label: `PLAN ${p?.plan_archetype} v${p?.version}` }
        }),
      ]} />
    </Section>
  ) : (
    <Section title="Plan comparison" t={t}>
      <div style={{ fontSize: t.body, color: BB.text3 }}>
        Select 2–4 plans to compare — tick the <b style={{ color: BB.text1 }}>compare</b> checkbox on plan
        cards in PLAN LAB. Comparison highlights differences (deployment, reserve, income, readiness,
        principal advantage/compromise/risk), not merely a winner.
      </div>
    </Section>
  )

  // ── TAB: PRO-FORMA ─────────────────────────────────────────────────────────
  const pf = proForma.data
  const proFormaTab = pf?.ok ? (
    <>
      <Section title={`Three-state pro-forma — ${planLabel}`} t={t}
        right={<span style={{ fontSize: t.label, color: BB.text3 }}>modeled {fmt$(pf.modeled_deploy_usd)} whole-share · as of {ago(pf.as_of)}</span>}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: t.gap }}>
          {(['pre_sale', 'post_sale', 'post_plan'] as const).map(k => {
            const s = pf.states[k]
            return (
              <div key={k} style={{ border: `1px solid ${k === 'post_plan' ? BB.amber : BB.border}`, borderRadius: 8, padding: t.gap }}>
                <div style={{ fontSize: t.subheading, fontWeight: 800, color: k === 'post_plan' ? BB.amber : BB.text0, marginBottom: 8 }}>
                  {k.replace('_', '-').toUpperCase()}
                </div>
                {[
                  ['Total', fmt$(s.total_usd)], ['Cash', `${fmt$(s.cash_usd)} (${pct(s.cash_pct, 1)})`],
                  ['Income /yr', fmt$(s.expected_annual_income_usd)], ['Income /mo', fmt$(s.expected_monthly_income_usd)],
                  ['Yield', pct(s.portfolio_yield_pct)], ['Weighted ER', s.weighted_expense_ratio_pct == null ? '—' : `${s.weighted_expense_ratio_pct}% (${pct(s.expense_ratio_coverage_pct, 0)} cov)`],
                  ['Beta (1Y)', s.weighted_beta_1y == null ? '—' : `${s.weighted_beta_1y} (${pct(s.beta_coverage_pct, 0)} cov)`],
                  ['Top-10 concentration', pct(s.concentration_top10_pct, 1)],
                ].map(([kk, vv]) => (
                  <div key={kk as string} style={{ display: 'flex', justifyContent: 'space-between', fontSize: t.body, padding: '3px 0' }}>
                    <span style={{ color: BB.text3 }}>{kk}</span><span style={{ color: BB.text0, fontFamily: BB.mono }}>{vv}</span>
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      </Section>
      <Section title="Sector restoration (pct-pts of portfolio, look-through)" t={t}>
        <DataTable t={t} rows={pf.deltas.sectors} cols={[
          { key: 'sector', label: 'SECTOR' },
          { key: 'pre_pct', label: 'PRE-SALE', align: 'right', render: r => pct(r.pre_pct, 2) },
          { key: 'post_sale_pct', label: 'POST-SALE', align: 'right', render: r => pct(r.post_sale_pct, 2) },
          { key: 'post_plan_pct', label: 'POST-PLAN', align: 'right', render: r => pct(r.post_plan_pct, 2) },
          { key: 'lost_pct_pts', label: 'LOST', align: 'right', render: r => <span style={{ color: toneFor(-r.lost_pct_pts) }}>{num(r.lost_pct_pts)}</span> },
          { key: 'restored_pct_pts', label: 'RESTORED', align: 'right', render: r => <span style={{ color: toneFor(r.restored_pct_pts) }}>{num(r.restored_pct_pts)}</span> },
          { key: 'restoration_ratio', label: 'RATIO', align: 'right', render: r => r.restoration_ratio == null ? '—' : `${(r.restoration_ratio * 100).toFixed(0)}%` },
        ]} />
      </Section>
      <Section title="Scalar deltas" t={t}>
        <DataTable t={t} rows={Object.entries(pf.deltas).filter(([k]) => k !== 'sectors').map(([k, v]: any) => ({ metric: k.replace(/_/g, ' '), ...v }))} cols={[
          { key: 'metric', label: 'METRIC' },
          { key: 'pre', label: 'PRE-SALE', align: 'right', render: r => num(r.pre) },
          { key: 'post_sale', label: 'POST-SALE', align: 'right', render: r => num(r.post_sale) },
          { key: 'post_plan', label: 'POST-PLAN', align: 'right', render: r => num(r.post_plan) },
          { key: 'plan_delta', label: 'PLAN Δ', align: 'right', render: r => <span style={{ color: toneFor(r.plan_delta) }}>{num(r.plan_delta)}</span> },
        ]} />
      </Section>
      {pf.remaining_gaps?.length ? (
        <Section title="Remaining gaps after this plan" t={t}>
          {pf.remaining_gaps.map((g: any) => (
            <div key={g.sector} style={{ fontSize: t.body, color: BB.amberAlt, padding: '5px 0' }}>⚠ {g.statement}</div>
          ))}
        </Section>
      ) : <div style={{ fontSize: t.body, color: BB.green }}>No sector gap above threshold remains after this plan.</div>}
    </>
  ) : <div style={{ fontSize: t.body, color: BB.text3 }}>{proForma.loading ? 'Computing three-state pro-forma…' : (pf?.error || 'Select an event and plan.')}</div>

  // ── TAB: LOOK-THROUGH ──────────────────────────────────────────────────────
  // OVR-P0-OVERLAP-FALSE-NEGATIVE part 2: the wrapper-decontaminated contract
  // (underlying_issuers / direct_positions / unresolved_lookthrough) renders as
  // three separate tables; legacy top_issuers is a labeled fallback only.
  const postPlanState = pf?.ok ? pf.states.post_plan : null
  const hasIssuerContract = Array.isArray(postPlanState?.underlying_issuers)
  const lookThroughTab = pf?.ok ? (
    <>
      {hasIssuerContract ? (
        <>
          <Section title="Underlying economic issuers" t={t}
            right={<span style={{ fontSize: t.label, color: BB.text3 }}>wrapper-free — funds are resolved to their underlying issuers</span>}>
            <DataTable t={t} rows={postPlanState.underlying_issuers} empty="No resolved issuer exposure." cols={[
              { key: 'issuer', label: 'ISSUER', render: r => <b style={{ color: BB.text0 }}>{r.issuer}</b> },
              { key: 'direct_usd', label: 'DIRECT', align: 'right', render: r => fmt$(r.direct_usd) },
              { key: 'indirect_usd', label: 'INDIRECT (VIA FUNDS)', align: 'right', render: r => fmt$(r.indirect_usd) },
              { key: 'total_usd', label: 'TOTAL', align: 'right', render: r => fmt$(r.total_usd) },
              { key: 'pct_of_portfolio', label: '% PORTFOLIO', align: 'right', render: r => pct(r.pct_of_portfolio, 2) },
              { key: 'source_funds', label: 'SOURCE FUNDS', render: r => (r.source_funds || []).join(', ') || '—' },
              { key: 'coverage_note', label: 'COVERAGE', render: r => (
                <span style={{ fontSize: t.label, color: BB.text3, whiteSpace: 'normal' }}>{r.coverage_note || '—'}</span>) },
            ]} />
          </Section>
          <Section title="Direct positions" t={t}
            right={<span style={{ fontSize: t.label, color: BB.text3 }}>as held — fund wrappers flagged, not treated as issuers</span>}>
            <DataTable t={t} rows={postPlanState.direct_positions || []} empty="No direct positions." cols={[
              { key: 'symbol', label: 'SYMBOL', render: r => <b style={{ color: BB.text0 }}>{r.symbol}</b> },
              { key: 'dollars', label: 'DOLLARS', align: 'right', render: r => fmt$(r.dollars) },
              { key: 'is_fund_wrapper', label: 'TYPE', render: r => r.is_fund_wrapper
                ? <Pill text="FUND WRAPPER" color={BB.blue} title="A fund, not an issuer — its economics live in the underlying-issuers table" />
                : <span style={{ color: BB.text2 }}>single issuer</span> },
            ]} />
          </Section>
          <Section title="Unresolved look-through" t={t}
            right={<span style={{ fontSize: t.label, color: BB.text3 }}>fund dollars not resolvable to issuers — honest gap, not zero</span>}>
            <DataTable t={t} rows={postPlanState.unresolved_lookthrough || []} empty="All fund positions fully resolved to underlying issuers." cols={[
              { key: 'symbol', label: 'SYMBOL', render: r => <b style={{ color: BB.text0 }}>{r.symbol}</b> },
              { key: 'dollars', label: 'DOLLARS', align: 'right', render: r => fmt$(r.dollars) },
              { key: 'lookthrough_coverage_pct', label: 'COVERAGE', align: 'right', render: r => pct(r.lookthrough_coverage_pct, 0) },
              { key: 'note', label: 'NOTE', render: r => <span style={{ whiteSpace: 'normal', color: BB.text3 }}>{r.note || '—'}</span> },
            ]} />
          </Section>
        </>
      ) : (
        <Section title="Post-plan issuer exposure (legacy — may contain fund wrappers)" t={t}>
          <DataTable t={t} rows={postPlanState?.top_issuers || []} cols={[
            { key: 'symbol', label: 'ISSUER' },
            { key: 'usd', label: 'EXPOSURE', align: 'right', render: r => fmt$(r.usd) },
            { key: 'pct', label: '% PORTFOLIO', align: 'right', render: r => pct(r.pct, 2) },
          ]} />
        </Section>
      )}
      <Section title="Per-leg underlying holdings (from fund data)" t={t}>
        {(candidates.data?.candidates ?? [])
          .filter((c: any) => (selectedPlan?.legs || []).some((l: any) => l.ticker === c.symbol))
          .map((c: any) => (
            <div key={c.symbol} style={{ marginBottom: t.gap }}>
              <div style={{ fontSize: t.body, fontWeight: 700, color: BB.text0, marginBottom: 6 }}>
                {c.symbol} — {c.name || ''} {c.held_overlap_usd > 0 && <span style={{ color: BB.amberAlt }}>(already held: {fmt$(c.held_overlap_usd)})</span>}
              </div>
              {c.lookthrough_top_holdings
                ? <div style={{ fontSize: t.table, color: BB.text2, fontFamily: BB.mono }}>
                    {c.lookthrough_top_holdings.map((h: any) => `${h.ticker} ${num(h.weight ?? h.weight_pct, 1)}%`).join(' · ')}
                  </div>
                : <div style={{ fontSize: t.label, color: BB.text3 }}>no look-through data cached for this instrument</div>}
            </div>
          ))}
      </Section>
      <Section title="Data gaps (honest)" t={t}>
        {(pf.states.post_plan.data_gaps || []).slice(0, 20).map((g: string) => (
          <div key={g} style={{ fontSize: t.label, color: BB.text3 }}>• {g}</div>
        ))}
      </Section>
    </>
  ) : <div style={{ fontSize: t.body, color: BB.text3 }}>Select an event and plan first.</div>

  // ── TAB: PERFORMANCE ───────────────────────────────────────────────────────
  const perf = performance.data
  // Whole-plan vs invested-sleeve summary blocks (new contract), falling back
  // to the legacy plan_weighted block — backend agents land concurrently.
  const perfBlocks: { label: string; b: any }[] = perf?.ok ? [
    ...(perf.whole_plan ? [{ label: 'Whole plan (incl. reserve)', b: perf.whole_plan }] : []),
    ...(perf.invested_sleeve ? [{ label: 'Invested sleeve (risk legs only)', b: perf.invested_sleeve }] : []),
    ...(!perf.whole_plan && !perf.invested_sleeve && perf.plan_weighted
      ? [{ label: 'Plan (dollar-weighted)', b: perf.plan_weighted }] : []),
  ] : []
  const performanceTab = perf?.ok ? (
    <>
      <Section title={`Performance — ${planLabel}`} t={t}
        right={<span style={{ fontSize: t.label, color: BB.text3 }}>total return where distributions cached; price return otherwise — see basis per leg</span>}>
        <DataTable t={t} rows={[
          ...perfBlocks.map(({ label, b }) => ({
            k: label,
            ...Object.fromEntries(['1Y', '3Y', '5Y'].map(w => {
              const v = b?.return_windows?.[w]
              return [w, v ? `${v.pct}%${v.coverage_pct_of_allocation != null ? ` (${v.coverage_pct_of_allocation}% cov)` : ''}` : '—']
            })),
            yield: pct(b?.yield_pct),
            er: b?.expense_ratio_pct == null ? '—' : `${b.expense_ratio_pct}%`,
            income: fmt$(b?.expected_annual_income_usd),
          })),
          ...(perf.sold_reference ? [{
            k: `${perf.sold_reference.symbol} (sold)`,
            ...Object.fromEntries(['1Y', '3Y', '5Y'].map(w => {
              const b = perf.sold_reference.profile?.total_return || perf.sold_reference.profile?.price_return || {}
              return [w, b[w]?.pct != null ? `${b[w].pct}%` : '—']
            })),
            yield: pct(perf.sold_reference.trailing_yield_pct),
            er: perf.sold_reference.expense_ratio_pct == null ? '—' : `${perf.sold_reference.expense_ratio_pct}%`,
            income: '—',
          }] : []),
        ]} cols={[
          { key: 'k', label: '' }, { key: '1Y', label: '1Y', align: 'right' }, { key: '3Y', label: '3Y', align: 'right' },
          { key: '5Y', label: '5Y', align: 'right' }, { key: 'yield', label: 'YIELD', align: 'right' },
          { key: 'er', label: 'FEES', align: 'right' }, { key: 'income', label: 'INCOME/YR', align: 'right' },
        ]} />
      </Section>
      {(perf.scenarios || []).length > 0 && (
        <Section title="Scenario matrix — plan-level, dollar-weighted" t={t}
          right={<span style={{ fontSize: t.label, color: BB.text3 }} title={perf.scenario_kinds_note}>hover a row for methodology · unavailable ≠ zero</span>}>
          <DataTable t={t} rows={perf.scenarios} cols={[
            { key: 'label', label: 'SCENARIO', render: (s: any) => <span title={s.label}>{String(s.label || s.key || '').split('—')[0].trim()}</span> },
            { key: 'kind', label: 'KIND', render: (s: any) => (
              <span style={{ fontSize: t.label, color:
                s.kind === 'HISTORICAL_OBSERVATION' ? BB.text2
                  : s.kind === 'STATISTICAL_BAND' ? BB.blue
                    : s.kind === 'DETERMINISTIC_SHOCK' ? BB.amberAlt
                      : s.kind === 'UNAVAILABLE' ? BB.text3 : BB.blue }}>{s.kind}</span>) },
            { key: 'plan_pct', label: 'PLAN IMPACT', align: 'right', render: (s: any) => (
              // unavailable is never rendered as a number — 0% would be a lie
              <span title={s.note} style={{ color: s.unavailable ? BB.amberAlt : toneFor(s.plan_pct), fontFamily: BB.mono }}>
                {s.unavailable ? (s.note || 'UNAVAILABLE FOR RISKY LEGS') : `${s.plan_pct > 0 ? '+' : ''}${s.plan_pct}%`}
              </span>) },
            { key: 'coverage_pct_of_plan', label: 'COVERAGE', align: 'right', render: (s: any) => (
              <span title={s.risky_coverage_pct_of_invested != null ? `risky-leg coverage of invested sleeve: ${s.risky_coverage_pct_of_invested}%` : undefined}>
                {pct(s.coverage_pct_of_plan, 0)}
              </span>) },
            { key: 'label2', label: 'METHODOLOGY', render: (s: any) => (
              <span style={{ fontSize: t.label, color: BB.text3 }} title={s.date_range || undefined}>
                {(s.methodology || s.note || String(s.label || '').split('—').slice(1).join('—')).trim()}
              </span>) },
          ]} />
        </Section>
      )}
      <Section title="Per-leg detail" t={t}>
        {(perf.legs || []).filter((l: any) => l.symbol).map((l: any) => (
          <div key={l.symbol} style={{ border: `1px solid ${BB.border}`, borderRadius: 8, padding: t.gap, marginBottom: t.gap }}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
              <span style={{ fontSize: t.subheading, fontWeight: 800, color: BB.text0 }}>{l.symbol}</span>
              <Pill text={`${fmt$(l.target_dollars)} target`} color={BB.blue} />
              <Pill text={`yield ${pct(l.distribution_yield_pct)}`} color={BB.green} title={l.yield_basis} />
              {l.expense_ratio_pct != null && <Pill text={`ER ${l.expense_ratio_pct}%`} color={BB.text3} />}
              <span style={{ fontSize: t.label, color: BB.text3 }}>history {l.history_days}d from {l.history_start} · as of {l.as_of}</span>
            </div>
            <DataTable t={t} rows={[
              { basis: 'Price return', ...Object.fromEntries(Object.entries(l.price_return || {}).map(([w, v]: any) => [w, v?.pct != null ? `${v.pct}%` : '—'])) },
              ...(l.total_return ? [{ basis: 'Total return', ...Object.fromEntries(Object.entries(l.total_return).map(([w, v]: any) => [w, v?.pct != null ? `${v.pct}%` : '—'])) }] : []),
            ]} cols={[
              { key: 'basis', label: 'BASIS' },
              ...['1M', '3M', '6M', 'YTD', '1Y', '3Y', '5Y'].map(w => ({ key: w, label: w, align: 'right' as const })),
            ]} />
            <div style={{ display: 'flex', gap: t.gap, flexWrap: 'wrap', marginTop: 8, fontSize: t.body, color: BB.text2 }}>
              <span>vol(1Y) <b style={{ color: BB.text0 }}>{pct(l.volatility_1y_pct, 1)}</b></span>
              <span>max DD <b style={{ color: BB.red }}>{l.max_drawdown ? `${l.max_drawdown.pct}% (${l.max_drawdown.from} → ${l.max_drawdown.to})` : '—'}</b></span>
              <span>beta vs SPY <b style={{ color: BB.text0 }}>{num(l.beta_1y_vs_spy)}</b></span>
              {l.vs_sold?.windows && <span>vs {l.vs_sold.sold_symbol} 1Y <b style={{ color: toneFor(l.vs_sold.windows['1Y']?.excess_pct_pts) }}>{l.vs_sold.windows['1Y'] ? `${l.vs_sold.windows['1Y'].excess_pct_pts > 0 ? '+' : ''}${l.vs_sold.windows['1Y'].excess_pct_pts}pp` : '—'}</b></span>}
            </div>
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: t.label, color: BB.text3, fontWeight: 700, marginBottom: 4 }}>HISTORICAL STRESS (observations)</div>
              <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: t.body }}>
                {(l.stress || []).map((s: any) => (
                  <span key={s.key} title={s.label} style={{ color: s.history_available ? toneFor(s.pct) : BB.text3 }}>
                    {s.label.split('(')[0].trim()}: {s.history_available ? `${s.pct}%` : 'no history'}
                  </span>
                ))}
              </div>
            </div>
            {l.scenarios_1y_forecast && (
              <div style={{ marginTop: 6, fontSize: t.body, color: BB.text2 }}>
                <b style={{ color: BB.blue }}>FORECAST</b> ({l.scenarios_1y_forecast.basis}): bear {l.scenarios_1y_forecast.bear_pct}% · base {l.scenarios_1y_forecast.base_pct}% · bull {l.scenarios_1y_forecast.bull_pct}%
              </div>
            )}
            {l.monthly_returns_12m?.length ? (
              <DataTable t={t} rows={[Object.fromEntries(l.monthly_returns_12m.map((m: any) => [m.month, `${m.pct}%`]))]}
                cols={l.monthly_returns_12m.map((m: any) => ({ key: m.month, label: m.month.slice(2), align: 'right' as const }))} />
            ) : null}
            {l.annual_returns?.length ? (
              <div style={{ fontSize: t.body, color: BB.text2, marginTop: 6 }}>
                annual: {l.annual_returns.map((a: any) => `${a.year}${a.partial ? '*' : ''} ${a.pct}%`).join(' · ')} {l.annual_returns.some((a: any) => a.partial) && <span style={{ color: BB.text3 }}>(* partial year)</span>}
              </div>
            ) : null}
          </div>
        ))}
      </Section>
    </>
  ) : <div style={{ fontSize: t.body, color: BB.text3 }}>{performance.loading ? 'Computing performance…' : 'Select an event and plan first.'}</div>

  // ── TAB: ENTRIES (Phase 16 — operator workflow order) ─────────────────────
  const entriesLegs = selectedPlan?.legs || []
  const riskLegs = entriesLegs.filter((l: any) => !l.is_reserve)
  const legHasStages = (l: any) => [1, 2, 3].some(s => l[`stage_${s}_pct`])
  const implementNowRows = riskLegs.map((l: any) => legHasStages(l)
    ? { ticker: l.ticker, role: l.role || l.dual_label, shares: l.stage_1_shares, price: l.stage_1_price ?? l.preferred_entry, dollars: l.stage_1_dollars }
    : { ticker: l.ticker, role: l.role || l.dual_label, shares: l.target_shares, price: l.preferred_entry ?? l.current_price, dollars: l.target_dollars })
    .filter((r: any) => r.dollars || r.shares)
  const waitRows = riskLegs.flatMap((l: any) => [2, 3]
    .filter(s => l[`stage_${s}_pct`])
    .map(s => ({ ticker: l.ticker, stage: s, price: l[`stage_${s}_price`], shares: l[`stage_${s}_shares`], dollars: l[`stage_${s}_dollars`] })))
    .map((r: any, i: number) => ({
      ...r,
      trigger: (selectedPlan?.tranche_triggers || [])[i]
        || (r.price != null ? `price trigger $${num(r.price)}` : '—'),
    }))
  const selReadiness = selectedPlan ? readinessOf(selectedPlan) : null
  const subHead = (s: string, color: string = BB.text0) => (
    <div style={{ fontSize: t.subheading, fontWeight: 800, color, margin: `${t.gap}px 0 6px` }}>{s}</div>
  )
  const entriesTab = (
    <Section title={`Entry workflow — ${planLabel ?? 'no plan selected'}`} t={t}
      right={<button onClick={refreshQuotes} style={{ background: BB.blueDim, color: BB.blue, border: `1px solid ${BB.blue}55`, borderRadius: 4, padding: '6px 12px', fontSize: t.label, fontWeight: 700, cursor: 'pointer' }}>REFRESH ALL QUOTES</button>}>
      {actionMsg && <div style={{ fontSize: t.body, color: BB.amberAlt, marginBottom: 8 }}>{actionMsg}</div>}
      {!selectedPlan && <div style={{ fontSize: t.body, color: BB.text3 }}>Select a plan in PLAN LAB — entries are always shown in the context of their plan.</div>}
      {selectedPlan && (
        <>
          {subHead('IMPLEMENT NOW', BB.green)}
          <DataTable t={t} rows={implementNowRows} empty="No stage-1 tranche is priced yet." cols={[
            { key: 'ticker', label: 'TICKER', render: (r: any) => <b style={{ color: BB.text0 }}>{r.ticker}</b> },
            { key: 'role', label: 'ROLE', render: (r: any) => String(r.role || '—').replace(/_/g, ' ') },
            { key: 'shares', label: 'SHARES', align: 'right' },
            { key: 'price', label: 'TARGET PX', align: 'right', render: (r: any) => r.price != null ? `$${num(r.price)}` : '—' },
            { key: 'dollars', label: 'DOLLARS', align: 'right', render: (r: any) => fmt$(r.dollars) },
          ]} />
          {subHead('WAIT FOR STAGE 2/3', BB.amberAlt)}
          <DataTable t={t} rows={waitRows} empty="Single-tranche plan — nothing staged for later." cols={[
            { key: 'ticker', label: 'TICKER', render: (r: any) => <b style={{ color: BB.text0 }}>{r.ticker}</b> },
            { key: 'stage', label: 'STAGE', align: 'right', render: (r: any) => `Stage ${r.stage}` },
            { key: 'trigger', label: 'TRIGGER', render: (r: any) => <span style={{ color: BB.text2 }}>{r.trigger}</span> },
            { key: 'shares', label: 'SHARES', align: 'right' },
            { key: 'dollars', label: 'DOLLARS', align: 'right', render: (r: any) => fmt$(r.dollars) },
          ]} />
          {subHead('REMAINING RESERVE', BB.blue)}
          <div style={{ fontSize: t.body, color: BB.text2, marginBottom: 4 }}>
            <b style={{ color: BB.text0, fontFamily: BB.mono }}>{fmt$(selectedPlan.financials?.reserve_usd ?? selectedPlan.reserve_usd)}</b>
            {selectedPlan.reserve_vehicle && <> parked in <b style={{ color: BB.text0 }}>{selectedPlan.reserve_vehicle}</b></>}
            {selectedPlan.reserve_vehicle_yield_pct != null && <> yielding <b style={{ color: BB.green }}>{pct(selectedPlan.reserve_vehicle_yield_pct)}</b></>}
            {selectedPlan.revisit_date && <> · revisit <b style={{ color: BB.amberAlt }}>{String(selectedPlan.revisit_date).slice(0, 10)}</b></>}
          </div>
          {reserveDetail(selectedPlan)}
          {(selectedPlan.entry_triggers || []).map((tr: string, i: number) => (
            <div key={i} style={{ fontSize: t.body, color: BB.text3 }}>• deploy trigger: {tr}</div>
          ))}
          {selReadiness && !selReadiness.operator_ready && (
            <>
              {subHead('BLOCKERS', BB.red)}
              {(selReadiness.reasons.length ? selReadiness.reasons : [selReadiness.display]).map((r: string, i: number) => (
                <div key={i} style={{ fontSize: t.body, color: BB.red }}>• {r}</div>
              ))}
            </>
          )}
          {subHead('CURRENT ACTION', BB.amber)}
          <div style={{ fontSize: t.body + 1, color: BB.text0, marginBottom: t.gap }}>{nextActionFor(selectedPlan)}</div>
          {subHead('PER-LEG DETAIL')}
        </>
      )}
      {riskLegs.map((l: any) => (
        <div key={l.ticker} style={{ border: `1px solid ${BB.border}`, borderRadius: 8, padding: t.gap, marginBottom: t.gap }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
            <span style={{ fontSize: t.subheading, fontWeight: 800, color: BB.text0 }}>{l.ticker}</span>
            <Pill text={`${planLabel}`} color={BB.amber} />
            <Pill text={`${fmt$(l.target_dollars)} · ${pct(l.allocation_pct_of_net ?? l.allocation_pct, 1)} of net`} color={BB.blue} />
            <span style={{ fontSize: t.label, color: l.price_stale ? BB.red : BB.text3 }}>
              quote {l.current_price ? `$${num(l.current_price)}` : '—'} · {l.price_stale ? 'STALE · ' : ''}{ago(l.price_as_of)}
            </span>
            <button onClick={() => refreshOneQuote(l.ticker)} style={{ background: BB.bgRowAlt, color: BB.text2, border: `1px solid ${BB.border}`, borderRadius: 4, padding: '4px 10px', fontSize: t.label, cursor: 'pointer' }}>refresh</button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 10, fontSize: t.body, color: BB.text2 }}>
            <div>preferred entry <b style={{ color: BB.text0, fontFamily: BB.mono }}>{l.preferred_entry ? `$${num(l.preferred_entry)}` : '—'}</b></div>
            <div>acceptable range <b style={{ color: BB.text0, fontFamily: BB.mono }}>{l.entry_range_low && l.entry_range_high ? `$${num(l.entry_range_low)} – $${num(l.entry_range_high)}` : '—'}</b></div>
            <div>do not chase above <b style={{ color: BB.red, fontFamily: BB.mono }}>{l.do_not_chase ? `$${num(l.do_not_chase)}` : '—'}</b></div>
            <div>whole shares <b style={{ color: BB.text0, fontFamily: BB.mono }}>{l.target_shares ?? '—'}</b></div>
          </div>
          <DataTable t={t} rows={[1, 2, 3].map(s => ({
            stage: `Stage ${s}`, pct: l[`stage_${s}_pct`], price: l[`stage_${s}_price`],
            shares: l[`stage_${s}_shares`], dollars: l[`stage_${s}_dollars`],
          })).filter(r => r.pct)} empty="single-tranche entry" cols={[
            { key: 'stage', label: 'STAGE' },
            { key: 'pct', label: '% OF LEG', align: 'right', render: r => pct(r.pct, 0) },
            { key: 'price', label: 'TARGET PX', align: 'right', render: r => r.price ? `$${num(r.price)}` : '—' },
            { key: 'shares', label: 'SHARES', align: 'right' },
            { key: 'dollars', label: 'DOLLARS', align: 'right', render: r => fmt$(r.dollars) },
          ]} />
          {l.invalidation && <div style={{ fontSize: t.body, color: BB.amberAlt, marginTop: 6 }}>invalidation: {l.invalidation}</div>}
          {l.thesis && <div style={{ fontSize: t.body, color: BB.text3, marginTop: 4 }}>{l.thesis}</div>}
        </div>
      ))}
      {exportRes.data && exportRes.data.ok === false && (
        <div style={{ fontSize: t.body, color: BB.red, marginTop: 8 }}>
          export blocked: {exportRes.data.error} {exportRes.data.stale_symbols ? `(${exportRes.data.stale_symbols.join(', ')})` : ''} — use REFRESH ALL QUOTES above.
        </div>
      )}
    </Section>
  )

  // ── TAB: MONITORING ────────────────────────────────────────────────────────
  const mon = monitoring.data
  const monitoringTab = mon?.ok ? (
    <>
      <Section title="Recorded fills (production operator evidence only)" t={t}>
        <DataTable t={t} rows={mon.fills || []} empty="No production fills recorded — nothing has been deployed yet." cols={[
          { key: 'filled_at', label: 'FILLED', render: r => String(r.filled_at).slice(0, 16) },
          { key: 'ticker', label: 'TICKER' },
          { key: 'plan_archetype', label: 'PLAN', render: r => `${r.plan_archetype}${r.plan_version ? ` v${r.plan_version}` : ''}` },
          { key: 'stage', label: 'STAGE', align: 'right' },
          { key: 'filled_shares', label: 'SHARES', align: 'right' },
          { key: 'filled_price', label: 'PRICE', align: 'right', render: r => `$${num(r.filled_price)}` },
          { key: 'filled_dollars', label: 'DOLLARS', align: 'right', render: r => fmt$(r.filled_dollars) },
          { key: 'evidence_source', label: 'EVIDENCE', render: r => `${r.evidence_source}${r.evidence_note ? ` — ${r.evidence_note}` : ''}` },
        ]} />
        {(eventRow?.warnings || []).some((w: string) => w.startsWith('quarantined')) && (
          <div style={{ fontSize: t.body, color: BB.red, marginTop: 8 }}>
            ⚠ Quarantined test-fixture fills exist for this event (excluded from every number on this page).
            Deletion awaits operator approval — see docs/audits/REDEPLOY_FIXTURE_AUDIT_2026-07-13.md.
          </div>
        )}
      </Section>
      <Section title="Restoration vs exposure removed" t={t}>
        <DataTable t={t} rows={mon.restoration_metrics?.sectors || []} empty="No restoration yet." cols={[
          { key: 'sector', label: 'SECTOR' },
          { key: 'usd_removed', label: 'REMOVED', align: 'right', render: r => fmt$(r.usd_removed) },
          { key: 'usd_restored', label: 'RESTORED', align: 'right', render: r => fmt$(r.usd_restored) },
          { key: 'restoration_pct', label: '%', align: 'right', render: r => pct(r.restoration_pct, 1) },
        ]} />
        <div style={{ fontSize: t.body, color: BB.text2, marginTop: 6 }}>
          overall restoration <b style={{ color: BB.text0 }}>{pct(mon.restoration_metrics?.restoration_pct, 1)}</b> of {fmt$(mon.restoration_metrics?.total_removed_usd)} removed
        </div>
      </Section>
      <Section title="Re-evaluation triggers" t={t}>
        {(mon.reeval_flags || []).map((f: any) => (
          <div key={f.code} style={{ fontSize: t.body, color: BB.text1, padding: '4px 0' }}>
            <b style={{ color: BB.amber }}>{f.code}</b> — {f.message}
          </div>
        ))}
      </Section>
    </>
  ) : !eventId ? <div style={{ fontSize: t.body, color: BB.text3 }}>Select an event first.</div>
    : monitoring.loading ? <div style={{ fontSize: t.body, color: BB.text3 }}>Loading monitoring state…</div>
      : (
        <div style={{ fontSize: t.body, color: BB.red }}>
          Monitoring failed to load{mon?.error ? `: ${String(mon.error).slice(0, 200)}` : monitoring.error ? `: ${monitoring.error.slice(0, 200)}` : ''}.
          {' '}<button onClick={() => monitoring.refetch()} style={{ background: 'transparent', color: BB.amber, border: `1px solid ${BB.border}`, borderRadius: 4, padding: '2px 10px', fontSize: t.label, cursor: 'pointer' }}>RETRY</button>
        </div>
      )

  // ── TAB: REJECTED ──────────────────────────────────────────────────────────
  const rejectedTab = (
    <>
      <Section title="Rejected plan alternatives" t={t}>
        {(selectedPlan?.rejected_alternatives || []).length
          ? (selectedPlan.rejected_alternatives).map((r: any, i: number) => (
              <div key={i} style={{ fontSize: t.body, color: BB.text2, padding: '5px 0' }}>
                <b style={{ color: BB.text0 }}>{r.ticker || r.symbol || r.name || `alt ${i + 1}`}</b>
                {r.reason_code && <> <Pill text={String(r.reason_code).replace(/_/g, ' ')} color={BB.amberAlt} /></>}
                {' '}— {r.reason || r.note || 'no reason recorded'}
                {r.eligible_again_when && <div style={{ fontSize: t.label, color: BB.text3, marginLeft: 14 }}>eligible again when: {r.eligible_again_when}</div>}
              </div>
            ))
          : <div style={{ fontSize: t.body, color: BB.text3 }}>No rejected alternatives recorded on this plan.</div>}
      </Section>
      <Section title={`Candidate universe exclusions (${candidates.data?.rejected_count ?? '…'})`} t={t}
        right={<span style={{ fontSize: t.label, color: BB.text3 }}>universe {candidates.data?.universe_size ?? '…'} · accepted {candidates.data?.accepted_count ?? '…'}</span>}>
        <DataTable t={t} rows={candidates.data?.rejected ?? []} cols={[
          { key: 'symbol', label: 'SYMBOL' },
          { key: 'sources', label: 'SOURCES', render: r => (r.sources || []).join(', ') },
          { key: 'reason_code', label: 'CODE', render: r => r.reason_code
            ? <span style={{ color: BB.amberAlt, fontSize: t.label }}>{String(r.reason_code).replace(/_/g, ' ')}</span> : '—' },
          { key: 'reason', label: 'REJECTION REASON', render: r => <span style={{ whiteSpace: 'normal' }}>{r.reason || '—'}</span> },
          { key: 'eligible_again_when', label: 'ELIGIBLE AGAIN WHEN', render: r => (
            <span style={{ color: BB.text3, whiteSpace: 'normal' }}>{r.eligible_again_when || '—'}</span>) },
        ]} />
      </Section>
    </>
  )

  // ── TAB: PM MEMO (defect 21 — professional memo, never raw JSON) ──────────
  const memoTab = !eventId ? <div style={{ fontSize: t.body, color: BB.text3 }}>Select a sale event.</div>
    : memoStruct?.sections ? (
      <Section title="PM memo" t={t}
        right={<span style={{ fontSize: t.label, color: BB.text3 }}>memo v{memoStruct.memo_version ?? '—'} · structured synthesis</span>}>
        <div style={{ maxWidth: 900 }}>
          {[
            ...MEMO_SECTIONS,
            // any sections the builder adds later still render, after the known order
            ...Object.keys(memoStruct.sections)
              .filter(k => !MEMO_SECTIONS.some(([known]) => known === k))
              .map(k => [k, k.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase())] as [string, string]),
          ].map(([key, label]) => {
            const lines = memoLines(memoStruct.sections[key])
            if (!lines.length) return null
            return (
              <div key={key} style={{ marginBottom: t.gap }}>
                <div style={{ fontSize: t.subheading, fontWeight: 800, color: BB.amber, marginBottom: 4 }}>{label}</div>
                {lines.length === 1
                  ? <div style={{ fontSize: t.body + 1, lineHeight: 1.65, color: BB.text1, whiteSpace: 'pre-wrap' }}>{lines[0]}</div>
                  : lines.map((ln, i) => (
                    <div key={i} style={{ fontSize: t.body + 1, lineHeight: 1.6, color: BB.text1, padding: '2px 0' }}>• {ln}</div>
                  ))}
              </div>
            )
          })}
        </div>
      </Section>
    ) : selectedPlan ? (
      <Section title={`PM memo — ${planLabel}`} t={t}>
        <div style={{ fontSize: t.label, color: BB.text3, marginBottom: 8 }}>
          Structured memo not yet generated for this event — showing the legacy plan narrative. Recompute plans to produce the full memo.
        </div>
        {selectedPlan.hermes_narrative
          ? <div style={{ fontSize: t.body + 1, lineHeight: 1.65, color: BB.text1, whiteSpace: 'pre-wrap', maxWidth: 900 }}>{selectedPlan.hermes_narrative}</div>
          : <div style={{ fontSize: t.body, color: BB.text3 }}>No narrative persisted for this plan version — plan is not operator-ready.</div>}
        {selectedPlan.unmet_exposure?.length ? (
          <div style={{ marginTop: t.gap }}>
            <div style={{ fontSize: t.label, color: BB.amberAlt, fontWeight: 700, marginBottom: 4 }}>UNMET EXPOSURE</div>
            {selectedPlan.unmet_exposure.map((u: any, i: number) => (
              <div key={i} style={{ fontSize: t.body, color: BB.text2 }}>• {typeof u === 'string' ? u : `${u.sector ?? ''} ${u.usd ? fmt$(u.usd) : ''} ${u.note ?? ''}`}</div>
            ))}
          </div>
        ) : null}
      </Section>
    ) : <div style={{ fontSize: t.body, color: BB.text3 }}>Select a plan first.</div>

  // ── TAB: AUDIT — decision lineage first, legacy monitor rows collapsed ─────
  const lineageRows: any[] = audit.data?.lineage ?? []
  const auditTab = (
    <>
      <Section title="Decision lineage" t={t}
        right={<span style={{ fontSize: t.label, color: BB.text3 }}>who changed what, when, and why — per plan version</span>}>
        {lineageRows.length ? (
          <DataTable t={t} rows={lineageRows} cols={[
            { key: 'when', label: 'WHEN', render: r => String(r.occurred_at || r.created_at || '—').slice(0, 19) },
            { key: 'action', label: 'ACTION', render: r => <b style={{ color: BB.text0 }}>{String(r.action || '—').replace(/_/g, ' ')}</b> },
            { key: 'actor', label: 'ACTOR', render: r => r.actor || '—' },
            { key: 'detail', label: 'DETAIL', render: r => (
              <span style={{ whiteSpace: 'normal' }}>
                {r.prior_value != null && <span style={{ color: BB.text3 }}>{String(r.prior_value)} → </span>}
                <span style={{ color: BB.text1 }}>{r.new_value != null ? String(r.new_value) : '—'}</span>
                {r.reason && <span style={{ color: BB.text3 }}> — {r.reason}</span>}
              </span>) },
            { key: 'plan', label: 'PLAN', render: r => r.plan_id
              ? `#${r.plan_id}${r.plan_version != null ? ` v${r.plan_version}` : ''}` : '—' },
            { key: 'inferred', label: 'PROVENANCE', render: r => r.inferred
              ? <Pill text="INFERRED" color={BB.amberAlt} title="Backfilled from surrounding evidence, not a recorded operator action" />
              : <Pill text="recorded" color={BB.green} /> },
          ]} />
        ) : audit.loading ? (
          <div style={{ fontSize: t.body, color: BB.text3 }}>Loading lineage…</div>
        ) : (
          <div style={{ fontSize: t.body, color: BB.red }}>
            ⚠ GOVERNANCE GAP — no decision lineage exists for this event. Every plan generation,
            selection, and lock must leave a lineage row; an empty trail means provenance cannot be audited.
          </div>
        )}
      </Section>
      <details style={{ marginBottom: t.gap }}>
        <summary style={{ fontSize: t.body, color: BB.text2, cursor: 'pointer', padding: '6px 0' }}>
          monitor events (legacy audit rows — {audit.data?.rows?.length ?? 0})
        </summary>
        <DataTable t={t} rows={audit.data?.rows ?? []} empty="No audit rows for this event." cols={[
          { key: 'created_at', label: 'AT', render: r => String(r.created_at).slice(0, 19) },
          { key: 'action', label: 'ACTION' },
          { key: 'is_test_artifact', label: 'INTEGRITY', render: r => r.is_test_artifact
            ? <Pill text="TEST ARTIFACT — cleanup pending" color={BB.red} />
            : <Pill text="operator" color={BB.green} /> },
          { key: 'payload', label: 'PAYLOAD', render: r => <span style={{ fontSize: t.label, color: BB.text3 }}>{JSON.stringify(r.payload).slice(0, 140)}</span> },
        ]} />
      </details>
    </>
  )

  const body: Record<Tab, any> = {
    'CAPITAL BOOK': capitalBook,
    'DECISION': decisionTab,
    'EVENT OVERVIEW': eventId ? eventOverview : <div style={{ fontSize: t.body, color: BB.text3 }}>Select a sale event.</div>,
    'PLAN LAB': eventId ? plansTab : null,
    'PLAN COMPARISON': eventId ? comparisonTab : null,
    'PRO-FORMA': proFormaTab,
    'LOOK-THROUGH': lookThroughTab,
    'PERFORMANCE': performanceTab,
    'ENTRIES': entriesTab,
    'MONITORING': monitoringTab,
    'REJECTED': rejectedTab,
    'PM MEMO': memoTab,
    'AUDIT': auditTab,
  }

  return (
    <div style={{ minWidth: 0, maxWidth: 1680, margin: '0 auto', fontFamily: BB.mono, color: BB.text1, fontSize: t.body }}>
      {contextBar}
      {tabBar}
      {body[tab]}
      <div style={{ marginTop: 24, paddingTop: 10, borderTop: `1px solid ${BB.border}`, fontSize: t.label, color: BB.text3 }}>
        Advisory workstation — no broker orders are placed from this desk. Fidelity is manual-ticket only.
        Record-fill is manual operator evidence. Settlement verification means a plan may proceed to operator
        implementation review, never execution approval.
      </div>
    </div>
  )
}
