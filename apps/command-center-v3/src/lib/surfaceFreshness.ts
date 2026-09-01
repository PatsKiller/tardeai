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
  /**
   * Oldest contributing DATA date, and the account that owns it.
   *
   * Distinct from `asOf`: `as_of` on the overview payload records when the
   * LOADER RAN (portfolio_loader writes it `= today`), not when any data was
   * fetched. On 2026-09-01 it read 2026-08-29 while the Schwab rows carried
   * 08-31 and the moomoo/alpaca CASH rows carried 08-03/04 — older than 28 of
   * 30 rows and newer than the other 2. One number, wrong in both directions.
   *
   * null means the producer did not supply one. That is UNDATED, never "today".
   */
  dataAsOf: string | null
  dataAsOfAccount: string | null
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
      dataAsOf: null,
      dataAsOfAccount: null,
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
  const cacheMissing = tradeAi.cache_missing === true
  // API marks stale after ~600s (warm-cache TTL / "please refresh"). That is a
  // transport signal — NOT operator chrome STALE. Chrome uses a 6h glance
  // threshold so brief warm lag is not amber noise; multi-hour empty / prior
  // caches still surface. Bare `apiStale` used to paint SETUPS STALE at ~10–21m
  // after a good Finviz recovery with tickers>0 (2026-09-01).
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

  // Do NOT OR bare apiStale: RUN_UNDERFILLED / cache-TTL stale must not become
  // the SETUPS STALE badge when the scan universe is present and <6h old.
  const stale =
    cacheMissing
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
    // tradeAiSurfaceFreshness has no data clock of its own; the scanner surface
    // dates itself from its run/cache stamps. Explicitly null rather than absent.
    return { stale: false, reason: null, asOf, ageHours: ageFromCache, surfaceLabel: null,
             dataAsOf: null, dataAsOfAccount: null }
  }

  const bits: string[] = []
  if (cacheMissing) bits.push('cache missing')
  if (emptyUniverse) bits.push('empty scan')
  if (cacheOld || (emptyUniverse && apiStale)) bits.push(`cache ${fmtAgeHours(ageFromCache) || 'old'}`)
  else if (runDatePrior) bits.push('prior session')
  const reason = bits.join(' · ') || 'stale'
  return {
    stale: true,
    reason,
    asOf,
    ageHours: ageFromCache,
    surfaceLabel: `STALE · ${reason}`,
    dataAsOf: null,
    dataAsOfAccount: null,
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
      dataAsOf: null,
      dataAsOfAccount: null,
    }
  }
  const pricing = (overview.pricing && typeof overview.pricing === 'object')
    ? (overview.pricing as Record<string, unknown>)
    : {}
  const dataAsOf = typeof overview.data_as_of === 'string' && overview.data_as_of
    ? overview.data_as_of
    : null
  const dataAsOfAccount = typeof overview.data_as_of_account === 'string' && overview.data_as_of_account
    ? overview.data_as_of_account
    : null

  // The DATA clock leads. `as_of` is the loader-run date and cannot date the
  // data; it stays on the payload and is reported, but it no longer sets age.
  const dataStamp = parseTimestamp(dataAsOf, nowMs)

  // No data clock is UNDATED — fail closed. A missing clock that falls back to
  // a loader-run date reports fresh while the data underneath is a month old,
  // which is exactly the defect this replaces.
  if (!dataStamp) {
    return {
      stale: true,
      reason: 'data_as_of UNDATED',
      asOf: (typeof overview.as_of === 'string' && overview.as_of) || null,
      ageHours: null,
      surfaceLabel: 'STALE · data UNDATED',
      dataAsOf: null,
      dataAsOfAccount,
    }
  }

  const age = ageHoursFrom(dataStamp, nowMs)
  const stale = age != null && age >= 36
  const acct = dataAsOfAccount ? ` · ${dataAsOfAccount}` : ''

  if (!stale) {
    return {
      stale: false, reason: null, asOf: dataAsOf, ageHours: age,
      surfaceLabel: null, dataAsOf, dataAsOfAccount,
    }
  }
  // Name the account so a stale $500 cash row cannot hide behind 28 fresh rows.
  const reason = `data ${fmtAgeHours(age)}${acct}`
  return {
    stale: true,
    reason,
    asOf: dataAsOf,
    ageHours: age,
    surfaceLabel: `STALE · ${reason}`,
    dataAsOf,
    dataAsOfAccount,
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
