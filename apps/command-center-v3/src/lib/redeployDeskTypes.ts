/** Institutional Redeploy Desk v2 — shared types (Phase D). */

export type InstitutionalPlanSummary = {
  archetype?: string
  plan_type?: string
  confidence?: number
  operator_status?: string
  deploy_pct_of_net?: number
  reserve_usd?: number
  leg_count?: number
}

export type ExportReadiness = {
  quotes_fresh?: boolean
  stale_symbols?: string[]
  fresh_symbols?: string[]
  export_allowed?: boolean
  export_quote_max_age_minutes?: number
}

export type RedeployPlanLeg = {
  ticker: string
  account?: string
  target_dollars?: number
  target_shares?: number
  is_reserve?: boolean
  is_actionable?: boolean
  current_price?: number
  price_as_of?: string
  price_stale?: boolean
  preferred_entry?: number
  entry_range_low?: number
  entry_range_high?: number
  do_not_chase?: number
  stage_1_pct?: number
  stage_1_price?: number
  stage_1_shares?: number
  stage_1_dollars?: number
  stage_2_pct?: number
  stage_2_price?: number
  stage_2_shares?: number
  stage_2_dollars?: number
  stage_3_pct?: number
  stage_3_price?: number
  stage_3_shares?: number
  stage_3_dollars?: number
  thesis?: string
  invalidation?: string
  monitoring_rules?: string
  expected_yield_pct?: number
  overlap_note?: string
  dual_label?: string
}

export type InstitutionalPlan = {
  plan_archetype: string
  plan_type?: string
  plan_description?: string
  tags?: string[]
  objective?: string
  total_deployable_usd?: number
  reserve_usd?: number
  deploy_pct_of_net?: number
  confidence?: number
  operator_status?: string
  oversight_status?: string
  composite_rank?: number
  advantages?: string[]
  compromises?: string[]
  risks?: string[]
  hermes_narrative?: string
  legs?: RedeployPlanLeg[]
  unmet_exposure?: Record<string, unknown>
}

export type RejectedAlternative = {
  symbol?: string
  score?: number
  reason_code?: string
  reason?: string
}

export type RedeployTarget = {
  symbol: string
  score: number
  sleeve?: string
  rationale?: string
  review_amount_range?: { low?: number; high?: number; basis?: string }
  evidence?: Record<string, unknown>
  hermes?: {
    composite?: number | null
    rank?: number | null
    research_count?: number
    external_lane_count?: number
    research_snippets?: { title?: string; summary?: string }[]
  }
}

export type RedeployEventDetail = {
  id: number
  symbol: string
  account: string
  sold_at: string
  proceeds_usd?: number
  deployable_cash_usd?: number
  reconciliation_status?: string
  proxy_symbol?: string
  proxy_sleeve?: string
  tier?: string
  redeploy_plan?: RedeployTarget[]
  lookthrough_delta?: { theme?: string; delta_pct?: number; note?: string }[]
  institutional_plans_summary?: InstitutionalPlanSummary[]
  primary_plan_archetype?: string
  pm_memo?: string
  export_readiness?: ExportReadiness
  metadata?: {
    sale_context?: { tier?: string; reduced_themes?: string[]; proceeds_usd?: number; proxy_symbol?: string }
    advisory_note?: string
    sleeve_gaps?: { theme?: string; gap_pct?: number; gap_usd?: number }[]
    market_context?: {
      geopolitical?: { posture?: string; catalyst_count?: number; active_themes?: string[] }
      regime_posture?: string
      regime?: { label?: string }
    }
    methodology?: string
    phase_a?: {
      reconciliation?: {
        net_proceeds_usd?: number
        deployable_cash_usd?: number
        planned_not_actionable_usd?: number
        reconciliation_status?: string
      }
      exposure_loss?: {
        sectors?: { sector?: string; usd_removed?: number; weight_pct?: number }[]
        income_status?: string
        income_usd_removed?: number
      }
      portfolio_context?: {
        is_major_sale?: boolean
        default_deployment_account?: string
      }
    }
    phase_b?: {
      plans?: InstitutionalPlan[]
      rejected_alternatives?: RejectedAlternative[]
      primary_archetype?: string
      pm_memo?: string
    }
    phase_c?: {
      export_readiness?: ExportReadiness
      regime_posture?: string
    }
  }
}

export const ARCHETYPE_LABELS: Record<string, string> = {
  A: 'Strategic',
  B: 'Diversified',
  C: 'Income',
  D: 'Defensive',
  E: 'Tactical',
  F: 'Staged',
  G: 'Hold',
}

export function plansFromEvent(ev: RedeployEventDetail): InstitutionalPlan[] {
  const meta = ev.metadata?.phase_b
  return meta?.plans ?? []
}

export function rejectedFromEvent(ev: RedeployEventDetail): RejectedAlternative[] {
  return ev.metadata?.phase_b?.rejected_alternatives ?? []
}