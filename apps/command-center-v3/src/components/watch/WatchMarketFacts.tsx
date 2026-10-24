/** Stored source facts only; no fetch, policy change, level derivation, record write or action. */
import type { WatchMarketFacts as Facts, WatchMarketField } from '../../lib/watchListsModel'
import { levelSourceTag, levelText, levelTimeUnknown, marketAmount, marketObserved, pricePresentation } from '../../lib/watchMarketFactsPresentation'

const missing: WatchMarketField = { value: null, as_of: null, source: null, source_label: 'Source unavailable',
  stale: null, freshness: 'MISSING', reason: 'Market evidence is unavailable for this record.' }

function detail(field: WatchMarketField): string {
  return [field.source_label, field.source, marketObserved(field.as_of), field.as_of_basis, field.reason,
    field.broken_reference ? `Broken reference: ${field.broken_reference.source_label} · ${field.broken_reference.source} · ${marketObserved(field.broken_reference.as_of)}` : null]
    .filter(Boolean).join(' · ')
}

export default function WatchMarketFacts({ facts, retained = false, now = new Date() }: { facts?: Facts | null; retained?: boolean; now?: Date }) {
  const price = facts?.price || missing
  const support = facts?.support || missing
  const resistance = facts?.resistance || missing
  const display = pricePresentation(price, now, retained)
  const levels = [support, resistance]
  const relationUnknown = levels.some(field => field.value != null && field.compatibility === 'UNKNOWN')
  return <section className="watch-my-list-market-facts" data-testid="watch-market-facts" aria-label="Stored market facts">
    <div className="watch-market-field watch-market-price" data-testid="watch-market-price">
      <div className="watch-market-value"><b>Price</b><span>{marketAmount(price.value)}</span>
        <span className="watch-market-state" data-state={display.state}>{display.state}</span></div>
      <div className="watch-market-price-meta"><span className="watch-market-source" title={detail(price)}>{price.source_label}</span>
        <time dateTime={price.as_of || undefined}>{marketObserved(price.as_of)}</time></div>
      {display.qualification && <div className="watch-market-qualification">{display.qualification}</div>}
      {!display.state.startsWith('Closed session') && price.reason && <div className="watch-market-reason">{price.reason}</div>}
    </div>
    <div className="watch-market-levels">
      {(['support', 'resistance'] as const).map(kind => {
        const field = kind === 'support' ? support : resistance
        return <div className="watch-market-field watch-market-level" data-testid={`watch-market-${kind}`} key={kind}>
          <b>{kind === 'support' ? 'Support' : 'Resistance'}</b><span>{levelText(kind, field)}</span>
          <span className="watch-market-source" title={detail(field)}>{levelSourceTag(field)}</span>
        </div>
      })}
      <div className="watch-market-level-notes">
        {levelTimeUnknown(levels) && <span data-testid="watch-market-time-unknown">time unknown</span>}
        {relationUnknown && <span>Price unavailable; nearest relation unknown</span>}
        {retained && <span>Last snapshot</span>}
      </div>
    </div>
    <details className="watch-market-details"><summary>Source details</summary>
      <div>Price: {detail(price)}</div><div>Support: {detail(support)}</div><div>Resistance: {detail(resistance)}</div>
    </details>
  </section>
}
