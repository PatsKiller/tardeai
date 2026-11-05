// node --experimental-strip-types src/lib/opportunityViewport.test.mjs
// FQ-071 (/trading D): at phone widths the opportunity table separates labels from values. The page
// must start in its labelled card view there, keep the table for wider screens, and not change the
// toggle. A missing width is not a reason to guess narrow.
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defaultOpportunityView, CARD_VIEW_MAX_WIDTH } from './opportunityViewport.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

check(defaultOpportunityView(390) === 'cards', '390 px still starts in the unlabeled table')
check(defaultOpportunityView(412) === 'cards', '412 px still starts in the unlabeled table')
check(defaultOpportunityView(CARD_VIEW_MAX_WIDTH) === 'cards', 'the boundary width does not start in cards')
check(defaultOpportunityView(CARD_VIEW_MAX_WIDTH + 1) === 'table', 'a desktop width was forced into cards')
check(defaultOpportunityView(null) === 'table', 'an unknown width was guessed as narrow')
check(defaultOpportunityView(1440) === 'table', '1440 px no longer shows the table')

const page = readFileSync(join(HERE, '../components/tradeai/TradeAiOpportunities.tsx'), 'utf8')
check(/initialOpportunityView\)?/.test(page), 'TradeAiOpportunities does not choose its starting view from the viewport')
check(/useState<'table' \| 'cards'>\(initialOpportunityView\)/.test(page), 'the starting view is still hardcoded to the table')
check(/v === 'table' \? 'Table' : 'Cards'/.test(page), 'the Table/Cards toggle was removed instead of kept')

if (failed) { console.error(`opportunityViewport: ${failed} failure(s)`); process.exit(1) }
console.log('opportunityViewport: ok')
