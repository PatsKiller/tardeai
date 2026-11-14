// LQ-20261107-2993 · completion-matrix W-04: the Watch v002 sub-nav model. Every designed tab must reach its OWN v002
// view — after the lead's 00:47 ET ruling, no tab may point at the classic hub at all ("in-page nested views"). Each
// destination must resolve back to itself, so the tab the router marks current is the tab the link goes to.
//   node --experimental-strip-types src/lib/watchNav.test.ts
import { WATCH_NAV, WATCH_NAV_V002_KEYS, watchNavCurrent, type WatchNavKey } from './watchNav.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}
const by = (k: WatchNavKey) => WATCH_NAV.find(i => i.key === k)!

console.log('watchNav destinations')
check('nine destinations, unique keys', WATCH_NAV.length === 9 && new Set(WATCH_NAV.map(i => i.key)).size === 9)
check('the nine v002 tabs are exactly the nav', WATCH_NAV_V002_KEYS.length === 9 &&
  WATCH_NAV.map(i => i.key).join(',') === WATCH_NAV_V002_KEYS.join(','))
check('NO destination points at the classic hub', WATCH_NAV.every(i => !i.to.startsWith('/watch-classic')))
check('every destination is one of the three v002 routes', WATCH_NAV.every(i => /^\/(watch|watch-lists|watch-setups)(\?|$)/.test(i.to)))
check('there is no classic-only item left', !('classic' in WATCH_NAV[0]) || WATCH_NAV.every(i => !(i as any).classic))
check('Pullback/MACD is an in-page v002 tab', by('pullback').to === '/watch-setups?tab=pullback' && !(by('pullback') as any).classic)
check('there is no "More" escape tab', !WATCH_NAV.some(i => i.key === ('more' as WatchNavKey)))
check('labels are the designed names', ['Overview', 'My List', 'Suggestions', 'Prospects', 'Setups', 'Sectors', 'Discover', 'Alerts', 'Pullback/MACD'].every(l => WATCH_NAV.some(i => i.label === l)))

console.log('watchNavCurrent')
check('/watch is Overview', watchNavCurrent('/watch') === 'overview')
check('/v3/watch (mount prefix) is Overview', watchNavCurrent('/v3/watch') === 'overview')
check('/watch-lists defaults to My List', watchNavCurrent('/watch-lists') === 'mine')
check('/watch-lists?list=suggests', watchNavCurrent('/watch-lists', '?list=suggests') === 'suggests')
check('/watch-lists?list=prospects', watchNavCurrent('/watch-lists', '?list=prospects') === 'prospects')
check('an unknown list is My List, not nothing', watchNavCurrent('/watch-lists', '?list=bogus') === 'mine')
check('/watch-setups defaults to Setups', watchNavCurrent('/watch-setups') === 'setups')
for (const t of ['sectors', 'discover', 'alerts', 'pullback'] as const) check(`/watch-setups?tab=${t}`, watchNavCurrent('/watch-setups', `?tab=${t}`) === t)
check('an unknown setups tab is Setups', watchNavCurrent('/watch-setups', '?tab=bogus') === 'setups')
check('the classic hub is not a v002 page: nothing is current', watchNavCurrent('/watch-classic') === null)
check('an old /watch-classic?tab=pullback-macd deep link marks nothing current', watchNavCurrent('/watch-classic', '?tab=pullback-macd') === null)
check('/watch/intelligence/AAPL is part of the surface, resolved as Overview', watchNavCurrent('/watch/intelligence/AAPL') === 'overview')
check('a trailing slash resolves the same way', watchNavCurrent('/watch-lists/', '?list=suggests') === 'suggests')

console.log('round trip: each destination resolves back to its own tab')
for (const item of WATCH_NAV) {
  const [path, q = ''] = item.to.split(/(?=\?)/)
  check(`${item.key}: ${item.to}`, watchNavCurrent(path, q) === item.key)
}

console.log(`\n${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
