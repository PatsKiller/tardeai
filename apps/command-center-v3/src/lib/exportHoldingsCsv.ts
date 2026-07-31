/** Client-side CSV export for filtered Portfolio holdings (WP-F). */

function esc(v: unknown): string {
  if (v == null) return ''
  const s = String(v)
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`
  return s
}

export function holdingsToCsv(rows: any[]): string {
  const headers = [
    'symbol', 'account', 'name', 'is_cash', 'shares', 'price', 'current_price',
    'market_value', 'day_change', 'day_change_pct', 'cost_basis', 'gain_loss',
    'gain_loss_pct', 'portfolio_pct', 'signal', 'sector',
  ]
  const lines = [headers.join(',')]
  for (const h of rows) {
    lines.push(headers.map(k => esc(h?.[k])).join(','))
  }
  return lines.join('\n') + '\n'
}

export function downloadHoldingsCsv(rows: any[], filename?: string) {
  const csv = holdingsToCsv(rows)
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || `portfolio-holdings-${new Date().toISOString().slice(0, 10)}.csv`
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
