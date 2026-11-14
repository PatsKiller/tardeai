/** Watch v002 surface navigation (LQ-20261107-2993 · completion-matrix W-04, owner cc-deepseek-3).
 *
 *  One list drives the sub-nav on all three v002 Watch pages, so a tab means the same thing everywhere. Every designed
 *  tab lands on its own **v002 view** — none of them is a link to the classic hub any more (lead 00:47 ET: "in-page
 *  nested views, no /watch-classic links"). Pullback/MACD is the fifth tab of the Setups page (`?tab=pullback`), which
 *  keeps the URL deep-linkable without a new route registration.
 *
 *  The classic hub stays reachable from the Overview header ("Classic Watch") and every old `/watch-classic?tab=…` URL
 *  still works; it is simply no longer the destination of any tab here.
 *
 *  Pure: no reads, no writes. The router decides which item is current.
 */

export type WatchNavKey =
  | 'overview' | 'mine' | 'suggests' | 'prospects' | 'setups' | 'sectors' | 'discover' | 'alerts' | 'pullback'

export interface WatchNavItem {
  key: WatchNavKey
  label: string
  /** Where the tab goes. Absolute path, plus the query when the destination is a tab of a v002 page. */
  to: string
}

export const WATCH_NAV: WatchNavItem[] = [
  { key: 'overview', label: 'Overview', to: '/watch' },
  { key: 'mine', label: 'My List', to: '/watch-lists?list=mine' },
  { key: 'suggests', label: 'Suggestions', to: '/watch-lists?list=suggests' },
  { key: 'prospects', label: 'Prospects', to: '/watch-lists?list=prospects' },
  { key: 'setups', label: 'Setups', to: '/watch-setups' },
  { key: 'sectors', label: 'Sectors', to: '/watch-setups?tab=sectors' },
  { key: 'discover', label: 'Discover', to: '/watch-setups?tab=discover' },
  { key: 'alerts', label: 'Alerts', to: '/watch-setups?tab=alerts' },
  { key: 'pullback', label: 'Pullback/MACD', to: '/watch-setups?tab=pullback' },
]

/** The v002 tabs: Overview plus the seven designed tabs. Each has a v002 view; a test asserts none is a classic link. */
export const WATCH_NAV_V002_KEYS: WatchNavKey[] = ['overview', 'mine', 'suggests', 'prospects', 'setups', 'sectors', 'discover', 'alerts', 'pullback']

const listsKey = (list: string | null): WatchNavKey =>
  (list === 'suggests' ? 'suggests' : list === 'prospects' ? 'prospects' : 'mine')
const setupsKey = (tab: string | null): WatchNavKey =>
  (tab === 'sectors' ? 'sectors' : tab === 'discover' ? 'discover' : tab === 'alerts' ? 'alerts' : tab === 'pullback' ? 'pullback' : 'setups')

/** Which sub-nav item the current location is, or null when the location is not a v002 page (the classic hub). Routes
 *  are matched by name; the /v3 mount prefix is a basename. */
export function watchNavCurrent(pathname: string, search = ''): WatchNavKey | null {
  const path = pathname.replace(/\/+$/, '')
  const qs = search && !search.startsWith('?') ? `?${search}` : search
  const q = new URLSearchParams(qs)
  if (/(^|\/)watch-classic$/.test(path)) return null
  if (/(^|\/)watch-lists$/.test(path)) return listsKey(q.get('list'))
  if (/(^|\/)watch-setups$/.test(path)) return setupsKey(q.get('tab'))
  if (/(^|\/)watch$/.test(path)) return 'overview'
  // /watch/intelligence/:symbol, /watch/discovery and the legacy gates are part of the Watch surface; Overview is the tab
  // a reader returns to, and none of the v002 destinations matches them.
  return /(^|\/)watch\//.test(path) ? 'overview' : null
}
