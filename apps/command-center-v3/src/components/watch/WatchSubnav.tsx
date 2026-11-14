/** Watch v002 sub-nav (LQ-20261107-2993 · W-04). Rendered on the Overview, Lists and Setups pages so the Watch surface is
 *  one surface: every designed tab routes to its own v002 view, and no tab leaves for the classic hub (lead 00:47 ET).
 *  Watching/navigation only — it reads no API and writes nothing. */
import { Link, useLocation } from 'react-router-dom'
import { WATCH_NAV, watchNavCurrent } from '../../lib/watchNav'
import './WatchSubnav.css'

export default function WatchSubnav({ label = 'Watch sections' }: { label?: string }) {
  const loc = useLocation()
  const current = watchNavCurrent(loc.pathname, loc.search)
  return (
    <nav className="wv2-subnav" aria-label={label} data-testid="watch-subnav">
      {WATCH_NAV.map(item => item.key === current ? (
        <span key={item.key} className="wv2-tab" aria-current="page" data-testid={`watch-subnav-${item.key}`}>{item.label}</span>
      ) : (
        <Link key={item.key} className="wv2-tab" to={item.to} data-testid={`watch-subnav-${item.key}`}>{item.label}</Link>
      ))}
    </nav>
  )
}
