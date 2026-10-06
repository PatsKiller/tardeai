// node src/lib/optionsDeskTruth.test.ts
import { isCardBlocked, sanitizeActionButtons } from './optionsCardSemantics.ts'
import {
  armedDeskLine, armedOverviewLine, blockedRouteNote, coveredCallFunnelCounts, floorCallouts,
  funnelNameText, optionsDeskPersonLine, packageLeadIds, rewardRiskPresentation, packagePointer, isReviewQueueRow,
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
ok('person line counts blocked and thesis apart', line.startsWith('Review: 0 ready for investment review. 4 need research, data or block resolution.'))
ok('person line does not say refused or incomplete', !line.includes('refused or incomplete'))

eq('hedge ratio stays neutral above 0.3', rewardRiskPresentation({ strategy: 'protective_put', risk_reward: 33.48, enterprise: { blocks: [{ code: 'x' }] } }), { label: 'hedge ratio', success: false })
eq('blocked credit is not a green R:R', rewardRiskPresentation({ strategy: 'cash_secured_put', risk_reward: 0.47, card_blocked: true }), { label: 'R:R', success: false })
eq('open credit at the old chip threshold can emphasize', rewardRiskPresentation({ strategy: 'covered_call', risk_reward: 0.3 }), { label: 'R:R', success: true })

const blockedButtons = sanitizeActionButtons({ card_blocked: true, action_buttons: [{ action: 'hold', label: 'Pass' }] } as never)
eq('blocked hold button says Skip', blockedButtons.find(b => b.action === 'hold')?.label, 'Skip')
const remapped = sanitizeActionButtons({ action_buttons: [{ action: 'hold', label: 'Pass' }, { action: 'review_chain', label: 'View Chain' }] } as never)
eq('server Pass label is remapped', remapped.find(b => b.action === 'hold')?.label, 'Skip')
ok('isCardBlocked still sees enterprise blocks', isCardBlocked(blockedThesis as never))

eq('package table stays on the first card of a symbol', [...packageLeadIds([
  { id: 'a', symbol: 'SPCX', combined_exposure: { symbol: 'SPCX' } },
  { id: 'b', symbol: 'SPCX', combined_exposure: { symbol: 'SPCX' } },
  { id: 'c', symbol: 'XAR', combined_exposure: { symbol: 'XAR' } },
])], ['a', 'c'])
const armedNote = 'Live Schwab options path ARMED — use preflight + per-order 2FA before submit. Manual hedge — size to shares held.'
const blockedNote = blockedRouteNote(armedNote, true) || ''
ok('blocked route drops the submit invitation', !/before submit/i.test(blockedNote) && blockedNote.includes('not eligible'))
ok('blocked route keeps the hedge sizing note', blockedNote.includes('Manual hedge'))
eq('open route note is unchanged', blockedRouteNote(armedNote, false), armedNote)
eq('empty desk does not invite an order', armedDeskLine(true, 0), 'broker route open · no card on this page is eligible')
ok('overview with no eligible card does not say the book is ready', armedOverviewLine(true, 0).includes('No proposal on this desk is eligible'))
eq('wide quote names the 12% cap', floorCallouts({ strategy: 'cash_secured_put', legs_liquidity: [{ spread_pct: 40 }] }), ['Widest quote is 40.0% wide. The desk cap stays 12%.'])
eq('credit spread under 0.25 names the floor', floorCallouts({ strategy: 'credit_spread', risk_reward: 0.08 }), ['Reward/risk 0.08 is under the 0.25 credit-spread floor. The floor is unchanged.'])
eq('cash-secured put is not judged by the credit-spread floor', floorCallouts({ strategy: 'cash_secured_put', risk_reward: 0.08 }), [])
eq('spread text in a block is read', floorCallouts({ enterprise: { blocks: [{ reason: 'spread 63.6% > 12.0%' }] } })[0], 'Widest quote is 63.6% wide. The desk cap stays 12%.')

const pendingReview = { approvable: false, enterprise: { live_eligible: false }, review_workflow: { state: 'READY_FOR_REVIEW' } }
ok('pending CIO review is visible while execution stays blocked', isReviewQueueRow(pendingReview))
ok('review summary uses independent count', optionsDeskPersonLine([pendingReview], 0).includes('1 ready for investment review.'))
ok('same expiry is not reported as different', packagePointer('SPCX', ['2026-11-20']).includes('share one expiry'))
ok('different expiry is explicit', packagePointer('V', ['2026-10-30', '2026-11-20']).includes('Expiries differ'))
ok('unknown expiry stays unknown', packagePointer('X', []).includes('unavailable'))

if (failed) throw new Error(`optionsDeskTruth: ${failed} failed`)
console.log('optionsDeskTruth ok')
