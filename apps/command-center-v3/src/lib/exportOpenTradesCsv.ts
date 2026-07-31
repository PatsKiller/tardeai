/**
 * Client-side CSV export for filtered Open Trades (WP-T4).
 * Read-only download — no broker write.
 */

function esc(v: unknown): string {
  if (v == null) return ''
  const s = String(v)
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`
  return s
}

const HEADERS = [
  'symbol',
  'account',
  'broker',
  'strategy',
  'shares',
  'current_price',
  'market_value',
  'unrealized_pnl',
  'unrealized_pnl_pct',
  'today_move_pct',
  'basis',
  'protection_state',
  'operator_priority',
  'operator_decision',
  'risk_flags',
  'r_multiple',
  'rsi',
  'sector',
  'data_freshness',
  'trade_id',
] as const

function cell(p: any, key: string): unknown {
  switch (key) {
    case 'shares': return p.shares ?? p.quantity ?? p.qty
    case 'current_price': return p.current_price ?? p.price
    case 'basis': return p.basis ?? p.avg_cost ?? p.cost_basis
    case 'rsi': return p.technical?.rsi ?? p.rsi
    case 'sector': return p.sector_relative?.sector ?? p.sector
    case 'risk_flags': return Array.isArray(p.risk_flags) ? p.risk_flags.join('|') : p.risk_flags
    default: return p?.[key]
  }
}

export function openTradesToCsv(rows: any[]): string {
  const lines = [HEADERS.join(',')]
  for (const p of rows) {
    lines.push(HEADERS.map(k => esc(cell(p, k))).join(','))
  }
  return lines.join('\n') + '\n'
}

export function downloadOpenTradesCsv(rows: any[], filename?: string) {
  const csv = openTradesToCsv(rows)
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || `open-trades-${new Date().toISOString().slice(0, 10)}.csv`
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
