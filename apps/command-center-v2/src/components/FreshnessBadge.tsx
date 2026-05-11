interface Props {
  lastRefresh?: string | null
  label?: string
}

export default function FreshnessBadge({ lastRefresh, label }: Props) {
  if (!lastRefresh) return null

  let ageMinutes = 0
  let color = '#0ecb81' // green
  let text = 'Live'

  try {
    const ts = new Date(lastRefresh)
    ageMinutes = Math.floor((Date.now() - ts.getTime()) / 60000)
    if (ageMinutes < 60) {
      color = '#0ecb81'
      text = `${ageMinutes}m ago`
    } else if (ageMinutes < 360) {
      color = '#f0b90b'
      text = `${Math.floor(ageMinutes / 60)}h ago`
    } else {
      color = '#f6465d'
      text = `${Math.floor(ageMinutes / 60)}h ago`
    }
  } catch {
    text = 'Unknown'
    color = '#888'
  }

  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 4,
      fontSize: 10,
      color,
      padding: '2px 8px',
      borderRadius: 10,
      border: `1px solid ${color}33`,
      background: `${color}11`,
    }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: color }} />
      {label && <span>{label}:</span>}
      {text}
    </span>
  )
}
