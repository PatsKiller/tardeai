// node --experimental-strip-types src/lib/manualSetupScope.test.mjs
// FQ-044 (/manual-execution F): one draft card showed READY, TECH OK, DECISION PENDING and rating
// UNKNOWN with nothing saying what READY scopes. READY is draft completeness, not approval, and the
// decision on this desk is advisory. The words must carry that scope, and the card must render them.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { stateBadgeWords, stateScopeTitle, decisionWords } from './manualSetupScope.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

check(/NOT SENT/.test(stateBadgeWords('READY')), 'READY still does not say the draft has not been sent')
check(/NOT SENT/.test(stateBadgeWords('GENERATED')), 'GENERATED still does not say the draft has not been sent')
check(stateBadgeWords('BROKER_OBSERVED') === 'AUTO-LINKED FROM SCHWAB READ-ONLY', 'the broker-linked label changed')
check(stateBadgeWords('EXCEPTION') === 'EXCEPTION', 'a plain state was rewritten')
check(/not approval/i.test(stateScopeTitle('READY')), 'the READY tooltip does not say it is not approval')
check(/Schwab/.test(stateScopeTitle('BROKER_OBSERVED')), 'the broker-linked tooltip lost its source')

check(decisionWords('GO', 'PROPOSAL') === 'GO · advisory', 'GO does not say it is advisory')
check(decisionWords('WAIT', 'PROPOSAL') === 'WAIT · advisory', 'WAIT does not say it is advisory')
check(/advisory/.test(decisionWords(null, 'DRAFT')), 'DECISION PENDING does not say it is advisory')
check(decisionWords(null, 'WATCHLIST') === 'WATCHLIST ADVISORY', 'the watchlist advisory label changed')

const row = readFileSync(join(HERE, '../components/EntryDeskRow.tsx'), 'utf8')
check(/stateBadgeWords\(/.test(row), 'EntryDeskRow does not render the scoped state words')
check(/stateScopeTitle\(/.test(row), 'EntryDeskRow dropped the scope tooltip')
check(/decisionWords\(/.test(row), 'EntryDeskRow does not render the advisory-scoped decision')

const desk = readFileSync(join(HERE, '../pages/ManualTosDesk.tsx'), 'utf8')
check(/manual-desk-scope-legend/.test(desk), 'the desk has no one-line legend saying what READY means and that nothing here places an order')
check(/not approval/i.test(desk), 'the legend does not say READY is not approval')

if (failed) { console.error(`manualSetupScope: ${failed} failure(s)`); process.exit(1) }
console.log('manualSetupScope: ok')
