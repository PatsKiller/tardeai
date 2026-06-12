export type ManualTosRating = 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL' | 'UNKNOWN'

export function ratingLabel(v: ManualTosRating | 'ALL') {
  if (v === 'ALL') return 'All'
  return v.replace(/_/g, ' ').replace(/\b\w/g, m => m.toUpperCase())
}

export function normalizeAnalystRating(v: any): ManualTosRating {
  const s = String(v ?? '').trim().toLowerCase().replace(/[_-]/g, ' ')
  if (!s) return 'UNKNOWN'
  if (s.includes('strong buy') || s.includes('conviction buy') || s.includes('very bullish')) return 'STRONG_BUY'
  if (s === 'buy' || s.includes(' buy') || s.includes('outperform') || s.includes('overweight') || s.includes('bullish')) return 'BUY'
  if (s.includes('hold') || s.includes('neutral') || s.includes('market perform') || s.includes('equal weight')) return 'HOLD'
  if (s.includes('strong sell') || s.includes('very bearish')) return 'STRONG_SELL'
  if (s.includes('sell') || s.includes('underperform') || s.includes('underweight') || s.includes('bearish')) return 'SELL'
  return 'UNKNOWN'
}

export function deriveTradeAiRating(row: any): { rating: ManualTosRating; source: 'analyst' | 'trade_ai_derived' } {
  const raw = row?.analyst ?? row?.analyst_rating ?? row?.analyst_recommendation ?? row?.analyst_consensus ?? row?.consensus_rating ?? row?.recommendation ?? row?.recommendationKey ?? row?.rating ?? row?.finviz_analyst ?? row?.finviz_recommendation ?? row?.street_rating ?? row?.wall_street_rating ?? row?.tipranks_rating ?? row?.zacks_rank
  const analyst = normalizeAnalystRating(raw)
  if (analyst !== 'UNKNOWN') return { rating: analyst, source: 'analyst' }

  const decision = String(row?.decision ?? '').toUpperCase().replace('_', '-')
  const score = Number(row?.score ?? row?.final_score ?? row?.rating_score ?? 0)
  if (decision === 'GO' && score >= 42) return { rating: 'STRONG_BUY', source: 'trade_ai_derived' }
  if (decision === 'GO') return { rating: 'BUY', source: 'trade_ai_derived' }
  if (decision === 'WAIT' && score >= 38) return { rating: 'BUY', source: 'trade_ai_derived' }
  if (decision === 'WAIT') return { rating: 'HOLD', source: 'trade_ai_derived' }
  if (decision.includes('NO') && score < 10) return { rating: 'STRONG_SELL', source: 'trade_ai_derived' }
  if (decision.includes('NO')) return { rating: 'SELL', source: 'trade_ai_derived' }
  if (score >= 40) return { rating: 'BUY', source: 'trade_ai_derived' }
  if (score >= 30) return { rating: 'HOLD', source: 'trade_ai_derived' }
  if (score > 0) return { rating: 'SELL', source: 'trade_ai_derived' }
  return { rating: 'UNKNOWN', source: 'trade_ai_derived' }
}

export function ratingRank(v: ManualTosRating) {
  return v === 'STRONG_BUY' ? 5 : v === 'BUY' ? 4 : v === 'HOLD' ? 3 : v === 'SELL' ? 2 : v === 'STRONG_SELL' ? 1 : 0
}
