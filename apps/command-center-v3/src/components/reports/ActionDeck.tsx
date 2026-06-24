export interface DeckAction {
  id?: string
  text: string
  symbol?: string
  severity?: string
  route?: string
  route_label?: string
  source?: string
  action_class?: string
}

const SEV: Record<string, string> = { critical: '#ef4444', urgent: '#ef4444', warning: '#f59e0b', info: '#60a5fa' }

export function buildDeckActions(opts: {
  briefActions?: any[]
  triggeredPositions?: { symbol: string; stop_price?: number; market_value?: number }[]
  rankedLines?: string[]
  cap?: number
}): DeckAction[] {
  const cap = opts.cap ?? 8
  const out: DeckAction[] = []
  const seen = new Set<string>()

  const push = (a: DeckAction) => {
    const key = `${(a.symbol || '').toUpperCase()}|${a.text.slice(0, 80).toLowerCase()}`
    if (seen.has(key)) return
    seen.add(key)
    out.push(a)
  }

  for (const p of opts.triggeredPositions || []) {
    push({
      text: `${p.symbol} stop triggered — verify broker protection`,
      symbol: p.symbol,
      severity: 'urgent',
      route: '/v3/risk',
      route_label: 'Risk',
      source: 'live-stops',
    })
  }
  for (const a of opts.briefActions || []) {
    const text = typeof a === 'string' ? a : (a.text || a.message || a.title || '')
    if (!text) continue
    push({
      text,
      symbol: a.symbol,
      severity: a.severity || 'warning',
      route: a.route || '/v3/',
      route_label: a.route_label || 'Action',
      source: 'morning-brief',
    })
  }
  for (const line of opts.rankedLines || []) {
    push({ text: line, severity: 'info', route: '/v3/', route_label: 'Review', source: 'brief-ranked' })
  }
  return out.slice(0, cap)
}

export default function ActionDeck({ actions }: { actions: DeckAction[] }) {
  if (!actions.length) {
    return <div style={{ fontSize: 11, color: 'var(--text3)', padding: 12 }}>No prioritized actions from today&apos;s brief.</div>
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {actions.map((a, i) => {
        const c = SEV[(a.severity || 'info').toLowerCase()] || '#60a5fa'
        return (
          <div key={a.id || i} style={{
            display: 'flex', gap: 10, alignItems: 'flex-start', padding: '10px 12px',
            background: 'var(--bg1)', border: '1px solid var(--border)', borderLeft: `4px solid ${c}`, borderRadius: 9,
          }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, color: 'var(--text0)', lineHeight: 1.45 }}>{a.text}</div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {a.symbol && <span style={{ fontWeight: 800, color: '#60a5fa', fontFamily: 'monospace' }}>{a.symbol}</span>}
                {a.source && <span>{a.source}</span>}
              </div>
            </div>
            {a.route && (
              <a href={a.route} style={{ fontSize: 10, fontWeight: 700, color: '#60a5fa', textDecoration: 'none', whiteSpace: 'nowrap' }}>
                {a.route_label || 'Open'} →
              </a>
            )}
          </div>
        )
      })}
    </div>
  )
}