/** Resolve trailing-stop % from protection advisory — trail width matches advised stop distance when possible. */

export type TrailResolution = {
  pct: number
  stopDistPct: number | null
  advisorTrail: boolean
  /** Trail width equals the advised fixed-stop distance (e.g. both 12%). */
  matchesStopWidth: boolean
}

export function resolvedTrailPct(pr: any): TrailResolution | null {
  if (!pr) return null
  const stopDist = pr.stop_distance_pct != null ? Number(pr.stop_distance_pct) : null
  if (pr.suggested_trail_pct != null) {
    const pct = Number(pr.suggested_trail_pct)
    return {
      pct,
      stopDistPct: stopDist,
      advisorTrail: Boolean(pr.trail_recommended),
      matchesStopWidth: Boolean(pr.trail_matches_stop) || (stopDist != null && Math.abs(pct - stopDist) < 1.2),
    }
  }
  if (pr.trail_recommended && pr.trail_offset != null) {
    const pct = pr.trail_type === 'PERCENT' ? Number(pr.trail_offset) : 10
    return { pct, stopDistPct: stopDist, advisorTrail: true, matchesStopWidth: stopDist != null && Math.abs(pct - stopDist) < 1.2 }
  }
  if (stopDist != null && stopDist >= 3) {
    const pct = Math.round(stopDist * 10) / 10
    return { pct, stopDistPct: stopDist, advisorTrail: false, matchesStopWidth: true }
  }
  return null
}

export function protectionExplain(pr: any, trail: TrailResolution | null, opts?: { brokerFixedActive?: boolean }): string {
  const dist = trail?.stopDistPct ?? pr?.stop_distance_pct
  const distLbl = dist != null ? `${Number(dist).toFixed(1)}%` : '—'
  if (opts?.brokerFixedActive) {
    return `Live fixed stop @ $${Number(pr?.stop_price).toFixed(2)} (${distLbl} below) — trigger stays at $${Number(pr?.stop_price).toFixed(2)} until hit or you cancel/replace. Trail ${trail?.pct ?? distLbl}% is optional if you later want the stop to ratchet up with price.`
  }
  if (pr?.trail_recommended && trail) {
    return `Advisor recommends ${trail.pct}% trailing (ratchets up with price). Fixed stop is the fallback if you want a non-moving trigger.`
  }
  if (trail?.matchesStopWidth) {
    return `Fixed @ $${Number(pr?.stop_price).toFixed(2)} (${distLbl} below) — trigger does not rise (advisor default for core holds). Trail ${trail.pct}% uses the same ${distLbl} width but ratchets up — usually better when the stock has already run (e.g. YTD +100%).`
  }
  return `Fixed stop advisory · optional ${trail?.pct ?? '—'}% trail`
}