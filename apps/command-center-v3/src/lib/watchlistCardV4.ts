// Security Card v4 helpers — market-aware staleness + rule-of-one text composition.
// v4 evaluation build (2026-07-04, operator-directed): v3 stays untouched; the Watch hub
// toggle picks which card renders. Everything here is presentation logic only.

/** Approximate NYSE session awareness, client-side (weekends + rough hours only —
 *  holidays are owned by the backend market_session module; a holiday Monday will
 *  briefly re-arm staleness, which is acceptable for a display hint). */
function lastMarketCloseMs(now: Date): number {
  const close = new Date(now)
  close.setHours(16, 0, 0, 0)
  const day = now.getDay()
  if (day === 0) close.setDate(close.getDate() - 2)            // Sun → Friday 16:00
  else if (day === 6) close.setDate(close.getDate() - 1)       // Sat → Friday 16:00
  else if (now.getTime() < close.getTime()) {
    close.setDate(close.getDate() - (day === 1 ? 3 : 1))       // before today's close → prior session
  }
  return close.getTime()
}

function marketOpenNow(now: Date): boolean {
  const day = now.getDay()
  if (day === 0 || day === 6) return false
  const mins = now.getHours() * 60 + now.getMinutes()
  return mins >= 9 * 60 + 30 && mins < 16 * 60
}

/** Weekend-calm staleness: 1h-old data is only STALE if the market has actually moved
 *  since enrichment — i.e. the market is open now, or the enrichment predates the last
 *  close. A Friday-evening enrichment stays fresh all weekend and re-arms at Monday
 *  09:30. Mirrors the server-side pipeline-freshness market-closure grace. */
export function marketAwareStale(lastEnrichedAt: string | null | undefined, nowMs = Date.now()): boolean {
  if (!lastEnrichedAt) return false
  const t = new Date(lastEnrichedAt).getTime()
  if (!Number.isFinite(t)) return false
  const ageMs = nowMs - t
  if (ageMs <= 3600 * 1000) return false
  const now = new Date(nowMs)
  return marketOpenNow(now) || t < lastMarketCloseMs(now)
}

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim()

/** Rule-of-one sentence composer: drops segments that just restate what's already said
 *  (the v3 banner could render "refresh before acting" twice from warning + reasoning). */
export function composeWhy(parts: (string | null | undefined)[]): string {
  const kept: string[] = []
  let acc = ''
  for (const raw of parts) {
    const p = (raw || '').trim()
    if (!p) continue
    const n = norm(p)
    if (!n) continue
    if (acc.includes(n)) continue
    const tokens = n.split(' ').filter(w => w.length > 3)
    const dupTokens = tokens.filter(w => acc.includes(w)).length
    if (tokens.length >= 3 && dupTokens / tokens.length > 0.6) continue
    kept.push(p)
    acc += ` ${n}`
  }
  return kept.join(' · ')
}

/** True when two headlines are effectively the same story (catalyst vs top news dedupe). */
export function sameHeadline(a?: string | null, b?: string | null): boolean {
  if (!a || !b) return false
  const na = norm(String(a)), nb = norm(String(b))
  if (!na || !nb) return false
  if (na === nb) return true
  const short = na.length <= nb.length ? na : nb
  const long = na.length <= nb.length ? nb : na
  return short.length >= 24 && long.startsWith(short.slice(0, Math.min(short.length, 48)))
}

export type VisibleWarningSeverity = 'red' | 'amber'

/** Inline warning line — always on-page (never tooltip-only). */
export function warningLineStyle(severity: VisibleWarningSeverity): { color: string; fontWeight: number; fontSize: number; lineHeight: number } {
  return {
    fontSize: 10.5,
    fontWeight: 600,
    lineHeight: 1.45,
    color: severity === 'red' ? '#ef5350' : '#f5a623',
  }
}

/** Catalyst freshness for the intelligence line: amber past 7 days. */
export function catalystAgeDays(catalystAt: string | null | undefined): number | null {
  if (!catalystAt) return null
  const t = new Date(catalystAt).getTime()
  if (!Number.isFinite(t)) return null
  return Math.max(0, Math.floor((Date.now() - t) / 864e5))
}
