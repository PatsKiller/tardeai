/** Map legacy /v2/* and ticker tokens to v3 routes — shared by brief panels + reader. */

const FQDN = typeof window !== 'undefined' ? window.location.origin : ''

const PAGE: Record<string, { label: string; route: string }> = {
  risk: { label: 'Risk', route: '/v3/risk' },
  approvals: { label: 'Approvals', route: '/v3/trading' },
  recovery: { label: 'Recovery', route: '/v3/risk' },
  reco: { label: 'Recovery', route: '/v3/risk' },
  actions: { label: 'Actions', route: '/v3/' },
  trading: { label: 'Trading', route: '/v3/trading' },
  journal: { label: 'Journal', route: '/v3/journal' },
  system: { label: 'System', route: '/v3/system' },
  portfolio: { label: 'Portfolio', route: '/v3/portfolio' },
  research: { label: 'Research', route: '/v3/research-intelligence' },
  'research-topics': { label: 'Research', route: '/v3/research-intelligence' },
  proposals: { label: 'Proposals', route: '/v3/trading' },
  retirement: { label: 'Retirement', route: '/v3/retirement' },
}

const NOT_TICKER = new Set(['STOP', 'STOPS', 'RISK', 'HEAT', 'ETF', 'IRA', 'EOD', 'RSI', 'OPEN', 'THE', 'AND', 'FOR', 'NOW', 'TODAY'])

export function pageLink(path: string) {
  const seg = (path.split('/')[2] || '').toLowerCase()
  if (PAGE[seg]) return PAGE[seg]
  return { label: 'Open', route: '/v3/' }
}

export function relUrl(u?: string) {
  return u ? u.replace(/^https?:\/\/[^/]+/, '') : u
}

export function v3Href(route: string, symbol?: string) {
  const r = route.replace(/^\/v2/, '/v3')
  const base = r.startsWith('/') ? r : `/v3/${r}`
  if (symbol && /\/v3\/(risk|trading|portfolio)/.test(base)) {
    const sep = base.includes('?') ? '&' : '?'
    return FQDN + base + sep + `symbol=${symbol}`
  }
  return FQDN + base
}

/** Strip markdown bold and clean a brief line for display */
export function cleanLine(text: string): string {
  return text
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/\s*→\s*\/v[23]\/[a-z0-9-]+/gi, '')
    .replace(/\s+/g, ' ')
    .trim()
}

export function isStatLine(text: string): boolean {
  const t = cleanLine(text).toLowerCase()
  return /^(deferred|failed|in review|needs john|resolved|pending):\s*\d/i.test(t)
    || /^iris:/i.test(t)
    || /^\d+\s+events?\s+fired/i.test(t)
}

export function lineSymbol(text: string): string | undefined {
  const m = text.match(/^[•\-▪◦·*\s]*\d*\.?\s*([A-Z]{2,5}):/)
  return m?.[1]
}

export function isRiskLine(text: string): boolean {
  return /\bstop|\btrigger|unprotected|protective/i.test(text)
}

export { FQDN, NOT_TICKER }