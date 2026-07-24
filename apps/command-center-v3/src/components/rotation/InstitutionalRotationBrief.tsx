import { useMemo, useState } from 'react'
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

const SECTOR_ALIASES: Record<string, string> = {
  'financial services': 'Financials',
  financial: 'Financials',
  'consumer cyclical': 'Consumer Discretionary',
  'consumer defensive': 'Consumer Staples',
  'basic materials': 'Materials',
  'communication services': 'Communications',
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
  if (card) return 'ELIGIBLE NOW'
  if (state === 'WEAKENING' || state === 'LAGGING') return 'AVOID / REDUCE'
  return 'RESEARCH WATCH'
}

function accountRows(card: any, accountLabels: Record<string, string>): any[] {
  const sizing = card?.account_sizing || {}
  const decisions = card?.allocation_policy || {}
  const dollars = card?.dollars_by_account || {}
  const accounts: string[] = card?.accounts || Object.keys(sizing)
  return accounts.map(account => {
    const row = sizing[account] || {}
    const decision = decisions[account] || {}
    const band = row.pct_band || (Array.isArray(dollars[account]) ? null : undefined)
    return {
      account,
      label: accountLabels[account] || account,
      low: band?.[0],
      high: band?.[1],
      dollars: row.dollar_band || dollars[account],
      current: decision.current_account_weight_pct ?? decision.current_weight_pct,
      capacity: decision.capacity_pct,
      target: decision.risk_target_pct,
      quality: decision.quality,
    }
  })
}

export default function InstitutionalRotationBrief({
  sectors = [], industries = [], recommendations, generatedAt, industryCapturedAt, compact = false,
}: Props) {
  const [showMethod, setShowMethod] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const groups = recommendations?.groups || {}
  const addCards: any[] = groups.get_into || []
  const riskCards: any[] = [...(groups.protect || []), ...(groups.short_side || [])]
  const accountLabels: Record<string, string> = recommendations?.accounts || {}
  const leanReview = (recommendations?.directive_reviews || [])[0] || {}

  const sectorByEtf = useMemo(() => new Map(sectors.map((s: any) => [s.etf, s])), [sectors])
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

  const decisions = useMemo(() => sectors.map((sector: any) => {
    const name = canonicalSector(sector.sector)
    const card = addBySector.get(name)
    const status = statusFor(sector, card)
    const supportiveIndustries = (industriesBySector.get(name) || [])
      .filter((i: any) => !i.quarantined && ['LEADING', 'IMPROVING'].includes(String(i.state || '').toUpperCase()))
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
    if (!card && leanReview.enabled && leanReview.requires_review &&
        !['Utilities', 'Consumer Staples', 'Healthcare'].includes(name) &&
        ['LEADING', 'IMPROVING'].includes(state)) {
      blocking.push('dated defensive-lean policy currently blocks non-defensive adds pending operator review')
    }
    if (!card && status === 'RESEARCH WATCH' && recommendations?.empty_reasons?.get_into) {
      blocking.push(recommendations.empty_reasons.get_into)
    }
    if (status === 'AVOID / REDUCE') {
      blocking.push(`${state || 'weak'} relative state is not an entry condition`)
    }

    const why = card
      ? `${state} vs SPY with RS20 ${signed(sector.rs20)}; governed portfolio and risk rails passed`
      : `${state || 'unclassified'} vs SPY with RS20 ${signed(sector.rs20)} and slope ${signed(sector.slope)}`
    return { sector, name, card, status, supportiveIndustries, blocking: [...new Set(blocking)], why }
  }).sort((a: any, b: any) => {
    const rank: Record<DecisionStatus, number> = { 'ELIGIBLE NOW': 0, 'RESEARCH WATCH': 1, 'AVOID / REDUCE': 2, 'NO DECISION': 3 }
    const sr = rank[a.status] - rank[b.status]
    if (sr) return sr
    return Number(b.sector.rs20 ?? -999) - Number(a.sector.rs20 ?? -999)
  }), [sectors, addBySector, industriesBySector, leanReview, recommendations])

  const visible = (showAll ? decisions : decisions.slice(0, compact ? 5 : 8))
  const counts = decisions.reduce((acc: Record<string, number>, d: any) => {
    acc[d.status] = (acc[d.status] || 0) + 1
    return acc
  }, {})

  return (
    <section style={{ background: BB.bgPanel, border: `1px solid ${BB.border}`, borderRadius: 2, padding: compact ? '10px 12px' : '12px 14px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap', marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: DASH.panel, fontWeight: 800, color: BB.text1 }}>Sector decision board</div>
          <div style={{ fontSize: DASH.data, color: BB.text3, marginTop: 2 }}>
            what is eligible · what is only a watch · what to avoid · what evidence changes the answer
          </div>
        </div>
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={statePill('green')}>eligible {counts['ELIGIBLE NOW'] || 0}</span>
          <span style={statePill('amber')}>watch {counts['RESEARCH WATCH'] || 0}</span>
          <span style={statePill('red')}>avoid/reduce {counts['AVOID / REDUCE'] || 0}</span>
          <span style={statePill('slate')}>no decision {counts['NO DECISION'] || 0}</span>
          <span style={statePill('slate')} title="GPT, Grok and paid seats challenge the packet; they do not create prices, sizing or permission truth">model critique only</span>
          <button type="button" onClick={() => setShowMethod(v => !v)} style={{ ...metricChip(true), color: T.link, borderColor: T.link }}>
            {showMethod ? 'hide math contract' : 'math & freshness'}
          </button>
        </div>
      </div>

      {addCards.length === 0 && (
        <div style={{ fontSize: DASH.data, color: BB.amber, background: BB.amberDim, borderLeft: `3px solid ${BB.amber}`, padding: '7px 9px', marginBottom: 10 }}>
          <b>No governed add card is active.</b> The watch rows below now state the blocking gate; they remain research, not allocation instructions.
        </div>
      )}

      {showMethod && (
        <div style={{ fontSize: DASH.data, color: BB.text2, background: BB.bgShift, borderLeft: `3px solid ${BB.amber}`, padding: '8px 10px', marginBottom: 10, display: 'grid', gap: 3 }}>
          <div><b>Sector state:</b> {shortTime(generatedAt)} · ETF 5/20/60-session returns aligned to SPY; state uses RS20 level plus change in RS20 and requires two-close confirmation.</div>
          <div><b>Breadth:</b> exact latest close versus each covered member’s latest 20 distinct sessions. Coverage and membership counts must remain visible; this is a covered-universe measure, not automatically the ETF’s official constituent breadth.</div>
          <div><b>Industry state:</b> {shortTime(industryCapturedAt)} · same-vendor one-month relative level and one-week relative direction. It is a confirmation heuristic, not the same slope calculation used for sectors.</div>
          <div><b>Sizing:</b> an actionable card must show each account’s own effective exposure, risk target, remaining capacity, percentage band and dollar band. A shared maximum across accounts is not acceptable.</div>
          <div><b>AI oversight:</b> free or paid model lanes may concur, qualify or object. They do not validate source data, recompute deterministic math, approve an order or widen permissions.</div>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fit, minmax(${compact ? 270 : 310}px, 1fr))`, gap: 8 }}>
        {visible.map((d: any) => {
          const { sector, name, card, status, supportiveIndustries, blocking, why } = d
          const stocks = (card?.instruments || []).filter((i: any) => i.kind === 'constituent').slice(0, 3)
          const accounts = accountRows(card, accountLabels)
          const tone = statusTone(status)
          const toneColor = tone === 'green' ? BB.green : tone === 'red' ? BB.red : tone === 'amber' ? BB.amber : BB.text3
          return (
            <article key={sector.etf || name} style={{ border: `1px solid ${BB.borderHair}`, borderLeft: `4px solid ${toneColor}`, background: BB.bg, padding: '10px 11px', minWidth: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'flex-start' }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: DASH.section, fontWeight: 800, color: BB.text1 }}>{name}</div>
                  <div style={{ ...numStyle, fontSize: DASH.data, color: T.link }}>{sector.etf || 'ETF not mapped'}</div>
                </div>
                <span style={statePill(tone)}>{status}</span>
              </div>

              <div style={{ fontSize: DASH.data, color: BB.text2, marginTop: 7 }}><b>Why:</b> {why}</div>
              <div style={{ fontSize: DASH.data, color: BB.text3, marginTop: 3 }}>
                breadth {sector.breadth_pct == null ? '—' : `${sector.breadth_pct}%`} ({sector.breadth_coverage_n ?? sector.breadth_n ?? '—'}/{sector.breadth_membership_n ?? '—'} covered) · book {sector.book_pct == null ? '—' : `${sector.book_pct}%`} · as of {sector.as_of || '—'}
              </div>

              {supportiveIndustries.length > 0 && (
                <div style={{ marginTop: 7 }}>
                  <div style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', color: BB.text3, marginBottom: 3 }}>confirming industries</div>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {supportiveIndustries.map((industry: any) => (
                      <span key={industry.industry} style={metricChip()} title={`${industry.state} · relative month ${signed(industry.rel1m)} · relative week ${signed(industry.rel1w)}`}>
                        {industry.industry}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {status === 'ELIGIBLE NOW' ? (
                <>
                  <div style={{ marginTop: 8, padding: '7px 8px', background: BB.greenDim, borderLeft: `3px solid ${BB.green}` }}>
                    <div style={{ fontSize: DASH.data, color: BB.text1 }}><b>Activation:</b> {card?.levels?.entry_zone || card?.entry_logic || 'governed entry condition unavailable'}</div>
                    <div style={{ fontSize: DASH.data, color: BB.amber, marginTop: 2 }}><b>Invalidation:</b> {card?.invalidation || 'not reported'}</div>
                  </div>
                  <div style={{ marginTop: 7 }}>
                    <div style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', color: BB.text3, marginBottom: 3 }}>account-specific capacity</div>
                    {accounts.length ? accounts.map(row => (
                      <div key={row.account} style={{ fontSize: DASH.data, color: BB.text2, padding: '2px 0', borderBottom: `1px solid ${BB.borderHair}` }}>
                        <b>{row.label}</b> · current {row.current == null ? '—' : `${row.current}%`} · target {row.target == null ? '—' : `${row.target}%`} · capacity {row.capacity == null ? '—' : `${row.capacity}%`}
                        {row.low != null && row.high != null ? ` · act ${row.low}–${row.high}%` : ''}
                        {Array.isArray(row.dollars) ? ` · ${money(row.dollars[0])}–${money(row.dollars[1])}` : ''}
                        {row.quality && row.quality !== 'ok' ? ` · ${row.quality}` : ''}
                      </div>
                    )) : <div style={{ fontSize: DASH.data, color: BB.red }}>WITHHELD — account-specific sizing evidence is missing.</div>}
                  </div>
                  <div style={{ marginTop: 7 }}>
                    <div style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', color: BB.text3, marginBottom: 3 }}>instrument choice</div>
                    <div style={{ fontSize: DASH.data, color: BB.text2 }}>
                      <b>{sector.etf}</b>{card?.levels?.price != null ? ` near $${Number(card.levels.price).toFixed(2)}` : ''}
                      {stocks.length ? ` · stocks passing full evidence: ${stocks.map((s: any) => s.symbol).join(', ')}` : ' · ETF only; no stock cleared every required field and close-industry gate'}
                    </div>
                  </div>
                </>
              ) : (
                <div style={{ marginTop: 8, padding: '7px 8px', background: status === 'AVOID / REDUCE' ? BB.redDim : BB.bgShift, borderLeft: `3px solid ${toneColor}` }}>
                  <div style={{ fontSize: DASH.chip, fontWeight: 800, color: toneColor, textTransform: 'uppercase', marginBottom: 3 }}>
                    {status === 'NO DECISION' ? 'required before evaluation' : status === 'AVOID / REDUCE' ? 'why not an entry' : 'promote only when'}
                  </div>
                  {blocking.length ? blocking.slice(0, 4).map((item: string, i: number) => (
                    <div key={i} style={{ fontSize: DASH.data, color: BB.text2, padding: '1px 0' }}>• {item}</div>
                  )) : <div style={{ fontSize: DASH.data, color: BB.text3 }}>A governed recommendation card with complete account and entry evidence must appear.</div>}
                </div>
              )}
            </article>
          )
        })}
      </div>

      {decisions.length > visible.length && (
        <button type="button" onClick={() => setShowAll(v => !v)} style={{ ...metricChip(true), marginTop: 8, color: T.link, borderColor: T.link }}>
          {showAll ? 'show priority rows' : `show all ${decisions.length} sectors`}
        </button>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 8, marginTop: 9 }}>
        <div style={{ border: `1px solid ${BB.borderHair}`, background: BB.bg, padding: '8px 9px' }}>
          <div style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', color: BB.red, marginBottom: 3 }}>governed defense actions</div>
          {riskCards.length ? riskCards.slice(0, 4).map((card: any) => {
            const withheld = (String(card.id || '').startsWith('pput-') && !card.put_struct) || (String(card.id || '').startsWith('cc-') && !card.cc_struct)
            return (
              <div key={card.id} style={{ fontSize: DASH.data, color: withheld ? BB.red : BB.text2, padding: '2px 0' }} title={card.invalidation || card.entry_logic}>
                <b style={{ color: BB.text1 }}>{card.title}</b> · {withheld ? 'WITHHELD — structure failed evidence or liquidity rails' : card.mode || 'advisory'}
              </div>
            )
          }) : <div style={{ fontSize: DASH.data, color: BB.text3 }}>No complete protect, trim or hedge card passed the current field and risk gates.</div>}
        </div>
        <div style={{ border: `1px solid ${BB.borderHair}`, background: BB.bg, padding: '8px 9px' }}>
          <div style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', color: BB.amber, marginBottom: 3 }}>operator policy requiring review</div>
          {leanReview.requires_review ? (
            <div style={{ fontSize: DASH.data, color: BB.text2 }}>
              Defensive lean set {leanReview.set_at || 'date unavailable'} is due for adjudication. Conflicts: {(leanReview.conflicting_sectors || []).join(', ') || 'none listed'}. It remains active until the operator explicitly retains or revokes it.
            </div>
          ) : <div style={{ fontSize: DASH.data, color: BB.text3 }}>No dated rotation directive is currently due for review.</div>}
        </div>
      </div>

      <div style={{ fontSize: DASH.data, color: BB.text3, marginTop: 8 }}>
        This board does not place, stage, approve or authorize an order. Deterministic source, portfolio, account and permission systems remain authoritative; model seats provide independent critique only.
      </div>
    </section>
  )
}
