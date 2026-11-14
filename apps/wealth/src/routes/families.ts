// Page-family registry for the Wealth site. Families come from WEALTH_MANAGEMENT_501 §3 and the
// operator's 2026-11-14 themes. The exact 56 views are defined by the accepted reference
// (sha256 9bafaac1…), which is NOT in this tree yet: viewCount stays null until it arrives and
// each family's views are listed from it, not invented here.
//
// `readers` are EXISTING canonical endpoints (same origin, existing auth). The Wealth app adds no
// data source, database, calculation or producer. A family whose need has no reader lists it
// under `gaps`; a gap is owned backend work, never a permanent placeholder or mock data.

export type BuildState = 'NOT_BUILT' | 'IN_PROGRESS' | 'READY_FOR_REVIEW' | 'RELEASED_ALT' | 'ACCEPTED'

export interface Family {
  id: string
  path: string
  title: string
  decision: string          // the user decision the page exists for (WM501 §3)
  readers: string[]
  gaps: string[]
  slice: 1 | 2              // 1 = first real-data vertical slice
  viewCount: number | null  // from the reference mockup, once present
  state: BuildState
}

export const FAMILIES: Family[] = [
  { id: 'home', path: '/', title: 'Home', slice: 1, viewCount: null, state: 'NOT_BUILT',
    decision: 'What needs my attention now?',
    readers: ['/api/v2/overview', '/api/v2/home/since-close', '/api/v2/home/cio-card', '/api/v2/home/do-now',
      '/api/v2/home/priorities-live', '/api/v2/market-risk/latest', '/api/v2/morning-brief', '/api/v2/market-movers'],
    gaps: ['directional outlook + conditional scenarios: no dedicated reader (methodology decision LQ-946 pending)'] },
  { id: 'portfolio', path: '/portfolio', title: 'Portfolio', slice: 1, viewCount: null, state: 'NOT_BUILT',
    decision: 'What do I own and what has it earned?',
    readers: ['/api/v2/portfolio/holdings', '/api/v2/portfolio/book-map', '/api/v2/tax-lots', '/api/v2/symbol-cards',
      '/api/v2/portfolio/performance'],
    gaps: ['valuation-assessment@1: no centralized backend contract; every row UNASSESSED until one is wired'] },
  { id: 'performance', path: '/performance', title: 'Performance & Income', slice: 2, viewCount: null, state: 'NOT_BUILT',
    decision: 'How did investments perform over the chosen interval?',
    readers: ['/api/v2/portfolio/performance', '/api/v2/income-dashboard', '/api/v2/dividends'],
    gaps: ['verified economic P&L stays UNVERIFIED (no stored reconciliation)'] },
  { id: 'retirement', path: '/retirement', title: 'Retirement', slice: 2, viewCount: null, state: 'NOT_BUILT',
    decision: 'Is the long-term allocation aligned?', readers: ['/api/v2/retirement'], gaps: [] },
  { id: 'risk', path: '/risk', title: 'Risk', slice: 2, viewCount: null, state: 'NOT_BUILT',
    decision: 'What exposure could harm the book?',
    readers: ['/api/v2/risk', '/api/v2/risk/protection-truth', '/api/v2/market-risk/latest'], gaps: [] },
  { id: 'defense', path: '/defense', title: 'Defense & Cash Alternative', slice: 2, viewCount: null, state: 'NOT_BUILT',
    decision: 'What protection alternatives are supported?', readers: ['/api/v2/defense/posture'], gaps: [] },
  { id: 'reentry', path: '/reentry', title: 'Re-entry', slice: 2, viewCount: null, state: 'NOT_BUILT',
    decision: 'When is a previously exited position worth reconsidering?',
    readers: ['/api/v2/recovery', '/api/v2/reentry/decision-desk'], gaps: [] },
  { id: 'rotation', path: '/rotation', title: 'Rotation & Redeploy', slice: 2, viewCount: null, state: 'NOT_BUILT',
    decision: 'Where should reviewed capital move?', readers: ['/api/v2/rotation/summary'], gaps: [] },
  { id: 'watch', path: '/watch', title: 'Watch (all tabs)', slice: 2, viewCount: null, state: 'NOT_BUILT',
    decision: 'What monitored ideas changed, and which do I track?',
    readers: ['/api/v3/watch/', '/api/v2/watch/alerts/list', '/api/v2/watch/decision/latest', '/api/v3/opportunities'], gaps: [] },
  { id: 'security', path: '/security/:symbol', title: 'Security detail', slice: 2, viewCount: null, state: 'NOT_BUILT',
    decision: 'Why hold or consider this security?',
    readers: ['/api/v2/symbol-cards', '/api/v2/tax-lots', '/api/v3/opportunities/'], gaps: ['valuation-assessment@1 (as Portfolio)'] },
  { id: 'trading', path: '/trading', title: 'Trading & Strategy', slice: 2, viewCount: null, state: 'NOT_BUILT',
    decision: 'Which governed proposals are ready for review?', readers: ['/api/v2/strategy-desk'], gaps: [] },
  { id: 'journal', path: '/journal', title: 'Journal', slice: 2, viewCount: null, state: 'NOT_BUILT',
    decision: 'What did actual decisions produce?', readers: ['/api/v2/journal'], gaps: [] },
  { id: 'cio', path: '/cio', title: 'CIO, Research & History', slice: 2, viewCount: null, state: 'NOT_BUILT',
    decision: 'What does the desk know and why?',
    readers: ['/api/v3/cio', '/api/v3/watch/cio/history', '/api/v2/reports/list'], gaps: [] },
  { id: 'ops', path: '/ops', title: 'Ops (investor impact first)', slice: 2, viewCount: null, state: 'NOT_BUILT',
    decision: 'Which investment workflows are impaired?',
    readers: ['/api/v2/system/platform-health', '/api/v2/home/incidents', '/api/v2/needs-action'], gaps: [] },
]
