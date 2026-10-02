// HermesResearchLinks@v1 / AgentRuntimeProof@v1 client contract tests (pure; run with node).
import {
  decisionLineageHref,
  decisionLinkState,
  hermesProvenanceHref,
  linkItems,
  proofRow,
  researchLinksUrl,
  symbolResearchHref,
  thesisHref,
} from './hermesResearchLinks.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, condition: boolean) {
  if (condition) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

const payload = {
  items: [
    { result_id: 'rr_aaa', symbol: 'CSCO', decision_ids: ['prod_1', 'cio_books_1'], decision_link: { state: 'RECORDED' as const }, thesis_refs: ['symbol_csco@v3'] },
    { result_id: 'rr_bbb', symbol: null, decision_ids: [], decision_link: { state: 'NOT_RECORDED' as const, reason: 'none' }, thesis_refs: [] },
    { nope: true },
  ],
}
const items = linkItems(payload as never)
check('malformed rows are dropped', items.length === 2)
check('recorded decision link stays RECORDED', decisionLinkState(items[0]) === 'RECORDED')
check('absent decision link is NOT_RECORDED', decisionLinkState(items[1]) === 'NOT_RECORDED')
check('RECORDED state without ids is not trusted', decisionLinkState({ result_id: 'x', decision_ids: [], thesis_refs: [], decision_link: { state: 'RECORDED' } }) === 'NOT_RECORDED')
check('decision href targets CIO decision lineage', decisionLineageHref('prod_1') === '/cio?tab=evidence-comms&sub=decision-lineage&decision=prod_1')
check('research links url carries filters', researchLinksUrl({ symbol: 'csco', limit: 5 }) === '/api/v3/hermes/research-links?limit=5&symbol=CSCO')

const hrefs = [decisionLineageHref('a'), symbolResearchHref('A'), thesisHref('t@v1'), hermesProvenanceHref('rr_1')]
check('internal hrefs are router-relative (no /v3/ prefix)', hrefs.every(h => h.startsWith('/') && !h.startsWith('/v3/')))

const proof = {
  fields: {
    last_natural_wake: { attributable: true },
    last_research_action: { attributable: true },
    last_memory_retrieval: { attributable: false },
    decisions_contributed: { attributable: true },
  },
  agents: {
    alex: {
      last_natural_wake: { state: 'RECORDED' as const, value: 'material_scan', at: '2026-10-02T15:45:19.322+00:00' },
      decisions_contributed: { state: 'RECORDED' as const, value: 3, recent_ids: ['dec_1'] },
      last_memory_retrieval: { state: 'NOT_EXPOSED' as const, reason: 'retrieval rows carry no agent attribution' },
    },
  },
}
check('no payload keeps NOT EXPOSED BY READ CONTRACT', proofRow(null, 'alex', 'last_natural_wake')[1] === 'UNKNOWN')
check('recorded wake is RUNTIME', proofRow(proof, 'alex', 'last_natural_wake')[1] === 'RUNTIME')
check('unattributable memory is NOT_EXPOSED', proofRow(proof, 'alex', 'last_memory_retrieval')[1] === 'NOT_EXPOSED')
check('agent with no rows is NOT_RECORDED, never RUNTIME', proofRow(proof, 'sentinel', 'last_natural_wake')[1] === 'NOT_RECORDED')
check('decision count rendered', proofRow(proof, 'alex', 'decisions_contributed')[0].startsWith('3 decisions'))

// The source-file scan for "/v3/" internal links lives in tests/test_cio_xsurface_census_completeness_20261002.py.

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
