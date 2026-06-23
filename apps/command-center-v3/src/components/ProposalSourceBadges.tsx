import { deriveSourceAttribution, sourceAttributionTitle, type SourceAttribution } from '../lib/proposalSource'

const GREEN = '#22c55e'
const BLUE = '#60a5fa'
const PURPLE = '#a78bfa'

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

export default function ProposalSourceBadges({
  proposal,
  size = 'sm',
  showBothCombined = false,
}: {
  proposal: Record<string, unknown> | null | undefined
  size?: Size
  showBothCombined?: boolean
}) {
  const att: SourceAttribution = deriveSourceAttribution(proposal)
  if (att.label === 'unknown') return null

  const title = sourceAttributionTitle(att)

  if (att.label === 'both' && showBothCombined) {
    return (
      <Badge
        size={size}
        color={PURPLE}
        title={title}
        label={`◆ Watchlist + ${att.proposalChannel || 'Proposal'}`}
      />
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
    </>
  )
}