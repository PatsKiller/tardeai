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

function stateTone(state?: string | null): 'green' | 'amber' | 'red' | 'slate' {
  const s = String(state || '').toUpperCase()
  if (s === 'LEADING') return 'green'
  if (s === 'IMPROVING' || s === 'WEAKENING') return 'amber'
  if (s === 'LAGGING') return 'red'
  return 'slate'
}

function cardSector(card: any, sectorByEtf: Map<string, any>): string {
  const etf = (card?.instruments || []).find((i: any) => i.kind === 'sector ETF')?.symbol
  if (etf && sectorByEtf.has(etf)) return canonicalSector(sectorByEtf.get(etf)?.sector)
  const match = String(card?.title || '').match(/·\s*(.+?)\s*\(/)
  return canonicalSector(match?.[1] || '')
}

export default function InstitutionalRotationBrief({
  sectors = [], industries = [], recommendations, generatedAt, industryCapturedAt, compact = false,
}: Props) {
  const [showMethod, setShowMethod] = useState(false)
  const groups = recommendations?.groups || {}
  const addCards: any[] = groups.get_into || []
  const riskCards: any[] = [...(groups.protect || []), ...(groups.short_side || [])]

  const sectorByEtf = useMemo(() => new Map(sectors.map((s: any) => [s.etf, s])), [sectors])
  const addBySector = useMemo(() => {
    const out = new Map<string, any>()
    addCards.forEach(card => {
      const sector = cardSector(card, sectorByEtf)
      if (sector && !out.has(sector)) out.set(sector, card)
    })
    return out
  }, [addCards, sectorByEtf])

  const candidateSectors = useMemo(() => {
    const preferred = sectors
      .filter((s: any) => ['LEADING', 'IMPROVING'].includes(String(s.state || '').toUpperCase()) || addBySector.has(canonicalSector(s.sector)))
      .sort((a: any, b: any) => {
        const ac = addBySector.has(canonicalSector(a.sector)) ? 1 : 0
        const bc = addBySector.has(canonicalSector(b.sector)) ? 1 : 0
        if (ac !== bc) return bc - ac
        return Number(b.rs20 ?? -999) - Number(a.rs20 ?? -999)
      })
    return preferred.slice(0, compact ? 3 : 4)
  }, [sectors, addBySector, compact])

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

  const weakSectors = useMemo(() => sectors
    .filter((s: any) => ['WEAKENING', 'LAGGING'].includes(String(s.state || '').toUpperCase()))
    .sort((a: any, b: any) => Number(a.rs20 ?? 999) - Number(b.rs20 ?? 999))
    .slice(0, 3), [sectors])

  return (
    <section style={{ background: BB.bgPanel, border: `1px solid ${BB.border}`, borderRadius: 2, padding: compact ? '10px 12px' : '12px 14px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap', marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: DASH.panel, fontWeight: 800, color: BB.text1 }}>Institutional rotation brief</div>
          <div style={{ fontSize: DASH.data, color: BB.text3, marginTop: 2 }}>
            sector → industry → ETF → stock · deterministic market facts first · portfolio-aware, advisory only
          </div>
        </div>
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={statePill('green')} title="Price-relative state, breadth and portfolio exposure are deterministic inputs">deterministic facts</span>
          <span style={statePill('amber')} title="Recommendation cards incorporate portfolio exposure, account and risk rails">portfolio aware</span>
          <span style={statePill('slate')} title="GPT, Grok, Claude and legacy Hermes outputs are critiques or rankings, not market truth">model critique only</span>
          <button type="button" onClick={() => setShowMethod(v => !v)} style={{ ...metricChip(true), color: T.link, borderColor: T.link }}>
            {showMethod ? 'hide method' : 'method & freshness'}
          </button>
        </div>
      </div>

      {addCards.length === 0 && (
        <div style={{ fontSize: DASH.data, color: BB.amber, background: BB.amberDim, borderLeft: `3px solid ${BB.amber}`, padding: '7px 9px', marginBottom: 10 }}>
          <b>No governed add card is active.</b> Leading and improving sectors below are research watches only; portfolio capacity, policy, or recommendation rails did not authorize an add.
        </div>
      )}

      {showMethod && (
        <div style={{ fontSize: DASH.data, color: BB.text2, background: BB.bgShift, borderLeft: `3px solid ${BB.amber}`, padding: '8px 10px', marginBottom: 10 }}>
          <div><b>Sector snapshot:</b> {shortTime(generatedAt)} · 5/20/60-session ETF returns relative to SPY with a two-close state confirmation.</div>
          <div><b>Industry snapshot:</b> {shortTime(industryCapturedAt)} · Finviz week/month performance compared with local SPY 5/21-session returns.</div>
          <div><b>Governed adds:</b> {addCards.length} complete card{addCards.length === 1 ? '' : 's'} in the current recommendation build.</div>
          <div style={{ color: BB.amber }}><b>Quality note:</b> industry ranks are directionally useful but the vendor windows are not perfectly synchronized. Treat close calls as watch candidates, not precise allocation signals.</div>
        </div>
      )}

      {candidateSectors.length ? (
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fit, minmax(${compact ? 230 : 250}px, 1fr))`, gap: 8 }}>
          {candidateSectors.map((sector: any) => {
            const name = canonicalSector(sector.sector)
            const card = addBySector.get(name)
            const rowAge = ageDays(sector.as_of)
            const stale = rowAge != null && rowAge > 4
            const narrow = Number(sector.breadth_pct) < 35
            const industryList = (industriesBySector.get(name) || [])
              .filter((i: any) => ['LEADING', 'IMPROVING'].includes(String(i.state || '').toUpperCase()))
              .slice(0, 3)
            const stocks = (card?.instruments || []).filter((i: any) => i.kind === 'constituent').slice(0, 3)
            const posture = card ? 'ADD ON PULLBACK' : 'RESEARCH WATCH'
            return (
              <article key={sector.etf || name} style={{ border: `1px solid ${BB.borderHair}`, borderLeft: `3px solid ${card ? BB.green : stale ? BB.red : BB.amber}`, background: BB.bg, padding: '9px 10px', minWidth: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: DASH.section, fontWeight: 800, color: BB.text1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{name}</div>
                    <div style={{ ...numStyle, fontSize: DASH.data, color: T.link }}>{sector.etf || 'ETF not mapped'}</div>
                  </div>
                  <span style={statePill(card ? 'green' : stale ? 'red' : stateTone(sector.state))}>{stale ? 'STALE RESEARCH' : posture}</span>
                </div>
                <div style={{ fontSize: DASH.data, color: BB.text2, marginTop: 6 }}>
                  <b>{sector.state || 'unclassified'}</b> · RS20 {signed(sector.rs20)} · slope {signed(sector.slope)}
                </div>
                <div style={{ fontSize: DASH.data, color: BB.text3, marginTop: 2 }}>
                  breadth {sector.breadth_pct == null ? '—' : `${sector.breadth_pct}%`} · book {sector.book_pct == null ? '—' : `${sector.book_pct}%`} · as of {sector.as_of || '—'}
                </div>
                {narrow && <div style={{ fontSize: DASH.data, color: BB.amber, marginTop: 3 }}><b>Narrow participation:</b> only {sector.breadth_pct}% of sampled members are above the current breadth measure.</div>}
                {!card && <div style={{ fontSize: DASH.data, color: BB.text3, marginTop: 3 }}>No governed add card; this is not an allocation instruction.</div>}
                <div style={{ marginTop: 7 }}>
                  <div style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', color: BB.text3, marginBottom: 3 }}>industries underneath</div>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {industryList.length ? industryList.map((industry: any) => (
                      <span key={industry.industry} style={metricChip()} title={`${industry.state} · relative 1m ${signed(industry.rel1m)} · relative 1w ${signed(industry.rel1w)}`}>
                        {industry.industry}
                      </span>
                    )) : <span style={{ fontSize: DASH.data, color: BB.text3 }}>no confirmed leading/improving industry</span>}
                  </div>
                </div>
                <div style={{ marginTop: 7 }}>
                  <div style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', color: BB.text3, marginBottom: 3 }}>governed stock candidates</div>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {stocks.length ? stocks.map((stock: any) => (
                      <span key={stock.symbol} style={{ ...metricChip(), color: BB.text1 }} title={stock.note || 'constituent passing current recommendation rails'}>
                        {stock.symbol}{stock.price != null ? ` $${Number(stock.price).toFixed(2)}` : ''}
                      </span>
                    )) : <span style={{ fontSize: DASH.data, color: BB.text3 }}>{card ? 'ETF preferred; no constituent passed all rails' : 'none — screening names are not recommendations'}</span>}
                  </div>
                </div>
                {card?.entry_logic && <div style={{ fontSize: DASH.data, color: BB.text2, marginTop: 7 }}><b>Trigger:</b> {card.entry_logic}</div>}
                {card?.invalidation && <div style={{ fontSize: DASH.data, color: BB.amber, marginTop: 3 }}><b>Invalidation:</b> {card.invalidation}</div>}
              </article>
            )
          })}
        </div>
      ) : (
        <div style={{ fontSize: DASH.data, color: BB.text3, padding: '10px 0' }}>No leading or improving sector is available even as a research watch.</div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 8, marginTop: 8 }}>
        <div style={{ border: `1px solid ${BB.borderHair}`, background: BB.bg, padding: '7px 9px' }}>
          <div style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', color: BB.red, marginBottom: 3 }}>funding / reduce watch</div>
          {weakSectors.length ? weakSectors.map((sector: any) => {
            const stale = (ageDays(sector.as_of) ?? 0) > 4
            return (
              <div key={sector.etf} style={{ fontSize: DASH.data, color: stale ? BB.red : BB.text2, padding: '1px 0' }}>
                <b style={{ color: BB.text1 }}>{canonicalSector(sector.sector)}</b> · {sector.etf} · {sector.state} · RS20 {signed(sector.rs20)}{stale ? ` · STALE ${sector.as_of}` : ''}
              </div>
            )
          }) : <div style={{ fontSize: DASH.data, color: BB.text3 }}>No weakening or lagging sector in the current snapshot.</div>}
        </div>
        <div style={{ border: `1px solid ${BB.borderHair}`, background: BB.bg, padding: '7px 9px' }}>
          <div style={{ fontSize: DASH.chip, fontWeight: 800, textTransform: 'uppercase', color: BB.amber, marginBottom: 3 }}>governed protect / trim review</div>
          {riskCards.length ? riskCards.slice(0, 3).map((card: any) => {
            const withheld = String(card.id || '').startsWith('pput-') && !card.put_struct
            return (
              <div key={card.id} style={{ fontSize: DASH.data, color: withheld ? BB.red : BB.text2, padding: '1px 0', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={card.invalidation || card.entry_logic}>
                <b style={{ color: BB.text1 }}>{card.title}</b> · {withheld ? 'WITHHELD — failed structure rails' : card.mode || 'advisory'}
              </div>
            )
          }) : <div style={{ fontSize: DASH.data, color: BB.text3 }}>No complete protect, trim or hedge card passed the current field and risk gates.</div>}
        </div>
      </div>

      <div style={{ fontSize: DASH.data, color: BB.text3, marginTop: 8 }}>
        This brief does not place, approve or authorize an order. Model seats should challenge stale evidence and missing risks; deterministic market, portfolio and permission systems remain authoritative.
      </div>
    </section>
  )
}
