// node src/lib/optionsDeskTruth.test.ts
import { isCardBlocked, sanitizeActionButtons } from './optionsCardSemantics.ts'
import {
  coveredCallFunnelCounts, funnelNameText, optionsDeskPersonLine, rewardRiskPresentation,
} from './optionsDeskTruth.ts'

let failed = 0
function eq(name: string, got: unknown, want: unknown) {
  const g = JSON.stringify(got), w = JSON.stringify(want)
  if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) }
}
function ok(name: string, cond: unknown) { if (!cond) { failed++; console.error(`FAIL ${name}`) } }

const rows = [
  { symbol: 'LMT', account: 'schwab_rollover_ira', cc: { status: 'CC_ELIGIBLE' } },
  { symbol: 'SCHD', account: 'schwab_rollover_ira', cc: { status: 'INTENT_BYPASS' } },
  { symbol: 'SPCX', account: 'schwab_taxable', cc: { status: 'EDGE_BELOW' } },
  { symbol: 'V', account: 'schwab_rollover_ira', cc: { status: 'NEED_100_SHARES' } },
]
const counts = coveredCallFunnelCounts(rows, { CC_ELIGIBLE: 9, INTENT_BYPASS: 9 })
eq('cleared ignores intent bypass and the summed tally', counts.cleared, {
  count: 1, names: ['LMT · schwab rollover ira'], namesKnown: true,
})
eq('intent iv is separate', counts.intentIvOnly.count, 1)
eq('edge below is not cleared', counts.cleared.names.includes('SPCX · schwab taxable'), false)
eq('empty cleared list says none', funnelNameText({ count: 0, names: [], namesKnown: true }), 'none')
eq('tally without rows does not pretend the names are none', funnelNameText(coveredCallFunnelCounts([], { INTENT_BYPASS: 2 }).intentIvOnly), 'row list missing')

const blockedThesis = {
  options_decision_packet: { state: 'BLOCKED' },
  flags: [{ key: 'THESIS_INCOMPLETE' }, { key: 'NOT_APPROVABLE' }],
  enterprise: { blocks: [{ code: 'oi' }] },
}
const blockedComplete = {
  options_decision_packet: { state: 'BLOCKED' },
  flags: [{ key: 'NOT_APPROVABLE' }],
  enterprise: { blocks: [{ code: 'spread' }] },
}
const line = optionsDeskPersonLine([blockedThesis, blockedThesis, blockedThesis, blockedComplete], 0)
ok('person line counts blocked and thesis apart', line.startsWith('Needs a person: 0 ready for operator review. 4 blocked. 3 missing a thesis.'))
ok('person line does not say refused or incomplete', !line.includes('refused or incomplete'))

eq('hedge ratio stays neutral above 0.3', rewardRiskPresentation({ strategy: 'protective_put', risk_reward: 33.48, enterprise: { blocks: [{ code: 'x' }] } }), { label: 'hedge ratio', success: false })
eq('blocked credit is not a green R:R', rewardRiskPresentation({ strategy: 'cash_secured_put', risk_reward: 0.47, card_blocked: true }), { label: 'R:R', success: false })
eq('open credit at the old chip threshold can emphasize', rewardRiskPresentation({ strategy: 'covered_call', risk_reward: 0.3 }), { label: 'R:R', success: true })

const blockedButtons = sanitizeActionButtons({ card_blocked: true, action_buttons: [{ action: 'hold', label: 'Pass' }] } as never)
eq('blocked hold button says Skip', blockedButtons.find(b => b.action === 'hold')?.label, 'Skip')
const remapped = sanitizeActionButtons({ action_buttons: [{ action: 'hold', label: 'Pass' }, { action: 'review_chain', label: 'View Chain' }] } as never)
eq('server Pass label is remapped', remapped.find(b => b.action === 'hold')?.label, 'Skip')
ok('isCardBlocked still sees enterprise blocks', isCardBlocked(blockedThesis as never))

if (failed) throw new Error(`optionsDeskTruth: ${failed} failed`)
console.log('optionsDeskTruth ok')
