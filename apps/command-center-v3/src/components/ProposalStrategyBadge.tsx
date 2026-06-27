type Size = 'sm' | 'md'

const sizeStyle = (size: Size) => size === 'md'
  ? { fontSize: 10, padding: '3px 9px', borderRadius: 5 }
  : { fontSize: 9, padding: '2px 7px', borderRadius: 4 }

export default function ProposalStrategyBadge({
  proposal,
  size = 'sm',
}: {
  proposal: Record<string, unknown> | null | undefined
  size?: Size
}) {
  const p = proposal || {}
  const id = String(p.resolved_strategy_id || p.strategy_id || '').trim()
  if (!id) return null
  const display = String(p.strategy_display_name || id.replace(/_/g, ' ')).trim()
  const typeLabel = String(p.strategy_type_label || p.strategy_type || '').trim()
  const title = [
    id,
    p.strategy_description || p.strategy_purpose,
    typeLabel,
    p.strategy_timeframe || p.strategy_timeframe_class,
  ].filter(Boolean).join(' · ')

  return (
    <span
      title={title}
      style={{
        ...sizeStyle(size),
        fontWeight: 700,
        background: 'rgba(249,115,22,.14)',
        color: '#fb923c',
        whiteSpace: 'nowrap',
      }}
    >
      {display}
    </span>
  )
}