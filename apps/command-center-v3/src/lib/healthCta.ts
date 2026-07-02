/** Map health finding → operator CTA route (mirrors health_agent._attach_cta). */
export function healthFindingCta(f: { type?: string; category?: string }): { label: string; route: string } {
  const t = f.type ?? ''
  const byType: Record<string, { label: string; route: string }> = {
    portfolio_repricer_stale: { label: 'System → Pipeline', route: '/system?tab=pipeline' },
    finviz_quote_cache_stale: { label: 'System → Admin', route: '/system?tab=admin' },
    agent_jobs_processing_stuck: { label: 'System → Jobs', route: '/system?tab=jobs' },
    trade_proposals_backlog: { label: 'Trading → Proposals', route: '/trading?tab=Proposals' },
    watchlist_stale: { label: 'Watch → Watchlist', route: '/watch?tab=watchlist' },
    rotation_empty: { label: 'Rotation desk', route: '/rotation' },
  }
  if (byType[t]) return byType[t]
  const cat = f.category ?? ''
  if (cat === 'execution_health') return { label: 'Trading → Proposals', route: '/trading?tab=Proposals' }
  if (cat === 'risk_protection') return { label: 'Risk → Exposure', route: '/risk' }
  if (cat === 'pipeline_freshness') return { label: 'System → Pipeline', route: '/system?tab=pipeline' }
  if (cat === 'intelligence_quality') return { label: 'Hermes', route: '/hermes' }
  if (cat === 'retirement_planning') return { label: 'Retirement', route: '/retirement' }
  return { label: 'Health Agent', route: '/health' }
}