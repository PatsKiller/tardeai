/** Tagged CIO v2 evidence bullets + data_i_doubt banner (fleet parity UI). */

export type EvidenceItem = { tag?: string; text?: string }

const TAG_COLOR: Record<string, string> = {
  fact: '#60a5fa',
  technical: '#a855f7',
  risk: '#f59e0b',
}

function normalizeEvidence(raw: unknown): EvidenceItem[] {
  if (!raw) return []
  if (typeof raw === 'string') {
    try {
      return normalizeEvidence(JSON.parse(raw))
    } catch {
      return raw.trim() ? [{ tag: 'fact', text: raw }] : []
    }
  }
  if (!Array.isArray(raw)) return []
  return raw.map((item) => {
    if (typeof item === 'string') return { tag: 'fact', text: item }
    if (item && typeof item === 'object') {
      const o = item as EvidenceItem
      return { tag: (o.tag || 'fact').toLowerCase(), text: o.text || '' }
    }
    return { tag: 'fact', text: String(item) }
  }).filter((e) => e.text?.trim())
}

export function EvidenceBlock({
  evidence,
  dataIDoubt,
  title,
  compact,
  maxItems = 5,
}: {
  evidence?: unknown
  dataIDoubt?: string | null
  title?: string
  compact?: boolean
  maxItems?: number
}) {
  const items = normalizeEvidence(evidence).slice(0, maxItems)
  const doubt = (dataIDoubt || 'none').trim()
  const showDoubt = doubt && doubt.toLowerCase() !== 'none'
  if (!items.length && !showDoubt) return null

  const fs = compact ? 10 : 11
  return (
    <div style={{
      marginTop: compact ? 4 : 6,
      padding: compact ? '5px 8px' : '7px 10px',
      borderRadius: 8,
      background: 'rgba(15,23,42,.45)',
      border: '1px solid rgba(148,163,184,.2)',
    }}>
      {title && (
        <div style={{ fontSize: 9, fontWeight: 800, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 4 }}>
          {title}
        </div>
      )}
      {items.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 16, listStyle: 'disc' }}>
          {items.map((ev, i) => {
            const tag = (ev.tag || 'fact').toLowerCase()
            const color = TAG_COLOR[tag] || '#94a3b8'
            return (
              <li key={i} style={{ fontSize: fs, lineHeight: 1.45, color: '#cbd5e1', marginBottom: 2 }}>
                <span style={{ fontSize: 8.5, fontWeight: 800, color, marginRight: 5, textTransform: 'uppercase' }}>
                  [{tag}]
                </span>
                {ev.text}
              </li>
            )
          })}
        </ul>
      )}
      {showDoubt && (
        <div style={{
          fontSize: fs,
          color: '#fbbf24',
          marginTop: items.length ? 5 : 0,
          lineHeight: 1.4,
          fontWeight: 650,
        }}>
          Data doubt: {doubt}
        </div>
      )}
    </div>
  )
}