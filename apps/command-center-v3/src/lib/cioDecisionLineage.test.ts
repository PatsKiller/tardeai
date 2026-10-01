import { decisionLineageHref, isCioLineageState } from './cioDecisionLineage.ts'

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
