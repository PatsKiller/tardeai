/**
 * Surface freshness honesty for Command Center chrome.
 *
 * R24 rule (copied, not reinvented): HTTP 200 is not a live claim.
 * When a block aggregates sources, age is the oldest contributing stamp —
 * never composition time and never the freshest sibling.
 *
 * Display contract: STALE must be visible on the surface (label + amber),
 * not only buried in a tooltip `as_of`.
 */

export type SurfaceFreshness = {
  stale: boolean
  /** Short operator-facing reason, or null when live. */
  reason: string | null
  /** Best available as-of ISO/date string for the block. */
  asOf: string | null
  ageHours: number | null
  /** Visible chrome fragment, e.g. "STALE · cache 85h". Null when live. */
  surfaceLabel: string | null
}

const HOUR_MS = 3_600_000

/** Parse ISO / date-only / epoch-ish values. Returns null when unusable. */
export function parseTimestamp(raw: unknown, nowMs = Date.now()): Date | null {
  if (raw == null || raw === '') return null
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    const ms = raw > 1e12 ? raw : raw > 1e9 ? raw * 1000 : NaN
    if (!Number.isFinite(ms)) return null
    const d = new Date(ms)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const s = String(raw).trim()
  if (!s) return null
  // Date-only → local midnight (session calendar), same as isScanStale.
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) {
    const d = new Date(`${s}T00:00:00`)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return null
  // Reject absurd future stamps (>1h ahead) as unusable for age.
  if (d.getTime() - nowMs > HOUR_MS) return null
  return d
}

function ageHoursFrom(ts: Date | null, nowMs: number): number | null {
  if (!ts) return null
  const h = (nowMs - ts.getTime()) / HOUR_MS
  return h >= 0 ? h : null
}

function fmtAgeHours(h: number | null): string {
  if (h == null) return ''
  if (h < 1) return `${Math.max(1, Math.round(h * 60))}m`
  if (h < 48) return `${Math.round(h)}h`
  return `${(h / 24).toFixed(1)}d`
}

/**
 * Trade-AI / scanner chrome freshness.
 *
 * Prefer the API's own `stale` + `cached_at` / `cache_age_sec` over
 * session-normalized `run_date` (heal bumps run_date to "today" while the
 * cache stays empty for days — the 2026-08-28 empty cache case).
 */
export function tradeAiSurfaceFreshness(
  tradeAi: Record<string, unknown> | null | undefined,
  now: Date = new Date(),
): SurfaceFreshness {
  const nowMs = now.getTime()
  if (!tradeAi) {
    return {
      stale: true,
      reason: 'trade-ai payload missing',
      asOf: null,
      ageHours: null,
      surfaceLabel: 'STALE · no scan payload',
    }
  }

  const cachedAt = parseTimestamp(
    tradeAi.cached_at ?? tradeAi._cached_at ?? tradeAi.as_of,
    nowMs,
  )
  const cacheAgeSec = Number(tradeAi.cache_age_sec)
  const ageFromCache =
    Number.isFinite(cacheAgeSec) && cacheAgeSec >= 0
      ? cacheAgeSec / 3600
      : ageHoursFrom(cachedAt, nowMs)

  const apiStale = tradeAi.stale === true
  // API marks stale after 600s; chrome uses a looser glance threshold (6h) so
  // brief warm-cache lag is not amber noise, but multi-hour empty caches are.
  const cacheOld = ageFromCache != null && ageFromCache >= 6
  const go = Number(tradeAi.go_count ?? 0)
  const wait = Number(tradeAi.wait_count ?? 0)
  const avoid = Number(tradeAi.avoid_count ?? 0)
  const scanned = Number(
    tradeAi.current_run_scanned
      ?? tradeAi.latest_run_symbols_scanned
      ?? tradeAi.ticker_count
      ?? 0,
  )
  const emptyUniverse =
    (Number.isFinite(scanned) && scanned === 0)
    && go === 0 && wait === 0
    && (!Number.isFinite(avoid) || avoid === 0)

  // Session-normalized run_date can lie "today" after heal — still honor true prior dates.
  const runDateRaw = tradeAi.run_date ?? tradeAi.date
  let runDatePrior = false
  if (typeof runDateRaw === 'string' && /^\d{4}-\d{2}-\d{2}/.test(runDateRaw)) {
    const m = runDateRaw.match(/(\d{4}-\d{2}-\d{2})/)
    if (m) {
      const scan = new Date(`${m[1]}T00:00:00`)
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
      const scanDay = new Date(scan.getFullYear(), scan.getMonth(), scan.getDate())
      runDatePrior = scanDay.getTime() < today.getTime()
    }
  }

  const stale =
    apiStale
    || cacheOld
    || runDatePrior
    || (emptyUniverse && (apiStale || cacheOld || ageFromCache == null))

  const asOf =
    (typeof tradeAi.cached_at === 'string' && tradeAi.cached_at)
    || (typeof tradeAi._cached_at === 'string' && tradeAi._cached_at)
    || (typeof tradeAi.as_of === 'string' && tradeAi.as_of)
    || (typeof runDateRaw === 'string' ? runDateRaw : null)
    || null

  if (!stale) {
    return { stale: false, reason: null, asOf, ageHours: ageFromCache, surfaceLabel: null }
  }

  const bits: string[] = []
  if (emptyUniverse) bits.push('empty scan')
  if (apiStale || cacheOld) bits.push(`cache ${fmtAgeHours(ageFromCache) || 'old'}`)
  else if (runDatePrior) bits.push('prior session')
  const reason = bits.join(' · ') || 'stale'
  return {
    stale: true,
    reason,
    asOf,
    ageHours: ageFromCache,
    surfaceLabel: `STALE · ${reason}`,
  }
}

/**
 * Overview chrome freshness. Uses overview.as_of when present; falls back to
 * pricing.last_repriced. Threshold 36h so overnight quiet markets stay calm,
 * but multi-day freezes surface.
 */
export function overviewSurfaceFreshness(
  overview: Record<string, unknown> | null | undefined,
  now: Date = new Date(),
): SurfaceFreshness {
  const nowMs = now.getTime()
  if (!overview) {
    return {
      stale: true,
      reason: 'overview missing',
      asOf: null,
      ageHours: null,
      surfaceLabel: 'STALE · no overview',
    }
  }
  const pricing = (overview.pricing && typeof overview.pricing === 'object')
    ? (overview.pricing as Record<string, unknown>)
    : {}
  const stamps = [
    parseTimestamp(overview.as_of, nowMs),
    parseTimestamp(pricing.last_repriced ?? overview.last_repriced, nowMs),
  ].filter((d): d is Date => !!d)

  // Oldest contributing stamp drives block age.
  const oldest = stamps.length
    ? new Date(Math.min(...stamps.map(d => d.getTime())))
    : null
  const age = ageHoursFrom(oldest, nowMs)
  const asOf =
    (typeof overview.as_of === 'string' && overview.as_of)
    || (typeof pricing.last_repriced === 'string' && pricing.last_repriced)
    || (typeof overview.last_repriced === 'string' && overview.last_repriced)
    || (oldest ? oldest.toISOString() : null)

  const stale = age != null && age >= 36
  if (!stale) {
    return { stale: false, reason: null, asOf, ageHours: age, surfaceLabel: null }
  }
  const reason = `as_of ${fmtAgeHours(age)}`
  return {
    stale: true,
    reason,
    asOf,
    ageHours: age,
    surfaceLabel: `STALE · ${reason}`,
  }
}

/** R24-aligned provenance for Watch Intelligence synopsis (not InstrumentRecord). */
export const WI_SYNOPSIS_PROVENANCE = {
  dataSource: 'decision_projection' as const,
  liveClaim: false as const,
  spine: false as const,
  schema: 'watchlist_intelligence.card.v1',
  /** Visible one-liner under the synopsis. */
  surfaceNote:
    'Decision projection — not InstrumentRecord spine (cc_narrative / lessons)',
}
