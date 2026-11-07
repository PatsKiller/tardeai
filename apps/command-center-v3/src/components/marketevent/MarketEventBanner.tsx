import { Link } from 'react-router-dom'
import { RADIUS, TOKENS, TYPE, chipStyle, toneVars } from '../../lib/designTokens'
import { useMarketEvent } from '../../hooks/useMarketEvent'

export const EVENT_HREF = '/portfolio/re-entry?tab=event'

/** Home banner (spec §4.6). Hidden while there is no open episode; an API failure reads "unavailable", never "all clear". */
export default function MarketEventBanner() {
  const { banner } = useMarketEvent()
  if (banner.kind === 'hidden' || banner.kind === 'loading') return null
  if (banner.kind === 'unavailable') {
    return <div data-testid="market-event-banner" data-kind="unavailable" role="status" style={{ minHeight: 44, display: 'flex', alignItems: 'center', padding: '8px 12px', border: `1px dashed ${TOKENS.border}`, borderRadius: RADIUS.lg, color: TOKENS.text[2], fontSize: TYPE.base }}>{banner.text}</div>
  }
  const t = toneVars(banner.tone)
  return (
    <Link to={EVENT_HREF} data-testid="market-event-banner" data-kind="event" data-stale={banner.stale ? 'true' : 'false'}
      style={{ display: 'block', minHeight: 44, padding: '10px 12px', background: t.bg, border: `1px solid ${t.color}`, borderRadius: RADIUS.lg, color: TOKENS.text[0], textDecoration: 'none', fontSize: TYPE.md }}>
      <span style={{ color: t.color, fontWeight: 700 }}>Market event</span> · {banner.headline} · <span style={chipStyle(banner.tone)}>{banner.stateLabel}</span>
      <span style={{ display: 'block', marginTop: 2, color: TOKENS.text[1], fontSize: TYPE.base }}>{banner.detail}</span>
    </Link>
  )
}
