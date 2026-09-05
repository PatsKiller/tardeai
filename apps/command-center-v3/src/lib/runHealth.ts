/**
 * runHealth.ts — one classifier for scanner run health, shared by every surface.
 *
 * These four helpers lived unexported inside TradingHub.tsx, so the underfill
 * banner had them and the header did not. The header therefore rendered
 * "12 classified / 21 scanned" in healthy green while the panel directly below
 * it said RUN UNDERFILLED (21 scanned against a floor of 40) — one run, two
 * verdicts, because only one surface could see the status.
 *
 * Run health and count reconciliation are ORTHOGONAL and must never be merged
 * into a single "degraded" boolean:
 *
 *   count_integrity   did the tally account for every scanned row?
 *   freshness_status  did the run scan enough rows to be worth trusting?
 *
 * The live 2026-09-04::1730 run was RECONCILED (21 = 12 classified + 9 manual
 * review, nothing unaccounted) and RUN_UNDERFILLED at the same time. Both are
 * true. Collapsing them loses the one that matters.
 *
 * Pure functions. No network, no React, no side effects.
 */

export type RunHealthTier = 'healthy' | 'underfilled' | 'partial' | 'failed' | 'unknown'

/** The status strings the producer emits — scripts/screener_run_health.py::classify_run_health. */
export function classifyRunHealth(status?: string | null): RunHealthTier {
  const s = String(status || '').toUpperCase()
  if (!s) return 'unknown'
  if (s === 'RUN_HEALTHY' || s === 'HEALTHY') return 'healthy'
  if (s === 'RUN_UNDERFILLED' || s.includes('UNDERFILL')) return 'underfilled'
  if (s === 'RUN_PARTIAL' || s.includes('PARTIAL')) return 'partial'
  if (s === 'RUN_FAILED' || s.includes('FAILED') || s.includes('CSV_EMPTY')) return 'failed'
  return 'unknown'
}

/** A tier that is not 'healthy' and not 'unknown' is a stated problem. */
export function isRunHealthDegraded(tier: RunHealthTier): boolean {
  return tier === 'underfilled' || tier === 'partial' || tier === 'failed'
}

export function runHealthReasonCodes(tradeAi: any): string[] {
  const raw = tradeAi?.run_health_reason_codes ?? tradeAi?.reason_codes ?? []
  if (!Array.isArray(raw)) return []
  return raw.map((x: any) => String(x ?? '').trim()).filter(Boolean)
}

/**
 * Plain-language gloss for a reason code.
 *
 * Returning the code unchanged is the honest fallback for a code we have no
 * gloss for — but a caller that renders `${code} — ${gloss}` then prints it
 * twice. The live panel read "UNIVERSE_TOO_SMALL — UNIVERSE_TOO_SMALL" for
 * exactly that reason, because the most common code had no case here.
 * `hasReasonGloss` lets a caller omit the dash rather than repeat itself.
 */
export function reasonCodeOneLiner(code: string): string {
  const c = String(code || '').toUpperCase()
  if (c === 'UNIVERSE_TOO_SMALL') {
    return 'Screener universe returned fewer symbols than the health floor — filters too tight, or a source returned nothing'
  }
  if (c === 'ROW_LIMIT_10_DETECTED') {
    return 'Finviz export returned ≤10 raw rows for active screeners (thin premarket filters or row cap)'
  }
  if (c === 'CSV_EMPTY') return 'No CSV rows ingested'
  if (c === 'FINVIZ_AUTH_FAILED' || c === 'FINVIZ_AUTH_MISSING') return 'Finviz auth problem'
  if (c === 'ONLY_ONE_SCREENER_RETURNED') return 'Only one screener returned rows'
  return code
}

/** True when reasonCodeOneLiner adds meaning rather than echoing the code. */
export function hasReasonGloss(code: string): boolean {
  return reasonCodeOneLiner(code) !== code
}

/**
 * Colour for a tier. Returns a CSS custom property or a token value — never a
 * raw hex, because MetricStrip.tsx has a design-token budget of exactly zero.
 */
export function runHealthChipColor(tier: RunHealthTier): string {
  if (tier === 'healthy') return 'var(--green)'
  if (tier === 'underfilled' || tier === 'partial') return 'var(--amber)'
  if (tier === 'failed') return 'var(--red)'
  return 'var(--text3)'
}

/** Short uppercase label for a chip face, e.g. RUN_UNDERFILLED -> UNDERFILLED. */
export function runHealthLabel(status?: string | null): string {
  const s = String(status || '').toUpperCase()
  if (!s) return 'UNKNOWN'
  return s.startsWith('RUN_') ? s.slice(4) : s
}
