import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { BB, T } from '../lib/watchTokens'

const panel: CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 4 }
const button = (active = false): CSSProperties => ({ fontSize: 10.5, fontWeight: 800, padding: '6px 9px', borderRadius: 3, cursor: 'pointer', border: `1px solid ${active ? T.link : 'var(--border)'}`, background: active ? 'rgba(96,165,250,.10)' : 'transparent', color: active ? T.link : BB.text2 })
const primaryButton: CSSProperties = { ...button(true), minWidth: 104, textAlign: 'center' }

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
  const asOf = text(item?.fundamentals_as_of, fv?.fundamentals_as_of, card?.fundamentals_as_of, item?.decision_packet?.fundamentals?.fundamentals_as_of, item?.last_enriched_at)
  const instrument = text(item?.instrument_type, item?.asset_type).toLowerCase()
  return { pe, forwardPe, peg, asOf, notApplicable: /etf|fund|mutual/.test(instrument), available: pe !== null || forwardPe !== null || peg !== null }
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
  if (symbol) url.searchParams.set('symbol', symbol)
  else url.searchParams.delete('symbol')
  if (reviewOpen) url.searchParams.set('review', '1')
  else url.searchParams.delete('review')
  window.history.replaceState(window.history.state, '', url)
}

export default function WatchTruthAuditPanel() {
  const { data: wl, refetch: refetchWatch } = useApi<any>('/api/v2/watchlist/items?sort=hermes', 60_000)
  const { data: fv } = useApi<any>('/api/v2/finviz-strip-map', 300_000)
  const { data: cards } = useApi<any>('/api/v2/symbol-cards', 300_000)
  const [open, setOpen] = useState(() => new URL(window.location.href).searchParams.get('review') === '1')
  const [lane, setLane] = useState<'favorites' | 'automated' | 'all'>('favorites')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(() => new URL(window.location.href).searchParams.get('symbol')?.toUpperCase() ?? '')
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
  const shown = (lane === 'favorites' ? favorites : lane === 'automated' ? automated : unique)
    .filter(item => !search.trim() || `${item.symbol} ${item.origin_system ?? ''} ${item.profile_sector ?? ''}`.toUpperCase().includes(search.trim().toUpperCase()))
    .slice(0, 30)

  useEffect(() => {
    if (selected && unique.some(item => String(item.symbol).toUpperCase() === selected)) return
    const first = favorites[0] ?? unique[0]
    if (first) setSelected(String(first.symbol).toUpperCase())
  }, [unique.length, favorites.length])

  const selectedItem = unique.find(item => String(item.symbol).toUpperCase() === selected)
  const selectedVal = selectedItem ? valuation(selectedItem, fvMap[selected], cardMap[selected]) : null
  const selectedTicket = selectedItem ? ticketState(selectedItem) : null

  const selectForReview = (symbol: string) => {
    setSelected(symbol)
    setOpen(true)
    setMessage('')
    setPremium(null)
    updateReviewUrl(symbol, true)
  }
  const setDeskOpen = (next: boolean) => {
    setOpen(next)
    updateReviewUrl(selected, next)
  }

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

  const selectedPrice = selectedItem ? num(selectedItem.price, selectedItem.last_price, selectedItem.price_live) : null
  const selectedRsi = selectedItem ? num(selectedItem.rsi, selectedItem.rsi_14, fvMap[selected]?.rsi) : null
  const selectedPriceAt = selectedItem ? text(selectedItem.price_as_of, selectedItem.last_enriched_at) : ''

  return <section style={{ ...panel, margin: '8px 0 12px', overflow: 'hidden' }} aria-label="Watch truth and independent review">
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto', alignItems: 'center', gap: 12, padding: '10px 12px' }}>
      <div><div style={{ fontSize: 13, fontWeight: 900 }}>Truth & independent review</div><div style={{ marginTop: 2, fontSize: 10.5, color: BB.text3 }}>Choose a symbol, then use the clearly labeled review actions. Row clicks and Enter/Space select the symbol; no broker action occurs here.</div></div>
      <button onClick={() => setDeskOpen(!open)} aria-expanded={open} style={primaryButton}>{open ? 'CLOSE REVIEW DESK' : 'OPEN REVIEW DESK'}</button>
    </div>

    {!open && <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '8px 12px', borderTop: '1px solid var(--border)', background: 'var(--bg2)', flexWrap: 'wrap' }}><span style={{ fontSize: 10.5, color: BB.text3 }}>Favorites {favorites.length} · Automated {automated.length}</span>{selected && <><span style={{ color: BB.text2, fontSize: 10.5 }}>Current symbol: <b>{selected}</b></span><button onClick={() => setDeskOpen(true)} style={button(true)}>REVIEW {selected}</button><button onClick={() => { window.location.href = `/v3/portfolio/re-entry?classify=${encodeURIComponent(selected)}` }} style={button(false)}>CLASSIFY RE-ENTRY</button></>}</div>}

    {open && <div style={{ borderTop: '1px solid var(--border)', padding: 10 }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>{([['favorites', `★ Favorites ${favorites.length}`], ['automated', `Automated ${automated.length}`], ['all', `All ${unique.length}`]] as const).map(([key, label]) => <button key={key} onClick={() => setLane(key)} style={button(lane === key)}>{label}</button>)}<input value={search} onChange={event => setSearch(event.target.value)} placeholder="Filter symbol, origin, sector…" aria-label="Filter Watch review symbols" style={{ marginLeft: 'auto', minWidth: 240, fontSize: 11, padding: '6px 8px', background: 'var(--bg2)', border: '1px solid var(--border)', color: BB.text0 }} /></div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(620px,1.2fr) minmax(330px,.8fr)', gap: 10, marginTop: 9, alignItems: 'start' }}>
        <div style={{ ...panel, overflow: 'hidden' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '100px 155px 85px 85px 120px 1fr 118px', gap: 7, padding: '7px 8px', borderBottom: '1px solid var(--border)', fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}><span>Symbol</span><span>Origin</span><span>Price</span><span>Valuation</span><span>Ticket</span><span>Coverage</span><span>Open</span></div>
          {shown.map(item => {
            const symbol = String(item.symbol).toUpperCase(); const value = valuation(item, fvMap[symbol], cardMap[symbol]); const ticket = ticketState(item); const rsi = num(item.rsi, item.rsi_14, fvMap[symbol]?.rsi); const price = num(item.price, item.last_price, item.price_live); const priceAt = text(item.price_as_of, item.last_enriched_at); const isSelected = selected === symbol
            const coverage = [price === null ? 'price unavailable' : `price ${age(priceAt)}`, rsi === null ? 'technical unavailable' : `RSI ${rsi.toFixed(1)}`, value.notApplicable ? 'valuation N/A' : value.available ? `valuation ${age(value.asOf)}` : 'valuation unavailable', item.catalyst_headline ? `catalyst ${age(item.catalyst_at)}` : 'catalyst unavailable'].join(' · ')
            return <div key={symbol} role="button" tabIndex={0} aria-selected={isSelected} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectForReview(symbol) } }} onClick={() => selectForReview(symbol)} style={{ display: 'grid', gridTemplateColumns: '100px 155px 85px 85px 120px 1fr 118px', gap: 7, padding: '8px', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10.5, cursor: 'pointer', background: isSelected ? 'var(--bg2)' : 'transparent', boxShadow: isSelected ? `inset 3px 0 0 ${T.link}` : undefined }}><div><b style={{ fontSize: 13 }}>{symbol}</b><br /><span style={{ color: BB.text3 }}>{item.starred ? '★ favorite' : 'system'}</span></div><div>{originLabel(item)}<br /><span style={{ color: BB.text3 }}>{text(item.profile_sector, 'sector unavailable')}</span></div><div><b>{money(price)}</b><br /><span style={{ color: BB.text3 }}>{age(priceAt)}</span></div><div>{value.notApplicable ? 'N/A' : <><span>P/E {value.pe === null ? '—' : value.pe.toFixed(1)}</span><br /><span style={{ color: BB.text3 }}>Fwd {value.forwardPe === null ? '—' : value.forwardPe.toFixed(1)}</span></>}</div><div><b style={{ color: isFailure(ticket.deterministic) ? BB.red : BB.text1 }}>{ticket.deterministic}</b><br /><span style={{ color: isFailure(ticket.reconciled) ? BB.red : BB.text3 }}>{ticket.reconciled}</span></div><div style={{ color: BB.text3 }}>{coverage}</div><div onClick={event => event.stopPropagation()}><button onClick={() => selectForReview(symbol)} aria-label={`Open review for ${symbol}`} style={isSelected ? primaryButton : button(false)}>{isSelected ? 'SELECTED' : 'OPEN REVIEW'}</button></div></div>
          })}
          {!shown.length && <div style={{ padding: 16, color: BB.text3 }}>No symbols match this lane and filter.</div>}
        </div>

        <aside style={{ ...panel, padding: 10, position: 'sticky', top: 8 }} aria-live="polite">
          {!selectedItem || !selectedVal || !selectedTicket ? <div style={{ color: BB.text3 }}>Choose a symbol from the list to open its evidence and actions.</div> : <>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}><b style={{ fontSize: 16 }}>{selected}</b><span style={{ color: BB.text3, fontSize: 10.5 }}>{originLabel(selectedItem)}</span><button onClick={() => void toggleStar(selectedItem)} style={{ ...button(Boolean(selectedItem.starred)), marginLeft: 'auto' }}>{selectedItem.starred ? 'UNSTAR' : 'PROMOTE ★'}</button></div>
            <div style={{ marginTop: 5, fontSize: 10.5, color: BB.text3 }}>{text(selectedItem.profile_sector, 'sector unavailable')} · price {money(selectedPrice)} ({age(selectedPriceAt)}) · RSI {selectedRsi === null ? '—' : selectedRsi.toFixed(1)}</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0, marginTop: 9, borderTop: '1px solid var(--border)', borderLeft: '1px solid var(--border)' }}>{[['DETERMINISTIC', selectedTicket.deterministic], ['RECONCILED', selectedTicket.reconciled], ['LOCAL', selectedTicket.local], ['GROK OAUTH', selectedTicket.grok], ['CHATGPT OAUTH', selectedTicket.chatgpt], ['VALUATION', selectedVal.notApplicable ? 'N/A' : selectedVal.available ? `P/E ${selectedVal.pe ?? '—'}` : 'UNAVAILABLE']].map(([label, value]) => <div key={label} style={{ padding: 7, borderRight: '1px solid var(--border)', borderBottom: '1px solid var(--border)' }}><div style={{ color: BB.text3, fontSize: 10 }}>{label}</div><b style={{ color: isFailure(String(value)) ? BB.red : BB.text1 }}>{value}</b></div>)}</div>
            <div style={{ marginTop: 8, fontSize: 10, color: BB.text3 }}>Review actions create independent critique artifacts only. Deterministic validation remains the release authority.</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 9 }}><button disabled={Boolean(reviewBusy)} onClick={() => void runReview('local', 'Local critic')} style={button(false)}>{reviewBusy === 'Local critic' ? 'LOCAL…' : 'RUN LOCAL'}</button><button disabled={Boolean(reviewBusy)} onClick={() => void runReview('grok', 'Grok OAuth')} style={button(false)}>{reviewBusy === 'Grok OAuth' ? 'GROK…' : 'RUN GROK OAUTH'}</button><button disabled={Boolean(reviewBusy)} onClick={() => void runReview('chatgpt', 'ChatGPT OAuth')} style={button(false)}>{reviewBusy === 'ChatGPT OAuth' ? 'CHATGPT…' : 'RUN CHATGPT OAUTH'}</button><button disabled={Boolean(reviewBusy)} onClick={() => void runReview('local,grok,chatgpt', 'All free critics')} style={button(true)}>{reviewBusy === 'All free critics' ? 'ALL FREE…' : 'RUN ALL FREE'}</button></div>
            <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}><button onClick={() => { window.location.href = `/v3/portfolio/re-entry?classify=${encodeURIComponent(selected)}` }} style={primaryButton}>CLASSIFY RE-ENTRY</button><button onClick={() => { window.location.href = `/v3/rotation?symbol=${encodeURIComponent(selected)}` }} style={button(false)}>OPEN ROTATION</button><button disabled={Boolean(reviewBusy)} onClick={() => void estimatePremium()} style={button(false)}>{reviewBusy === 'premium estimate' ? 'ESTIMATING…' : 'PAID EXPERT…'}</button></div>
            {message && <div style={{ marginTop: 8, color: /failed|error|not configured|not implemented/i.test(message) ? BB.red : BB.text2, fontSize: 10.5 }}>{message}</div>}
            {premium && <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border)' }}>{premium.available ? <><div style={{ fontSize: 10 }}>{premium.provider}/{premium.model} · estimated ${Number(premium.est_cost_usd).toFixed(4)} · latency {premium.expected_latency_s}s</div><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 7 }}>TYPE EXACTLY: <code>{premium.confirm_with}</code><input value={confirmation} onChange={event => setConfirmation(event.target.value)} style={{ width: '100%', boxSizing: 'border-box', marginTop: 4, fontSize: 11, padding: '6px 8px', background: 'var(--bg1)', border: '1px solid var(--border)', color: BB.text0 }} /></label><button disabled={confirmation !== premium.confirm_with || Boolean(reviewBusy)} onClick={() => void runPremium()} style={{ ...button(true), marginTop: 7, opacity: confirmation === premium.confirm_with ? 1 : .5 }}>CONFIRM PAID REVIEW</button></> : <div style={{ fontSize: 10, color: BB.text2 }}>{premium.reason}<br />No paid call was made.</div>}</div>}
          </>}
        </aside>
      </div>
    </div>}
  </section>
}
