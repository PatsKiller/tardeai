// node --experimental-strip-types --import ./src/testharness/tsxRegister.mjs src/lib/releasesOperatorView.render.test.mjs
//
// THE PAGE, RENDERED (codex, #2541 round four). The previous suite drove pure helpers beside each JSX branch, so
// deleting a branch left 131/131 green — it tested the sibling, not the page. Every case below renders the REAL
// OperatorView with react-dom/server and asserts on the STRING THE OPERATOR WOULD SEE.
//
// The rule under test is the one the page claims: a panel may assert "none" only when its own source is current.
import '../testharness/tsxRegister.mjs'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'

const { OperatorView, flightAnswered, inFlightCensus } = await import('../pages/ReleasesSchedules.tsx')

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
    now: over.now ?? Date.parse('2026-11-04T10:05:00Z'),
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


// ── THE SOURCE BOUNDARY (codex round five): feed {} through the PAGE'S OWN derivation, not a pre-computed false ──
// The previous case handed `flightAnswered: false` to the child, so reverting the derivation to `!!wire` left the
// suite green. The payload shapes below go through the function the page actually calls.
check('an invalid {} payload is NOT an answered census', flightAnswered({}) === false)
check('a payload without prs is not answered', flightAnswered({ status: 'OK' }) === false)
check('null is not answered', flightAnswered(null) === false)
// F1: a census needs a supported schema and a fresh wire — a bare prs[] is not enough any more
const VALID = { schema: 'DeployInFlight@v2', freshness: 'OK', status: 'OK', prs: [] }
check('a validated empty census IS answered', flightAnswered(VALID) === true)
check('an unsupported schema is NOT a census', flightAnswered({ ...VALID, schema: 'Unexpected@v9' }).valueOf() === false)
check('a STALE wire is NOT a census', flightAnswered({ ...VALID, freshness: 'STALE' }) === false)
check('an UNAVAILABLE wire is NOT a census', flightAnswered({ ...VALID, freshness: 'UNAVAILABLE' }) === false)
check('a dropped member makes completeness UNKNOWN', inFlightCensus({ ...VALID, prs: [null] }).answered === false)
check('a bare prs list is not a census', flightAnswered({ prs: [] }) === false)
const viaInvalid = render({ flightAnswered: flightAnswered({}) })
check('{} through the real derivation renders "cannot tell", never "nothing needs you"',
  viaInvalid.includes('Cannot tell') && !viaInvalid.includes('Nothing needs you.'))
check('{} through the real derivation never says nothing is stuck', !viaInvalid.includes('Nothing is stuck right now.'))
const viaEmpty = render({ flightAnswered: flightAnswered(VALID) })
check('an empty prs list through the real derivation may say nothing needs you',
  viaEmpty.includes('Nothing needs you.'))



// F1 #2592: captured from deploy_in_flight.build with injected lister/coordination (native v1, no actions).
// The wire itself, normalizer and census all reach the REAL OperatorView. Missing authority stays read-only.
const nativeLegacy = {
  "schema": "DeployInFlight@v1",
  "authority": "READ_ONLY_ADVISORY",
  "generated_at": "2026-11-05T17:55:00+00:00",
  "repo": "synthetic/test",
  "source": "gh pr list (GitHub REST API via subprocess, read-only; cached 60s)",
  "prs": [
    {
      "number": 900001,
      "title": "Synthetic harmless improvement",
      "url": "https://example.invalid/change",
      "head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "head_sha_short": "aaaaaaaaa",
      "branch": "wt/synthetic",
      "has_operator_merge": false,
      "mergeable": "MERGEABLE",
      "merge_state": "CLEAN",
      "is_draft": false,
      "why_held": null,
      "next": "auto-merge",
      "work": {
        "owner": "synthetic-reviewer",
        "current_task": "Synthetic harmless improvement",
        "local_head": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "published_head": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "review": {
          "state": "MERGE",
          "head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        },
        "ci": {
          "state": "GREEN",
          "head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        },
        "blockers": [],
        "source": "synthetic",
        "as_of": "2026-11-05T17:55:00+00:00",
        "publication_state": "published"
      }
    }
  ],
  "count": 1,
  "status": "OK",
  "freshness": "OK",
  "reason": null,
  "coordination": {
    "status": "OK",
    "agents": [],
    "as_of": "2026-11-05T17:55:00+00:00"
  }
}
const { normalizeRows } = await import('./deployInFlight.ts')
const legacyWire = (publication) => {
  const wire = structuredClone(nativeLegacy)
  wire.prs[0].work.published_head = ['published', 'merged', 'live'].includes(publication) ? wire.prs[0].head_sha : null
  if (publication === 'missing') delete wire.prs[0].work.publication_state
  else wire.prs[0].work.publication_state = publication === 'malformed' ? { unexpected: 'value' } : publication
  return wire
}
const renderWire = wire => render({ rows: normalizeRows(wire.prs).rows,
  flightAnswered: inFlightCensus(wire).answered, flightAsOf: wire.generated_at,
  flightError: wire.reason ?? null, coordStatus: wire.coordination?.status ?? 'UNAVAILABLE',
  now: Date.parse(wire.generated_at), s: {} })
const knownFacts = {
  published: 'recorded as uploaded', local_only: 'has not been uploaded yet',
  merged: 'recorded as merged', live: 'recorded as live',
  unknown: 'Whether this work has been uploaded is not recorded',
  missing: 'Whether this work has been uploaded is not recorded',
  malformed: 'Whether this work has been uploaded is not recorded',
}
for (const [publication, fact] of Object.entries(knownFacts)) {
  const output = renderWire(legacyWire(publication))
  check(`legacy ${publication}: publication fact stays true`, output.includes(fact))
  check(`legacy ${publication}: missing actions never invent approval or upload authorization`,
    !output.includes('Authorize the upload') && !output.includes('Open the change and approve it'))
  check(`legacy ${publication}: only an existing read-only change link is offered`,
    output.includes('View the recorded change') && output.includes('https://example.invalid/change'))
  check(`legacy ${publication}: summary does not claim an operator action`,
    output.includes('Check the recorded items below') && !/thing(?:s)? need you/.test(output))
}
for (const [publication, eligible, label, fact] of [
  ['published', ['approve'], 'Open the change and approve it', 'checks passed'],
  ['published', ['push'], 'Authorize the upload', 'recorded as uploaded'],
  ['local_only', ['push'], 'Authorize the upload', 'has not been uploaded yet'],
  ['unknown', ['push'], 'Authorize the upload', 'Whether this work has been uploaded is not recorded'],
  ['published', [], 'View the recorded change', 'recorded as uploaded'],
]) {
  const wire = legacyWire(publication)
  wire.schema = 'DeployInFlight@v2'
  wire.prs[0].operator_actions = { required: true, eligible }
  const output = renderWire(wire)
  check(`server ${publication}/${eligible}: explicit action or absence is preserved`, output.includes(label))
  check(`server ${publication}/${eligible}: action never rewrites publication`, output.includes(fact))
}
const missingLink = legacyWire('unknown')
missingLink.prs[0].url = ''
const withoutLink = renderWire(missingLink)
check('missing legacy link: no link or authorization is invented',
  !withoutLink.includes('View the recorded change') && !withoutLink.includes('Authorize the upload')
  && withoutLink.includes('No change link was supplied'))

// Keep the prior structured-receipt render controls at the actual history boundary.
for (const [name, verification] of [
  ['failed', { ok: false }], ['errors', { ok: true, readback_errors: ['synthetic failure'] }],
  ['rolled-back', { ok: true, rolled_back: true }], ['success', { ok: true, readback_errors: [] }],
]) {
  const output = render({ s: { history: sec({ releases: [{ receipt: name, mode: 'apply',
    at: nativeLegacy.generated_at, verify: verification }], receipts_total: 1 }) } })
  check(`actual history ${name}: working claim matches structured receipt`,
    name === 'success' ? output.includes('Checked working: yes.') : !output.includes('Checked working: yes.'))
}

// FIRST cloud #2592: assert the real v1 producer ABI answers; merely rendering its rows
// did not test the census contract and allowed the page's v2-only check to pass.
check('native build v1 list is an answered census', inFlightCensus(nativeLegacy).answered)
const nativeEmpty = { ...structuredClone(nativeLegacy), prs: [], count: 0 }
check('native build v1 empty list is an answered census', inFlightCensus(nativeEmpty).answered)
const nativeEmptyHtml = renderWire(nativeEmpty)
check('native v1 empty: Needs you may state its measured empty answer', nativeEmptyHtml.includes(noneNeedsYou))
check('native v1 empty: Stuck may state its measured empty answer', nativeEmptyHtml.includes(noneStuck))
check('native v1 empty: no false source-unanswered warning', !nativeEmptyHtml.includes('Nothing has been read from the open-change source'))
// build() keeps a successful PR census OK when its independent coordination read fails/partly answers.
for (const coordinationStatus of ['PARTIAL', 'UNAVAILABLE']) {
  const wire = { ...structuredClone(nativeEmpty), coordination: { ...nativeEmpty.coordination, status: coordinationStatus } }
  check(`native v1/${coordinationStatus}: separate coordination failure does not erase PR census`, inFlightCensus(wire).answered)
  const output = renderWire(wire)
  check(`native v1/${coordinationStatus}: no claim that all agents are idle`, !output.includes('No agent is working right now.'))
  check(`native v1/${coordinationStatus}: coordination gap is stated`, /partly answered|Cannot tell who is working/.test(output))
}
for (const [name, wire] of [
  ['lister failure', { ...nativeEmpty, status: 'UNAVAILABLE', freshness: 'UNAVAILABLE', prs: null, count: null, reason: 'synthetic lister failure' }],
  ['stale', { ...nativeEmpty, freshness: 'STALE' }],
  ['error status', { ...nativeEmpty, status: 'ERROR' }],
  ['missing list', { ...nativeEmpty, prs: undefined }],
  ['dropped row', { ...nativeEmpty, prs: [null] }],
  ['unsupported schema', { ...nativeEmpty, schema: 'Unsupported@v3' }],
]) {
  check(`native v1/${name}: unusable census is not answered`, !inFlightCensus(wire).answered)
  const output = renderWire(wire)
  check(`native v1/${name}: unanswered is not a measured empty decision list`, !output.includes(noneNeedsYou))
  check(`native v1/${name}: unanswered is not a measured empty stuck list`, !output.includes(noneStuck))
}
// Real normalized rows reach the real component; a label must not yield Ready or merging
// while draft/conflict/unknown/head-binding/review/CI facts say it is unready.
for (const [name, overrides] of [
  ['draft', { is_draft: true }], ['conflict', { mergeable: 'CONFLICTING' }],
  ['unknown mergeability', { mergeable: 'UNKNOWN' }],
  ['local only', { work: { ...nativeLegacy.prs[0].work, publication_state: 'local_only' } }],
  ['missing review', { work: { ...nativeLegacy.prs[0].work, review: undefined } }],
  ['old review', { work: { ...nativeLegacy.prs[0].work, review: { state: 'MERGE', head_sha: 'b'.repeat(40) } } }],
  ['missing CI', { work: { ...nativeLegacy.prs[0].work, ci: undefined } }],
  ['red CI', { work: { ...nativeLegacy.prs[0].work, ci: { state: 'RED', head_sha: nativeLegacy.prs[0].head_sha } } }],
  ['pending CI', { work: { ...nativeLegacy.prs[0].work, ci: { state: 'PENDING', head_sha: nativeLegacy.prs[0].head_sha } } }],
]) {
  const wire = structuredClone(nativeLegacy)
  wire.prs[0] = { ...wire.prs[0], has_operator_merge: true, ...overrides }
  const output = renderWire(wire)
  check(`approved/${name}: actual page never groups unready change as Ready`, !/>Ready\s*·/.test(output))
  check(`approved/${name}: actual page never promises merging`, !output.includes('Merging in the next window'))
}
for (const approved of [false, true]) {
  const wire = structuredClone(nativeLegacy)
  wire.prs[0].has_operator_merge = approved
  const output = renderWire(wire)
  check(`ready/approval=${approved}: actual positive group remains`, approved
    ? output.includes('Merging in the next window') : />Ready\s*·/.test(output))
}

console.log(`releasesOperatorView.render: ${pass} passed, ${fail} failed`)
process.exit(fail > 0 ? 1 : 0)
