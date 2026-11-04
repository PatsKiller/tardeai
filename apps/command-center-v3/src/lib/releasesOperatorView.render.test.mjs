// node --experimental-strip-types --import ./src/lib/tsxRegister.mjs src/lib/releasesOperatorView.render.test.mjs
//
// THE PAGE, RENDERED (codex, #2541 round four). The previous suite drove pure helpers beside each JSX branch, so
// deleting a branch left 131/131 green — it tested the sibling, not the page. Every case below renders the REAL
// OperatorView with react-dom/server and asserts on the STRING THE OPERATOR WOULD SEE.
//
// The rule under test is the one the page claims: a panel may assert "none" only when its own source is current.
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'

const { OperatorView } = await import('../pages/ReleasesSchedules.tsx')

let pass = 0, fail = 0
const check = (name, cond, detail = '') => {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name} ${detail}`) }
}

const sec = (value, state = 'OK') => ({ state, value, reason: null, source: 'fixture', asOf: '2026-11-04T10:00:00Z',
  ageS: 60, label: state })
const sections = (over = {}) => ({
  serving: sec({ release_name: 'rel', since: '2026-11-04T08:00:00Z', pins_agree: true }),
  next_release: sec({ is_serving: true, commits_ahead: 0 }),
  release_errors: sec({ rows: [] }),
  history: sec({ releases: [], receipts_total: 0 }),
  n8n_today: sec({ total: 3, errors_total: 0, dead_letters: { available: true, unreleased: 0 } }),
  timeline: sec({}),
  ...over,
})

function render(over = {}) {
  const props = {
    s: sections(over.s), rows: over.rows ?? [], agents: over.agents ?? [],
    generatedAt: '2026-11-04T10:00:00Z', flightAsOf: over.flightAsOf ?? '2026-11-04T10:00:00Z',
    coordAsOf: '2026-11-04T10:00:00Z', flightError: over.flightError ?? null, loading: over.loading ?? false,
    now: Date.parse('2026-11-04T10:05:00Z'),
    flightLoading: over.flightLoading ?? false, flightStale: over.flightStale ?? false,
    flightAnswered: over.flightAnswered ?? true, coordStatus: over.coordStatus ?? 'OK',
  }
  return renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(OperatorView, props)))
}

const html = render({})
check('the real component renders at all', html.includes('data-testid="rs-operator-view"'), html.slice(0, 200))

// ── the three states codex measured, each asserted on the RENDERED text ─────────────────────────────────────────
const noneNeedsYou = 'Nothing needs you.'
const noneStuck = 'Nothing is stuck right now.'

// (2) invalid {} census: the in-flight payload carries no prs array, so it is not an answered census
const invalid = render({ flightAnswered: false })
check('invalid census: the page does not claim nothing needs you', !invalid.includes(noneNeedsYou))
check('invalid census: the page does not claim nothing is stuck', !invalid.includes(noneStuck))
check('invalid census: the page says it cannot tell', /Cannot tell/.test(invalid))

// a genuinely answered, empty census MAY still say none
const answered = render({})
check('answered empty census: may say nothing needs you', answered.includes(noneNeedsYou) || answered.includes('Nothing needs you from'))
check('answered empty census: may say nothing is stuck', answered.includes(noneStuck))

// (1) a STALE next_release comparison is not decisive
const staleNext = render({ s: { next_release: sec({ is_serving: true, commits_ahead: 0 }, 'STALE') } })
check('stale comparison: the page does not claim nothing is going live', !staleNext.includes('Nothing is going live today'))
check('stale comparison: the page says the comparison could not be read', /could not be read/.test(staleNext))

// unknown comparison with a measured-empty open list: both sentences must not coexist
const unknownComparison = render({ s: { next_release: sec(null, 'UNAVAILABLE') } })
check('unknown comparison: no all-clear anywhere in Going live',
  !unknownComparison.includes('Nothing is going live today'))

// stale agents must not read as idle
const staleAgents = render({ flightStale: true })
check('stale agents: the page does not say no agent is working', !staleAgents.includes('No agent is working right now.'))
check('stale agents: it says it cannot tell who is working', /Cannot tell who is working/.test(staleAgents))

// stale open-change rows must not certify "nothing is stuck"
const staleStuck = render({ flightStale: true, rows: [] })
check('stale census: the page does not say nothing is stuck', !staleStuck.includes(noneStuck))

console.log(`releasesOperatorView.render: ${pass} passed, ${fail} failed`)
process.exit(fail > 0 ? 1 : 0)
