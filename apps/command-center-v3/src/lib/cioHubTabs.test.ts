/**
 * Hermetic nav alias tests for the CIO Desk 4-tab IA (intel/v001: Today · Holdings verdicts · My questions · Report).
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

eq('default tab', CIO_HUB_DEFAULT_TAB, 'today')
eq('four tabs', [...CIO_HUB_TABS], ['today', 'holdings', 'questions', 'report'])
eq('null → today', resolveCioHubTab(null), 'today')
eq('empty → today', resolveCioHubTab(''), 'today')
eq('overview → today', resolveCioHubTab('overview'), 'today')
eq('decisions → today', resolveCioHubTab('decisions'), 'today')
eq('cio-brain → report', resolveCioHubTab('cio-brain'), 'report')
eq('cio-now → today', resolveCioHubTab('cio-now'), 'today')
eq('opportunities → today', resolveCioHubTab('opportunities'), 'today')
eq('universe-theses → report', resolveCioHubTab('universe-theses'), 'report')
eq('investment-books → report', resolveCioHubTab('investment-books'), 'report')
eq('capital-plan → report', resolveCioHubTab('capital-plan'), 'report')
eq('posture → report', resolveCioHubTab('posture'), 'report')
eq('operator-policy → report', resolveCioHubTab('operator-policy'), 'report')
eq('evidence-comms → report', resolveCioHubTab('evidence-comms'), 'report')
eq('telegram-receipts → report', resolveCioHubTab('telegram-receipts'), 'report')
eq('advisory → holdings', resolveCioHubTab('advisory'), 'holdings')
eq('questions', resolveCioHubTab('questions'), 'questions')
eq('unknown → today', resolveCioHubTab('unknown-tab'), 'today')
eq('sub telegram', resolveEvidenceSubtab('telegram-receipts'), 'telegram-receipts')
eq('sub cio-brain', resolveEvidenceSubtab('cio-brain'), 'full-brain')
eq('sub evidence', resolveEvidenceSubtab('evidence'), 'audit')
eq('sub research', resolveEvidenceSubtab('research'), 'research')
eq('sub posture', resolveEvidenceSubtab('posture'), 'capital-policy')
eq('sub overview null', resolveEvidenceSubtab('overview'), null)

if (failed) throw new Error(`cioHubTabs.test.ts: ${failed} failed`)
console.log('cioHubTabs.test.ts: ok')
