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
