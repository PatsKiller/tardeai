// The v04 top bar: the portfolio scope control and the two book values v04 draws beside it.
//
// One read serves both the page and this bar (snapshot.tsx): Portfolio › Holdings publishes what it read, and this
// bar renders the SAME book under the SAME scope. The bar never fetches — `/api/v2/portfolio/holdings` is a heavy
// reader the shell may not originate (`HeavyReaderFromShell`) — so on any other route it says the book is not read
// here, rather than showing a stale number or an UNKNOWN with no reason. That is enforced by route as well as by
// snapshot state (`bookView.barStatus`): a snapshot left over from another route is not shown, even before the
// provider withdraws it on unmount.
//
// Each value states its binding, because the binding is what a reviewer can check:
//   * BOUND — the served field and its clock are named under the value;
//   * not read on this page / the read failed — a structural state, stated, never a number;
//   * a single-account scope — "not served per account": the read serves book-level measures only, and rows are
//     never summed to stand in for a per-account total (scope.ts).
//
// Deliberate deviations from the reference's markup, each because the label would otherwise misstate the data:
//   * the second value is labelled "Estimated price move", not "Regular-session move": the served measure is
//     `price_move_estimate` (sum of stored per-position day changes) and the wire declares the day-change clock
//     UNKNOWN (`clock_provenance.day_pnl`), so nothing on this read supports "regular-session";
//   * a signed CHANGE is coloured by direction (operator visual-semantic route 2026-11-15T1555Z): loss red,
//     gain green, and unknown/stale stays NEUTRAL — an UNKNOWN is never painted as a direction the wire did
//     not serve. A STOCK amount (Account value) carries no direction and is never coloured. Colour is never
//     the only carrier: the sign and the "measured, not verified" caption say the same thing in text.
import type { BookMeasure, HoldingsBook } from './contract'
import { barStatus } from './bookView'
import type { BarStatus } from './bookView'
import { money, moneyTone, notCurrent, toneClass } from './format'
import type { Scope } from './scope'
import { scopeOptions, scopedMeasure } from './scope'
import { useBookSnapshot } from './snapshot'
import { useLocation } from 'react-router-dom'
import './semantic.css'

interface ValueSpec {
  id: BookMeasure['id']
  label: string
  /** The field path and clock, for the tooltip — the trace a reviewer reads. */
  field: string
  /** True only for a value whose meaning is a CHANGE (a signed move). A stock amount is never coloured. */
  signed?: boolean
}

const VALUES: ValueSpec[] = [
  { id: 'account_value', label: 'Account value', field: 'data.measures.measures.account_value.value · clock data.measures.measures.account_value.as_of' },
  { id: 'price_move_estimate', label: 'Estimated price move', signed: true, field: 'data.measures.measures.price_move_estimate.value · clock data.measures.measures.price_move_estimate.as_of · day-change clock data.clock_provenance.day_pnl reports UNKNOWN' },
]

const NOT_READ = 'The holdings reader is heavy; the shell may not originate it. Open Portfolio › Holdings to read the book.'
const PER_ACCOUNT =
  'Book-level measure: this read serves no per-account split, and the page never sums rows to stand in for one.'

function Value({ spec, book, scope, status }: { spec: ValueSpec; book: HoldingsBook | null; scope: Scope; status: BarStatus }) {
  if (status.kind !== 'book' || book === null) {
    const detail = status.kind === 'not-read' ? 'not read on this page' : status.kind === 'loading' ? 'reading the book' : 'the read failed'
    const title = status.kind === 'not-read' ? NOT_READ : status.kind === 'loading' ? 'The Holdings page is reading the book; this bar shows what it publishes.' : status.kind === 'error' ? status.reason : ''
    return (
      <div title={title}>
        <span className="muted">{spec.label}</span>
        <strong>Unknown</strong>
        <small className="muted">{detail}</small>
      </div>
    )
  }
  const m = scopedMeasure(book, spec.id, scope)
  if (!m.available) {
    return (
      <div title={`${PER_ACCOUNT} (${m.reason.trim()})`}>
        <span className="muted">{spec.label}</span>
        <strong>Unknown</strong>
        <small className="muted">{m.reason}</small>
      </div>
    )
  }
  const measure = m.measure
  const clock = measure?.asOf ?? 'clock not served'
  const verified = measure?.verified === true
  // A signed CHANGE from a current read carries a direction; from a read the page calls last-good it keeps
  // neutral ink, because the move is not current (the same verdict the page prints under the session strip).
  const tone = spec.signed && !notCurrent(book.freshness) ? moneyTone(m.valueUsd) : 'flat'
  return (
    <div title={`${spec.field} · ${verified ? 'verified' : 'measured, not verified'}`}>
      <span className="muted">{spec.label}</span>
      <strong className={toneClass(tone) || undefined}>{money(m.valueUsd)}</strong>
      <small className="muted">
        {clock} · {verified ? 'verified' : 'measured, not verified'}
      </small>
    </div>
  )
}

export function PortfolioTopBar() {
  const { props, scope, setScope } = useBookSnapshot()
  const { pathname } = useLocation()
  // Route-aware as well as state-aware: a snapshot is only shown on the route whose page read it (bookView.ts).
  const status = barStatus(pathname, props)
  const book = status.kind === 'book' ? (props?.book ?? null) : null
  return (
    <div className="scope">
      <button className="mobile-menu quiet" aria-label="Open navigation" onClick={() => document.body.classList.toggle('menu-open')}>
        ☰
      </button>
      <label>
        <span className="mini-label">Portfolio scope</span>
        <br />
        {book === null ? (
          <select id="account" aria-label="Portfolio account scope" disabled value="ALL" title={NOT_READ}>
            <option value="ALL">All accounts · not read here</option>
          </select>
        ) : (
          <select id="account" aria-label="Portfolio account scope" value={scope} onChange={e => setScope(e.target.value)}>
            {scopeOptions(book).map(o => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </select>
        )}
      </label>
      <div className="top-values">
        {VALUES.map(v => (
          <Value key={v.id} spec={v} book={book} scope={scope} status={status} />
        ))}
      </div>
    </div>
  )
}
