/** Derive watchlist vs proposal source attribution for queue cards. */

export type SourceAttribution = {
  watchlist: boolean
  proposal: boolean
  watchlistRating?: string | null
  proposalChannel?: string | null
  label: 'watchlist' | 'proposal' | 'both' | 'protection' | 'unknown'
  routing_lane?: 'paper_atm' | 'live_2fa' | string | null
}

function norm(v: unknown): string {
  return String(v ?? '').trim().toLowerCase().replace(/\s+/g, '_')
}

function formatRating(v: unknown): string {
  return String(v ?? 'BUY').replace(/_/g, ' ').toUpperCase()
}

function sizingBasis(row: Record<string, unknown>): Record<string, unknown> | null {
  const b = row.sizing_basis
  if (b && typeof b === 'object') return b as Record<string, unknown>
  if (typeof b === 'string') {
    try {
      const parsed = JSON.parse(b)
      return parsed && typeof parsed === 'object' ? parsed : null
    } catch {
      return null
    }
  }
  return null
}

function proposalChannelLabel(p: Record<string, unknown>): string {
  const disc = norm(p.discovery_source)
  const proposedBy = norm(p.proposed_by)
  const screener = String((p.signal_evidence as any)?.screener || p.screener_name || p.scan_screener || '').trim()
  if (disc === 'pullback_macd' || proposedBy.includes('pullback_macd')) return 'Pullback MACD'
  if (disc === 'screener' || screener) {
    return screener ? `Screener · ${screener.replace(/_/g, ' ')}` : 'Screener'
  }
  if (disc === 'incubator') return 'Incubator'
  if (disc && disc !== 'watchlist') return disc.replace(/_/g, ' ')
  return 'Proposal'
}

function isCuratedProposalSource(p: Record<string, unknown>): boolean {
  const disc = norm(p.discovery_source)
  const origin = norm(p.origin)
  const proposedBy = norm(p.proposed_by)
  return (
    disc === 'pullback_macd'
    || disc === 'screener'
    || disc === 'incubator'
    || disc === 'signal'
    || origin === 'auto'
    || proposedBy.includes('auto_proposal')
    || proposedBy.includes('incubator')
    || proposedBy.includes('pullback_macd')
    || Boolean(p.auto_created)
  )
}

export function deriveSourceAttribution(p: Record<string, unknown> | null | undefined): SourceAttribution {
  const row = p || {}
  const kind = norm(row.proposal_kind || row.queue_kind)
  if (kind === 'protection' || norm(row.origin) === 'protection') {
    return {
      watchlist: false,
      proposal: false,
      label: 'protection',
      proposalChannel: 'Protection · ATM',
      routing_lane: row.routing_lane as string | null,
    }
  }

  const api = row.source_attribution as SourceAttribution | undefined
  if (api && typeof api.watchlist === 'boolean' && typeof api.proposal === 'boolean' && api.label !== 'unknown') {
    const basis = sizingBasis(row)
    return {
      ...api,
      routing_lane: api.routing_lane || (basis?.routing_lane as string | undefined) || null,
    }
  }

  const origin = norm(row.origin)
  const discovery = norm(row.discovery_source)
  const proposedBy = norm(row.proposed_by)
  const basis = sizingBasis(row)
  const rating = formatRating(row.cio_view || row.watchlist_rating || basis?.watchlist_rating)
  const hasSignal = Boolean((row.signal_evidence as any)?.screener || row.screener_name || row.scan_screener)
  const routingLane = (basis?.routing_lane as string | undefined) || null

  const watchlistBridge = origin === 'watchlist' || discovery === 'watchlist' || proposedBy === 'watchlist_proposal_bridge'
  const watchlist = watchlistBridge || Boolean(row.also_on_watchlist)

  const autoProposal = isCuratedProposalSource(row) || hasSignal
  const proposal = autoProposal && !(watchlistBridge && !hasSignal && discovery !== 'pullback_macd')

  let label: SourceAttribution['label'] = 'unknown'
  if (watchlist && proposal) label = 'both'
  else if (watchlist) label = 'watchlist'
  else if (proposal) label = 'proposal'

  return {
    watchlist,
    proposal,
    watchlistRating: watchlist ? rating : null,
    proposalChannel: proposal ? proposalChannelLabel(row) : null,
    label,
    routing_lane: routingLane,
  }
}

export function sourceAttributionTitle(att: SourceAttribution): string {
  if (att.label === 'protection') {
    return att.proposalChannel || 'ATM protection adjustment for an open position'
  }
  if (att.label === 'both') {
    return `Watchlist ${att.watchlistRating || 'BUY'} + ${att.proposalChannel || 'proposal signal'}`
  }
  if (att.label === 'watchlist') {
    return `Watchlist ${att.watchlistRating || 'BUY'} — persists while rating holds`
  }
  if (att.label === 'proposal') {
    return `Auto proposal via ${att.proposalChannel || 'signal pipeline'}`
  }
  return 'Source unknown'
}