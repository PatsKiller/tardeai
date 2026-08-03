import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { BB, T, heatRamp } from '../lib/watchTokens'

export const WATCH_OPERATOR_CONTRACT = 'watch-operator-v2'

// Closed-session support/resistance heat. distance% is (price − level)/level, so a
// positive number means price sits ABOVE the level. For both levels positive is the
// favorable direction — above resistance is a breakout, above support is safe — so one
// ramp serves both. ±8% saturates the ramp; a value at the level reads slate.
function levelHeat(distancePct: number | null): string {
  if (distancePct === null || !Number.isFinite(distancePct)) return BB.text3
  return heatRamp(Math.max(-3, Math.min(3, (distancePct / 8) * 3)))
}
function signedPct(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
}
// Tooltip copy for the valuation ratios — plain definitions, never a buy/sell read.
const VAL_TIP = {
  pe: 'Trailing P/E — price ÷ trailing-12-month EPS. Lower is cheaper; blank means no trailing profit. Evidence, not a signal.',
  fwd: 'Forward P/E — price ÷ next-fiscal-year EPS estimate. Blank when no estimate is published.',
  pb: 'Price-to-book — price ÷ book value per share. Below 1 trades under accounting net worth.',
  ps: 'Price-to-sales — price ÷ trailing-12-month revenue per share. Useful where earnings are negative.',
}

const panel: CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 4 }
const button = (active = false): CSSProperties => ({ fontSize: 10.5, fontWeight: 800, padding: '6px 9px', borderRadius: 3, cursor: 'pointer', border: `1px solid ${active ? T.link : 'var(--border)'}`, background: active ? 'rgba(96,165,250,.10)' : 'transparent', color: active ? T.link : BB.text2 })
const primaryButton: CSSProperties = { ...button(true), minWidth: 104, textAlign: 'center' }
const PAGE_SIZE = 20

type Lane = 'favorites' | 'automated' | 'all'
type QueueFilter = 'all' | 'needs_review' | 'deterministic_fail' | 'data_gaps' | 'actionable'

function num(...values: any[]): number | null { for (const value of values) { if (value === null || value === undefined || value === '') continue; const parsed = Number(value); if (Number.isFinite(parsed)) return parsed } return null }
function text(...values: any[]): string { for (const value of values) if (value !== null && value !== undefined && String(value).trim()) return String(value).trim(); return '' }
function dig(value: any, path: string): any { return path.split('.').reduce((current: any, key) => current?.[key], value) }
function money(value: any): string { const parsed = num(value); return parsed === null ? '—' : `$${parsed.toFixed(2)}` }
function age(value: any): string { if (!value) return 'as-of unavailable'; const time = new Date(value).getTime(); if (!Number.isFinite(time)) return String(value).slice(0, 16); const hours = Math.max(0, Math.round((Date.now() - time) / 36e5)); return hours < 1 ? 'current' : hours < 48 ? `${hours}h old` : `${Math.round(hours / 24)}d old` }
function valuation(item: any, fv: any, card: any) {
  const objects = [item, fv, card, item?.fundamentals, fv?.fundamentals, card?.fundamentals, item?.decision_packet?.fundamentals, item?.decision_packet?.current_input_snapshot?.fundamentals, item?.decision_packet?.blind_facts?.fundamentals]
  const first = (paths: string[]) => { for (const object of objects) for (const path of paths) { const value = num(dig(object, path)); if (value !== null) return value } return null }
  const pe = first(['pe', 'trailing_pe', 'trailingPe', 'valuation.pe'])
  const forwardPe = first(['forward_pe', 'forwardPe', 'fwd_pe', 'valuation.forward_pe'])
  const peg = first(['peg', 'peg_ratio', 'valuation.peg'])
  const pb = first(['pb', 'price_to_book', 'valuation.pb'])
  const ps = first(['ps', 'price_to_sales', 'valuation.ps'])
  const asOf = text(item?.fundamentals_as_of, fv?.fundamentals_as_of, card?.fundamentals_as_of, item?.decision_packet?.fundamentals?.fundamentals_as_of, item?.last_enriched_at)
  const instrument = text(item?.instrument_type, item?.asset_type).toLowerCase()
  return { pe, forwardPe, peg, pb, ps, asOf, notApplicable: /etf|fund|mutual/.test(instrument), available: pe !== null || forwardPe !== null || peg !== null || pb !== null || ps !== null }
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
function originLabel(item: any): string { return item?.starred ? 'Operator favorite' : text(item?.origin_system, item?.source, 'Automated').replace(/_/g, ' ') }
function updateReviewUrl(symbol: string, reviewOpen: boolean) {
  const url = new URL(window.location.href)
  if (symbol) url.searchParams.set('symbol', symbol); else url.searchParams.delete('symbol')
  if (reviewOpen) url.searchParams.set('review', '1'); else url.searchParams.delete('review')
  window.history.replaceState(window.history.state, '', url)
}
function nextAction(item: any, ticket: ReturnType<typeof ticketState>, value: ReturnType<typeof valuation>, rsi: number | null): string {
  if (isFailure(ticket.deterministic)) return 'Open evidence; deterministic failure blocks proposal.'
  if (ticket.reconciled === 'UNVALIDATED' || /UNAVAILABLE|PENDING|REQUIRED/.test(ticket.reconciled)) return 'Run or inspect independent review.'
  if (rsi === null) return 'Refresh technical inputs before acting.'
  if (!value.notApplicable && !value.available) return 'Valuation is missing; review source coverage.'
  if (item?.starred) return 'Review current plan, alert and Re-Entry context.'
  return 'Decide whether to promote, suppress or keep automated.'
}

export default function WatchTruthAuditPanel() {
  const { data: wl, refetch: refetchWatch } = useApi<any>('/api/v2/watchlist/items?sort=hermes', 60_000)
  const { data: fv } = useApi<any>('/api/v2/finviz-strip-map', 300_000)
  const { data: cards } = useApi<any>('/api/v2/symbol-cards', 300_000)
  // Closed-session support/resistance for the price cell. Same cache the Re-Entry and
  // Portfolio desks read, so the levels match across surfaces.
  const { data: lv } = useApi<any>('/api/v2/ui/prefs/get?key=portfolio.reentry.resistance.v1', 300_000)
  const levelMap: Record<string, any> = lv?.data?.value?.symbols ?? lv?.value?.symbols ?? {}
  const initialUrl = new URL(window.location.href)
  const [open, setOpen] = useState(() => initialUrl.searchParams.get('review') !== '0')
  const [lane, setLane] = useState<Lane>('favorites')
  const [queueFilter, setQueueFilter] = useState<QueueFilter>('all')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(() => initialUrl.searchParams.get('symbol')?.toUpperCase() ?? '')
  const [page, setPage] = useState(0)
  const [reviewBusy, setReviewBusy] = useState('')
  const [message, setMessage] = useState('')
  const [premium, setPremium] = useState<any>(null)
  const [confirmation, setConfirmation] = useState('')

  const items: any[] = wl?.items ?? wl?.data?.items ?? []
  const fvMap = fv?.map ?? fv?.data?.map ?? {}
  const cardMap = cards?.cards ?? cards?.data?.cards ?? {}
  const unique = useMemo(() => {
    const map = new Map<string, any>()
    for (const item of items) {
      const symbol = text(item?.symbol).toUpperCase(); if (!symbol) continue
      const prior = map.get(symbol)
      const rich = (item.starred ? 1e12 : 0) + (item.directive_id ? 1e9 : 0) + (num(item.score) ?? 0)
      const priorRich = prior ? (prior.starred ? 1e12 : 0) + (prior.directive_id ? 1e9 : 0) + (num(prior.score) ?? 0) : -1
      if (!prior || rich > priorRich) map.set(symbol, item)
    }
    return [...map.values()]
  }, [items])
  const favorites = unique.filter(item => Boolean(item.starred))
  const automated = unique.filter(item => !item.starred)

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
    const needsReview = ticket.reconciled === 'UNVALIDATED' || /UNAVAILABLE|PENDING|REQUIRED/.test(ticket.reconciled)
    const actionable = !isFailure(ticket.deterministic) && !hasDataGap && !needsReview
    return { item, symbol, value, ticket, rsi, price, priceAt, level, hasDataGap, needsReview, actionable, next: nextAction(item, ticket, value, rsi) }
  }), [unique, fv, cards, lv])

  const laneRows = classified.filter(row => lane === 'all' || (lane === 'favorites' ? row.item.starred : !row.item.starred))
  const filtered = laneRows.filter(row => {
    if (search.trim() && !`${row.symbol} ${row.item.origin_system ?? ''} ${row.item.profile_sector ?? ''} ${row.ticket.deterministic} ${row.ticket.reconciled} ${row.next}`.toUpperCase().includes(search.trim().toUpperCase())) return false
    if (queueFilter === 'needs_review' && !row.needsReview) return false
    if (queueFilter === 'deterministic_fail' && !isFailure(row.ticket.deterministic)) return false
    if (queueFilter === 'data_gaps' && !row.hasDataGap) return false
    if (queueFilter === 'actionable' && !row.actionable) return false
    return true
  })
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, pageCount - 1)
  const shown = filtered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE)

  useEffect(() => { setPage(0) }, [lane, queueFilter, search])
  useEffect(() => {
    if (selected && unique.some(item => String(item.symbol).toUpperCase() === selected)) return
    const first = favorites[0] ?? unique[0]
    if (first) setSelected(String(first.symbol).toUpperCase())
  }, [unique.length, favorites.length])

  const selectedRow = classified.find(row => row.symbol === selected)
  const selectForReview = (symbol: string) => { setSelected(symbol); setOpen(true); setMessage(''); setPremium(null); updateReviewUrl(symbol, true) }
  const setDeskOpen = (next: boolean) => { setOpen(next); updateReviewUrl(selected, next) }

  const toggleStar = async (item: any) => {
    const symbol = String(item.symbol).toUpperCase(); setMessage(`${symbol} — updating favorite state…`)
    try {
      const response = await fetch('/api/v2/watchlist/star', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol, starred: !item.starred }) })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.ok === false) throw new Error(payload?.error || 'favorite update failed')
      setMessage(`${symbol} — ${item.starred ? 'removed from favorites' : 'promoted to favorites'}`)
      window.setTimeout(() => refetchWatch(), 500)
    } catch (error: any) { setMessage(`${symbol} — ${String(error?.message || error)}`) }
  }
  const runReview = async (lanes: string, label: string) => {
    if (!selected || reviewBusy) return
    setReviewBusy(label); setMessage('')
    try {
      const response = await fetch('/api/v2/watch/ticket-review/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: selected, lanes }) })
      const payload = await response.json().catch(() => ({})); const data = payload?.data ?? payload
      if (!response.ok || data?.ok === false) throw new Error(data?.error || 'review failed')
      setMessage(`${selected} — ${label} queued. Deterministic validation remains authoritative.`)
      window.setTimeout(() => refetchWatch(), 6000)
    } catch (error: any) { setMessage(`${selected} — ${String(error?.message || error)}`) } finally { setReviewBusy('') }
  }
  const estimatePremium = async () => {
    if (!selected || reviewBusy) return
    setReviewBusy('premium estimate'); setMessage(''); setPremium(null); setConfirmation('')
    try {
      const response = await fetch('/api/v2/watch/ticket-review/premium/estimate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: selected }) })
      const payload = await response.json().catch(() => ({})); const data = payload?.data ?? payload
      if (!response.ok || data?.ok === false) throw new Error(data?.error || 'estimate failed')
      setPremium(data); setMessage(data.available ? `${selected} — paid estimate ready; review cost and type the exact confirmation.` : `${selected} — ${data.reason}`)
    } catch (error: any) { setMessage(`${selected} — ${String(error?.message || error)}`) } finally { setReviewBusy('') }
  }
  const runPremium = async () => {
    if (!selected || !premium?.available || reviewBusy) return
    setReviewBusy('premium run'); setMessage('')
    try {
      const response = await fetch('/api/v2/watch/ticket-review/premium/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: selected, ticket_hash: premium.ticket_hash, confirmation }) })
      const payload = await response.json().catch(() => ({})); const data = payload?.data ?? payload
      if (!response.ok || data?.ok === false) throw new Error(data?.error || 'paid review failed')
      setMessage(`${selected} — paid review queued.`); setPremium(null); setConfirmation(''); window.setTimeout(() => refetchWatch(), 6000)
    } catch (error: any) { setMessage(`${selected} — ${String(error?.message || error)}`) } finally { setReviewBusy('') }
  }

  const counts = {
    needsReview: classified.filter(row => row.needsReview).length,
    failures: classified.filter(row => isFailure(row.ticket.deterministic)).length,
    gaps: classified.filter(row => row.hasDataGap).length,
    actionable: classified.filter(row => row.actionable).length,
  }

  return <section style={{ ...panel, margin: '8px 0 12px', overflow: 'hidden' }} aria-label="Watch operator queue and independent review">
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto', alignItems: 'center', gap: 12, padding: '10px 12px' }}>
      <div><div style={{ fontSize: 14, fontWeight: 900 }}>Watch Operator Queue</div><div style={{ marginTop: 2, fontSize: 10.5, color: BB.text3 }}>Click a row or OPEN REVIEW. The selected symbol's evidence and actions remain visible at right. Contract {WATCH_OPERATOR_CONTRACT}.</div></div>
      <button onClick={() => setDeskOpen(!open)} aria-expanded={open} style={primaryButton}>{open ? 'COLLAPSE QUEUE' : 'OPEN OPERATOR QUEUE'}</button>
    </div>

    {!open && <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '8px 12px', borderTop: '1px solid var(--border)', background: 'var(--bg2)', flexWrap: 'wrap' }}><span style={{ fontSize: 10.5, color: BB.text3 }}>Favorites {favorites.length} · Automated {automated.length} · Review needed {counts.needsReview} · Data gaps {counts.gaps}</span>{selected && <><span style={{ color: BB.text2, fontSize: 10.5 }}>Selected: <b>{selected}</b></span><button onClick={() => setDeskOpen(true)} style={button(true)}>REVIEW {selected}</button><button onClick={() => { window.location.href = `/v3/portfolio/re-entry?classify=${encodeURIComponent(selected)}` }} style={button(false)}>CLASSIFY RE-ENTRY</button></>}</div>}

    {open && <div style={{ borderTop: '1px solid var(--border)', padding: 10 }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        {([['favorites', `★ Favorites ${favorites.length}`], ['automated', `Automated ${automated.length}`], ['all', `All ${unique.length}`]] as const).map(([key, label]) => <button key={key} onClick={() => setLane(key)} style={button(lane === key)}>{label}</button>)}
        <select value={queueFilter} onChange={event => setQueueFilter(event.target.value as QueueFilter)} aria-label="Watch operator queue filter" style={{ fontSize: 11, padding: '6px 8px', background: 'var(--bg2)', border: '1px solid var(--border)', color: BB.text0 }}><option value="all">ALL QUEUE STATES</option><option value="needs_review">NEEDS REVIEW ({counts.needsReview})</option><option value="deterministic_fail">DETERMINISTIC FAIL ({counts.failures})</option><option value="data_gaps">DATA GAPS ({counts.gaps})</option><option value="actionable">ACTIONABLE ({counts.actionable})</option></select>
        <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Filter symbol, origin, sector, ticket, action…" aria-label="Filter Watch review symbols" style={{ marginLeft: 'auto', minWidth: 280, fontSize: 11, padding: '6px 8px', background: 'var(--bg2)', border: '1px solid var(--border)', color: BB.text0 }} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(650px,1.25fr) minmax(350px,.75fr)', gap: 10, marginTop: 9, alignItems: 'start' }}>
        <div style={{ ...panel, overflow: 'hidden' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '92px 130px 150px 120px 110px 1fr 108px', gap: 7, padding: '7px 8px', borderBottom: '1px solid var(--border)', fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}><span>Symbol</span><span>Origin</span><span>Levels · Price</span><span>Valuation</span><span>Ticket</span><span>Next action / coverage</span><span>Open</span></div>
          {shown.map(row => {
            const isSelected = selected === row.symbol
            const coverage = [row.price === null ? 'price unavailable' : `price ${age(row.priceAt)}`, row.rsi === null ? 'technical unavailable' : `RSI ${row.rsi.toFixed(1)}`, row.value.notApplicable ? 'valuation N/A' : row.value.available ? `valuation ${age(row.value.asOf)}` : 'valuation unavailable', row.item.catalyst_headline ? `catalyst ${age(row.item.catalyst_at)}` : 'catalyst unavailable'].join(' · ')
            const lvl = row.level
            return <div key={row.symbol} role="button" tabIndex={0} aria-selected={isSelected} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectForReview(row.symbol) } }} onClick={() => selectForReview(row.symbol)} style={{ display: 'grid', gridTemplateColumns: '92px 130px 150px 120px 110px 1fr 108px', gap: 7, padding: '8px', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10.5, cursor: 'pointer', background: isSelected ? 'var(--bg2)' : 'transparent', boxShadow: isSelected ? `inset 3px 0 0 ${T.link}` : undefined }}>
              <div><b style={{ fontSize: 13 }}>{row.symbol}</b><br /><span style={{ color: BB.text3 }}>{row.item.starred ? '★ favorite' : 'system'}</span></div>
              <div>{originLabel(row.item)}<br /><span style={{ color: BB.text3 }}>{text(row.item.profile_sector, 'sector unavailable')}</span></div>
              {/* Levels before the price: resistance overhead, support below, then the live
                  price. Heat-colored by distance so overhead resistance reads warm and a
                  held support reads green. Symbols outside the levels cache show price only. */}
              <div style={{ lineHeight: 1.35 }}>
                {lvl && (lvl.resistance !== null || lvl.support !== null) ? <>
                  <div title={`Closed-session resistance $${lvl.resistance?.toFixed(2) ?? '—'} · ${signedPct(lvl.resistancePct)} from price${lvl.resistanceState ? ` · ${lvl.resistanceState}` : ''}`} style={{ color: levelHeat(lvl.resistancePct), fontWeight: 700 }}>R {lvl.resistance === null ? '—' : `$${lvl.resistance.toFixed(2)}`} <span style={{ fontSize: 10 }}>{signedPct(lvl.resistancePct)}</span></div>
                  <div title={`Closed-session support $${lvl.support?.toFixed(2) ?? '—'} · ${signedPct(lvl.supportPct)} from price${lvl.supportState ? ` · ${lvl.supportState}` : ''}`} style={{ color: levelHeat(lvl.supportPct), fontWeight: 700 }}>S {lvl.support === null ? '—' : `$${lvl.support.toFixed(2)}`} <span style={{ fontSize: 10 }}>{signedPct(lvl.supportPct)}</span></div>
                </> : <span style={{ color: BB.text3, fontSize: 10 }}>levels n/a</span>}
                <div><b>{money(row.price)}</b> <span style={{ color: BB.text3, fontSize: 10 }}>{age(row.priceAt)}</span></div>
              </div>
              <div>{row.value.notApplicable ? 'N/A' : <>
                <span><span title={VAL_TIP.pe} style={{ cursor: 'help', borderBottom: '1px dotted var(--border)' }}>P/E</span> {row.value.pe === null ? '—' : row.value.pe.toFixed(1)} · <span title={VAL_TIP.fwd} style={{ cursor: 'help', borderBottom: '1px dotted var(--border)' }}>Fwd</span> {row.value.forwardPe === null ? '—' : row.value.forwardPe.toFixed(1)}</span><br />
                <span style={{ color: BB.text3 }}><span title={VAL_TIP.pb} style={{ cursor: 'help', borderBottom: '1px dotted var(--border)' }}>P/B</span> {row.value.pb === null ? '—' : row.value.pb.toFixed(1)} · <span title={VAL_TIP.ps} style={{ cursor: 'help', borderBottom: '1px dotted var(--border)' }}>P/S</span> {row.value.ps === null ? '—' : row.value.ps.toFixed(1)}</span>
              </>}</div>
              <div><b style={{ color: isFailure(row.ticket.deterministic) ? BB.red : BB.text1 }}>{row.ticket.deterministic}</b><br /><span style={{ color: isFailure(row.ticket.reconciled) ? BB.red : BB.text3 }}>{row.ticket.reconciled}</span></div>
              <div><b style={{ color: isFailure(row.ticket.deterministic) ? BB.red : BB.text1 }}>{row.next}</b><br /><span style={{ color: BB.text3 }}>{coverage}</span></div>
              <div onClick={event => event.stopPropagation()}><button onClick={() => selectForReview(row.symbol)} aria-label={`Open review for ${row.symbol}`} style={isSelected ? primaryButton : button(false)}>{isSelected ? 'SELECTED' : 'OPEN REVIEW'}</button></div>
            </div>
          })}
          {!shown.length && <div style={{ padding: 16, color: BB.text3 }}>No symbols match this lane, queue state and filter.</div>}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '7px 8px', borderTop: '1px solid var(--border)', color: BB.text3, fontSize: 10.5 }}><span>{filtered.length} matching · page {safePage + 1} of {pageCount}</span><span style={{ display: 'flex', gap: 5 }}><button disabled={safePage === 0} onClick={() => setPage(value => Math.max(0, value - 1))} style={{ ...button(false), opacity: safePage === 0 ? .5 : 1 }}>PREVIOUS</button><button disabled={safePage >= pageCount - 1} onClick={() => setPage(value => Math.min(pageCount - 1, value + 1))} style={{ ...button(false), opacity: safePage >= pageCount - 1 ? .5 : 1 }}>NEXT</button></span></div>
        </div>

        <aside style={{ ...panel, padding: 10, position: 'sticky', top: 8 }} aria-live="polite">
          {!selectedRow ? <div style={{ color: BB.text3 }}>Choose a symbol from the queue to open its evidence and actions.</div> : <>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}><b style={{ fontSize: 17 }}>{selectedRow.symbol}</b><span style={{ color: BB.text3, fontSize: 10.5 }}>{originLabel(selectedRow.item)}</span><button onClick={() => void toggleStar(selectedRow.item)} style={{ ...button(Boolean(selectedRow.item.starred)), marginLeft: 'auto' }}>{selectedRow.item.starred ? 'UNSTAR' : 'PROMOTE ★'}</button></div>
            <div style={{ marginTop: 5, fontSize: 10.5, color: BB.text3 }}>{text(selectedRow.item.profile_sector, 'sector unavailable')} · price {money(selectedRow.price)} ({age(selectedRow.priceAt)}) · RSI {selectedRow.rsi === null ? '—' : selectedRow.rsi.toFixed(1)}</div>
            <div style={{ ...panel, marginTop: 8, padding: 8, background: 'var(--bg2)' }}><div style={{ fontSize: 10, color: BB.text3 }}>NEXT OPERATOR ACTION</div><b style={{ color: isFailure(selectedRow.ticket.deterministic) ? BB.red : BB.text1 }}>{selectedRow.next}</b></div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0, marginTop: 9, borderTop: '1px solid var(--border)', borderLeft: '1px solid var(--border)' }}>{[['DETERMINISTIC', selectedRow.ticket.deterministic], ['RECONCILED', selectedRow.ticket.reconciled], ['LOCAL', selectedRow.ticket.local], ['GROK OAUTH', selectedRow.ticket.grok], ['CHATGPT OAUTH', selectedRow.ticket.chatgpt], ['VALUATION', selectedRow.value.notApplicable ? 'N/A' : selectedRow.value.available ? `P/E ${selectedRow.value.pe ?? '—'}` : 'UNAVAILABLE']].map(([label, value]) => <div key={label} style={{ padding: 7, borderRight: '1px solid var(--border)', borderBottom: '1px solid var(--border)' }}><div style={{ color: BB.text3, fontSize: 10 }}>{label}</div><b style={{ color: isFailure(String(value)) ? BB.red : BB.text1 }}>{value}</b></div>)}</div>
            {!selectedRow.value.notApplicable && <div style={{ marginTop: 8, fontSize: 10.5, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              {([['P/E', selectedRow.value.pe, VAL_TIP.pe], ['Fwd P/E', selectedRow.value.forwardPe, VAL_TIP.fwd], ['P/B', selectedRow.value.pb, VAL_TIP.pb], ['P/S', selectedRow.value.ps, VAL_TIP.ps]] as const).map(([label, value, tip]) => <span key={label} title={tip} style={{ cursor: 'help' }}><span style={{ color: BB.text3, borderBottom: '1px dotted var(--border)' }}>{label}</span> <b>{value === null ? '—' : Number(value).toFixed(2)}</b></span>)}
            </div>}
            {selectedRow.level && (selectedRow.level.resistance !== null || selectedRow.level.support !== null) && <div style={{ marginTop: 6, fontSize: 10.5, display: 'flex', gap: 12 }}>
              <span title={`Closed-session resistance${selectedRow.level.resistanceState ? ` · ${selectedRow.level.resistanceState}` : ''}`} style={{ cursor: 'help', color: levelHeat(selectedRow.level.resistancePct) }}><span style={{ color: BB.text3 }}>R</span> {selectedRow.level.resistance === null ? '—' : `$${selectedRow.level.resistance.toFixed(2)}`} {signedPct(selectedRow.level.resistancePct)}</span>
              <span title={`Closed-session support${selectedRow.level.supportState ? ` · ${selectedRow.level.supportState}` : ''}`} style={{ cursor: 'help', color: levelHeat(selectedRow.level.supportPct) }}><span style={{ color: BB.text3 }}>S</span> {selectedRow.level.support === null ? '—' : `$${selectedRow.level.support.toFixed(2)}`} {signedPct(selectedRow.level.supportPct)}</span>
            </div>}
            <div style={{ marginTop: 8, fontSize: 10, color: BB.text3 }}>Reviews create independent critique artifacts. Deterministic arithmetic, freshness, validation and release remain authoritative.</div>
            {/* Free critics only for RUN ALL FREE. DeepSeek Flash is metered — never in free ensemble.
                DeepSeek Pro is only via PAID EXPERT… (premium estimate + typed confirmation). */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6, marginTop: 9 }}>
              <button disabled={Boolean(reviewBusy)} onClick={() => void runReview('local', 'Local critic')} style={button(false)}>{reviewBusy === 'Local critic' ? 'LOCAL…' : 'RUN LOCAL'}</button>
              <button disabled={Boolean(reviewBusy)} onClick={() => void runReview('grok', 'Grok OAuth')} style={button(false)}>{reviewBusy === 'Grok OAuth' ? 'GROK…' : 'RUN GROK OAUTH'}</button>
              <button disabled={Boolean(reviewBusy)} onClick={() => void runReview('chatgpt', 'ChatGPT OAuth')} style={button(false)}>{reviewBusy === 'ChatGPT OAuth' ? 'CHATGPT…' : 'RUN CHATGPT OAUTH'}</button>
              <button disabled={Boolean(reviewBusy)} onClick={() => void runReview('deepseek-flash', 'DeepSeek Flash')} style={button(false)} title="Metered DeepSeek V4 Flash API — not free">{reviewBusy === 'DeepSeek Flash' ? 'FLASH…' : 'DEEPSEEK FLASH · METERED'}</button>
              <button disabled={Boolean(reviewBusy)} onClick={() => void runReview('local,grok,chatgpt', 'All free critics')} style={button(true)}>{reviewBusy === 'All free critics' ? 'ALL…' : 'RUN ALL FREE'}</button>
            </div>
            <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}><button onClick={() => { window.location.href = `/v3/portfolio/re-entry?classify=${encodeURIComponent(selectedRow.symbol)}` }} style={primaryButton}>CLASSIFY RE-ENTRY</button><button onClick={() => { window.location.href = `/v3/rotation?symbol=${encodeURIComponent(selectedRow.symbol)}` }} style={button(false)}>OPEN ROTATION</button><button disabled={Boolean(reviewBusy)} onClick={() => void estimatePremium()} style={button(false)} title="Paid expert Pro path: cost estimate + typed confirmation before any call">{reviewBusy === 'premium estimate' ? 'ESTIMATING…' : 'PAID EXPERT…'}</button></div>
            {message && <div style={{ marginTop: 8, color: /failed|error|not configured|not implemented/i.test(message) ? BB.red : BB.text2, fontSize: 10.5 }}>{message}</div>}
            {premium && <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border)' }}>{premium.available ? <><div style={{ fontSize: 10 }}>{premium.provider}/{premium.model} · estimated ${Number(premium.est_cost_usd).toFixed(4)} · latency {premium.expected_latency_s}s</div><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 7 }}>TYPE EXACTLY: <code>{premium.confirm_with}</code><input value={confirmation} onChange={event => setConfirmation(event.target.value)} style={{ width: '100%', boxSizing: 'border-box', marginTop: 4, fontSize: 11, padding: '6px 8px', background: 'var(--bg1)', border: '1px solid var(--border)', color: BB.text0 }} /></label><button disabled={confirmation !== premium.confirm_with || Boolean(reviewBusy)} onClick={() => void runPremium()} style={{ ...button(true), marginTop: 7, opacity: confirmation === premium.confirm_with ? 1 : .5 }}>CONFIRM PAID REVIEW</button></> : <div style={{ fontSize: 10, color: BB.text2 }}>{premium.reason}<br />No paid call was made.</div>}</div>}
          </>}
        </aside>
      </div>
    </div>}
  </section>
}
