/**
 * Client-side CSV export for Path B broker proposals queue (WP-T5).
 * Read-only download — no broker write / no auto-route.
 */

function esc(v: unknown): string {
  if (v == null) return ''
  const s = String(v)
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`
  return s
}

const HEADERS = [
  'id',
  'symbol',
  'account',
  'intended_broker',
  'strategy_id',
  'status',
  'queue_kind',
  'routing_lane',
  'shares',
  'entry',
  'stop',
  'target',
  'rr_planned',
  'rr_live',
  'thesis_zone',
  'route_ready',
  'source',
  'created_at',
  'priority',
] as const

function routingLaneOf(p: any): string {
  let basis = p.sizing_basis
  if (typeof basis === 'string') {
    try { basis = JSON.parse(basis) } catch { basis = null }
  }
  return basis?.routing_lane || p.routing_lane || p.source_attribution?.routing_lane || ''
}

function cell(p: any, key: string): unknown {
  switch (key) {
    case 'strategy_id': return p.strategy_id || p.resolved_strategy_id
    case 'shares': return p.shares ?? p.qty ?? p.quantity
    case 'entry': return p.entry ?? p.entry_price ?? p.limit_price
    case 'stop': return p.stop ?? p.stop_price
    case 'target': return p.target ?? p.target_price
    case 'rr_planned': return p.rr ?? p.planned_rr ?? p.risk_reward
    case 'rr_live': return p.rr_live ?? p.live_rr
    case 'thesis_zone': return p.thesis_zone ?? p.zone ?? p.thesis_validity?.zone_status
    case 'route_ready': return p.route_ready ?? p.lane_gates?.route_ready ?? ''
    case 'routing_lane': return routingLaneOf(p)
    case 'source': return p.source ?? p.source_attribution?.source ?? p.origin
    case 'priority': return p.priority ?? p.hermes_score ?? p.score
    case 'queue_kind': return p.queue_kind || p.proposal_kind || 'proposal'
    default: return p?.[key]
  }
}

export function brokerProposalsToCsv(rows: any[]): string {
  const lines = [HEADERS.join(',')]
  for (const p of rows) {
    lines.push(HEADERS.map(k => esc(cell(p, k))).join(','))
  }
  return lines.join('\n') + '\n'
}

export function downloadBrokerProposalsCsv(rows: any[], filename?: string) {
  const csv = brokerProposalsToCsv(rows)
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || `broker-proposals-${new Date().toISOString().slice(0, 10)}.csv`
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
