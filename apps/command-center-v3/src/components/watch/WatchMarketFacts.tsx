/** Stored source facts only; no fetch, policy change, level derivation, record write or action. */
import type { WatchMarketFacts as Facts, WatchMarketField } from '../../lib/watchListsModel'
import { levelFootnoteTime, levelSourceTag, levelText, marketAmount, marketObserved, pricePresentation } from '../../lib/watchMarketFactsPresentation'
import { FONT, TOKENS, TYPE, numStyle } from '../../lib/designTokens'
import { levelPercent } from '../../lib/watchRecordCardModel'
import WatchLevelLadder from './WatchLevelLadder'
import type { ReactNode } from 'react'

const missing: WatchMarketField = { value: null, as_of: null, source: null, source_label: 'Source unavailable',
  stale: null, freshness: 'MISSING', reason: 'Market evidence is unavailable for this record.' }

function detail(field: WatchMarketField): string {
  return [field.source_label, field.source, marketObserved(field.as_of), field.as_of_basis, field.reason,
    field.broken_reference ? `Broken reference: ${field.broken_reference.source_label} · ${field.broken_reference.source} · ${marketObserved(field.broken_reference.as_of)}` : null]
    .filter(Boolean).join(' · ')
}

function shortContext(price: WatchMarketField, qualification: string | null): string {
  const at = price.as_of && /T.*(?:Z|[+-]\d\d:\d\d)$/.test(price.as_of) ? new Date(price.as_of) : null
  const clock = at && Number.isFinite(at.getTime()) ? new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(at) + ' ET' : null
  const kind = qualification?.replace(' observation', '').toLowerCase()
  return kind || clock ? ` · ${[kind, clock].filter(Boolean).join(' ')}` : ''
}

export default function WatchMarketFacts({ facts, retained = false, now = new Date(), zone = [null, null], ownership, testId = 'watch-market-facts' }: {
  facts?: Facts | null; retained?: boolean; now?: Date; zone?: [number | null, number | null]; ownership?: ReactNode; testId?: string
}) {
  const price = facts?.price || missing
  const support = facts?.support || missing
  const resistance = facts?.resistance || missing
  const display = pricePresentation(price, now, retained)
  const levels = [support, resistance]
  const relationUnknown = levels.some(field => field.value != null && field.compatibility === 'UNKNOWN')
  const source = Array.from(new Set(levels.filter(f => f.value != null).map(levelSourceTag))).join(' / ') || 'No reference'
  const footnoteTime = levelFootnoteTime(levels)
  const zoneText = zone[0] != null && zone[1] != null ? `${marketAmount(zone[0])}–${marketAmount(zone[1])}` : '—'
  const renderLevel = (kind: 'support' | 'resistance') => {
    const field = kind === 'support' ? support : resistance
    const value = field.broken_reference ? null : field.value
    return <div data-testid={`watch-market-${kind}`} title={detail(field)}>
      <div style={{ color: TOKENS.text[2], fontSize: TYPE.sm }}>{kind === 'support' ? 'Support' : 'Resistance'}</div>
      <div style={{ ...numStyle, fontSize: TYPE.base, color: value == null ? TOKENS.text[2] : kind === 'support' ? TOKENS.success : TOKENS.danger }}>{marketAmount(value)}</div>
      {field.broken_reference && <div style={{ fontSize: TYPE.xs, color: TOKENS.text[2] }}>{levelText(kind, field)}</div>}
      {!field.broken_reference && value == null && <div style={{ fontSize: TYPE.xs, color: TOKENS.text[2] }}>No reference</div>}
      <div className="watch-card-level-percent" style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>{levelPercent(value, price.value)}</div>
    </div>
  }
  return <section className="watch-card-market-facts" data-testid={testId} aria-label="Stored market facts" style={{ minWidth: 0, fontSize: TYPE.base }}>
    <div className="watch-market-field watch-market-price" data-testid="watch-market-price" title={detail(price)}>
      <div className="watch-market-value" style={{ justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
        <span className="watch-card-desktop-price" style={{ ...numStyle, fontSize: TYPE.lg, fontWeight: 600, color: TOKENS.text[0] }}>{marketAmount(price.value)}</span>
        <span className="watch-market-state" style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}><span data-state={display.state}>{display.state}</span>{shortContext(price, display.qualification)}</span>
      </div>
    </div>
    <WatchLevelLadder support={support.broken_reference ? null : support.value} resistance={resistance.broken_reference ? null : resistance.value} price={price.value} zone={zone} />
    <div className="watch-card-level-strip">
      {renderLevel('support')}
      <div className="watch-card-desktop-zone"><div style={{ color: TOKENS.text[2], fontSize: TYPE.sm }}>Zone</div><div style={{ ...numStyle, color: TOKENS.info }}>{zoneText}</div></div>
      <div className="watch-card-phone-price"><div style={{ color: TOKENS.text[2], fontSize: TYPE.sm }}>Price</div><div style={{ ...numStyle, fontWeight: 600 }}>{marketAmount(price.value)}</div></div>
      {renderLevel('resistance')}
    </div>
    <div className="watch-card-phone-zone" style={{ color: TOKENS.text[2], fontSize: TYPE.base }}>Zone <span style={{ fontFamily: FONT.mono, color: TOKENS.info }}>{zoneText}</span>{ownership && <> · {ownership}</>}</div>
    <div className="watch-market-level-notes" style={{ fontSize: TYPE.xs, color: TOKENS.text[2], marginTop: 8 }}>
      levels: {source} · {footnoteTime === 'time unknown' ? <span data-testid="watch-market-time-unknown">time unknown</span> : footnoteTime}
      {relationUnknown && <span>Price unavailable; nearest relation unknown</span>}
      {retained && <span>Last snapshot</span>}
    </div>
    <details className="watch-market-details"><summary>Source details</summary>
      <div className="watch-price-provenance" data-testid="watch-price-provenance"><span title={detail(price)}>Price: {price.source_label} · {price.source}</span> · <time dateTime={price.as_of || undefined}>{marketObserved(price.as_of)}</time>{display.qualification && <> · {display.qualification}</>}{price.reason && <> · {price.reason}</>}</div><div>Support: {detail(support)}</div><div>Resistance: {detail(resistance)}</div>
    </details>
  </section>
}
