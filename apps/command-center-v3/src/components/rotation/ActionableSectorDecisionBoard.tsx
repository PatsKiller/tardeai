import { useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { BB, DASH, T, metricChip, numStyle, statePill } from '../../lib/watchTokens'

interface Props {
  sectors?: any[]
  industries?: any[]
  recommendations?: any
  generatedAt?: string | null
  industryCapturedAt?: string | null
  compact?: boolean
}

type DecisionStatus = 'ELIGIBLE NOW' | 'RESEARCH WATCH' | 'AVOID / REDUCE' | 'NO DECISION'
type StatusFilter = DecisionStatus | 'ALL'

type DecisionRow = {
  sector: any
  name: string
  card: any
  status: DecisionStatus
  supportiveIndustries: any[]
  blocking: string[]
  why: string
}

type EvidenceState = {
  symbol: string
  loading: boolean
  error?: string
  payload?: any
} | null

const SECTOR_ALIASES: Record<string, string> = {
  'financial services': 'Financials',
  financial: 'Financials',
  'consumer cyclical': 'Consumer Discretionary',
  'consumer defensive': 'Consumer Staples',
  'basic materials': 'Materials',
  'communication services': 'Communications',
}

const actionButton = (tone: 'primary' | 'secondary' | 'danger' = 'secondary'): CSSProperties => ({
  border: `1px solid ${tone === 'primary' ? T.link : tone === 'danger' ? BB.red : BB.border}`,
  background: tone === 'primary' ? `${T.link}18` : tone === 'danger' ? BB.redDim : BB.bgShift,
  color: tone === 'primary' ? T.link : tone === 'danger' ? BB.red : BB.text2,
  borderRadius: 2,
  padding: '5px 8px',
  fontSize: DASH.data,
  fontWeight: 800,
  cursor: 'pointer',
})

const closeButton: CSSProperties = {
  ...actionButton('secondary'),
  padding: '3px 8px',
}

function canonicalSector(value?: string | null): string {
  const clean = String(value || '').trim()
  return SECTOR_ALIASES[clean.toLowerCase()] || clean
}

function signed(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  const n = Number(value)
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`
}

function money(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  return `$${Math.round(Number(value)).toLocaleString()}`
}

function shortTime(value?: string | null): string {
  if (!value) return 'not reported'
  const d = new Date(value)
  if (!Number.isFinite(d.getTime())) return String(value).slice(0, 19)
  return d.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

function ageDays(value?: string | null): number | null {
  if (!value) return null
  const d = new Date(`${String(value).slice(0, 10)}T00:00:00Z`)
  if (!Number.isFinite(d.getTime())) return null
  return Math.max(0, Math.floor((Date.now() - d.getTime()) / 86_400_000))
}

function cardSector(card: any, sectorByEtf: Map<string, any>): string {
  const etf = (card?.instruments || []).find((i: any) => i.kind === 'sector ETF')?.symbol
  if (etf && sectorByEtf.has(etf)) return canonicalSector(sectorByEtf.get(etf)?.sector)
  const match = String(card?.title || '').match(/·\s*(.+?)\s*\(/)
  return canonicalSector(match?.[1] || '')
}

function hasAccountSizing(card: any): boolean {
  return Boolean(card && Object.keys(card.account_sizing || {}).length)
}

function statusTone(status: DecisionStatus): 'green' | 'amber' | 'red' | 'slate' {
  if (status === 'ELIGIBLE NOW') return 'green'
  if (status === 'RESEARCH WATCH') return 'amber'
  if (status === 'AVOID / REDUCE') return 'red'
  return 'slate'
}

function statusFor(sector: any, card: any): DecisionStatus {
  const state = String(sector?.state || '').toUpperCase()
  const stale = Boolean(sector?.quarantined || sector?.freshness?.stale || ((ageDays(sector?.as_of) ?? 0) > 4))
  if (stale || !state) return 'NO DECISION'
  if (card && hasAccountSizing(card)) return 'ELIGIBLE NOW'
  if (state === 'WEAKENING' || state === 'LAGGING') return 'AVOID / REDUCE'
  return 'RESEARCH WATCH'
}

function accountRows(card: any, accountLabels: Record<string, string>): any[] {
  const sizing = card?.account_sizing || {}
  const decisions = card?.allocation_policy || {}
  return Object.keys(sizing).map(account => {
    const row = sizing[account] || {}
    const decision = decisions[account] || {}
    return {
      account,
      label: accountLabels[account] || account,
      low: row.pct_band?.[0],
      high: row.pct_band?.[1],
      dollars: row.dollar_band,
      current: decision.current_account_weight_pct,
      capacity: decision.capacity_pct,
      target: decision.risk_target_pct,
      quality: decision.quality,
    }
  })
}

async function copyText(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value)
    return
  }
  const area = document.createElement('textarea')
  area.value = value
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  document.execCommand('copy')
  area.remove()
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div role="presentation" onMouseDown={onClose} style={{ position: 'fixed', inset: 0, zIndex: 10000, background: 'rgba(2,6,23,.82)', display: 'grid', placeItems: 'center', padding: 16 }}>
      <section role="dialog" aria-modal="true" aria-label={title} onMouseDown={event => event.stopPropagation()} style={{ width: 'min(920px, 96vw)', maxHeight: '90vh', overflow: 'auto', background: BB.bgPanel, border: `1px solid ${BB.border}`, boxShadow: '0 24px 80px rgba(0,0,0,.55)', padding: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontSize: DASH.panel, fontWeight: 900, color: BB.text1 }}>{title}</div>
          <button type="button" onClick={onClose} style={closeButton}>Close</button>
        </div>
        {children}
      </section>
    </div>
  )
}

export default function ActionableSectorDecisionBoard({
  sectors = [], industries = [], recommendations, generatedAt, industryCapturedAt, compact = false,
}: Props) {
  const navigate = useNavigate()
  const { data: sectorMonitor, refetch: refetchSectorMonitor } = useApi<any>('/api/v2/sectors/monitor', 120_000)
  const [showMethod, setShowMethod] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL')
  const [industryFilter, setIndustryFilter] = useState<string | null>(null)
  const [selected, setSelected] = useState<DecisionRow | null>(null)
  const [riskReview, setRiskReview] = useState<any | null>(null)
  const [policyReview, setPolicyReview] = useState(false)
  const [evidence, setEvidence] = useState<EvidenceState>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [watched, setWatched] = useState<Record<string, boolean>>({})

  const groups = recommendations?.groups || {}
  const addCards: any[] = groups.get_into || []
  const riskCards: any[] = [...(groups.protect || []), ...(groups.short_side || [])]
  const accountLabels: Record<string, string> = recommendations?.accounts || {}
  const leanReview = (recommendations?.directive_reviews || [])[0] || {}

  const sectorByEtf = useMemo(() => new Map(sectors.map((sector: any) => [sector.etf, sector])), [sectors])
  const monitorBySector = useMemo(() => {
    const out = new Map<string, any>()
    for (const row of sectorMonitor?.sectors || []) out.set(canonicalSector(row.sector), row)
    return out
  }, [sectorMonitor])

  const addBySector = useMemo(() => {
    const out = new Map<string, any>()
    addCards.forEach(card => {
      const sector = cardSector(card, sectorByEtf)
      if (sector && !out.has(sector)) out.set(sector, card)
    })
    return out
  }, [addCards, sectorByEtf])

  const industriesBySector = useMemo(() => {
    const out = new Map<string, any[]>()
    industries.forEach((industry: any) => {
      const key = canonicalSector(industry.sector)
      if (!key) return
      const list = out.get(key) || []
      list.push(industry)
      out.set(key, list)
    })
    out.forEach(list => list.sort((a, b) => {
      const aState = ['LEADING', 'IMPROVING'].includes(String(a.state || '').toUpperCase()) ? 1 : 0
      const bState = ['LEADING', 'IMPROVING'].includes(String(b.state || '').toUpperCase()) ? 1 : 0
      if (aState !== bState) return bState - aState
      return Number(b.rel1m ?? -999) - Number(a.rel1m ?? -999)
    }))
    return out
  }, [industries])

  const decisions = useMemo<DecisionRow[]>(() => sectors.map((sector: any): DecisionRow => {
    const name = canonicalSector(sector.sector)
    const card = addBySector.get(name)
    const status = statusFor(sector, card)
    const supportiveIndustries = (industriesBySector.get(name) || [])
      .filter((industry: any) => !industry.quarantined && ['LEADING', 'IMPROVING'].includes(String(industry.state || '').toUpperCase()))
      .slice(0, 3)
    const blocking: string[] = []
    const breadth = sector.breadth_pct == null ? null : Number(sector.breadth_pct)
    const state = String(sector.state || '').toUpperCase()
    const stale = status === 'NO DECISION'

    if (stale) blocking.push(sector.quarantine_reason === 'stale_row' || sector.freshness?.stale
      ? `sector row is stale (${sector.as_of || 'date unavailable'})`
      : 'sector state or timestamp is unavailable')
    if (breadth == null) blocking.push('covered-universe breadth is unavailable')
    else if (breadth < 35) blocking.push(`participation is narrow: ${breadth}% above the exact 20-session measure`)
    if (!supportiveIndustries.length && !stale) blocking.push('no mapped leading/improving industry is confirming the sector')
    if (card && !hasAccountSizing(card)) blocking.push('legacy shared-size card withheld: regenerate account-specific exposure, target, capacity, percentage band and dollar band')
    if (!card && leanReview.enabled && leanReview.requires_review && !['Utilities', 'Consumer Staples', 'Healthcare'].includes(name) && ['LEADING', 'IMPROVING'].includes(state)) {
      blocking.push('dated defensive-lean policy currently blocks non-defensive adds pending operator review')
    }
    if (!card && status === 'RESEARCH WATCH' && recommendations?.empty_reasons?.get_into) blocking.push(recommendations.empty_reasons.get_into)
    if (status === 'AVOID / REDUCE') blocking.push(`${state || 'weak'} relative state is not an entry condition`)

    const why = card && hasAccountSizing(card)
      ? `${state} vs SPY with RS20 ${signed(sector.rs20)}; governed account and risk rails passed`
      : card
        ? `${state} vs SPY with RS20 ${signed(sector.rs20)}; signal passed legacy rails but the sizing contract is incomplete`
        : `${state || 'unclassified'} vs SPY with RS20 ${signed(sector.rs20)} and slope ${signed(sector.slope)}`
    return { sector, name, card, status, supportiveIndustries, blocking: [...new Set(blocking)], why }
  }).sort((a, b) => {
    const rank: Record<DecisionStatus, number> = { 'ELIGIBLE NOW': 0, 'RESEARCH WATCH': 1, 'AVOID / REDUCE': 2, 'NO DECISION': 3 }
    return rank[a.status] - rank[b.status] || Number(b.sector.rs20 ?? -999) - Number(a.sector.rs20 ?? -999)
  }), [sectors, addBySector, industriesBySector, leanReview, recommendations])

  const counts = decisions.reduce((acc: Record<DecisionStatus, number>, row) => {
    acc[row.status] += 1
    return acc
  }, { 'ELIGIBLE NOW': 0, 'RESEARCH WATCH': 0, 'AVOID / REDUCE': 0, 'NO DECISION': 0 })

  const filtered = decisions.filter(row => {
    if (statusFilter !== 'ALL' && row.status !== statusFilter) return false
    if (industryFilter && !row.supportiveIndustries.some(industry => industry.industry === industryFilter)) return false
    return true
  })
  const visible = showAll ? filtered : filtered.slice(0, compact ? 5 : 8)
  const legacyAddCount = addCards.filter(card => !hasAccountSizing(card)).length

  const openEvidence = async (symbol: string) => {
    setEvidence({ symbol, loading: true })
    try {
      const response = await fetch(`/api/v2/watch/provenance/${encodeURIComponent(symbol)}`)
      const text = await response.text()
      let payload: any
      try { payload = text ? JSON.parse(text) : {} } catch { payload = { raw: text } }
      if (!response.ok) throw new Error(payload?.error || `HTTP ${response.status}`)
      setEvidence({ symbol, loading: false, payload })
    } catch (error) {
      setEvidence({ symbol, loading: false, error: error instanceof Error ? error.message : String(error) })
    }
  }

  const watchSector = async (row: DecisionRow) => {
    if (watched[row.name]) return
    if (!window.confirm(`Create a governed watch directive for ${row.name}? This does not create a recommendation, proposal or order.`)) return
    setBusy(`watch:${row.name}`)
    setToast(null)
    try {
      const response = await fetch('/api/v2/watch/directives', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: 'sector', label: `sector ${row.name}`, spec: { finviz_sector: row.name }, rationale: 'watched from actionable sector decision board' }),
      })
      const payload = await response.json()
      if (!response.ok || !payload?.ok) throw new Error(payload?.error || `HTTP ${response.status}`)
      setWatched(current => ({ ...current, [row.name]: true }))
      setToast(`Watching ${row.name}. Directive #${payload.directive_id ?? 'created'} is now in Watch.`)
      refetchSectorMonitor()
    } catch (error) {
      setToast(`Watch action failed: ${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(null)
    }
  }

  const openRotationReview = async (row: DecisionRow) => {
    const text = `Review ${row.name} (${row.sector.etf || 'ETF unavailable'}): ${row.why}. Current blockers: ${row.blocking.join('; ') || 'none listed'}. Book exposure: ${row.sector.book_pct ?? 'unknown'}%. Provide a SHADOW-only rotation review; do not stage or place an order.`
    try { await copyText(text); setToast('Rotation review brief copied. Paste it into Rotation Intelligence.') } catch { setToast('Rotation review opened; copy the visible decision details manually.') }
    navigate('/rotation?from=sector-decision-board')
  }

  const queueRefresh = async () => {
    if (!window.confirm('Queue a Defense evidence refresh? This refreshes snapshots only and does not place or stage orders.')) return
    setBusy('refresh')
    setToast(null)
    try {
      const response = await fetch('/api/v2/defense/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.ok === false) throw new Error(payload?.error || `HTTP ${response.status}`)
      setToast('Evidence refresh queued. Recheck freshness after the producer finishes.')
    } catch (error) {
      setToast(`Refresh failed: ${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setBusy(null)
    }
  }

  const statusButton = (status: DecisionStatus, label: string, tone: 'green' | 'amber' | 'red' | 'slate') => (
    <button type="button" aria-label={`Filter ${status} (${counts[status]})`} aria-pressed={statusFilter === status}
      onClick={() => setStatusFilter(current => current === status ? 'ALL' : status)}
      style={{ ...statePill(tone), cursor: 'pointer', opacity: statusFilter === 'ALL' || statusFilter === status ? 1 : .45 }}>
      {label} {counts[status]}
    </button>
  )

  return (
    <section style={{ background: BB.bgPanel, border: `1px solid ${BB.border}`, borderRadius: 2, padding: compact ? '10px 12px' : '12px 14px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap', marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: DASH.panel, fontWeight: 800, color: BB.text1 }}>Sector decision board</div>
          <div style={{ fontSize: DASH.data, color: BB.text3, marginTop: 2 }}>filter · inspect · open evidence · create a governed watch · hand off a review brief</div>
        </div>
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
          {statusButton('ELIGIBLE NOW', 'eligible', 'green')}
          {statusButton('RESEARCH WATCH', 'watch', 'amber')}
          {statusButton('AVOID / REDUCE', 'avoid/reduce', 'red')}
          {statusButton('NO DECISION', 'no decision', 'slate')}
          <span style={statePill('slate')} title="Model lanes challenge the packet; they do not create prices, sizing or permission truth">model critique only</span>
          <button type="button" onClick={() => setShowMethod(value => !value)} style={{ ...metricChip(true), color: T.link, borderColor: T.link, cursor: 'pointer' }}>{showMethod ? 'hide math contract' : 'math & freshness'}</button>
        </div>
      </div>

      {(statusFilter !== 'ALL' || industryFilter) && (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8, fontSize: DASH.data, color: BB.text2 }}>
          <b>Active filter:</b> {statusFilter !== 'ALL' ? statusFilter : ''}{statusFilter !== 'ALL' && industryFilter ? ' · ' : ''}{industryFilter || ''}
          <button type="button" onClick={() => { setStatusFilter('ALL'); setIndustryFilter(null) }} style={actionButton('secondary')}>Clear filters</button>
        </div>
      )}

      {toast && <div role="status" style={{ fontSize: DASH.data, color: toast.includes('failed') ? BB.red : BB.green, background: BB.bgShift, borderLeft: `3px solid ${toast.includes('failed') ? BB.red : BB.green}`, padding: '7px 9px', marginBottom: 8 }}>{toast}</div>}

      {addCards.length === 0 && (
        <div style={{ fontSize: DASH.data, color: BB.amber, background: BB.amberDim, borderLeft: `3px solid ${BB.amber}`, padding: '7px 9px', marginBottom: 10 }}>
          <b>No governed add card is active.</b> Use Review decision to see the exact blocker, create a sector watch, inspect evidence, or hand the case to Rotation Intelligence.
        </div>
      )}
      {legacyAddCount > 0 && (
        <div style={{ fontSize: DASH.data, color: BB.red, background: BB.redDim, borderLeft: `3px solid ${BB.red}`, padding: '7px 9px', marginBottom: 10 }}>
          <b>{legacyAddCount} legacy add card{legacyAddCount === 1 ? ' is' : 's are'} withheld.</b> Shared sizing is not actionable across accounts.
        </div>
      )}

      {showMethod && (
        <div style={{ fontSize: DASH.data, color: BB.text2, background: BB.bgShift, borderLeft: `3px solid ${BB.amber}`, padding: '8px 10px', marginBottom: 10, display: 'grid', gap: 3 }}>
          <div><b>Sector state:</b> {shortTime(generatedAt)} · ETF 5/20/60-session returns aligned to SPY; state uses RS20 level plus change in RS20 and requires two-close confirmation.</div>
          <div><b>Breadth:</b> exact latest close versus each covered member’s latest 20 distinct sessions. It is covered-universe breadth, not automatically official ETF-constituent breadth.</div>
          <div><b>Industry state:</b> {shortTime(industryCapturedAt)} · one-month relative level plus one-week relative direction; this is not the sector slope formula.</div>
          <div><b>Sizing:</b> an actionable card must show each account’s own exposure, target, capacity, percentage band and dollar band.</div>
          <div><b>Actions:</b> watches and refreshes change research workflow only. Nothing on this board stages, approves or places an order.</div>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fit, minmax(${compact ? 285 : 330}px, 1fr))`, gap: 9 }}>
        {visible.map(row => {
          const { sector, name, card, status, supportiveIndustries, blocking, why } = row
          const tone = statusTone(status)
          const toneColor = tone === 'green' ? BB.green : tone === 'red' ? BB.red : tone === 'amber' ? BB.amber : BB.text3
          const isWatching = watched[name] || Boolean(monitorBySector.get(name)?.is_watched)
          return (
            <article key={sector.etf || name} style={{ border: `1px solid ${BB.borderHair}`, borderLeft: `4px solid ${toneColor}`, background: BB.bg, padding: '10px 11px', minWidth: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'flex-start' }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: DASH.section, fontWeight: 800, color: BB.text1 }}>{name}</div>
                  <button type="button" onClick={() => void openEvidence(sector.etf)} title={`Open provenance and evidence for ${sector.etf}`} style={{ ...numStyle, fontSize: DASH.data, color: T.link, background: 'transparent', border: 0, padding: 0, cursor: 'pointer', textDecoration: 'underline' }}>{sector.etf || 'ETF not mapped'}</button>
                </div>
                <span style={statePill(tone)}>{status}</span>
              </div>

              <div style={{ fontSize: DASH.data, color: BB.text2, marginTop: 7 }}><b>Why:</b> {why}</div>
              <div style={{ fontSize: DASH.data, color: BB.text3, marginTop: 3 }}>breadth {sector.breadth_pct == null ? '—' : `${sector.breadth_pct}%`} ({sector.breadth_coverage_n ?? sector.breadth_n ?? '—'}/{sector.breadth_membership_n ?? '—'} covered) · book {sector.book_pct == null ? '—' : `${sector.book_pct}%`} · as of {sector.as_of || '—'}</div>

              {supportiveIndustries.length > 0 && (
                <div style={{ marginTop: 7 }}>
                  <div style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', color: BB.text3, marginBottom: 3 }}>confirming industries · click to filter</div>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {supportiveIndustries.map((industry: any) => (
                      <button type="button" key={industry.industry} aria-pressed={industryFilter === industry.industry}
                        onClick={() => setIndustryFilter(current => current === industry.industry ? null : industry.industry)}
                        style={{ ...metricChip(industryFilter === industry.industry), cursor: 'pointer' }}
                        title={`${industry.state} · relative month ${signed(industry.rel1m)} · relative week ${signed(industry.rel1w)}`}>
                        {industry.industry}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div style={{ marginTop: 8, padding: '7px 8px', background: status === 'ELIGIBLE NOW' ? BB.greenDim : status === 'AVOID / REDUCE' ? BB.redDim : BB.bgShift, borderLeft: `3px solid ${toneColor}` }}>
                <div style={{ fontSize: DASH.chip, fontWeight: 800, color: toneColor, textTransform: 'uppercase', marginBottom: 3 }}>{status === 'ELIGIBLE NOW' ? 'activation ready for review' : status === 'NO DECISION' ? 'required before evaluation' : status === 'AVOID / REDUCE' ? 'why not an entry' : 'promote only when'}</div>
                {status === 'ELIGIBLE NOW' ? (
                  <>
                    <div style={{ fontSize: DASH.data, color: BB.text1 }}>{card?.levels?.entry_zone || card?.entry_logic || 'governed entry condition unavailable'}</div>
                    <div style={{ fontSize: DASH.data, color: BB.amber, marginTop: 2 }}>Invalidation: {card?.invalidation || 'not reported'}</div>
                  </>
                ) : blocking.length ? blocking.slice(0, 3).map((item, index) => (
                  <div key={index} style={{ fontSize: DASH.data, color: BB.text2, padding: '1px 0' }}>• {item}</div>
                )) : <div style={{ fontSize: DASH.data, color: BB.text3 }}>A complete governed recommendation card must appear.</div>}
              </div>

              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 9 }}>
                <button type="button" onClick={() => setSelected(row)} style={actionButton('primary')}>Review decision</button>
                <button type="button" disabled={isWatching || busy === `watch:${name}`} onClick={() => void watchSector(row)} style={{ ...actionButton('secondary'), opacity: isWatching ? .55 : 1, cursor: isWatching ? 'default' : 'pointer' }}>{isWatching ? 'Watching' : busy === `watch:${name}` ? 'Saving…' : 'Watch sector'}</button>
                <button type="button" onClick={() => void openRotationReview(row)} style={actionButton('secondary')}>Copy brief + Rotation</button>
                {status === 'NO DECISION' && <button type="button" disabled={busy === 'refresh'} onClick={() => void queueRefresh()} style={actionButton('secondary')}>{busy === 'refresh' ? 'Queueing…' : 'Refresh evidence'}</button>}
              </div>
            </article>
          )
        })}
      </div>

      {!visible.length && <div style={{ padding: 16, color: BB.text3, fontSize: DASH.data, textAlign: 'center' }}>No sectors match the active filter. Clear filters to restore the board.</div>}

      {filtered.length > visible.length && <button type="button" onClick={() => setShowAll(value => !value)} style={{ ...metricChip(true), marginTop: 8, color: T.link, borderColor: T.link, cursor: 'pointer' }}>{showAll ? 'show priority rows' : `show all ${filtered.length} sectors`}</button>}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 8, marginTop: 10 }}>
        <div style={{ border: `1px solid ${BB.borderHair}`, background: BB.bg, padding: '8px 9px' }}>
          <div style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', color: BB.red, marginBottom: 5 }}>governed defense actions · click to review</div>
          {riskCards.length ? riskCards.slice(0, 4).map((card: any) => {
            const withheld = (String(card.id || '').startsWith('pput-') && !card.put_struct) || (String(card.id || '').startsWith('cc-') && !card.cc_struct)
            return <button type="button" key={card.id} onClick={() => setRiskReview(card)} style={{ display: 'block', width: '100%', textAlign: 'left', fontSize: DASH.data, color: withheld ? BB.red : BB.text2, padding: '4px 2px', background: 'transparent', border: 0, borderBottom: `1px solid ${BB.borderHair}`, cursor: 'pointer' }}><b style={{ color: BB.text1 }}>{card.title}</b> · {withheld ? 'WITHHELD' : card.mode || 'advisory'} →</button>
          }) : <div style={{ fontSize: DASH.data, color: BB.text3 }}>No complete protect, trim or hedge card passed current rails.</div>}
        </div>
        <div style={{ border: `1px solid ${BB.borderHair}`, background: BB.bg, padding: '8px 9px' }}>
          <div style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', color: BB.amber, marginBottom: 5 }}>operator policy review</div>
          <div style={{ fontSize: DASH.data, color: BB.text2, marginBottom: 7 }}>{leanReview.requires_review ? `Defensive lean set ${leanReview.set_at || 'date unavailable'} requires adjudication.` : 'No dated rotation directive is currently due for review.'}</div>
          <button type="button" onClick={() => setPolicyReview(true)} style={actionButton('secondary')}>Open policy review</button>
        </div>
      </div>

      <div style={{ fontSize: DASH.data, color: BB.text3, marginTop: 8 }}>This board can filter, inspect, refresh evidence and create research watches. It cannot stage, approve or place an order.</div>

      {selected && (() => {
        const monitor = monitorBySector.get(selected.name)
        const accounts = accountRows(selected.card, accountLabels)
        const stocks = (selected.card?.instruments || []).filter((instrument: any) => instrument.kind === 'constituent')
        return (
          <Modal title={`${selected.name} decision review`} onClose={() => setSelected(null)}>
            <div style={{ display: 'grid', gap: 10 }}>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                <span style={statePill(statusTone(selected.status))}>{selected.status}</span>
                <button type="button" onClick={() => void openEvidence(selected.sector.etf)} style={actionButton('secondary')}>Open {selected.sector.etf} evidence</button>
                <button type="button" onClick={() => void watchSector(selected)} disabled={watched[selected.name] || Boolean(monitor?.is_watched)} style={actionButton('secondary')}>{watched[selected.name] || monitor?.is_watched ? 'Watching' : 'Watch sector'}</button>
                <button type="button" onClick={() => void openRotationReview(selected)} style={actionButton('primary')}>Copy brief + Rotation</button>
                <button type="button" onClick={() => navigate('/watch?tab=watchlist')} style={actionButton('secondary')}>Open Watchlist</button>
              </div>

              <div style={{ border: `1px solid ${BB.borderHair}`, background: BB.bg, padding: 10 }}>
                <div style={{ fontSize: DASH.section, fontWeight: 800, color: BB.text1 }}>Decision evidence</div>
                <div style={{ fontSize: DASH.data, color: BB.text2, marginTop: 5 }}>{selected.why}</div>
                <div style={{ fontSize: DASH.data, color: BB.text3, marginTop: 4 }}>RS20 {signed(selected.sector.rs20)} · slope {signed(selected.sector.slope)} · breadth {selected.sector.breadth_pct ?? '—'}% · book {selected.sector.book_pct ?? '—'}% · as of {selected.sector.as_of || '—'}</div>
              </div>

              <div style={{ border: `1px solid ${BB.borderHair}`, background: BB.bg, padding: 10 }}>
                <div style={{ fontSize: DASH.section, fontWeight: 800, color: BB.text1 }}>Blocking and promotion gates</div>
                {(selected.blocking.length ? selected.blocking : ['No blockers recorded; inspect the governed card before any proposal review.']).map((item, index) => <div key={index} style={{ fontSize: DASH.data, color: BB.text2, padding: '3px 0' }}>• {item}</div>)}
              </div>

              {accounts.length > 0 && <div style={{ border: `1px solid ${BB.borderHair}`, background: BB.bg, padding: 10 }}>
                <div style={{ fontSize: DASH.section, fontWeight: 800, color: BB.text1 }}>Account-specific capacity</div>
                {accounts.map(row => <div key={row.account} style={{ fontSize: DASH.data, color: BB.text2, padding: '4px 0', borderBottom: `1px solid ${BB.borderHair}` }}><b>{row.label}</b> · current {row.current ?? '—'}% · target {row.target ?? '—'}% · capacity {row.capacity ?? '—'}%{row.low != null && row.high != null ? ` · act ${row.low}–${row.high}%` : ''}{Array.isArray(row.dollars) ? ` · ${money(row.dollars[0])}–${money(row.dollars[1])}` : ''}</div>)}
              </div>}

              <div style={{ border: `1px solid ${BB.borderHair}`, background: BB.bg, padding: 10 }}>
                <div style={{ fontSize: DASH.section, fontWeight: 800, color: BB.text1 }}>Screened names and instrument evidence</div>
                {(monitor?.candidates || []).length ? (monitor.candidates || []).slice(0, 12).map((candidate: any) => <button type="button" key={candidate.symbol} aria-label={`${candidate.symbol} — open evidence`} onClick={() => void openEvidence(candidate.symbol)} style={{ display: 'flex', width: '100%', justifyContent: 'space-between', gap: 8, background: 'transparent', border: 0, borderBottom: `1px solid ${BB.borderHair}`, padding: '6px 2px', color: BB.text2, cursor: 'pointer', textAlign: 'left' }}><b style={{ ...numStyle, color: T.link }}>{candidate.symbol}</b><span>RSI {candidate.rsi ?? '—'} · {candidate.trend || 'trend unavailable'} · screen {candidate.score ?? '—'} →</span></button>) : <div style={{ fontSize: DASH.data, color: BB.text3 }}>No current sector-monitor candidates were returned.</div>}
                {stocks.length > 0 && <div style={{ marginTop: 8, fontSize: DASH.data, color: BB.text2 }}>Governed-card constituents: {stocks.map((stock: any) => stock.symbol).join(', ')}</div>}
              </div>
            </div>
          </Modal>
        )
      })()}

      {riskReview && <Modal title="Governed defense action review" onClose={() => setRiskReview(null)}>
        <div style={{ fontSize: DASH.section, fontWeight: 800, color: BB.text1 }}>{riskReview.title}</div>
        <div style={{ fontSize: DASH.data, color: BB.text2, marginTop: 8 }}><b>Entry logic:</b> {riskReview.entry_logic || 'not reported'}</div>
        <div style={{ fontSize: DASH.data, color: BB.amber, marginTop: 5 }}><b>Invalidation:</b> {riskReview.invalidation || 'not reported'}</div>
        <div style={{ fontSize: DASH.data, color: BB.text3, marginTop: 8 }}>Mode: {riskReview.mode || 'advisory'} · this review does not stage, approve or place an order.</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 12 }}>
          <button type="button" onClick={() => { void copyText(`${riskReview.title}\nEntry: ${riskReview.entry_logic || 'not reported'}\nInvalidation: ${riskReview.invalidation || 'not reported'}`); setToast('Defense action copied.') }} style={actionButton('secondary')}>Copy action</button>
          <button type="button" onClick={() => navigate('/defense')} style={actionButton('primary')}>Open Defense Desk</button>
        </div>
      </Modal>}

      {policyReview && <Modal title="Operator policy review" onClose={() => setPolicyReview(false)}>
        <div style={{ fontSize: DASH.data, color: BB.text2 }}>Current directive: {leanReview.enabled ? 'DEFENSIVE LEAN enabled' : 'no enabled directive reported'}.</div>
        <div style={{ fontSize: DASH.data, color: BB.text2, marginTop: 6 }}>Set at: {leanReview.set_at || 'not reported'} · review due: {leanReview.requires_review ? 'yes' : 'no'}.</div>
        <div style={{ fontSize: DASH.data, color: BB.text2, marginTop: 6 }}>Conflicting sectors: {(leanReview.conflicting_sectors || []).join(', ') || 'none listed'}.</div>
        <div style={{ fontSize: DASH.data, color: BB.amber, marginTop: 10 }}>This surface does not invent a retain/revoke endpoint. Use the existing operator policy workflow after reviewing the evidence.</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 12 }}>
          <button type="button" onClick={() => { const text = `Review the DEFENSIVE LEAN directive set ${leanReview.set_at || 'at an unknown date'}. Conflicts: ${(leanReview.conflicting_sectors || []).join(', ') || 'none listed'}. Decide whether to retain or revoke it; remain SHADOW and do not place orders.`; void copyText(text); setToast('Policy review brief copied.'); navigate('/rotation?from=policy-review') }} style={actionButton('primary')}>Copy brief + Rotation</button>
          <button type="button" onClick={() => setPolicyReview(false)} style={actionButton('secondary')}>Close without change</button>
        </div>
      </Modal>}

      {evidence && <Modal title={`Symbol evidence · ${evidence.symbol}`} onClose={() => setEvidence(null)}>
        {evidence.loading ? <div style={{ color: BB.text3 }}>Loading provenance…</div> : evidence.error ? <div style={{ color: BB.red }}>Evidence unavailable: {evidence.error}</div> : <pre style={{ margin: 0, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: DASH.data, lineHeight: 1.45, color: BB.text2, background: BB.bg, border: `1px solid ${BB.borderHair}`, padding: 10 }}>{JSON.stringify(evidence.payload, null, 2).slice(0, 12_000)}</pre>}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
          <button type="button" onClick={() => { void copyText(evidence.symbol); navigate('/watch?tab=watchlist') }} style={actionButton('primary')}>Copy {evidence.symbol} + open Watchlist</button>
          <button type="button" onClick={() => setEvidence(null)} style={actionButton('secondary')}>Close</button>
        </div>
      </Modal>}
    </section>
  )
}
