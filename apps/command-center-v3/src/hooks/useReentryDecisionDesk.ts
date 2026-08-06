/**
 * useReentryDecisionDesk — fetches the canonical Data Broker decision desk.
 * All price/RSI/indicator values sourced from market_quotes + indicator_confluence_cache.
 * The existing client-side scorecard (buildReEntryScorecard) remains as a fallback.
 */
import { useApi } from './useApi'

export type DecisionDeskGate = {
  id: string
  pass: boolean
  label: string
  value: string
}

export type DecisionDeskChip = {
  tone: string
  label: string
  detail?: string
}

export type DecisionDeskResistance = {
  state: string
  level: number | null
  distance_pct: number | null
  hold_days: number | null
  as_of: string | null
  source: string
}

export type DecisionDeskAdvisory = {
  date: string
  action: string
  ticker: string
  company: string | null
  reentry_range_low: number | null
  reentry_range_high: number | null
  stop_loss: number | null
  target: number | null
  rr: number | null
  live_price: number | null
  criteria: { id: string; label: string; met: boolean | null; detail: string }[]
  rationale: string[]
  confirmations_complete: boolean
  confirmation_gaps: string[]
  advisory_only: boolean
  sizing?: { shares: number | null; note: string }
  lookthrough?: Record<string, number> | null
  is_fund?: boolean
}

export type DecisionDeskIntel = {
  state: string
  action: string
  reason: string
  distance_pct: number | null
  criteria: Record<string, unknown>
  chips: DecisionDeskChip[]
  deterministic: boolean
  llm_in_path: boolean
}

export type DecisionDeskCatalyst = {
  headline: string | null
  date: string | null
  verified: boolean
  source: string | null
}

export type DecisionDeskRow = {
  symbol: string
  price: number | null
  price_as_of: string | null
  price_source: string | null
  price_age_h: number | null
  rsi: number | null
  rsi_status: string | null
  entry_low: number | null
  entry_high: number | null
  stop: number | null
  target: number | null
  rr: number | null
  plan_as_of: string | null
  resistance: DecisionDeskResistance | null
  catalyst: DecisionDeskCatalyst | null
  wash_blocked: boolean
  wash_until: string | null
  held: boolean
  heat_pct: number | null
  earnings_date: string | null
  company: string | null
  indicator_source: string | null
  sma20_pct: number | null
  sma50_pct: number | null
  sma200_pct: number | null
  gates: DecisionDeskGate[]
  why: string[]
  advisory: DecisionDeskAdvisory
  intel: DecisionDeskIntel
  research_summary: unknown
}

export type DecisionDeskBlocked = {
  symbol: string
  reason: string
}

export type DecisionDeskScorecardGate = {
  stage: string
  label: string
  fired: boolean
  data_available: boolean
}

export type DecisionDeskScorecardSummary = {
  decision_state: string
  confluence_count: number
  has_structure_gate: boolean
  hard_disqualifier: string | null
  thesis: string | null
  gates: DecisionDeskScorecardGate[]
}

export type DecisionDeskResponse = {
  ok: boolean
  version: string
  computed_at: string
  deterministic: boolean
  llm_in_path: boolean
  data_broker: {
    enforced: boolean
    modules: Record<string, string>
    quote_source_counts: Record<string, number>
    quote_batch_hits: number
    indicator_hits: number
    plan_hits: number
    note: string
  }
  criteria: {
    rsi_ready: string
    near_pct: number
    stale_hours: number
    wash_days: number
  }
  freshness: {
    resistance_generated_at: string | null
    price_age_h_median: number | null
    price_age_h_max_actionable: number | null
    price_age_h_max: number | null
    stale_symbol_count: number
    heat_pct: number | null
    symbol_count: number
    actionable_count: number
  }
  blocked: DecisionDeskBlocked[]
  insights: {
    generated_at: string | null
    total_calls: number
    success_count: number
    total_estimated_cost_usd: number
    model: string
    policy: string
    advisory_only: boolean
    insight_count: number
  } | null
  scorecard_summary: {
    computed_at: string
    symbols_scored: number
    ready_count: number
    near_count: number
    wait_count: number
    skip_count: number
    disqualified_count: number
    by_symbol: Record<string, DecisionDeskScorecardSummary>
  } | null
  rows: DecisionDeskRow[]
}

export function useReentryDecisionDesk(): {
  data: DecisionDeskResponse | null
  loading: boolean
  error: string | null
} {
  return useApi<DecisionDeskResponse>(
    '/api/v2/reentry/decision-desk',
    120_000,
    { enabled: true },
  )
}
