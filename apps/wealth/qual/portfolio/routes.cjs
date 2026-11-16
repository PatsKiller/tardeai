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
    { id: 'retirement', path: '/wealth/portfolio/retirement', status: 'not-built', reads: [] },
    { id: 'levels', path: '/wealth/portfolio/levels', status: 'not-built', reads: [] },
  ],
}
