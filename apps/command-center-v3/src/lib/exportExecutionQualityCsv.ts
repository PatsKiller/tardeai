/**
 * Client-side CSV export for TCA / execution-quality fills (WP-T6).
 * Read-only — no broker write.
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
  'strategy_id',
  'fill_quality',
  'intended_entry',
  'fill_price',
  'arrival_price',
  'slippage_pct',
  'slippage_dollars',
  'spread_pct',
  'time_to_fill_seconds',
  'intended_shares',
  'filled_shares',
  'partial_fill',
  'price_improvement_pct',
  'market_session',
  'order_submitted_at',
  'order_filled_at',
  'created_at',
  'proposal_id',
  'paper_trade_id',
] as const

export function executionQualityToCsv(rows: any[]): string {
  const lines = [HEADERS.join(',')]
  for (const e of rows) {
    lines.push(HEADERS.map(k => esc(e?.[k])).join(','))
  }
  return lines.join('\n') + '\n'
}

export function downloadExecutionQualityCsv(rows: any[], filename?: string) {
  const csv = executionQualityToCsv(rows)
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || `execution-quality-${new Date().toISOString().slice(0, 10)}.csv`
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** Filter fills by fill/created timestamp within the last `days` calendar days (local). */
export function filterExecutionByDays(rows: any[], days: number | 'all'): any[] {
  if (days === 'all' || !Array.isArray(rows)) return rows || []
  const cutoff = Date.now() - Number(days) * 864e5
  return rows.filter(e => {
    const raw = e.order_filled_at || e.created_at || e.order_submitted_at
    if (!raw) return true // keep undated (fail-open for completeness)
    const t = new Date(raw).getTime()
    if (!Number.isFinite(t)) return true
    return t >= cutoff
  })
}
