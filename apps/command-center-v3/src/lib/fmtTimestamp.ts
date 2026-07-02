/** Format ISO / DB timestamps for desk UI (local time, compact). */
export function fmtDeskTimestamp(iso: string | null | undefined): string | null {
  if (!iso) return null
  const raw = String(iso).trim()
  if (!raw) return null
  const d = new Date(/[zZ]$|[+-]\d\d:?\d\d$/.test(raw) ? raw : `${raw}Z`)
  if (Number.isNaN(d.getTime())) return raw.slice(0, 16).replace('T', ' ')
  return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function fmtDeskAge(iso: string | null | undefined): string | null {
  if (!iso) return null
  const raw = String(iso).trim()
  const d = new Date(/[zZ]$|[+-]\d\d:?\d\d$/.test(raw) ? raw : `${raw}Z`)
  if (Number.isNaN(d.getTime())) return null
  const mins = Math.floor((Date.now() - d.getTime()) / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 48) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}