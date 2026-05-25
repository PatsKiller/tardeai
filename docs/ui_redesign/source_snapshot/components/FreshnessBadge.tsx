interface Props {
  lastRefresh?: string | null
  label?: string
  context?: string | null  // weekend context, stale reason
  isWeekend?: boolean
}

export default function FreshnessBadge({ lastRefresh, label, context, isWeekend }: Props) {
  if (!lastRefresh) return null

  let ageMinutes = 0
  let color = '#0ecb81' // green
  let text = 'Live'
  let tooltip = ''

  try {
    const ts = new Date(lastRefresh)
    ageMinutes = Math.floor((Date.now() - ts.getTime()) / 60000)
    const hours = Math.floor(ageMinutes / 60)

    if (isWeekend && hours > 24 && hours < 72) {
      color = '#4a90f4' // blue for weekend-paused
      text = `${hours}h · Weekend`
      tooltip = context || 'Weekend — market data refreshes Monday 07:00 ET'
    } else if (ageMinutes < 60) {
      color = '#0ecb81'
      text = `${ageMinutes}m ago`
      tooltip = 'Data is current'
    } else if (hours < 6) {
      color = '#0ecb81'
      text = `${hours}h ago`
      tooltip = 'Data is recent'
    } else if (hours < 24) {
      color = '#f0b90b'
      text = `${hours}h ago`
      tooltip = 'Data is aging — refresh recommended'
    } else {
      color = '#f6465d'
      text = `${hours}h ago`
      tooltip = context || `Data is ${hours}h stale — check pipeline`
    }
  } catch {
    text = 'Unknown'
    color = '#888'
  }

  return (
    <span
      title={tooltip}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        fontSize: 10,
        color,
        padding: '2px 8px',
        borderRadius: 10,
        border: `1px solid ${color}33`,
        background: `${color}11`,
        cursor: tooltip ? 'help' : 'default',
      }}
    >
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: color }} />
      {label && <span>{label}:</span>}
      {text}
    </span>
  )
}
