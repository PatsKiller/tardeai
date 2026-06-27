import { deriveSourceAttribution, sourceAttributionTitle, type SourceAttribution } from '../lib/proposalSource'

const GREEN = '#22c55e'
const BLUE = '#60a5fa'
const PURPLE = '#a78bfa'
const TEAL = '#2dd4bf'
const AMBER = '#f59e0b'

type Size = 'sm' | 'md'

const sizeStyle = (size: Size) => size === 'md'
  ? { fontSize: 9, padding: '3px 8px', borderRadius: 5 }
  : { fontSize: 8, padding: '1px 6px', borderRadius: 3 }

function Badge({ label, color, title, size }: { label: string; color: string; title: string; size: Size }) {
  const s = sizeStyle(size)
  return (
    <span title={title} style={{
      ...s,
      fontWeight: 800,
      background: `${color}22`,
      color,
      border: `1px solid ${color}44`,
      whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  )
}

function RoutingLaneBadge({ lane, size }: { lane: string; size: Size }) {
  if (lane === 'paper_atm') {
    return <Badge size={size} color={TEAL} title="Paper lane — ATM auto-test on tradeai_automated" label="◆ ATM test" />
  }
  if (lane === 'live_2fa') {
    return <Badge size={size} color={AMBER} title="Broker lane — operator 2FA in Proposals UI" label="◆ 2FA live" />
  }
  return null
}

export default function ProposalSourceBadges({
  proposal,
  size = 'sm',
  showBothCombined = false,
  showRoutingLane = true,
}: {
  proposal: Record<string, unknown> | null | undefined
  size?: Size
  showBothCombined?: boolean
  showRoutingLane?: boolean
}) {
  const att: SourceAttribution = deriveSourceAttribution(proposal)
  const title = sourceAttributionTitle(att)

  if (att.label === 'protection') {
    return (
      <>
        <Badge size={size} color={PURPLE} title={title} label="◆ Protection" />
        {showRoutingLane && att.routing_lane && <RoutingLaneBadge lane={att.routing_lane} size={size} />}
      </>
    )
  }

  if (att.label === 'unknown') {
    const disc = String((proposal as any)?.discovery_source || (proposal as any)?.origin || '').trim()
    if (!disc) return null
    return (
      <>
        <Badge size={size} color={BLUE} title={title} label={`◆ ${disc.replace(/_/g, ' ')}`} />
        {showRoutingLane && att.routing_lane && <RoutingLaneBadge lane={att.routing_lane} size={size} />}
      </>
    )
  }

  if (att.label === 'both' && showBothCombined) {
    return (
      <>
        <Badge
          size={size}
          color={PURPLE}
          title={title}
          label={`◆ Watchlist + ${att.proposalChannel || 'Proposal'}`}
        />
        {showRoutingLane && att.routing_lane && <RoutingLaneBadge lane={att.routing_lane} size={size} />}
      </>
    )
  }

  return (
    <>
      {att.watchlist && (
        <Badge
          size={size}
          color={GREEN}
          title={title}
          label={`◆ Watchlist ${String(att.watchlistRating || 'BUY').replace(/_/g, ' ')}`}
        />
      )}
      {att.proposal && (
        <Badge
          size={size}
          color={BLUE}
          title={title}
          label={`◆ ${att.proposalChannel || 'Proposal'}`}
        />
      )}
      {showRoutingLane && att.routing_lane && <RoutingLaneBadge lane={att.routing_lane} size={size} />}
    </>
  )
}