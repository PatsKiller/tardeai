'use strict'
// Route expectation table. The lead flips `status` from 'not-built' to 'built' when a partial page lands, then fills
// `ready` (text that must appear once the page has data) and `populated` (text that proves real data, not a shell).
// A route marked 'built' without `ready` and `populated` FAILS on purpose: a built page needs a stated expectation.
//
// status 'not-built': the page must say so truthfully today (matches `notBuiltText`) and show no figures or tables.
module.exports = {
  KNOWN_WEALTH_ROUTES: [
    '/wealth/portfolio/holdings', '/wealth/portfolio/performance', '/wealth/portfolio/income', '/wealth/portfolio/allocation',
    '/wealth/portfolio/fundamentals', '/wealth/portfolio/retirement', '/wealth/portfolio/levels',
    '/wealth/home/today', '/wealth/home/outlook', '/wealth/home/needs', '/wealth/',
  ],
  NOT_BUILT_TEXT: /Not built yet/i,
  ROUTES: [
    { id: 'holdings', path: '/wealth/portfolio/holdings', status: 'built', reads: ['/api/v2/portfolio/holdings'],
      ready: ['QZBIG'], populated: ['QZBIG', 'QZDUP', 'QZGAP', 'Synthetic Taxable', 'Synthetic Roth'] },
    { id: 'fundamentals', path: '/wealth/portfolio/fundamentals', status: 'built', reads: ['/api/v2/portfolio/holdings'],
      ready: ['QZBIG'], populated: ['QZBIG', 'QZOWN', 'Synthetic Taxable'] },
    { id: 'performance', path: '/wealth/portfolio/performance', status: 'built', reads: ['/api/v2/portfolio/performance', '/api/v2/overview'],
      ready: ['Performance evidence', 'Synthetic Taxable'], populated: ['Household', 'Synthetic Taxable', 'Synthetic Roth', 'Synthetic NoPerf'] },
    { id: 'income', path: '/wealth/portfolio/income', status: 'built', reads: ['/api/v2/dividends'],
      ready: ['QZDIVQ'], populated: ['QZDIVQ', 'QZDIVM', 'Synthetic Taxable', 'Forecast payers'] },
    { id: 'allocation', path: '/wealth/portfolio/allocation', status: 'built', reads: ['/api/v2/portfolio/holdings'],
      ready: ['Where the book is allocated', 'matching rows'], populated: ['Where the book is allocated', 'matching rows', 'Technology'] },
    // Partial pages (2026-11-16): `ready`/`populated` prove the served state rendered; INTERACTIONS in run.cjs assert the
    // truthful partial states (Unknown for zero-fills and producer defaults, withheld projections, levels freshness Unknown).
    { id: 'retirement', path: '/wealth/portfolio/retirement', status: 'built', reads: ['/api/v2/retirement', '/api/v2/retirement/planning-research'],
      ready: ['Retirement roadmap', 'Synthetic milestone QZRET'], populated: ['Synthetic milestone QZRET', '$123,456', '2045-06-01', 'Synthetic planning theme', 'Not served, so not shown'] },
    // Levels reads nothing until an explicit submit, so its declared reads are empty and lifecycle cases skip it.
    { id: 'levels', path: '/wealth/portfolio/levels', status: 'built', reads: [],
      ready: ['Levels and valuation', 'Nothing is requested until you do'], populated: ['Read levels', 'Valuation is not wired', 'fetches market data from an external provider'] },
  ],
}
