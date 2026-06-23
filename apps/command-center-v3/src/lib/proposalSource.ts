/** Derive watchlist vs proposal source attribution for queue cards. */

export type SourceAttribution = {
  watchlist: boolean
  proposal: boolean
  watchlistRating?: string | null
  proposalChannel?: string | null
  label: 'watchlist' | 'proposal' | 'both' | 'unknown'
}

function norm(v: unknown): string {
  return String(v ?? '').trim().toLowerCase().replace(/\s+/g, '_')
}

function formatRating(v: unknown): string {
  return String(v ?? 'BUY').replace(/_/g, ' ').toUpperCase()
}

function proposalChannelLabel(p: Record<string, unknown>): string {
  const disc = norm(p.discovery_source)
  const screener = String((p.signal_evidence as any)?.screener || p.screener_name || p.scan_screener || '').trim()
  if (disc === 'screener' || screener) {
    return screener ? `Screener · ${screener.replace(/_/g, ' ')}` : 'Screener'
  }
  if (disc === 'incubator') return 'Incubator'
  if (disc && disc !== 'watchlist') return disc.replace(/_/g, ' ')
  return 'Proposal'
}

export function deriveSourceAttribution(p: Record<string, unknown> | null | undefined): SourceAttribution {
  const row = p || {}
  const api = row.source_attribution as SourceAttribution | undefined
  if (api && typeof api.watchlist === 'boolean' && typeof api.proposal === 'boolean' && api.label !== 'unknown') {
    return api
  }

  const origin = norm(row.origin)
  const discovery = norm(row.discovery_source)
  const proposedBy = norm(row.proposed_by)
  const basis = (typeof row.sizing_basis === 'object' && row.sizing_basis) as Record<string, unknown> | null
  const rating = formatRating(row.cio_view || row.watchlist_rating || basis?.watchlist_rating)
  const hasSignal = Boolean((row.signal_evidence as any)?.screener || row.screener_name || row.scan_screener)

  const watchlistBridge = origin === 'watchlist' || discovery === 'watchlist' || proposedBy === 'watchlist_proposal_bridge'
  const watchlist = watchlistBridge || Boolean(row.also_on_watchlist)

  const autoProposal = origin === 'auto'
    || discovery === 'screener'
    || discovery === 'incubator'
    || discovery === 'signal'
    || hasSignal
    || proposedBy.includes('auto_proposal')
    || proposedBy.includes('incubator')
    || (Boolean(row.auto_created) && !watchlistBridge)

  const proposal = autoProposal && !(watchlistBridge && !hasSignal)

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
  }
}

export function sourceAttributionTitle(att: SourceAttribution): string {
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