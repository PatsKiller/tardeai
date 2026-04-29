export interface Holding {
  symbol: string
  name: string
  account: string
  shares: number
  price: number
  market_value: number
  portfolio_pct: number
  day_change: number
  day_change_pct: number
  sector_type: string
  is_cash: boolean
  is_fund: boolean
}

export interface Holdings {
  as_of: string
  holdings: Holding[]
  portfolio_totals: { total_value: number; total_cash: number }
  account_summaries: Record<string, { total_value: number }>
}

export interface PerfPeriod {
  period: string
  change: number
  change_pct: number
  start_value: number
  end_value: number
  start_date: string
}

export interface PerfHistory {
  current_value: number
  periods: Record<string, PerfPeriod>
  accounts: Record<string, { current_value: number; periods: Record<string, PerfPeriod> }>
}

export interface Enrichment {
  company: string
  sector: string
  industry: string
  market_cap_b: number
  pe: number
  forward_pe: number
  eps_ttm: number
  beta: number
  rsi: number
  rsi_status: string
  sma20_pct: number
  sma50_pct: number
  sma200_pct: number
  perf_week_pct: number
  perf_month_pct: number
  perf_ytd_pct: number
  short_float_pct: number
  recom: number
  atr: number
  rvol: number
  week52_high_pct: number
  week52_low_pct: number
  [key: string]: unknown
}

export interface Catalyst {
  portfolio_symbol: string
  title: string
  source: string
  provider: string
  published_at: string
  llm_score: number
  llm_category: string
  llm_urgency: string
  llm_summary: string
  _source_family: string
  url: string
  impact_tier: string
}

export interface NewsData {
  date: string
  catalysts: Catalyst[]
  all_scored: Catalyst[]
  ticker_count: number
  total_articles: number
}

export interface Notification {
  notification_date: string
  notification_type: string
  channel: string
  status: string
  subject: string
  body_summary: string
  sent_at: string
}
