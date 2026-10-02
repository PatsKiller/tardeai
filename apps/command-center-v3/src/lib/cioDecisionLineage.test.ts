import {
  cioDeepLinkFocus, decisionFocusHref, decisionLineageHref, isCioLineageState, researchFocusHref, routerPath,
} from './cioDecisionLineage.ts'

if (decisionLineageHref('dec_same_symbol_1') !== '/cio?tab=evidence-comms&sub=decision-lineage&decision=dec_same_symbol_1') {
  throw new Error('decision lineage links must be basename-relative')
}
if (decisionLineageHref('dec/encoded') !== '/cio?tab=evidence-comms&sub=decision-lineage&decision=dec%2Fencoded') {
  throw new Error('decision lineage links must encode decision identity')
}
if (decisionLineageHref('dec_same_symbol_1').startsWith('/v3/')) {
  throw new Error('decision lineage link must not double the BrowserRouter basename')
}
if (!isCioLineageState('UNKNOWN') || !isCioLineageState('PENDING') || isCioLineageState('NOT_A_STATE')) {
  throw new Error('lineage state vocabulary is not enforced')
}
console.log('cioDecisionLineage.test.ts: ok')

// Deep links (review gap 4): router-relative and exact-id only.
if (decisionFocusHref('dec/a b') !== '/cio?tab=decisions&decision=dec%2Fa%20b') {
  throw new Error('decisions-tab focus link must encode the exact decision id')
}
if (researchFocusHref('dec_1', 'res_9') !== '/cio?tab=research&decision=dec_1&artifact=res_9'
  || researchFocusHref('dec_1') !== '/cio?tab=research&decision=dec_1') {
  throw new Error('research focus link must carry decision and optional artifact')
}
for (const href of [decisionFocusHref('x'), researchFocusHref('x', 'y'), decisionLineageHref('x')]) {
  if (href.startsWith('/v3/')) throw new Error(`doubled basename: ${href}`)
}
const focus = cioDeepLinkFocus(new URLSearchParams('tab=research&decision=%20dec_1%20&artifact=res_9&research='))
if (focus.decision !== 'dec_1' || focus.artifact !== 'res_9' || focus.research !== null) {
  throw new Error('deep-link focus must trim ids and treat blanks as no focus')
}
console.log('cioDecisionLineage.test.ts deep links: ok')

// Backend hrefs (scorecard tiles, evidence refs) already carry /v3; the router adds it again.
for (const [input, want] of [
  ['/v3/cio?tab=research', '/cio?tab=research'],
  ['/v3/cio?tab=evidence-comms&sub=telegram-receipts', '/cio?tab=evidence-comms&sub=telegram-receipts'],
  ['/cio?tab=decisions', '/cio?tab=decisions'],
  ['/v3', '/'],
  ['/v3x/keep', '/v3x/keep'],
] as const) {
  if (routerPath(input) !== want) throw new Error(`routerPath(${input}) = ${routerPath(input)}, want ${want}`)
}
console.log('cioDecisionLineage.test.ts routerPath: ok')
