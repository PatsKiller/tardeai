import { classifyRunHealth, isRunHealthDegraded, type RunHealthTier } from './runHealth.ts'

/**
 * setupRunSummary.ts — client half of the run-scoped GO/WAIT/NOGO contract.
 *
 * The backend serves one canonical `setup_run_summary` (SetupRunSummary@v1,
 * scripts/lib/setup_run_contract.py) identically from /api/v2/overview and
 * /api/v2/trade-ai/summary. This module is what every Home surface renders, so
 * a single scanner run is never split across two taxonomies that disagree.
 *
 * It replaces the legacy `go_count` / `wait_count` / `avoid_count` triple,
 * which:
 *   * lumped AVOID, NO_GO, disqualified, filtered-out, unclassified and error
 *     rows under one "NOGO" label;
 *   * read its "scanned" population from a different store than its classified
 *     counts (run_summary.json `ticker_count` vs trade_ai_scans rows).
 *
 * Enforced here (never trusted from the wire, never silently dropped):
 *   * GO + WAIT + NOGO == classified_count
 *   * classified + excluded + review + error + unclassified == scanned_count
 *   * a server PARTIAL / COUNT_MISMATCH / DATA_UNAVAILABLE verdict is surfaced,
 *     never rendered as an authoritative-looking number.
 *
 * RUN HEALTH IS NOT COUNT RECONCILIATION (live capture 2026-09-04, 741207cc2).
 * `degraded` here has always meant "the tally does not reconcile". The run's own
 * health lived on `freshness_status` / `quality`, declared on the type below and
 * read by nothing, so the header painted run 2026-09-04::1730 healthy green:
 * count_integrity RECONCILED, unaccounted 0 — while freshness_status said
 * RUN_UNDERFILLED and the run had scanned 21 symbols against a floor of 40.
 * Both facts were true. The tile could only say one of them.
 * `healthDegraded` is therefore a SEPARATE field, never folded into `degraded`:
 * a run can reconcile perfectly and still be worthless.
 *
 * v2 (live capture 2026-09-04, release a7c550d1d) — THE RESIDUAL WAS UNNAMED.
 * The header rendered "48 classified / 60 scanned / 0 excluded". 48 + 0 is 48;
 * twelve rows had no name anywhere in the string. They were MANUAL_REVIEW
 * escalations the taxonomy had no token for. The population fragment now states
 * every residual class it has a non-zero count for, and `unaccounted` is
 * rendered explicitly rather than being left for the reader to subtract.
 *
 * Pure functions. No network, no React, no side effects.
 */

export type SetupRunSummary = {
  contract_version?: string | null
  run_id?: string | null
  run_label?: string | null
  run_date?: string | null
  run_timestamp?: string | null
  source?: string | null
  calculation_version?: string | null
  scanned_count?: number | null
  classified_count?: number | null
  go_count?: number | null
  wait_count?: number | null
  nogo_count?: number | null
  review_count?: number | null
  excluded_count?: number | null
  error_count?: number | null
  unclassified_count?: number | null
  accounted_count?: number | null
  unaccounted_count?: number | null
  reconciled_scanned?: number | null
  freshness_status?: string | null
  quality?: string | null
  count_integrity?: string | null
  count_integrity_reason?: string | null
}

export const RECONCILED = 'RECONCILED'
export const COUNT_MISMATCH = 'COUNT_MISMATCH'
export const PARTIAL = 'PARTIAL'
export const DATA_UNAVAILABLE = 'DATA_UNAVAILABLE'

/**
 * Compute the reconciliation verdict for a setup_run_summary.
 *
 * GO + WAIT + NOGO == classified_count is re-derived from the counts on every
 * call — never trusted from `count_integrity` — so a summary whose triple does
 * not partition its own classified count cannot render as a healthy taxonomy.
 */
export function setupIntegrity(s: SetupRunSummary | null | undefined): string {
  if (!s) return DATA_UNAVAILABLE
  const go = Number(s.go_count ?? 0)
  const wait = Number(s.wait_count ?? 0)
  const nogo = Number(s.nogo_count ?? 0)
  const classified = Number(s.classified_count ?? NaN)
  const sum = go + wait + nogo

  // Invariant 1: the three labels partition classified_count.
  if (!Number.isFinite(classified)) {
    // A missing classified_count can never be RECONCILED: the counts needed to
    // confirm the partition are absent. Surface a residual NEGATIVE verdict, or
    // PARTIAL — never trust a RECONCILED wire string the counts cannot confirm.
    return s.count_integrity && s.count_integrity !== RECONCILED
      ? s.count_integrity
      : PARTIAL
  }
  if (sum !== classified) return COUNT_MISMATCH

  // Invariant 2: the tally reconciles against the scanned population.
  if (s.scanned_count == null) return DATA_UNAVAILABLE
  const scanned = Number(s.scanned_count)
  const excluded = Number(s.excluded_count ?? 0)
  const review = Number(s.review_count ?? 0)
  const error = Number(s.error_count ?? 0)
  const unclassified = Number(s.unclassified_count ?? 0)
  // Every class, not just the three the header used to print. Omitting a class
  // here is how 12 rows went missing while the verdict still read PARTIAL.
  if (classified + excluded + review + error + unclassified !== scanned) return COUNT_MISMATCH

  // Residual server verdict (e.g. two scanned contracts disagreeing) is the
  // only case left where count_integrity says something the counts alone do not.
  if (s.count_integrity && s.count_integrity !== RECONCILED) return s.count_integrity
  return RECONCILED
}

export type SetupCountsRender = {
  /** "2 GO · 1 WAIT · 24 NOGO" — the three canonical labels only. */
  counts: string
  /** "25 classified / 352 scanned · 3 excluded · 12 manual review" — every class with a count. */
  population: string
  /** scanned − accounted. Non-zero means rows the summary cannot name; always rendered. */
  unaccounted: number
  /** Run health tier from freshness_status — orthogonal to `integrity`. */
  runHealth: RunHealthTier
  /** Raw producer status, e.g. RUN_UNDERFILLED. Null when the run never reported one. */
  runHealthStatus: string | null
  /** True when the RUN is unhealthy. Never merged into `degraded` (reconciliation). */
  healthDegraded: boolean
  integrity: string
  /** true when integrity !== RECONCILED (amber, not green). */
  degraded: boolean
  /** true when go_count > 0 (green when not degraded). */
  goPositive: boolean
  runId: string | null
  runTimestamp: string | null
}

/**
 * Render a setup_run_summary into operator-facing fragments. When reconciliation
 * fails the integrity verdict is exposed by the caller as an explicit badge, and
 * this function never emits an authoritative-looking count.
 */
export function renderSetupCounts(
  s: SetupRunSummary | null | undefined,
  opts: { stale?: boolean; staleLabel?: string | null } = {},
): SetupCountsRender {
  const integrity = setupIntegrity(s)
  const runId = s?.run_id ?? null
  const runTimestamp = s?.run_timestamp ?? null
  // Run health rides alongside reconciliation on every return path, including
  // the stale and pre-run branches — a stale surface can still report that the
  // last run it saw was underfilled.
  const runHealthStatus = s?.freshness_status ?? null
  const runHealth = classifyRunHealth(runHealthStatus)
  const healthDegraded = isRunHealthDegraded(runHealth)

  if (opts.stale) {
    return {
      counts: opts.staleLabel ?? 'STALE',
      population: '',
      unaccounted: 0,
      runHealth,
      runHealthStatus,
      healthDegraded,
      integrity,
      degraded: true,
      goPositive: false,
      runId,
      runTimestamp,
    }
  }

  if (!s || s.classified_count == null || s.scanned_count == null) {
    return {
      counts: '— before first run',
      population: '',
      unaccounted: 0,
      runHealth,
      runHealthStatus,
      healthDegraded,
      integrity,
      degraded: integrity !== RECONCILED,
      goPositive: false,
      runId,
      runTimestamp,
    }
  }

  const go = Number(s.go_count ?? 0)
  const wait = Number(s.wait_count ?? 0)
  const nogo = Number(s.nogo_count ?? 0)
  const excluded = Number(s.excluded_count ?? 0)
  const review = Number(s.review_count ?? 0)
  const error = Number(s.error_count ?? 0)
  const unclassified = Number(s.unclassified_count ?? 0)
  const scanned = Number(s.scanned_count)
  const classified = Number(s.classified_count)
  const counts = `${go} GO · ${wait} WAIT · ${nogo} NOGO`

  // Only classes with rows in them are printed -- a wall of zeroes hides the one
  // that matters. But a non-zero class is NEVER omitted.
  const residual: string[] = []
  if (excluded) residual.push(`${excluded} excluded`)
  if (review) residual.push(`${review} manual review`)
  if (error) residual.push(`${error} error`)
  if (unclassified) residual.push(`${unclassified} unclassified`)

  const accounted = Number.isFinite(s.accounted_count as number)
    ? Number(s.accounted_count)
    : classified + excluded + review + error + unclassified
  const unaccounted = Number.isFinite(scanned) ? scanned - accounted : 0

  const population =
    `${classified} classified / ${scanned} scanned` +
    (residual.length ? ` · ${residual.join(' · ')}` : '') +
    // The reader must never have to do this subtraction themselves.
    (unaccounted ? ` · ${unaccounted} UNACCOUNTED` : '')

  return {
    counts,
    population,
    unaccounted,
    runHealth,
    runHealthStatus,
    healthDegraded,
    integrity,
    // Reconciliation ONLY. Run health is healthDegraded, deliberately separate:
    // folding them here is how "RECONCILED" came to mean "fine".
    degraded: integrity !== RECONCILED || unaccounted !== 0,
    goPositive: go > 0,
    runId,
    runTimestamp,
  }
}
