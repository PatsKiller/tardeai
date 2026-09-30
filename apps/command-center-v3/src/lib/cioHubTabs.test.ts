/**
 * Hermetic nav alias tests for CIO Desk 5-tab IA.
 * Run via: node --experimental-strip-types src/lib/cioHubTabs.test.ts
 */
import {
  CIO_HUB_DEFAULT_TAB,
  CIO_HUB_TABS,
  resolveCioHubTab,
  resolveEvidenceSubtab,
} from './cioHubTabs.ts'

let failed = 0
function eq(name: string, got: unknown, want: unknown) {
  const g = JSON.stringify(got), w = JSON.stringify(want)
  if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) }
}

eq('default tab', CIO_HUB_DEFAULT_TAB, 'overview')
eq('five tabs', [...CIO_HUB_TABS], [
  'overview',
  'decisions',
  'research',
  'capital-policy',
  'evidence-comms',
])
eq('null → overview', resolveCioHubTab(null), 'overview')
eq('empty → overview', resolveCioHubTab(''), 'overview')
eq('overview', resolveCioHubTab('overview'), 'overview')
eq('cio-brain → overview', resolveCioHubTab('cio-brain'), 'overview')
eq('cio-now → decisions', resolveCioHubTab('cio-now'), 'decisions')
eq('opportunities → decisions', resolveCioHubTab('opportunities'), 'decisions')
eq('universe-theses → research', resolveCioHubTab('universe-theses'), 'research')
eq('investment-books → research', resolveCioHubTab('investment-books'), 'research')
eq('capital-plan → capital-policy', resolveCioHubTab('capital-plan'), 'capital-policy')
eq('posture → capital-policy', resolveCioHubTab('posture'), 'capital-policy')
eq('operator-policy → capital-policy', resolveCioHubTab('operator-policy'), 'capital-policy')
eq('report → evidence-comms', resolveCioHubTab('report'), 'evidence-comms')
eq('telegram-receipts → evidence-comms', resolveCioHubTab('telegram-receipts'), 'evidence-comms')
eq('unknown → overview', resolveCioHubTab('unknown-tab'), 'overview')
eq('sub telegram', resolveEvidenceSubtab('telegram-receipts'), 'telegram-receipts')
eq('sub cio-brain', resolveEvidenceSubtab('cio-brain'), 'full-brain')
eq('sub evidence', resolveEvidenceSubtab('evidence'), 'audit')
eq('sub overview null', resolveEvidenceSubtab('overview'), null)

if (failed) {
  console.error(`cioHubTabs.test.ts: ${failed} failed`)
  process.exit(1)
}
console.log('cioHubTabs.test.ts: ok')
