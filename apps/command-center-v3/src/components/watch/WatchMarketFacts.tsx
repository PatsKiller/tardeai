/** Stored source facts only; no fetch, freshness policy, level derivation or action. */
import type { WatchMarketFacts as Facts, WatchMarketField } from '../../lib/watchListsModel'

const missing: WatchMarketField = { value: null, as_of: null, source: null, source_label: 'Source unavailable',
  stale: null, freshness: 'MISSING', reason: 'Market evidence is unavailable for this record.' }

function amount(value: number | null): string {
  if (value == null || !Number.isFinite(value) || value <= 0) return '—'
  if (value >= 1) return `$${value.toFixed(2)}`
  const text = value.toLocaleString('en-US', { useGrouping: false, minimumFractionDigits: 2, maximumFractionDigits: 20 })
  return `$${Number(text) === 0 ? value.toExponential(3) : text}`
}

function observed(value: string | null): string {
  if (!value) return 'As of —'
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `As of ${value} · closed session`
  const at = new Date(value)
  if (Number.isNaN(at.getTime())) return 'Observation time unknown'
  return `As of ${new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric', month: 'short',
    day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short' }).format(at)}`
}

function Field({ name, field, retained }: { name: string; field: WatchMarketField; retained: boolean }) {
  const state = field.value == null ? 'Missing' : retained ? 'Last snapshot' : field.freshness === 'UNKNOWN' ? 'Time / freshness unknown'
    : field.stale ? 'Stale' : 'Current'
  return <div className="watch-market-field" data-testid={`watch-market-${name.toLowerCase()}`}>
    <div className="watch-market-value"><b>{name}</b><span>{amount(field.value)}</span>
      <span className="watch-market-state" data-state={state}>{state}</span></div>
    <div>{field.source_label}{field.source ? ` · ${field.source}` : ''}</div>
    <div>{observed(field.as_of)}</div>
    {field.reason && <div className="watch-market-reason">{field.reason}</div>}
    {field.compatibility === 'UNKNOWN' && field.value != null && <div>Nearest relation unknown</div>}
  </div>
}

export default function WatchMarketFacts({ facts, retained = false }: { facts?: Facts | null; retained?: boolean }) {
  return <section className="watch-my-list-market-facts" data-testid="watch-market-facts" aria-label="Stored market facts">
    <Field name="Price" field={facts?.price || missing} retained={retained} />
    <Field name="Support" field={facts?.support || missing} retained={retained} />
    <Field name="Resistance" field={facts?.resistance || missing} retained={retained} />
  </section>
}
