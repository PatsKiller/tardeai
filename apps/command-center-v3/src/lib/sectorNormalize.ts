/**
 * Map holdings.sector (Yahoo/Finviz short labels) → overview/lookthrough GICS names
 * used by resolved_sectors / Allocation donut. Without this, "Financial Services"
 * never matches holdings tagged "Financial".
 */

const ALIAS: Record<string, string> = {
  financial: 'Financial Services',
  financials: 'Financial Services',
  'financial services': 'Financial Services',
  technology: 'Technology',
  'information technology': 'Technology',
  'info technology': 'Technology',
  'tech': 'Technology',
  industrials: 'Industrials',
  industrial: 'Industrials',
  healthcare: 'Healthcare',
  'health care': 'Healthcare',
  'consumer cyclical': 'Consumer Cyclical',
  'consumer discretionary': 'Consumer Cyclical',
  'consumer defensive': 'Consumer Defensive',
  'consumer staples': 'Consumer Defensive',
  'communication services': 'Communication Services',
  'communications': 'Communication Services',
  'communication': 'Communication Services',
  energy: 'Energy',
  'basic materials': 'Basic Materials',
  materials: 'Basic Materials',
  'real estate': 'Real Estate',
  utilities: 'Utilities',
  'fixed income': 'Fixed Income',
  bond: 'Fixed Income',
  bonds: 'Fixed Income',
  cash: 'Cash',
  'money market': 'Cash',
  unclassified: 'Other / Unclassified',
  other: 'Other / Unclassified',
  'other / unclassified': 'Other / Unclassified',
  unknown: 'Other / Unclassified',
}

/** Canonical sector label aligned with overview.resolved_sectors names. */
export function normalizeSectorLabel(raw: unknown): string {
  const s = String(raw ?? '').trim()
  if (!s) return 'Other / Unclassified'
  const hit = ALIAS[s.toLowerCase()]
  if (hit) return hit
  // Title-case unknown labels lightly so "financial services" still unifies if alias missed
  return s.replace(/\b\w/g, c => c.toUpperCase())
}

/** True when two sector labels refer to the same bucket. */
export function sectorsMatch(a: unknown, b: unknown): boolean {
  return normalizeSectorLabel(a) === normalizeSectorLabel(b)
}
