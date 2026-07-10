export function fmt$(n: number | null | undefined, decimals = 0): string {
  if (n == null) return '--'
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

export function fmtPct(n: number | null | undefined, decimals = 1): string {
  if (n == null) return '--'
  return `${n >= 0 ? '+' : ''}${n.toFixed(decimals)}%`
}

export function fmtNum(n: number | null | undefined, decimals = 0): string {
  if (n == null) return '--'
  return n.toLocaleString('en-US', { maximumFractionDigits: decimals })
}

/** Share volume for scanner (Finviz-style compact). */
export function fmtVol(n: number | null | undefined): string {
  if (n == null || n === 0) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`
  return String(Math.round(n))
}
