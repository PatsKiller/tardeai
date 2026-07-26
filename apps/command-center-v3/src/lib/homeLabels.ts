// Home v2 WS-D: the plain-English dictionary — the brain speaks operator.
// ADDITIVE rendering: raw states stay in tooltips/data attributes; a state with no
// confident translation renders through rawChip() (the Reports v3 producer pattern)
// and belongs in the findings log as visible debt.

export const STATE_LABELS: Record<string, string> = {
  // recovery / relist
  market_relist_monitor: 'monitoring for re-entry',
  reentry_candidate: 're-entry candidate',
  hold_for_reentry: 'holding for re-entry',
  // review states
  HUMAN_REVIEW: 'needs your review',
  ROTATION_REVIEW: 'rotation review',
  ADD_REVIEW: 'add-more review',
  MANUAL_REVIEW: 'manual review',
  read_only: 'analysis only — no action armed',
  'synthesis→human_review': 'awaiting your review',
  // origins / strategies
  unknown_sync: 'adopted from broker sync',
  pullback_macd_reversal: 'pullback reversal setup',
  dividend_growth_compounder: 'dividend growth',
  high_yield_income_bdc: 'high-yield income',
  core_index: 'core index',
  defense_thesis: 'defense thesis',
  // regimes
  risk_off: 'defensive regime',
  risk_on: 'risk-on',
  'risk on trend': 'risk-on trend',
  // run health
  RUN_UNDERFILLED: 'scan ran thin (few symbols)',
  kill_switch_db_unavailable: 'trading halted — database was unreachable',
  // proposal statuses
  RISK_BLOCKED: 'blocked by risk gate',
  APPROVED_FOR_PAPER_TEST: 'approved for validation',
  EXPIRED: 'expired unreviewed',
  PENDING: 'awaiting review',
  REJECTED: 'rejected',
}

/** Translate a raw state; returns null when no confident translation exists (render rawChip). */
export function plain(raw?: string | null): string | null {
  if (!raw) return null
  return STATE_LABELS[raw] ?? STATE_LABELS[String(raw).toUpperCase()] ?? null
}

/** Counts are integers: 4.0 → "4". */
export function count(n: any): string {
  const v = Number(n)
  return Number.isFinite(v) ? String(Math.round(v)) : '—'
}

/** "1000 2026-07-17" → "10:00 AM scan · Jul 17" */
export function runLabel(label?: string | null, date?: string | null): string {
  if (!label) return 'no run yet'
  const m = String(label).match(/^(\d{2})(\d{2})$/)
  let t = String(label)
  if (m) {
    const h = parseInt(m[1], 10)
    t = `${h === 0 ? 12 : h > 12 ? h - 12 : h}:${m[2]} ${h >= 12 ? 'PM' : 'AM'} scan`
  }
  if (date) {
    const d = new Date(`${date}T00:00:00`)
    if (!isNaN(d.getTime())) return `${t} · ${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`
  }
  return t
}

/** Threshold sentences: "Heat 8.9% — above your 5% ceiling" */
export function thresholdSentence(label: string, value: number, threshold: number, unit = '%'): string {
  const dir = value > threshold ? 'above' : 'within'
  return `${label} ${value}${unit} — ${dir} your ${threshold}${unit} ceiling`
}

/** Dev-speak alerts → operator alerts. Returns null when no rule matches (render raw + log). */
const ALERT_RULES: Array<[RegExp, (m: RegExpMatchArray) => string]> = [
  [/holdings\.json missing last_repriced/i, () => 'Price data incomplete — some holdings not repriced yet'],
  [/Schwab journal ingest log ([\d.]+)h old/i, m => `Trade journal sync is ${Math.round(parseFloat(m[1]))}h behind — closed trades may lag during market hours`],
  [/(\d+) decision-feeding agent jobs queued >2h/i, m => `${m[1]} agent analyses backed up over 2h`],
  [/(\d+) pipeline run failures in 24h/i, m => `${m[1]} pipeline run${m[1] === '1' ? '' : 's'} failed in the last 24h`],
  [/(\d+) orphaned stop orders/i, m => `${m[1]} stop order${m[1] === '1' ? '' : 's'} without a matching position`],
  [/kill_switch_db_unavailable/i, () => 'Trading halted — database was unreachable (auto-clears when healthy)'],
  [/cannot inspect live unlock state/i, () => 'Live-trading state unreadable — failing closed (no orders possible)'],
  [/(\d+) live-adjacent dirty files/i, m => `${m[1]} uncommitted change${m[1] === '1' ? '' : 's'} in live-trading code`],
  [/Release manifest status FAIL/i, () => 'Release manifest FAIL — live-adjacent dirty or validator failed'],
  [/uncommitted change in live-trading code/i, () => 'Uncommitted change in live-trading code — commit or revert before live path'],
  [/executed trade\(s\) in 7d not linked to a proposal/i, () => 'Executed trade in last 7d not linked to a proposal — every ATM trade must appear in Proposals first'],
  [/(\d+) executed trade/i, m => `${m[1]} executed trade(s) need proposal linkage`],
]

export function plainAlert(raw?: string | null): string | null {
  if (!raw) return null
  for (const [rx, fn] of ALERT_RULES) {
    const m = String(raw).match(rx)
    if (m) return fn(m)
  }
  return null
}
