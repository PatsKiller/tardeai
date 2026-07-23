import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { BB, T } from '../lib/watchTokens'

const panel: CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 3 }
const button = (active = false): CSSProperties => ({ fontSize: 10, fontWeight: 850, padding: '5px 9px', borderRadius: 3, cursor: 'pointer', border: `1px solid ${active ? T.link : 'var(--border)'}`, background: active ? 'rgba(96,165,250,.10)' : 'var(--bg2)', color: active ? T.link : BB.text2 })

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
function dig(value: any, path: string): any { return path.split('.').reduce((current: any, key) => current?.[key], value) }
function money(value: any): string { const parsed = num(value); return parsed === null ? '—' : `$${parsed.toFixed(2)}` }
function age(value: any): string {
  if (!value) return 'as-of unavailable'
  const time = new Date(value).getTime()
  if (!Number.isFinite(time)) return String(value).slice(0, 16)
  const hours = Math.max(0, Math.round((Date.now() - time) / 36e5))
  return hours < 1 ? 'current' : hours < 48 ? `${hours}h old` : `${Math.round(hours / 24)}d old`
}
function valuation(item: any, fv: any, card: any) {
  const objects = [
    item, fv, card,
    item?.fundamentals, fv?.fundamentals, card?.fundamentals,
    item?.decision_packet?.fundamentals,
    item?.decision_packet?.current_input_snapshot?.fundamentals,
    item?.decision_packet?.blind_facts?.fundamentals,
  ]
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
  const asOf = text(
    item?.fundamentals_as_of, fv?.fundamentals_as_of, card?.fundamentals_as_of,
    item?.decision_packet?.fundamentals?.fundamentals_as_of,
    item?.decision_packet?.current_input_snapshot?.fundamentals?.fundamentals_as_of,
    item?.last_enriched_at,
  )
  const instrument = text(item?.instrument_type, item?.asset_type).toLowerCase()
  const notApplicable = /etf|fund|mutual/.test(instrument)
  return { pe, forwardPe, peg, pb, ps, asOf, notApplicable, available: [pe, forwardPe, peg, pb, ps].some(value => value !== null) }
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
    proposalAllowed: Boolean(review?.reconciled?.proposal_allowed),
  }
}
function stateColor(value: string): string {
  if (['PASS', 'VERIFIED', 'APPROVE'].some(token => value.includes(token))) return BB.green
  if (['FAIL', 'REJECT', 'BLOCK'].some(token => value.includes(token))) return BB.red
  if (['CAUTION', 'REVIEW', 'SPLIT', 'UNVALIDATED'].some(token => value.includes(token))) return BB.amber
  return BB.text3
}
function originLabel(item: any): string {
  if (item?.starred) return 'OPERATOR FAVORITE'
  const origin = text(item?.origin_system, item?.source, 'unknown').replace(/_/g, ' ').toUpperCase()
  return `AUTOMATED · ${origin}`
}

export default function WatchTruthAuditPanel() {
  const { data: wl, refetch: refetchWatch } = useApi<any>('/api/v2/watchlist/items?sort=hermes', 60_000)
  const { data: fv } = useApi<any>('/api/v2/finviz-strip-map', 300_000)
  const { data: cards } = useApi<any>('/api/v2/symbol-cards', 300_000)
  const [lane, setLane] = useState<'favorites' | 'automated' | 'all'>('favorites')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState('')
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
      const symbol = text(item?.symbol).toUpperCase()
      if (!symbol) continue
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
    setSelected(first ? String(first.symbol).toUpperCase() : '')
  }, [unique.length, favorites.length])

  const selectedItem = unique.find(item => String(item.symbol).toUpperCase() === selected)
  const selectedVal = selectedItem ? valuation(selectedItem, fvMap[selected], cardMap[selected]) : null
  const selectedTicket = selectedItem ? ticketState(selectedItem) : null

  const toggleStar = async (item: any) => {
    const symbol = String(item.symbol).toUpperCase()
    setMessage(`${symbol} — updating favorite state…`)
    try {
      const response = await fetch('/api/v2/watchlist/star', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol, starred: !item.starred }) })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.ok === false) throw new Error(payload?.error || 'favorite update failed')
      setMessage(`${symbol} — ${item.starred ? 'removed from operator favorites' : 'promoted to operator favorites'}`)
      window.setTimeout(() => refetchWatch(), 500)
    } catch (error: any) {
      setMessage(`${symbol} — ${String(error?.message || error)}`)
    }
  }

  const runReview = async (lanes: string, label: string) => {
    if (!selected || reviewBusy) return
    setReviewBusy(label); setMessage('')
    try {
      const response = await fetch('/api/v2/watch/ticket-review/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: selected, lanes }) })
      const payload = await response.json().catch(() => ({}))
      const data = payload?.data ?? payload
      if (!response.ok || data?.ok === false) throw new Error(data?.error || 'review failed')
      setMessage(`${selected} — ${label} queued. Deterministic validation remains authoritative.`)
      window.setTimeout(() => refetchWatch(), 6000)
    } catch (error: any) {
      setMessage(`${selected} — ${String(error?.message || error)}`)
    } finally {
      setReviewBusy('')
    }
  }

  const estimatePremium = async () => {
    if (!selected || reviewBusy) return
    setReviewBusy('premium estimate'); setMessage(''); setPremium(null); setConfirmation('')
    try {
      const response = await fetch('/api/v2/watch/ticket-review/premium/estimate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: selected }) })
      const payload = await response.json().catch(() => ({}))
      const data = payload?.data ?? payload
      if (!response.ok || data?.ok === false) throw new Error(data?.error || 'estimate failed')
      setPremium(data)
      setMessage(data.available ? `${selected} — paid estimate ready; review cost and type the exact confirmation.` : `${selected} — ${data.reason}`)
    } catch (error: any) {
      setMessage(`${selected} — ${String(error?.message || error)}`)
    } finally {
      setReviewBusy('')
    }
  }

  const runPremium = async () => {
    if (!selected || !premium?.available || reviewBusy) return
    setReviewBusy('premium run'); setMessage('')
    try {
      const response = await fetch('/api/v2/watch/ticket-review/premium/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: selected, ticket_hash: premium.ticket_hash, confirmation }) })
      const payload = await response.json().catch(() => ({}))
      const data = payload?.data ?? payload
      if (!response.ok || data?.ok === false) throw new Error(data?.error || 'paid review failed')
      setMessage(`${selected} — paid review queued.`)
      setPremium(null); setConfirmation('')
      window.setTimeout(() => refetchWatch(), 6000)
    } catch (error: any) {
      setMessage(`${selected} — ${String(error?.message || error)}`)
    } finally {
      setReviewBusy('')
    }
  }

  return <div style={{ ...panel, padding: 10, margin: '8px 0 12px', borderColor: T.link }}>
    <div style={{ display: 'flex', gap: 10, alignItems: 'start', flexWrap: 'wrap' }}><div style={{ flex: 1 }}><div style={{ fontSize: 14, fontWeight: 900, color: T.link }}>WATCH TRUTH & REVIEW DESK</div><div style={{ fontSize: 10, color: BB.text3 }}>Deterministic facts first · explicit source/freshness · operator favorites separated from automated discovery · model lanes critique but cannot override hard failures.</div></div><div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>{([
      ['favorites', `★ FAVORITES ${favorites.length}`], ['automated', `AUTOMATED ${automated.length}`], ['all', `ALL ${unique.length}`],
    ] as const).map(([key, label]) => <button key={key} onClick={() => setLane(key)} title={key === 'favorites' ? 'Operator priority only; a star is not a quality score.' : key === 'automated' ? 'System-discovered names retain exact origin and do not inherit operator endorsement.' : 'All unique symbols.'} style={button(lane === key)}>{label}</button>)}</div></div>

    <div style={{ ...panel, background: 'var(--bg2)', padding: 8, marginTop: 8, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 10 }}><div><b style={{ color: BB.green }}>FAVORITES:</b> faster operator review, refresh, alert and Re-Entry classification. Starred status changes priority—not deterministic evidence.</div><div><b style={{ color: BB.amber }}>AUTOMATED:</b> exact discovery origin, promote-to-favorite control, and the same truth gates. No automated name receives an implied endorsement.</div></div>

    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(180px,1fr) auto', gap: 7, marginTop: 8 }}><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Filter symbol, origin, or sector…" style={{ fontSize: 11, padding: '6px 9px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 3, color: BB.text0 }} /><span style={{ color: BB.text3, fontSize: 10, alignSelf: 'center' }}>{shown.length} shown · top 30 cap</span></div>

    <div style={{ overflowX: 'auto', marginTop: 8 }}><div style={{ minWidth: 1180 }}><div style={{ display: 'grid', gridTemplateColumns: '125px 185px 90px 100px 100px 110px 130px 1fr 210px', gap: 7, padding: '6px 8px', borderBottom: '1px solid var(--border)', fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}><span>Symbol</span><span>Lane / origin</span><span>Price</span><span>Trailing P/E</span><span>Forward P/E</span><span>Technical</span><span>Ticket</span><span>Coverage truth</span><span>Actions</span></div>{shown.map(item => {
      const symbol = String(item.symbol).toUpperCase()
      const value = valuation(item, fvMap[symbol], cardMap[symbol])
      const ticket = ticketState(item)
      const rsi = num(item.rsi, item.rsi_14, fvMap[symbol]?.rsi)
      const price = num(item.price, item.last_price, item.price_live)
      const priceAt = text(item.price_as_of, item.last_enriched_at)
      const coverage = [
        price === null ? 'price unavailable' : `price ${age(priceAt)}`,
        rsi === null ? 'technicals unavailable' : `RSI ${rsi.toFixed(1)}`,
        value.notApplicable ? 'valuation N/A for fund/ETF' : value.available ? `valuation ${age(value.asOf)}` : 'valuation unavailable',
        item.catalyst_headline ? `catalyst ${age(item.catalyst_at)}` : 'catalyst unavailable',
      ].join(' · ')
      return <div key={symbol} onClick={() => setSelected(symbol)} title={`${symbol}: select for review controls`} style={{ display: 'grid', gridTemplateColumns: '125px 185px 90px 100px 100px 110px 130px 1fr 210px', gap: 7, padding: '7px 8px', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10, cursor: 'pointer', background: selected === symbol ? 'rgba(96,165,250,.08)' : 'transparent' }}><div><b style={{ fontSize: 13 }}>{symbol}</b><br /><span style={{ color: item.starred ? BB.amber : BB.text3 }}>{item.starred ? '★ operator' : '◇ system'}</span></div><div><b style={{ color: item.starred ? BB.green : BB.amber }}>{originLabel(item)}</b><br /><span style={{ color: BB.text3 }}>{text(item.profile_sector, 'sector unavailable')}</span></div><div><b>{money(price)}</b><br /><span style={{ color: BB.text3 }}>{age(priceAt)}</span></div><div><b style={{ color: value.pe === null ? BB.amber : BB.text1 }}>{value.notApplicable ? 'N/A' : value.pe === null ? 'UNAVAILABLE' : value.pe.toFixed(2)}</b></div><div><b style={{ color: value.forwardPe === null ? BB.amber : BB.text1 }}>{value.notApplicable ? 'N/A' : value.forwardPe === null ? 'UNAVAILABLE' : value.forwardPe.toFixed(2)}</b></div><div><b>{rsi === null ? 'UNAVAILABLE' : `RSI ${rsi.toFixed(1)}`}</b><br /><span style={{ color: BB.text3 }}>{text(item.trend_state, item.trend_direction, 'trend unavailable').replace(/_/g, ' ')}</span></div><div><b style={{ color: stateColor(ticket.deterministic) }}>{ticket.deterministic}</b><br /><span style={{ color: stateColor(ticket.reconciled) }}>{ticket.reconciled}</span></div><div style={{ color: BB.text3 }}>{coverage}</div><div onClick={event => event.stopPropagation()} style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}><button onClick={() => void toggleStar(item)} style={button(Boolean(item.starred))}>{item.starred ? 'UNSTAR' : 'PROMOTE ★'}</button><button onClick={() => setSelected(symbol)} style={button(selected === symbol)}>REVIEW</button><button onClick={() => { window.location.href = `/v3/portfolio/re-entry?classify=${encodeURIComponent(symbol)}` }} style={button(false)}>RE-ENTRY</button></div></div>
    })}</div></div>

    {selectedItem && selectedVal && selectedTicket && <div style={{ ...panel, marginTop: 9, padding: 10, borderColor: stateColor(selectedTicket.reconciled) }}><div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}><b style={{ fontSize: 14 }}>{selected} — EVIDENCE & INDEPENDENT REVIEW</b><span style={{ color: selectedItem.starred ? BB.green : BB.amber, fontSize: 10 }}>{originLabel(selectedItem)}</span><span style={{ marginLeft: 'auto', color: BB.text3, fontSize: 10 }}>P/E source: {selectedVal.available ? 'Finviz enrichment / blind facts' : selectedVal.notApplicable ? 'legitimately not applicable' : 'unavailable'} · {age(selectedVal.asOf)}</span></div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,minmax(125px,1fr))', gap: 6, marginTop: 8 }}>{[
        ['DETERMINISTIC', selectedTicket.deterministic], ['RECONCILED', selectedTicket.reconciled], ['LOCAL', selectedTicket.local], ['GROK OAUTH', selectedTicket.grok], ['CHATGPT OAUTH', selectedTicket.chatgpt],
      ].map(([label, value]) => <div key={label} style={{ ...panel, padding: 7, background: 'var(--bg2)' }}><div style={{ color: BB.text3, fontSize: 10 }}>{label}</div><b style={{ color: stateColor(value) }}>{value}</b></div>)}</div>
      <div style={{ ...panel, padding: 8, marginTop: 8, background: 'rgba(245,158,11,.06)', fontSize: 10 }}><b style={{ color: BB.amber }}>AUTHORITY:</b> arithmetic, freshness, validation and release remain deterministic. Local/OAuth/paid lanes are independent critics; model agreement cannot overturn a deterministic failure.</div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}><button disabled={Boolean(reviewBusy)} onClick={() => void runReview('local', 'Local critic')} title="Run local-only critic. No silent cloud fallback." style={button(false)}>{reviewBusy === 'Local critic' ? 'LOCAL…' : 'RUN LOCAL'}</button><button disabled={Boolean(reviewBusy)} onClick={() => void runReview('grok', 'Grok OAuth')} title="Run only the free Grok OAuth critic." style={button(false)}>{reviewBusy === 'Grok OAuth' ? 'GROK…' : 'RUN GROK OAUTH'}</button><button disabled={Boolean(reviewBusy)} onClick={() => void runReview('chatgpt', 'ChatGPT OAuth')} title="Run only the free ChatGPT OAuth critic." style={button(false)}>{reviewBusy === 'ChatGPT OAuth' ? 'CHATGPT…' : 'RUN CHATGPT OAUTH'}</button><button disabled={Boolean(reviewBusy)} onClick={() => void runReview('local,grok,chatgpt', 'All free critics')} title="Run local and both free OAuth lanes; disagreements remain visible." style={button(true)}>{reviewBusy === 'All free critics' ? 'ALL FREE…' : 'RUN ALL FREE'}</button><button disabled={Boolean(reviewBusy)} onClick={() => void estimatePremium()} title="Cost preview only. No paid call occurs until exact typed confirmation." style={{ ...button(false), color: '#a855f7', borderColor: '#a855f7' }}>{reviewBusy === 'premium estimate' ? 'ESTIMATING…' : 'PAID EXPERT…'}</button></div>
      {message && <div style={{ marginTop: 7, color: /failed|error|not configured|not implemented/i.test(message) ? BB.red : BB.green, fontSize: 10.5 }}>{message}</div>}
      {premium && <div style={{ ...panel, marginTop: 8, padding: 9, borderColor: premium.available ? '#a855f7' : BB.amber, background: 'var(--bg2)' }}><div style={{ fontSize: 11, fontWeight: 900, color: premium.available ? '#a855f7' : BB.amber }}>PAID EXPERT COST & CAPABILITY PREVIEW</div>{premium.available ? <><div style={{ fontSize: 10, marginTop: 5 }}>{premium.provider}/{premium.model} · estimated ${Number(premium.est_cost_usd).toFixed(4)} · input {premium.est_input_tokens} · output {premium.est_output_tokens} · expected latency {premium.expected_latency_s}s · daily budget ${premium.daily_budget_usd} · monthly budget ${premium.monthly_budget_usd}</div><div style={{ fontSize: 10, color: BB.text3, marginTop: 4 }}>{premium.scope}</div><label style={{ display: 'block', fontSize: 10, color: BB.text3, marginTop: 7 }}>TYPE EXACTLY: <code>{premium.confirm_with}</code><input value={confirmation} onChange={event => setConfirmation(event.target.value)} style={{ width: '100%', boxSizing: 'border-box', marginTop: 4, fontSize: 11, padding: '6px 8px', background: 'var(--bg1)', border: '1px solid var(--border)', color: BB.text0 }} /></label><button disabled={confirmation !== premium.confirm_with || Boolean(reviewBusy)} onClick={() => void runPremium()} style={{ ...button(true), marginTop: 7, color: '#a855f7', borderColor: '#a855f7', opacity: confirmation === premium.confirm_with ? 1 : .5 }}>CONFIRM PAID REVIEW</button></> : <div style={{ fontSize: 10, marginTop: 5, color: BB.amber }}>{premium.reason}<br />Registry entries: {(premium.providers_listed ?? []).join(', ') || 'none'}. No paid call was made.</div>}</div>}
    </div>}
  </div>
}
