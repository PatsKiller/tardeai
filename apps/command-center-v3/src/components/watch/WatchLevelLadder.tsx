import { TOKENS, toneVars } from '../../lib/designTokens'
import { ladderGeometry } from '../../lib/watchRecordCardModel'

export default function WatchLevelLadder({ support, resistance, price, zone }: {
  support: number | null; resistance: number | null; price: number | null; zone: [number | null, number | null]
}) {
  const g = ladderGeometry(support, resistance, price, zone)
  const info = toneVars('info')
  return <div className="watch-card-ladder" aria-hidden="true" data-testid="watch-card-ladder" data-known={g ? '1' : '0'}>
    <span className="watch-card-track" style={{ background: TOKENS.border }} />
    {g?.zone && <span className="watch-card-zone-band" style={{ left: `${g.zone[0]}%`, width: `${g.zone[1] - g.zone[0]}%`, background: info.bg, border: `1px solid ${info.border}` }} />}
    {g?.price != null && <span className="watch-card-price-marker" style={{ left: `calc(${g.price}% - 1.5px)`, background: TOKENS.text[0] }} />}
  </div>
}
