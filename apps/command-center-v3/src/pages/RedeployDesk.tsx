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

const TABS = [
  'CAPITAL BOOK', 'EVENT OVERVIEW', 'PLAN LAB', 'PLAN COMPARISON', 'PRO-FORMA', 'LOOK-THROUGH',
  'PERFORMANCE', 'ENTRIES', 'MONITORING', 'REJECTED', 'PM MEMO', 'AUDIT',
] as const
type Tab = (typeof TABS)[number]

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
    return (TABS as readonly string[]).includes(raw || '') ? (raw as Tab) : 'CAPITAL BOOK'
  })
  const eventId = params.get('event') ? Number(params.get('event')) : null

  const setEvent = useCallback((id: number | null, nextTab?: Tab) => {
    const p = new URLSearchParams(params)
    if (id) p.set('event', String(id)); else p.delete('event')
    if (nextTab) { p.set('tab', nextTab); setTab(nextTab) }
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

  // Part G — plan-quality gate: composite score alone is never enough
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
        <DataTable t={t} rows={bookRows} empty={book.loading ? 'Loading…' : 'No events.'} cols={[
          { key: 'event_id', label: '#', render: r => (
            <button onClick={() => setEvent(r.event_id, 'EVENT OVERVIEW')}
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

  // ── TAB: PLANS ─────────────────────────────────────────────────────────────
  const legCols = (p: any) => [
    { key: 'ticker', label: 'TICKER', render: (l: any) => <b style={{ color: BB.text0 }}>{l.is_reserve ? 'RESERVE' : l.ticker}</b> },
    { key: 'dual_label', label: 'ROLE', render: (l: any) => (l.dual_label || l.role || (l.is_reserve ? 'cash reserve' : '—')).replace(/_/g, ' ') },
    { key: 'allocation_pct_of_net', label: 'ALLOC %', align: 'right' as const, render: (l: any) => pct(l.allocation_pct_of_net ?? l.allocation_pct, 1) },
    { key: 'target_dollars', label: 'TARGET $', align: 'right' as const, render: (l: any) => fmt$(l.target_dollars) },
    { key: 'target_shares', label: 'SHARES', align: 'right' as const, render: (l: any) => l.target_shares ?? '—' },
    { key: 'expected_yield_pct', label: 'YIELD', align: 'right' as const, render: (l: any) => pct(l.expected_yield_pct, 2) },
    { key: 'income', label: 'INCOME/YR', align: 'right' as const, render: (l: any) =>
      l.expected_yield_pct != null && l.target_dollars ? fmt$(l.target_dollars * l.expected_yield_pct / 100) : '—' },
    { key: 'current_price', label: 'PRICE', align: 'right' as const, render: (l: any) => l.current_price ? `$${num(l.current_price)}` : '—' },
    { key: 'price_as_of', label: 'QUOTE AGE', render: (l: any) => (
      <span style={{ color: l.price_stale ? BB.red : BB.text3, fontSize: t.label }}>{l.price_stale ? 'STALE · ' : ''}{ago(l.price_as_of)}</span>) },
  ]

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
          const missing = planReadiness(p)
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
                <Pill text={`confidence ${num(p.confidence, 1)}`} color={BB.blue}
                      title="One decision component — never the sole selector" />
                {p.composite_rank != null && <Pill text={`rank ${p.composite_rank}`} color={BB.text3} />}
                {p.oversight_status && <Pill text={`oversight: ${p.oversight_status}`}
                  color={p.oversight_status === 'pass' ? BB.green : p.oversight_status === 'failed' ? BB.red : BB.text3} />}
                {missing.length
                  ? <Pill text={`NOT OPERATOR-READY: needs ${missing.join(', ')}`} color={BB.red} />
                  : <Pill text="OPERATOR-READY" color={BB.green} />}
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
              <DataTable t={t} rows={p.legs || []} empty="No legs — plan is not operator-ready." cols={legCols(p)} />
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
  const planIncome = (p: any) => (p?.legs || []).reduce((s: number, l: any) =>
    s + ((l.target_dollars && l.expected_yield_pct) ? l.target_dollars * l.expected_yield_pct / 100 : 0), 0)
  const staleLegs = (p: any) => (p?.legs || []).filter((l: any) => l.price_stale && !l.is_reserve).length
  const cmpCell = (fn: (p: any) => string) =>
    Object.fromEntries(compareIds.map(id => [String(id), fn(plans.find(p => p.id === id) || {})]))
  const comparisonTab = compareIds.length >= 2 ? (
    <Section title={`Plan comparison — ${compareIds.length} plans (differences, not merely winners)`} t={t}>
      <DataTable t={t} rows={[
        { k: 'Objective', ...cmpCell(p => p.objective || '—') },
        { k: 'Deployment % of net', ...cmpCell(p => pct(p.deploy_pct_of_net, 1)) },
        { k: 'Deployable $', ...cmpCell(p => fmt$(p.total_deployable_usd)) },
        { k: 'Reserve $', ...cmpCell(p => fmt$(p.reserve_usd)) },
        { k: 'Legs', ...cmpCell(p => (p.legs || []).map((l: any) => l.is_reserve ? 'RSV' : l.ticker).join(' + ') || '—') },
        { k: 'Leg count', ...cmpCell(p => String((p.legs || []).filter((l: any) => !l.is_reserve).length)) },
        { k: 'Expected income /yr', ...cmpCell(p => planIncome(p) > 0 ? fmt$(planIncome(p)) : '—') },
        { k: 'Confidence (component)', ...cmpCell(p => num(p.confidence, 1)) },
        { k: 'Composite rank', ...cmpCell(p => p.composite_rank == null ? '—' : String(p.composite_rank)) },
        { k: 'Oversight', ...cmpCell(p => p.oversight_status || '—') },
        { k: 'Stale-quote legs', ...cmpCell(p => String(staleLegs(p))) },
        { k: 'Readiness', ...cmpCell(p => { const m = planReadiness(p); return m.length ? `needs: ${m.join(', ')}` : 'operator-ready' }) },
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
  const lookThroughTab = pf?.ok ? (
    <>
      <Section title="Post-plan issuer exposure (direct + fund look-through, top 25)" t={t}>
        <DataTable t={t} rows={pf.states.post_plan.top_issuers} cols={[
          { key: 'symbol', label: 'ISSUER' },
          { key: 'usd', label: 'EXPOSURE', align: 'right', render: r => fmt$(r.usd) },
          { key: 'pct', label: '% PORTFOLIO', align: 'right', render: r => pct(r.pct, 2) },
        ]} />
      </Section>
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
  const performanceTab = perf?.ok ? (
    <>
      <Section title={`Performance — ${planLabel}`} t={t}
        right={<span style={{ fontSize: t.label, color: BB.text3 }}>total return where distributions cached; price return otherwise — see basis per leg</span>}>
        <DataTable t={t} rows={[
          { k: 'Plan (dollar-weighted)', ...Object.fromEntries(['1Y', '3Y', '5Y'].map(w => [w, perf.plan_weighted.return_windows[w] ? `${perf.plan_weighted.return_windows[w].pct}% (${perf.plan_weighted.return_windows[w].coverage_pct_of_allocation}% cov)` : '—'])), yield: pct(perf.plan_weighted.yield_pct), er: perf.plan_weighted.expense_ratio_pct == null ? '—' : `${perf.plan_weighted.expense_ratio_pct}%`, income: fmt$(perf.plan_weighted.expected_annual_income_usd) },
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
            { key: 'label', label: 'SCENARIO', render: (s: any) => <span title={s.label}>{s.label.split('—')[0].trim()}</span> },
            { key: 'kind', label: 'KIND', render: (s: any) => (
              <span style={{ fontSize: t.label, color: s.kind === 'HISTORICAL_OBSERVATION' ? BB.text2 : BB.blue }}>{s.kind}</span>) },
            { key: 'plan_pct', label: 'PLAN IMPACT', align: 'right', render: (s: any) => (
              <span style={{ color: s.unavailable ? BB.text3 : toneFor(s.plan_pct), fontFamily: BB.mono }}>
                {s.unavailable ? 'unavailable' : `${s.plan_pct > 0 ? '+' : ''}${s.plan_pct}%`}
              </span>) },
            { key: 'coverage_pct_of_plan', label: 'COVERAGE', align: 'right', render: (s: any) => pct(s.coverage_pct_of_plan, 0) },
            { key: 'label2', label: 'METHODOLOGY', render: (s: any) => (
              <span style={{ fontSize: t.label, color: BB.text3 }}>{(s.note || s.label.split('—').slice(1).join('—')).trim()}</span>) },
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

  // ── TAB: ENTRIES ───────────────────────────────────────────────────────────
  const entriesLegs = selectedPlan?.legs || []
  const entriesTab = (
    <Section title={`Entry targets — ${planLabel ?? 'no plan selected'}`} t={t}
      right={<button onClick={refreshQuotes} style={{ background: BB.blueDim, color: BB.blue, border: `1px solid ${BB.blue}55`, borderRadius: 4, padding: '6px 12px', fontSize: t.label, fontWeight: 700, cursor: 'pointer' }}>REFRESH ALL QUOTES</button>}>
      {actionMsg && <div style={{ fontSize: t.body, color: BB.amberAlt, marginBottom: 8 }}>{actionMsg}</div>}
      {!selectedPlan && <div style={{ fontSize: t.body, color: BB.text3 }}>Select a plan in PLAN LAB — entries are always shown in the context of their plan.</div>}
      {entriesLegs.filter((l: any) => !l.is_reserve).map((l: any) => (
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
                <b style={{ color: BB.text0 }}>{r.ticker || r.symbol || r.name || `alt ${i + 1}`}</b> — {r.reason || r.note || JSON.stringify(r).slice(0, 160)}
              </div>
            ))
          : <div style={{ fontSize: t.body, color: BB.text3 }}>No rejected alternatives recorded on this plan.</div>}
      </Section>
      <Section title={`Candidate universe exclusions (${candidates.data?.rejected_count ?? '…'})`} t={t}
        right={<span style={{ fontSize: t.label, color: BB.text3 }}>universe {candidates.data?.universe_size ?? '…'} · accepted {candidates.data?.accepted_count ?? '…'}</span>}>
        <DataTable t={t} rows={candidates.data?.rejected ?? []} cols={[
          { key: 'symbol', label: 'SYMBOL' },
          { key: 'sources', label: 'SOURCES', render: r => (r.sources || []).join(', ') },
          { key: 'reason', label: 'REJECTION REASON' },
        ]} />
      </Section>
    </>
  )

  // ── TAB: PM MEMO ───────────────────────────────────────────────────────────
  const memoTab = selectedPlan ? (
    <Section title={`PM memo — ${planLabel}`} t={t}>
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
      {selectedPlan.scenarios ? (
        <div style={{ marginTop: t.gap }}>
          <div style={{ fontSize: t.label, color: BB.blue, fontWeight: 700, marginBottom: 4 }}>PLAN SCENARIOS</div>
          <pre style={{ fontSize: t.table, color: BB.text2, whiteSpace: 'pre-wrap', fontFamily: BB.mono }}>
            {typeof selectedPlan.scenarios === 'string' ? selectedPlan.scenarios : JSON.stringify(selectedPlan.scenarios, null, 1)}
          </pre>
        </div>
      ) : null}
    </Section>
  ) : <div style={{ fontSize: t.body, color: BB.text3 }}>Select a plan first.</div>

  // ── TAB: AUDIT ─────────────────────────────────────────────────────────────
  const auditTab = (
    <Section title="Audit trail" t={t}>
      <DataTable t={t} rows={audit.data?.rows ?? []} empty="No audit rows for this event." cols={[
        { key: 'created_at', label: 'AT', render: r => String(r.created_at).slice(0, 19) },
        { key: 'action', label: 'ACTION' },
        { key: 'is_test_artifact', label: 'INTEGRITY', render: r => r.is_test_artifact
          ? <Pill text="TEST ARTIFACT — cleanup pending" color={BB.red} />
          : <Pill text="operator" color={BB.green} /> },
        { key: 'payload', label: 'PAYLOAD', render: r => <span style={{ fontSize: t.label, color: BB.text3 }}>{JSON.stringify(r.payload).slice(0, 140)}</span> },
      ]} />
    </Section>
  )

  const body: Record<Tab, any> = {
    'CAPITAL BOOK': capitalBook,
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
