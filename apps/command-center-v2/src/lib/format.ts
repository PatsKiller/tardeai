// Matches v1 command_center.html formatting exactly

/** $1,187,025 or $-5,451 (sign inside, no + for positive) */
export const fmt$ = (v: number, decimals = 0) =>
  v == null ? '—' : '$' + v.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })

/** +$5,451 or $-5,451 (+ for positive, sign inside $) */
export const fmtSigned$ = (v: number) =>
  v == null ? '—' : (v >= 0 ? '+' : '') + fmt$(v)

/** +1.23% or -0.46% */
export const fmtPct = (v: number, decimals = 2) =>
  v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(decimals) + '%'

/** 1,234 with commas */
export const fmtN = (v: number, decimals = 0) =>
  v == null ? '—' : v.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })

/** 1.2B / 456.3M / 12.5K */
export const fmtCompact = (v: number) => {
  if (v == null) return '—'
  if (Math.abs(v) >= 1e9) return (v / 1e9).toFixed(1) + 'B'
  if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(1) + 'M'
  if (Math.abs(v) >= 1e3) return (v / 1e3).toFixed(1) + 'K'
  return v.toFixed(1)
}

/** Color: green for positive, red for negative, muted for zero/null */
export const deltaColor = (v: number | null | undefined) =>
  v == null ? 'var(--text3)' : v > 0 ? 'var(--green)' : v < 0 ? 'var(--red)' : 'var(--text2)'

/** "3h ago" / "2d ago" — handles "2026-04-30 13:15:00 ET" format */
export const timeAgo = (iso: string) => {
  if (!iso) return '—'
  // Strip timezone abbreviations (ET, EST, EDT, PT, etc.) that Date() can't parse
  const cleaned = iso.replace(/\s+[A-Z]{2,4}$/, '').trim()
  const ts = new Date(cleaned).getTime()
  if (isNaN(ts)) return '—'
  const ms = Date.now() - ts
  if (ms < 0) return 'just now'
  const h = ms / 3600000
  if (h < 1) return Math.round(h * 60) + 'm ago'
  if (h < 24) return Math.round(h) + 'h ago'
  return Math.round(h / 24) + 'd ago'
}
