// Shared humanizer for raw finding_type / severity codes surfaced across the Intel
// section (Hermes pipeline-quality, validation findings, research backlog). A raw
// code like `unsupported_thesis` must never be the primary label an operator reads —
// this is the single source of truth so every Intel hub renders the same plain-English
// title/meaning/resolve for a given code, instead of each hub inventing its own mapping.

export type FindingSeverity = 'critical' | 'warning' | 'info'

export interface HumanizedFinding {
  title: string
  meaning: string
  resolve: string
  severity: FindingSeverity
  where?: string
}

function normSeverity(raw?: string): FindingSeverity {
  const s = String(raw ?? '').toLowerCase()
  if (s === 'critical' || s === 'urgent' || s === 'error') return 'critical'
  if (s === 'warning' || s === 'warn') return 'warning'
  return 'info'
}

// finding_type -> { title, resolve, where } from hermes_validation_findings producers:
// research_critique_pipeline.py, hermes_profit_protection_check.py,
// hermes_open_position_protection_check.py.
const FINDING_TYPE_MAP: Record<string, { title: string; resolve: string; where?: string }> = {
  unsupported_thesis: {
    title: 'Thesis lacks supporting evidence',
    resolve: 'Composite scoring flagged weak librarian/taxonomy support — review before acting on this directive.',
    where: 'Hermes → Research',
  },
  weak_evidence: {
    title: 'Weak research evidence',
    resolve: 'Composite score rejected this directive — treat as unproven until stronger evidence lands.',
    where: 'Hermes → Research',
  },
  scoring_inconsistency: {
    title: 'Taxonomy scoring inconsistency',
    resolve: 'Taxonomy classifier disagreed with the librarian score — check keyword/seed mapping.',
    where: 'Hermes → Research',
  },
  stale_data: {
    title: 'Stale data blocking review',
    resolve: 'Underlying data is out of date — refresh the source before trusting this finding.',
  },
  large_gain_loose_stop: {
    title: 'Large gain, stop does not lock profit',
    resolve: 'Second-opinion: raise the stop to lock in the unrealized gain.',
    where: 'Trading → Open Trades',
  },
  stop_only_breakeven_on_large_gain: {
    title: 'Large gain, stop only at breakeven',
    resolve: 'Consider trailing the stop further to protect more of the gain.',
    where: 'Trading → Open Trades',
  },
  profit_giveback_too_high: {
    title: 'Giving back too much unrealized gain',
    resolve: 'Position has retraced a large share of its peak gain — review protective stop placement.',
    where: 'Trading → Open Trades',
  },
  large_gain_no_take_profit: {
    title: 'Large gain with no take-profit set',
    resolve: 'Consider staging a take-profit or partial exit to lock in gains.',
    where: 'Trading → Open Trades',
  },
  trailing_policy_not_triggered_but_review_needed: {
    title: 'Trailing policy due for review',
    resolve: 'Trailing stop policy has not triggered yet — confirm it still matches current gain/volatility.',
    where: 'Trading → Open Trades',
  },
  strategy_metadata_missing_cannot_advise: {
    title: 'Missing strategy metadata',
    resolve: 'Classify this position to a strategy family so future advisories are more precise.',
    where: 'Trading → Open Trades',
  },
  stale_quote_blocking_protection_review: {
    title: 'Quote stale — protection review blocked',
    resolve: 'Wait for a fresh quote before trusting this profit-protection second opinion.',
  },
  open_position_no_broker_stop: {
    title: 'Open position has no broker stop',
    resolve: 'Assign a protective stop for this position via operator review.',
    where: 'Trading → Open Trades',
  },
  broker_stop_exists_db_untracked: {
    title: 'Broker stop untracked in database',
    resolve: 'Run the broker-stop verification job to persist the stop order id.',
    where: 'Trading → Open Trades',
  },
  stop_note_unverified: {
    title: 'Stop submission unverified',
    resolve: 'Confirm the stop order actually landed at the broker.',
    where: 'Trading → Open Trades',
  },
  protection_metadata_mismatch: {
    title: 'Protection metadata mismatch',
    resolve: 'Database stop/take-profit fields disagree with broker state — reconcile.',
    where: 'Trading → Open Trades',
  },
}

/** Humanize a Hermes pipeline-quality / validation-finding row (finding_type + description shape). */
export function humanizeFinding(item: {
  finding_type?: string
  description?: string
  recommended_action?: string
  severity?: string
  symbol?: string
}): HumanizedFinding {
  const code = String(item.finding_type ?? '').trim()
  const mapped = FINDING_TYPE_MAP[code]
  const severity = normSeverity(item.severity)
  const desc = String(item.description ?? '').trim()
  if (mapped) {
    return {
      title: item.symbol ? `${mapped.title} — ${item.symbol}` : mapped.title,
      meaning: desc || mapped.resolve,
      resolve: item.recommended_action || mapped.resolve,
      severity,
      where: mapped.where,
    }
  }
  // Unknown code — still never show the raw snake_case as the title.
  const fallbackTitle = code ? code.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase()) : 'Advisory finding'
  return {
    title: item.symbol ? `${fallbackTitle} — ${item.symbol}` : fallbackTitle,
    meaning: desc || 'Advisory finding — no further detail provided.',
    resolve: item.recommended_action || 'Review and decide.',
    severity,
  }
}

export const FINDING_SEVERITY_COLOR: Record<FindingSeverity, string> = {
  critical: '#ef4444',
  warning: '#f59e0b',
  info: '#60a5fa',
}
