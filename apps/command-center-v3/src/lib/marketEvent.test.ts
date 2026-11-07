// Pure-logic tests for marketEvent.ts (WP5, spec §4.4/§4.6).
//   node --experimental-strip-types src/lib/marketEvent.test.ts
import { bannerModel, candidateSubline, fmtNum, fmtPctSigned, normalizeMarketEvent } from './marketEvent.ts'
import { SYNTHETIC_MARKET_EVENT as FX } from '../components/marketevent/marketEventFixture.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) { if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) } }

console.log('marketEvent')
const ev = normalizeMarketEvent(FX)!
check('normalizes the fixture', ev != null && ev.candidates.length === 3 && ev.accounts.length === 2)
check('wrong schema is rejected, not coerced', normalizeMarketEvent({ ...FX, schema: 'MarketEvent@v2' }) === null && normalizeMarketEvent(null) === null)
check('data-envelope body is unwrapped', normalizeMarketEvent({ data: FX })?.episode?.id === 'ME-SYN-1')
check('candidates sort by rank', normalizeMarketEvent({ ...FX, candidates: [...FX.candidates].reverse() })!.candidates[0].symbol === 'AAA')
check('missing numbers stay null, never 0', ev.candidates[1].beta_expected_drawdown_pct === null && ev.candidates[2].quality_score === null)
check('missing values print "not on file"', fmtNum(null) === 'not on file' && fmtPctSigned(null) === 'not on file')
check('negative pct uses a minus sign', fmtPctSigned(-23.4) === '−23.4%')

const b = bannerModel({ data: FX, loading: false, error: null })
check('open RED episode shows a danger banner', b.kind === 'event' && b.tone === 'danger' && b.stateLabel === 'RED' && b.detail === '3 candidates · 1 ready')
check('no episode -> hidden', bannerModel({ data: { ...FX, episode: null }, loading: false, error: null }).kind === 'hidden')
check('CLOSED episode -> hidden', bannerModel({ data: { ...FX, episode: { ...FX.episode, state: 'CLOSED' } }, loading: false, error: null }).kind === 'hidden')
check('STABILIZING -> warning', (bannerModel({ data: { ...FX, episode: { ...FX.episode, state: 'STABILIZING' } }, loading: false, error: null }) as any).tone === 'warning')
check('RECOVERING -> success', (bannerModel({ data: { ...FX, episode: { ...FX.episode, state: 'RECOVERING' } }, loading: false, error: null }) as any).tone === 'success')
const st = bannerModel({ data: { ...FX, stale: true }, loading: false, error: null }) as any
check('stale hides the count and says so', st.stale === true && st.detail.startsWith('stale') && !/candidate/.test(st.detail))
check('server error -> unavailable (not hidden)', bannerModel({ data: null, loading: false, error: 'HTTP 500' }).kind === 'unavailable')
check('bad body -> unavailable (not hidden)', bannerModel({ data: { schema: 'nope' }, loading: false, error: null }).kind === 'unavailable')
check('404 (route not deployed) -> hidden', bannerModel({ data: null, loading: false, error: 'HTTP 404' }).kind === 'hidden')
check('first load -> loading, renders nothing', bannerModel({ data: null, loading: true, error: null }).kind === 'loading')
check('fell-for-a-reason subline says never auto-READY', /never auto-READY/.test(candidateSubline(ev.candidates[2])))
check('subline omits missing fundamentals', candidateSubline({ ...ev.candidates[1], fwd_pe: null, quality_score: null, universe: null }) === 'no fundamentals on file')
check('plan is carried for READY, absent otherwise', ev.candidates[0].plan?.tranches.length === 3 && ev.candidates[1].plan === null)
check('invalid account label is not echoed as a number', normalizeMarketEvent({ ...FX, accounts: [{ deployable_usd: 1 }] })!.accounts[0].account_label === 'Account not on file')

console.log(`\n${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
