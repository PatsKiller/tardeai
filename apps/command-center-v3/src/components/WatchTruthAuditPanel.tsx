/**
 * MAIN Setup Desk — visual + logic redesign (2026-07-31).
 * Default surface is ticket-honest GO/WAIT/NOGO on MAIN admission,
 * not Favorites/Automated/Hermes top-200.
 */
import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { BB, T, heatRamp } from '../lib/watchTokens'

export const WATCH_OPERATOR_CONTRACT = 'watch-operator-v3-main'

function levelHeat(distancePct: number | null): string {
  if (distancePct === null || !Number.isFinite(distancePct)) return BB.text3
  return heatRamp(Math.max(-3, Math.min(3, (distancePct / 8) * 3)))
}
function signedPct(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
}
const VAL_TIP = {
  pe: 'Trailing P/E — evidence only, not a signal.',
  fwd: 'Forward P/E estimate.',
  pb: 'Price-to-book.',
  ps: 'Price-to-sales.',
}

const shell: CSSProperties = {
  background: 'var(--bg1)',
  border: `1px solid ${BB.border}`,
  borderRadius: 8,
  margin: '8px 0 14px',
  overflow: 'hidden',
}
const chip = (active: boolean, color: string): CSSProperties => ({
  fontSize: 12,
  fontWeight: 800,
  padding: '10px 16px',
  borderRadius: 8,
  cursor: 'pointer',
  border: `2px solid ${active ? color : BB.border}`,
  background: active ? `${color}22` : 'var(--bg2)',
  color: active ? color : BB.text2,
  minWidth: 88,
  textAlign: 'center',
})
const btn = (active = false): CSSProperties => ({
  fontSize: 11,
  fontWeight: 800,
  padding: '7px 11px',
  borderRadius: 6,
  cursor: 'pointer',
  border: `1px solid ${active ? T.link : BB.border}`,
  background: active ? `${T.link}18` : 'transparent',
  color: active ? T.link : BB.text2,
})
const primaryBtn: CSSProperties = { ...btn(true), minWidth: 120, textAlign: 'center' }
const PAGE_SIZE = 12

type Lane = 'go' | 'wait' | 'nogo' | 'favorites' | 'legacy'
type QueueFilter = 'all' | 'needs_review' | 'deterministic_fail' | 'data_gaps' | 'actionable'

function num(...values: any[]): number | null {
  for (const value of values) {
    if (value === null || value === undefined || value === '') continue
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}
function text(...values: any[]): string {
  for (const value of values) if (value !== null && value !== undefined && String(value).trim()) return String(value).trim()
  return ''
}
function dig(value: any, path: string): any {
  return path.split('.').reduce((current: any, key) => current?.[key], value)
}
function money(value: any): string {
  const parsed = num(value)
  return parsed === null ? '—' : `$${parsed.toFixed(2)}`
}
function age(value: any): string {
  if (!value) return 'as-of unavailable'
  const time = new Date(value).getTime()
  if (!Number.isFinite(time)) return String(value).slice(0, 16)
  const hours = Math.max(0, Math.round((Date.now() - time) / 36e5))
  return hours < 1 ? 'current' : hours < 48 ? `${hours}h old` : `${Math.round(hours / 24)}d old`
}
function valuation(item: any, fv: any, card: any) {
  const objects = [item, fv, card, item?.fundamentals, fv?.fundamentals, card?.fundamentals, item?.decision_packet?.fundamentals]
  const first = (paths: string[]) => {
    for (const object of objects) for (const path of paths) {
      const value = num(dig(object, path))
      if (value !== null) return value
    }
    return null
  }
  const pe = first(['pe', 'trailing_pe', 'trailingPe', 'valuation.pe'])
  const forwardPe = first(['forward_pe', 'forwardPe', 'fwd_pe', 'valuation.forward_pe'])
  const peg = first(['peg', 'peg_ratio', 'valuation.peg'])
  const pb = first(['pb', 'price_to_book', 'valuation.pb'])
  const ps = first(['ps', 'price_to_sales', 'valuation.ps'])
  const asOf = text(item?.fundamentals_as_of, fv?.fundamentals_as_of, card?.fundamentals_as_of, item?.last_enriched_at)
  const instrument = text(item?.instrument_type, item?.asset_type).toLowerCase()
  return {
    pe, forwardPe, peg, pb, ps, asOf,
    notApplicable: /etf|fund|mutual/.test(instrument),
    available: pe !== null || forwardPe !== null || peg !== null || pb !== null || ps !== null,
  }
}
function ticketState(item: any) {
  const packet = item?.decision_packet ?? {}
  const validation = packet?.current_actionable_plan?.ticket_validation ?? {}
  const review = packet?.ticket_review ?? {}
  return {
    deterministic: text(validation.state, review?.tickets_validated?.[0]?.state, 'NOT RUN').toUpperCase(),
    reconciled: text(review?.reconciled?.state, 'UNVALIDATED').toUpperCase(),
    local: text(review?.reviews?.local?.verdict, 'NOT RUN').toUpperCase(),
    grok: text(review?.reviews?.grok?.verdict, 'NOT RUN').toUpperCase(),
    chatgpt: text(review?.reviews?.chatgpt?.verdict, 'NOT RUN').toUpperCase(),
  }
}
function isFailure(value: string): boolean { return /FAIL|REJECT|BLOCK/.test(value) }
function originLabel(item: any): string {
  return item?.starred ? 'Operator favorite' : text(item?.origin_system, item?.source, 'system').replace(/_/g, ' ')
}
function updateReviewUrl(symbol: string, reviewOpen: boolean) {
  const url = new URL(window.location.href)
  if (symbol) url.searchParams.set('symbol', symbol); else url.searchParams.delete('symbol')
  if (reviewOpen) url.searchParams.set('review', '1'); else url.searchParams.delete('review')
  window.history.replaceState(window.history.state, '', url)
}

/** Server MAIN admission (lane membership). */
function admissionNow(item: any): 'GO' | 'WAIT' | 'NOGO' {
  const n = String(item?.now_status || '').toUpperCase()
  if (n === 'GO' || n === 'WAIT' || n === 'NOGO') return n as 'GO' | 'WAIT' | 'NOGO'
  if (item?.starred) return 'WAIT'
  return 'NOGO'
}

/**
 * Operator-visible NOW — ticket truth overrides admission GO.
 * FAIL → NOGO; unvalidated / not run / data gap → WAIT.
 */
function operatorNow(
  item: any,
  ticket: ReturnType<typeof ticketState>,
  hasDataGap: boolean,
  needsReview: boolean,
): 'GO' | 'WAIT' | 'NOGO' {
  const admitted = admissionNow(item)
  if (admitted === 'NOGO') return 'NOGO'
  if (isFailure(ticket.deterministic) || isFailure(ticket.reconciled)) return 'NOGO'
  if (hasDataGap || needsReview || ticket.deterministic === 'NOT RUN' || /QUALITY_NOT_ASSESSED|UNVALIDATED/.test(ticket.reconciled)) {
    return 'WAIT'
  }
  if (admitted === 'GO') return 'GO'
  return admitted
}

function nextAction(
  item: any,
  ticket: ReturnType<typeof ticketState>,
  value: ReturnType<typeof valuation>,
  rsi: number | null,
  now: string,
): string {
  if (now === 'NOGO' && isFailure(ticket.deterministic)) return 'Fix deterministic gate — not proposeable.'
  if (now === 'NOGO') return 'Park / suppress — MAIN NOGO.'
  if (now === 'WAIT') {
    if (ticket.deterministic === 'NOT RUN') return 'Run ticket validation (local / free critics).'
    if (needsUnvalidated(ticket)) return 'Complete independent review before propose.'
    return 'Refresh plan / fill data gaps — MAIN WAIT.'
  }
  if (isFailure(ticket.deterministic)) return 'Open evidence; deterministic failure blocks proposal.'
  if (rsi === null) return 'Refresh technical inputs before acting.'
  if (!value.notApplicable && !value.available) return 'Valuation is missing; review source coverage.'
  return 'Propose / open evidence — MAIN GO setup.'
}
function needsUnvalidated(ticket: ReturnType<typeof ticketState>): boolean {
  return ticket.reconciled === 'UNVALIDATED' || /UNAVAILABLE|PENDING|REQUIRED|QUALITY_NOT_ASSESSED/.test(ticket.reconciled)
}

export default function WatchTruthAuditPanel() {
  const initialUrl = new URL(window.location.href)
  const [open, setOpen] = useState(() => initialUrl.searchParams.get('review') !== '0')
  const [lane, setLane] = useState<Lane>(() => {
    const q = (initialUrl.searchParams.get('now') || initialUrl.searchParams.get('op_lane') || 'go').toLowerCase()
    if (q === 'wait' || q === 'nogo' || q === 'favorites' || q === 'legacy') return q as Lane
    return 'go'
  })
  const [queueFilter, setQueueFilter] = useState<QueueFilter>('all')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(() => initialUrl.searchParams.get('symbol')?.toUpperCase() ?? '')
  const [page, setPage] = useState(0)
  const [reviewBusy, setReviewBusy] = useState('')
  const [message, setMessage] = useState('')
  const [premium, setPremium] = useState<any>(null)
  const [confirmation, setConfirmation] = useState('')

  // One MAIN fetch; client splits ticket-honest GO/WAIT/NOGO. Legacy = old warehouse.
  const itemsPath = lane === 'legacy'
    ? '/api/v2/watchlist/items?sort=hermes&lane=legacy_hermes'
    : '/api/v2/watchlist/items?sort=hermes&lane=main'

  const { data: wl, refetch: refetchWatch } = useApi<any>(itemsPath, 60_000)
  const { data: qualityBoard } = useApi<any>('/api/v2/watchlist/quality-board', 120_000)
  const { data: fv } = useApi<any>('/api/v2/finviz-strip-map', 300_000)
  const { data: cards } = useApi<any>('/api/v2/symbol-cards', 300_000)
  const { data: lv } = useApi<any>('/api/v2/ui/prefs/get?key=portfolio.reentry.resistance.v1', 300_000)
  const levelMap: Record<string, any> = lv?.data?.value?.symbols ?? lv?.value?.symbols ?? {}

  const items: any[] = wl?.items ?? wl?.data?.items ?? []
  const quality = wl?.quality ?? wl?.data?.quality ?? qualityBoard?.main_lane ?? qualityBoard?.data?.main_lane
  const fvMap = fv?.map ?? fv?.data?.map ?? {}
  const cardMap = cards?.cards ?? cards?.data?.cards ?? {}

  const unique = useMemo(() => {
    const map = new Map<string, any>()
    for (const item of items) {
      const symbol = text(item?.symbol).toUpperCase()
      if (!symbol) continue
      const prior = map.get(symbol)
      const rich = (item.starred ? 1e12 : 0) + (item.directive_id ? 1e9 : 0) + (num(item.score) ?? 0)
      const priorRich = prior ? (prior.starred ? 1e12 : 0) + (prior.directive_id ? 1e9 : 0) + (num(prior.score) ?? 0) : -1
      if (!prior || rich > priorRich) map.set(symbol, item)
    }
    return [...map.values()]
  }, [items])

  const classified = useMemo(() => unique.map(item => {
    const symbol = String(item.symbol).toUpperCase()
    const value = valuation(item, fvMap[symbol], cardMap[symbol])
    const ticket = ticketState(item)
    const rsi = num(item.rsi, item.rsi_14, fvMap[symbol]?.rsi)
    const price = num(item.price, item.last_price, item.price_live)
    const priceAt = text(item.price_as_of, item.last_enriched_at)
    const lvl = levelMap[symbol] ?? null
    const level = lvl ? {
      resistance: num(lvl.resistance), resistancePct: num(lvl.distance_pct),
      support: num(lvl.support), supportPct: num(lvl.support_distance_pct),
      resistanceState: text(lvl.state), supportState: text(lvl.support_state),
    } : null
    const hasDataGap = price === null || rsi === null || (!value.notApplicable && !value.available)
    const needsReview = needsUnvalidated(ticket)
    const now = operatorNow(item, ticket, hasDataGap, needsReview)
    const actionable = now === 'GO' && !isFailure(ticket.deterministic) && !hasDataGap
    return {
      item, symbol, value, ticket, rsi, price, priceAt, level,
      hasDataGap, needsReview, actionable, now,
      admitted: admissionNow(item),
      next: nextAction(item, ticket, value, rsi, now),
    }
  }), [unique, fv, cards, lv])

  const trueGo = classified.filter(r => r.now === 'GO')
  const trueWait = classified.filter(r => r.now === 'WAIT')
  const trueNogo = classified.filter(r => r.now === 'NOGO')
  const favorites = classified.filter(r => Boolean(r.item.starred))
  const demotedFromAdmissionGo = classified.filter(r => r.admitted === 'GO' && r.now !== 'GO').length

  const laneRows = classified.filter(row => {
    if (lane === 'go') return row.now === 'GO'
    if (lane === 'wait') return row.now === 'WAIT'
    if (lane === 'nogo') return row.now === 'NOGO'
    if (lane === 'favorites') return Boolean(row.item.starred)
    return true
  })

  const filtered = laneRows.filter(row => {
    if (search.trim() && !`${row.symbol} ${row.item.source ?? ''} ${row.item.profile_sector ?? ''} ${row.ticket.deterministic} ${row.next} ${row.now}`.toUpperCase().includes(search.trim().toUpperCase())) return false
    if (queueFilter === 'needs_review' && !row.needsReview) return false
    if (queueFilter === 'deterministic_fail' && !isFailure(row.ticket.deterministic)) return false
    if (queueFilter === 'data_gaps' && !row.hasDataGap) return false
    if (queueFilter === 'actionable' && !row.actionable) return false
    return true
  })
  // GO lane: true GO first, sort failures out already; prefer higher hermes only as tiebreak
  const sorted = useMemo(() => {
    const list = [...filtered]
    list.sort((a, b) => {
      if (a.actionable !== b.actionable) return a.actionable ? -1 : 1
      if (isFailure(a.ticket.deterministic) !== isFailure(b.ticket.deterministic)) return isFailure(a.ticket.deterministic) ? 1 : -1
      return (num(a.item.hermes_rank) ?? 9999) - (num(b.item.hermes_rank) ?? 9999)
    })
    return list
  }, [filtered])

  const pageCount = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE))
  const safePage = Math.min(page, pageCount - 1)
  const shown = sorted.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE)

  useEffect(() => { setPage(0) }, [lane, queueFilter, search, itemsPath])
  useEffect(() => {
    if (selected && classified.some(r => r.symbol === selected)) return
    const first = (lane === 'go' ? trueGo[0] : null) ?? favorites[0] ?? classified[0]
    if (first) setSelected(first.symbol)
  }, [classified.length, lane, trueGo.length])

  const selectedRow = classified.find(row => row.symbol === selected)
  const selectForReview = (symbol: string) => {
    setSelected(symbol); setOpen(true); setMessage(''); setPremium(null); updateReviewUrl(symbol, true)
  }
  const setDeskOpen = (next: boolean) => { setOpen(next); updateReviewUrl(selected, next) }

  const toggleStar = async (item: any) => {
    const symbol = String(item.symbol).toUpperCase()
    setMessage(`${symbol} — updating favorite…`)
    try {
      const response = await fetch('/api/v2/watchlist/star', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, starred: !item.starred }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.ok === false) throw new Error(payload?.error || 'favorite update failed')
      setMessage(`${symbol} — ${item.starred ? 'unstarred' : 'starred'}`)
      window.setTimeout(() => refetchWatch(), 500)
    } catch (error: any) { setMessage(`${symbol} — ${String(error?.message || error)}`) }
  }
  const runReview = async (lanes: string, label: string) => {
    if (!selected || reviewBusy) return
    setReviewBusy(label); setMessage('')
    try {
      const response = await fetch('/api/v2/watch/ticket-review/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: selected, lanes }),
      })
      const payload = await response.json().catch(() => ({}))
      const data = payload?.data ?? payload
      if (!response.ok || data?.ok === false) throw new Error(data?.error || 'review failed')
      setMessage(`${selected} — ${label} queued.`)
      window.setTimeout(() => refetchWatch(), 6000)
    } catch (error: any) { setMessage(`${selected} — ${String(error?.message || error)}`) }
    finally { setReviewBusy('') }
  }
  const estimatePremium = async () => {
    if (!selected || reviewBusy) return
    setReviewBusy('premium estimate'); setMessage(''); setPremium(null); setConfirmation('')
    try {
      const response = await fetch('/api/v2/watch/ticket-review/premium/estimate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: selected }),
      })
      const payload = await response.json().catch(() => ({}))
      const data = payload?.data ?? payload
      if (!response.ok || data?.ok === false) throw new Error(data?.error || 'estimate failed')
      setPremium(data)
      setMessage(data.available ? `${selected} — paid estimate ready.` : `${selected} — ${data.reason}`)
    } catch (error: any) { setMessage(`${selected} — ${String(error?.message || error)}`) }
    finally { setReviewBusy('') }
  }
  const runPremium = async () => {
    if (!selected || !premium?.available || reviewBusy) return
    setReviewBusy('premium run'); setMessage('')
    try {
      const response = await fetch('/api/v2/watch/ticket-review/premium/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: selected, ticket_hash: premium.ticket_hash, confirmation }),
      })
      const payload = await response.json().catch(() => ({}))
      const data = payload?.data ?? payload
      if (!response.ok || data?.ok === false) throw new Error(data?.error || 'paid review failed')
      setMessage(`${selected} — paid review queued.`); setPremium(null); setConfirmation('')
      window.setTimeout(() => refetchWatch(), 6000)
    } catch (error: any) { setMessage(`${selected} — ${String(error?.message || error)}`) }
    finally { setReviewBusy('') }
  }

  const mainCap = quality?.main_cap ?? 60
  const failures = classified.filter(r => isFailure(r.ticket.deterministic)).length

  return (
    <section style={shell} aria-label="MAIN setup command desk">
      {/* HERO — cannot miss redesign */}
      <div style={{
        padding: '16px 18px',
        background: 'linear-gradient(135deg, rgba(34,197,94,.12), rgba(15,23,42,.9) 45%, rgba(245,158,11,.08))',
        borderBottom: `1px solid ${BB.border}`,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: '.12em', color: BB.green, textTransform: 'uppercase' }}>
              Redesign · MAIN command desk
            </div>
            <div style={{ fontSize: 22, fontWeight: 900, color: BB.text0, marginTop: 4 }}>
              What do I do next?
            </div>
            <div style={{ fontSize: 12, color: BB.text3, marginTop: 4, maxWidth: 560, lineHeight: 1.45 }}>
              Ticket-honest GO only. Admission GO with FAIL / unvalidated tickets demote to WAIT or NOGO
              ({demotedFromAdmissionGo} demoted this load). Contract {WATCH_OPERATOR_CONTRACT}.
            </div>
          </div>
          <button type="button" onClick={() => setDeskOpen(!open)} aria-expanded={open} style={primaryBtn}>
            {open ? 'Collapse' : 'Open desk'}
          </button>
        </div>

        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 14, alignItems: 'stretch' }}>
          {([
            { key: 'go' as Lane, n: trueGo.length, label: 'GO', color: BB.green, hint: 'Propose-ready' },
            { key: 'wait' as Lane, n: trueWait.length, label: 'WAIT', color: BB.amber, hint: 'Fix ticket / data' },
            { key: 'nogo' as Lane, n: trueNogo.length, label: 'NOGO', color: BB.red, hint: 'Park / fail' },
          ]).map(b => (
            <button
              key={b.key}
              type="button"
              onClick={() => { setLane(b.key); setDeskOpen(true) }}
              style={{ ...chip(lane === b.key, b.color), minWidth: 110 }}
            >
              <div style={{ fontSize: 28, fontWeight: 900, lineHeight: 1.1 }}>{b.n}</div>
              <div style={{ fontSize: 12, marginTop: 2 }}>{b.label}</div>
              <div style={{ fontSize: 10, fontWeight: 600, opacity: 0.85, marginTop: 2 }}>{b.hint}</div>
            </button>
          ))}
          <div style={{
            marginLeft: 'auto',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            gap: 4,
            fontSize: 11,
            color: BB.text3,
            minWidth: 160,
          }}>
            <div>MAIN pool {classified.length}/{mainCap}</div>
            <div>★ {favorites.length} · ticket fail {failures}</div>
            <div>actionable {trueGo.length}</div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
          <button type="button" style={chip(lane === 'go', BB.green)} onClick={() => { setLane('go'); setDeskOpen(true) }}>
            Review GO →
          </button>
          <button type="button" style={chip(lane === 'wait', BB.amber)} onClick={() => { setLane('wait'); setDeskOpen(true) }}>
            Fix WAIT →
          </button>
          <button type="button" style={chip(lane === 'nogo', BB.red)} onClick={() => { setLane('nogo'); setDeskOpen(true) }}>
            Cull NOGO →
          </button>
          <button type="button" style={btn(lane === 'favorites')} onClick={() => { setLane('favorites'); setDeskOpen(true) }}>
            ★ Favorites
          </button>
          <button type="button" style={btn(lane === 'legacy')} onClick={() => { setLane('legacy'); setDeskOpen(true) }}>
            Legacy top-200
          </button>
        </div>
      </div>

      {!open && selected && (
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '10px 16px', background: 'var(--bg2)', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, color: BB.text2 }}>Selected <b style={{ color: BB.text0 }}>{selected}</b></span>
          <button type="button" onClick={() => setDeskOpen(true)} style={btn(true)}>Review {selected}</button>
        </div>
      )}

      {open && (
        <div style={{ padding: 12 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
            <span style={{ fontSize: 12, fontWeight: 800, color: BB.text0 }}>
              {lane === 'go' ? 'GO — propose-ready only' : lane === 'wait' ? 'WAIT — unblock these' : lane === 'nogo' ? 'NOGO — park / fail' : lane === 'favorites' ? '★ Favorites' : 'Legacy Hermes top-200'}
            </span>
            <span style={{ fontSize: 11, color: BB.text3 }}>{sorted.length} rows</span>
            <select
              value={queueFilter}
              onChange={e => setQueueFilter(e.target.value as QueueFilter)}
              style={{ fontSize: 11, padding: '6px 8px', background: 'var(--bg2)', border: `1px solid ${BB.border}`, color: BB.text0, borderRadius: 4 }}
            >
              <option value="all">All ticket states</option>
              <option value="deterministic_fail">Deterministic fail</option>
              <option value="needs_review">Needs review</option>
              <option value="data_gaps">Data gaps</option>
              <option value="actionable">Actionable only</option>
            </select>
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Filter symbol…"
              style={{ marginLeft: 'auto', minWidth: 180, fontSize: 11, padding: '6px 8px', background: 'var(--bg2)', border: `1px solid ${BB.border}`, color: BB.text0, borderRadius: 4 }}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.2fr) minmax(300px,.8fr)', gap: 12, alignItems: 'start' }}>
            {/* Compact command list — not a 200-row warehouse */}
            <div style={{ border: `1px solid ${BB.border}`, borderRadius: 8, overflow: 'hidden', background: 'var(--bg1)' }}>
              {shown.map(row => {
                const isSelected = selected === row.symbol
                const nowColor = row.now === 'GO' ? BB.green : row.now === 'WAIT' ? BB.amber : BB.red
                return (
                  <div
                    key={row.symbol}
                    role="button"
                    tabIndex={0}
                    onClick={() => selectForReview(row.symbol)}
                    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectForReview(row.symbol) } }}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '72px 1fr auto',
                      gap: 10,
                      padding: '12px 14px',
                      borderBottom: `1px solid ${BB.border}`,
                      cursor: 'pointer',
                      background: isSelected ? 'var(--bg2)' : 'transparent',
                      boxShadow: isSelected ? `inset 4px 0 0 ${nowColor}` : undefined,
                    }}
                  >
                    <div>
                      <div style={{ fontSize: 15, fontWeight: 900, color: BB.text0 }}>{row.symbol}</div>
                      <div style={{ fontSize: 11, fontWeight: 800, color: nowColor }}>{row.now}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 700, color: isFailure(row.ticket.deterministic) ? BB.red : BB.text1 }}>
                        {row.next}
                      </div>
                      <div style={{ fontSize: 11, color: BB.text3, marginTop: 3 }}>
                        {money(row.price)} · {originLabel(row.item)} · ticket {row.ticket.deterministic}
                        {row.admitted === 'GO' && row.now !== 'GO' ? ' · demoted from admission GO' : ''}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={e => { e.stopPropagation(); selectForReview(row.symbol) }}
                      style={isSelected ? primaryBtn : btn(false)}
                    >
                      {isSelected ? 'Selected' : 'Open'}
                    </button>
                  </div>
                )
              })}
              {!shown.length && (
                <div style={{ padding: 24, color: BB.text3, fontSize: 13 }}>
                  No symbols in this lane. Try WAIT if GO is empty (tickets still unvalidated).
                </div>
              )}
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', fontSize: 11, color: BB.text3 }}>
                <span>{sorted.length} matching · page {safePage + 1}/{pageCount}</span>
                <span style={{ display: 'flex', gap: 6 }}>
                  <button type="button" disabled={safePage === 0} onClick={() => setPage(p => Math.max(0, p - 1))} style={btn(false)}>Prev</button>
                  <button type="button" disabled={safePage >= pageCount - 1} onClick={() => setPage(p => Math.min(pageCount - 1, p + 1))} style={btn(false)}>Next</button>
                </span>
              </div>
            </div>

            <aside style={{ border: `1px solid ${BB.border}`, borderRadius: 8, padding: 12, position: 'sticky', top: 8, background: 'var(--bg1)' }} aria-live="polite">
              {!selectedRow ? (
                <div style={{ color: BB.text3, fontSize: 12 }}>Select a symbol.</div>
              ) : (
                <>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <b style={{ fontSize: 20 }}>{selectedRow.symbol}</b>
                    <span style={{
                      fontSize: 11, fontWeight: 800, padding: '3px 8px', borderRadius: 999,
                      color: selectedRow.now === 'GO' ? BB.green : selectedRow.now === 'WAIT' ? BB.amber : BB.red,
                      border: `1px solid currentColor`,
                    }}>{selectedRow.now}</span>
                    <button type="button" onClick={() => void toggleStar(selectedRow.item)} style={{ ...btn(Boolean(selectedRow.item.starred)), marginLeft: 'auto' }}>
                      {selectedRow.item.starred ? 'Unstar' : '★ Star'}
                    </button>
                  </div>
                  <div style={{ marginTop: 6, fontSize: 11, color: BB.text3 }}>
                    {text(selectedRow.item.profile_sector, '—')} · {money(selectedRow.price)} · RSI {selectedRow.rsi === null ? '—' : selectedRow.rsi.toFixed(1)}
                  </div>
                  <div style={{ marginTop: 10, padding: 10, borderRadius: 6, background: 'var(--bg2)', border: `1px solid ${BB.border}` }}>
                    <div style={{ fontSize: 10, fontWeight: 800, color: BB.text3, letterSpacing: '.06em' }}>NEXT ACTION</div>
                    <div style={{ fontSize: 14, fontWeight: 800, marginTop: 4, color: isFailure(selectedRow.ticket.deterministic) ? BB.red : BB.text0 }}>
                      {selectedRow.next}
                    </div>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0, marginTop: 10, border: `1px solid ${BB.border}`, borderRadius: 6, overflow: 'hidden' }}>
                    {([
                      ['Deterministic', selectedRow.ticket.deterministic],
                      ['Reconciled', selectedRow.ticket.reconciled],
                      ['Local', selectedRow.ticket.local],
                      ['Grok', selectedRow.ticket.grok],
                      ['ChatGPT', selectedRow.ticket.chatgpt],
                      ['Valuation', selectedRow.value.notApplicable ? 'N/A' : selectedRow.value.available ? `P/E ${selectedRow.value.pe ?? '—'}` : '—'],
                    ] as const).map(([label, value]) => (
                      <div key={label} style={{ padding: 8, borderBottom: `1px solid ${BB.border}`, borderRight: `1px solid ${BB.border}` }}>
                        <div style={{ fontSize: 10, color: BB.text3 }}>{label}</div>
                        <b style={{ fontSize: 12, color: isFailure(String(value)) ? BB.red : BB.text1 }}>{value}</b>
                      </div>
                    ))}
                  </div>
                  {!selectedRow.value.notApplicable && (
                    <div style={{ marginTop: 8, fontSize: 11, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                      {([['P/E', selectedRow.value.pe, VAL_TIP.pe], ['Fwd', selectedRow.value.forwardPe, VAL_TIP.fwd], ['P/B', selectedRow.value.pb, VAL_TIP.pb], ['P/S', selectedRow.value.ps, VAL_TIP.ps]] as const).map(([label, value, tip]) => (
                        <span key={label} title={tip}><span style={{ color: BB.text3 }}>{label}</span> <b>{value === null ? '—' : Number(value).toFixed(2)}</b></span>
                      ))}
                    </div>
                  )}
                  {selectedRow.level && (selectedRow.level.resistance !== null || selectedRow.level.support !== null) && (
                    <div style={{ marginTop: 6, fontSize: 11, display: 'flex', gap: 12 }}>
                      <span style={{ color: levelHeat(selectedRow.level.resistancePct) }}>R {selectedRow.level.resistance === null ? '—' : `$${selectedRow.level.resistance.toFixed(2)}`} {signedPct(selectedRow.level.resistancePct)}</span>
                      <span style={{ color: levelHeat(selectedRow.level.supportPct) }}>S {selectedRow.level.support === null ? '—' : `$${selectedRow.level.support.toFixed(2)}`} {signedPct(selectedRow.level.supportPct)}</span>
                    </div>
                  )}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 10 }}>
                    <button type="button" disabled={Boolean(reviewBusy)} onClick={() => void runReview('local', 'Local critic')} style={btn(false)}>{reviewBusy === 'Local critic' ? '…' : 'Run local'}</button>
                    <button type="button" disabled={Boolean(reviewBusy)} onClick={() => void runReview('grok', 'Grok OAuth')} style={btn(false)}>{reviewBusy === 'Grok OAuth' ? '…' : 'Grok OAuth'}</button>
                    <button type="button" disabled={Boolean(reviewBusy)} onClick={() => void runReview('chatgpt', 'ChatGPT OAuth')} style={btn(false)}>{reviewBusy === 'ChatGPT OAuth' ? '…' : 'ChatGPT OAuth'}</button>
                    <button type="button" disabled={Boolean(reviewBusy)} onClick={() => void runReview('local,grok,chatgpt', 'All free critics')} style={btn(true)}>{reviewBusy === 'All free critics' ? '…' : 'All free'}</button>
                  </div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
                    <button type="button" onClick={() => { window.location.href = `/v3/portfolio/re-entry?classify=${encodeURIComponent(selectedRow.symbol)}` }} style={primaryBtn}>Classify Re-Entry</button>
                    <button type="button" onClick={() => { window.location.href = `/v3/rotation?symbol=${encodeURIComponent(selectedRow.symbol)}` }} style={btn(false)}>Rotation</button>
                    <button type="button" disabled={Boolean(reviewBusy)} onClick={() => void estimatePremium()} style={btn(false)}>Paid…</button>
                  </div>
                  {message && <div style={{ marginTop: 8, fontSize: 11, color: /failed|error/i.test(message) ? BB.red : BB.text2 }}>{message}</div>}
                  {premium && (
                    <div style={{ marginTop: 8, paddingTop: 8, borderTop: `1px solid ${BB.border}` }}>
                      {premium.available ? (
                        <>
                          <div style={{ fontSize: 11 }}>{premium.provider}/{premium.model} · est ${Number(premium.est_cost_usd).toFixed(4)}</div>
                          <label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 6 }}>
                            Type: <code>{premium.confirm_with}</code>
                            <input value={confirmation} onChange={e => setConfirmation(e.target.value)} style={{ width: '100%', boxSizing: 'border-box', marginTop: 4, fontSize: 11, padding: '6px 8px', background: 'var(--bg2)', border: `1px solid ${BB.border}`, color: BB.text0 }} />
                          </label>
                          <button type="button" disabled={confirmation !== premium.confirm_with || Boolean(reviewBusy)} onClick={() => void runPremium()} style={{ ...btn(true), marginTop: 6, opacity: confirmation === premium.confirm_with ? 1 : 0.5 }}>Confirm paid</button>
                        </>
                      ) : <div style={{ fontSize: 11, color: BB.text2 }}>{premium.reason}</div>}
                    </div>
                  )}
                </>
              )}
            </aside>
          </div>
        </div>
      )}
    </section>
  )
}
