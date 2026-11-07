import { Link, Navigate, useLocation } from 'react-router-dom'
import DeskBoard from '../../components/DeskBoard'
import MarketEventSection from '../../components/marketevent/MarketEventSection'
import { useMarketEvent } from '../../hooks/useMarketEvent'
import { RADIUS, TOKENS, TYPE } from '../../lib/designTokens'

/** Approved board 1 (desks redesign 2026-10-24). Read-only; classic page stays at /portfolio/re-entry/classic. */
export const REENTRY_TABS = [
  { id: 'ready-now', label: 'Ready now' },
  { id: 'exits-review', label: 'Exits review' },
  { id: 'resistance-levels', label: 'Resistance & levels' },
  { id: 'analyst-evidence', label: 'Analyst evidence' },
] as const

/** Symbol-focused deep links (?symbol=, ?classify=, ?lane=) keep opening the classic workbench that reads them. */
const CLASSIC_PARAMS = ['symbol', 'classify', 'lane']

/** WP5: the Event section is reached at ?tab=event (the Home banner links here). The four desk tabs are unchanged. */
export const EVENT_TAB = 'event'

/** A one-line pointer to the Event section, shown on the desk only while an episode is open. */
function EventPointer() {
  const { banner } = useMarketEvent()
  if (banner.kind !== 'event') return null
  return <Link to={`/portfolio/re-entry?tab=${EVENT_TAB}`} data-testid="reentry-event-pointer"
    style={{ display: 'flex', alignItems: 'center', minHeight: 44, padding: '8px 12px', marginBottom: 10, border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.lg, background: TOKENS.bg[1], color: TOKENS.text[0], textDecoration: 'none', fontSize: TYPE.base }}>
    Market event open · {banner.headline} · {banner.detail} →</Link>
}

export default function ReEntryDesk() {
  const location = useLocation()
  const params = new URLSearchParams(location.search)
  if (CLASSIC_PARAMS.some(key => params.has(key))) return <Navigate to={`/portfolio/re-entry/classic${location.search}${location.hash}`} replace />
  if (params.get('tab') === EVENT_TAB) {
    return <div data-testid="reentry-event" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <h1 style={{ margin: 0, fontSize: TYPE.lg }}>Re-Entry · Event</h1>
      <MarketEventSection />
    </div>
  }
  return <>
    <EventPointer />
    <DeskBoard desk="reentry" testId="reentry-desk" title="Re-Entry"
      purpose="Names you sold: is it time to get back in, and at what level?"
      tabs={REENTRY_TABS} tabAliases={{ ready: 'ready-now', exits: 'exits-review', resistance: 'resistance-levels', analyst: 'analyst-evidence' }}
      classicHref="/portfolio/re-entry/classic" />
  </>
}
