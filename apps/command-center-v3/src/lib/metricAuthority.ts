// Trust debt LQ-20261107-1837 (coding standard C4: "One authority per metric. A number shown in two
// places is read from the same authority (G7). No second calculation."). Every CC v3 surface that
// prints one of these three numbers reads it through a function here, from the one endpoint below.
// Raw rows are never re-counted and no surface re-derives a value from `positions[]`.
//
//   market-risk score     MarketRiskSnapshot@v1  /api/v2/market-risk/latest   tier, score, as_of
//   portfolio heat        cio_truth.resolve      /api/v2/cio/pages            positions.portfolio_heat_pct
//   unprotected positions cio_truth.resolve      /api/v2/cio/pages            stops.unprotected_count
//
// /api/v2/risk serves the same cio_truth projection (portfolio_heat_pct, stop_health.unprotected_count);
// it is the same calculation behind a second route, not a second definition.
//
// Genuinely different numbers that are NOT this metric keep a distinct name where they are shown:
//   · risk_management.json's daily heat (all configured stops, invested book) is not the portfolio heat
//     above; /api/v2/home/do-now still publishes it and Home no longer prints it (residual, READY §5).
//   · the open-trades desk counts trades without a WORKING broker stop among positions >= $500; its label
//     names that population instead of saying "unprotected positions".
//
// Pure: no React, no fetch. One display precision for a metric, so two surfaces cannot differ by rounding.
export const MARKET_RISK_API = '/api/v2/market-risk/latest'
export const CIO_PAGES_API = '/api/v2/cio/pages'

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v : null)

/** The C4 authority table, readable by tests and by a reviewer. Never edit a number's surface without it. */
export const METRIC_AUTHORITY = {
  marketRiskScore: { endpoint: MARKET_RISK_API, fields: 'tier, score, as_of', source: 'MarketRiskSnapshot@v1' },
  portfolioHeat: { endpoint: CIO_PAGES_API, fields: 'positions.portfolio_heat_pct', source: 'cio_truth.resolve' },
  unprotectedPositions: { endpoint: CIO_PAGES_API, fields: 'stops.unprotected_count', source: 'cio_truth.resolve' },
} as const

/** One precision for the market-risk score everywhere ("44.2", never 44 on one page and 44.2 on another). */
export function scoreText(score: number | null | undefined): string {
  const n = num(score)
  return n === null ? '—' : n.toFixed(1)
}

/** One precision for portfolio heat everywhere; the authority rounds to 3 dp, the face shows 1. */
export function heatText(pct: number | null | undefined): string {
  const n = num(pct)
  return n === null ? '—' : `${n.toFixed(1)}%`
}

export interface MarketRiskFact { tier: string; score: number | null; asOf: string | null; state: string | null }

/** The market-risk score and tier: the engine snapshot the route serves, never a build artifact's copy. */
export function marketRiskFact(mr: any): MarketRiskFact {
  const tier = str(mr?.tier)?.toUpperCase() ?? 'NOT_EVALUATED'
  return { tier, score: num(mr?.score), asOf: str(mr?.as_of), state: str(mr?.state) }
}

export interface HeatFact { pct: number | null; asOf: string | null; basis: string | null; source: string | null }

/** Portfolio heat from /api/v2/cio/pages (`positions` block of the cio_truth projection). */
export function heatFact(cio: any): HeatFact {
  const p = cio?.positions && typeof cio.positions === 'object' ? cio.positions : null
  return {
    pct: num(p?.portfolio_heat_pct),
    asOf: str(p?.as_of),
    basis: str(p?.loss_basis),
    source: str(p?.source),
  }
}

export interface UnprotectedFact { count: number | null; valueUsd: number | null; asOf: string | null; source: string | null }

/** Unprotected positions (counted rows >= $100 with no working broker stop), from /api/v2/cio/pages. */
export function unprotectedFact(cio: any): UnprotectedFact {
  const p = cio?.positions && typeof cio.positions === 'object' ? cio.positions : null
  const s = cio?.stops && typeof cio.stops === 'object' ? cio.stops : null
  const count = num(s?.unprotected_count)
  // Pair the count with the value over the SAME rows (LQ-20261107-1390): the counted value, else the wide one
  // only when no counted split was published, else none — never a wide sum beside a counted count. A split the
  // producer published as null is a split that failed to compute, not an absent field.
  const counted = num(p?.unprotected_counted_value_usd)
  const wide = num(p?.unprotected_value_usd)
  const hasCountedKey = !!p && Object.prototype.hasOwnProperty.call(p, 'unprotected_counted_value_usd')
  return {
    count,
    valueUsd: counted ?? (hasCountedKey ? null : wide),
    asOf: str(s?.as_of),
    source: str(s?.source),
  }
}

/** The same cio_truth projection behind /api/v2/risk (`stop_health` block). Same calculation, one accessor. */
export function unprotectedFromRisk(risk: any): { count: number | null; asOf: string | null } {
  const h = risk?.stop_health && typeof risk.stop_health === 'object' ? risk.stop_health : null
  return { count: num(h?.unprotected_count), asOf: str(risk?.truth?.as_of) ?? str(risk?.positions_as_of) }
}
