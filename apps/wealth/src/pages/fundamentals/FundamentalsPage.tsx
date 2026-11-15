// Portfolio › Fundamentals — the reviewed Holdings preset, reused on its own nav page.
//
// Source of truth for this page is NOT a new reader: it is the same served book the Holdings page renders
// (`HoldingsLive` → `holdingsProps` → `adaptHoldings`), read once by `FundamentalsLive`, rendered through the
// approved `fundamentals` preset in `presets.ts`. Nothing here computes a value, applies a threshold, ranks,
// colours or judges: the cells are words about served fields.
//
// What the route fixes (LEAD-ROUTE-FUNDAMENTALS-NAV-WIRING-20261115T1613Z):
//   * the eight preset columns, and the same P/E, forward P/E and market-cap readings the preset shows;
//   * Peer TTM median and Evidence print `not wired — valuation-assessment@1`; no assessment status is derived
//     or displayed, on live data or on the synthetic fixture;
//   * market cap carries its provenance: the row's profile record source and clock (the only clock the row has);
//   * the page states what it is not: no peer median reader, no valuation assessment, no derived status.
//
// Scope: this page shows every served row. The shell's portfolio scope control is bound to the Holdings route
// (`bookView.isBookRoute`), so it is stated here rather than left to look like an active filter — a selection is
// never applied invisibly. Wiring the bar to this route is a change to files this route does not own.

import { useDrawer } from '../../components/Drawer'
import { Panel } from '../../components/primitives'
import type { HoldingsBook, HoldingsRow } from '../portfolio/contract'
import { detailHeading, detailSections } from '../portfolio/detail'
import { FIXTURE_BOOK } from '../portfolio/fixtures'
import { lastKnownSentence, notCurrent, servedFreshnessLine } from '../portfolio/format'
import { freshnessLine } from '../portfolio/HoldingsTable'
import { preset } from '../portfolio/presets'
import { FundamentalsTable } from './FundamentalsTable'
import { assessmentText, peerMedianText } from './evidence'

export interface FundamentalsPageProps {
  /** Fixture today; the live route always passes an explicit book, so a wiring mistake cannot fall through to it. */
  book?: HoldingsBook | null
  loading?: boolean
  error?: string | null
  /** What the read is NOT claiming (last good, not current, health unproven), set by `liveProps`. */
  notice?: string | null
  /** The read's own clock in ms. Unused for a derived value; kept for parity with the Holdings page props. */
  nowMs?: number | null
}

const SCOPE_NOTE =
  'The top bar’s portfolio scope control is bound to the Holdings route; it is not applied here. ' +
  'This page shows every row the read served.'

/** The row drawer: the same served fields the Holdings page's drawer shows, nothing recomputed. */
function DetailBody({ row }: { row: HoldingsRow }) {
  const { sections, unserved } = detailSections(row)
  return (
    <>
      {sections.map(s => (
        <div key={s.title}>
          <h3>{s.title}</h3>
          <dl>
            {s.fields.map(f => (
              <div key={f.label}>
                <dt>{f.label}</dt>
                <dd>
                  {f.value}
                  <br />
                  <small>{f.source}</small>
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
      {unserved.map(u => (
        <p key={u} className="small muted">
          {u}
        </p>
      ))}
    </>
  )
}

export function FundamentalsPage({ book = FIXTURE_BOOK, loading = false, error = null, notice = null }: FundamentalsPageProps) {
  const drawer = useDrawer()

  if (error !== null) {
    return (
      <section aria-label="Portfolio fundamentals">
        <div className="note bad" role="alert">
          <strong>Fundamentals could not be read.</strong> {error} No values are shown, because none were served.
        </div>
      </section>
    )
  }

  if (loading || book === null) {
    return (
      <section aria-label="Portfolio fundamentals" aria-busy={loading}>
        <p className="muted">{loading ? 'Reading the book…' : 'No book has been supplied.'}</p>
      </section>
    )
  }

  const active = preset('fundamentals')
  const rows = book.rows
  const accounts = new Set(book.rows.map(r => r.accountKey).filter(k => k !== '')).size

  const openRow = (row: HoldingsRow, origin?: HTMLElement) => {
    const h = detailHeading(row)
    drawer.open({ title: h.title, eyebrow: h.eyebrow, body: <DetailBody row={row} />, origin: origin ?? null })
  }

  const sourceText = book.source === 'FIXTURE' ? 'synthetic fixture' : 'served book'

  return (
    <section aria-label="Portfolio fundamentals">
      {book.source === 'FIXTURE' && (
        <div className="note" role="note">
          <strong>Fixture data.</strong> Every value on this page is synthetic and no live reader is bound.
          portfolio-holdings@2 is proposed, not approved for wiring.
        </div>
      )}

      {notice !== null && (
        <div className="note blue" role="status">
          <strong>Read status.</strong> {notice}
        </div>
      )}

      <div className="session">
        <div>
          <strong>{book.session.status === 'KNOWN' ? (book.session.phase ?? 'Session known') : 'Session UNKNOWN'}</strong>
          {' · '}
          {book.session.status === 'KNOWN'
            ? `last completed regular session ${book.session.latestOpenSession ?? 'not stated'}${
                book.session.source ? ` · source: ${book.session.source}` : ''
              }`
            : book.session.reason}
          <br />
          <span className="muted">
            {book.freshness.served === null
              ? freshnessLine(book.freshness.ageSeconds, book.freshness.staleAfterSeconds, book.freshness.stale)
              : servedFreshnessLine(book.freshness.served)} · Marks as of {book.asOf} ({book.asOfClock} clock)
          </span>
        </div>
      </div>

      <Panel
        title="Fundamentals workspace"
        sub={`${rows.length} rows · all accounts (${accounts}) · ${sourceText}`}
      >
        <p className="small muted">
          The approved Fundamentals preset over the same holdings read: price, trailing P/E, forward P/E, market
          cap and yield are served fields, printed as served. Peer TTM median prints “{peerMedianText()}” — no
          reader serves one on any route — and Evidence prints “{assessmentText()}” — no assessment status is
          derived, ranked or coloured here.
        </p>

        {rows.length === 0 ? (
          <p>
            <strong>No positions.</strong> {book.coverageNote}
          </p>
        ) : (
          <FundamentalsTable rows={rows} preset={active} onRowOpen={openRow} />
        )}

        <div className="table-foot">
          <span>
            Marks: {book.asOf} ({book.asOfClock} clock) · market cap provenance: each row’s profile record
            {' '}(source and record clock, under the cap) · USD · day change: no declared per-row clock
          </span>
          <span>Every P/E is a served provider multiple, not an assessment.</span>
        </div>
        <p className="small muted">{book.coverageNote}</p>
        <p className="small muted">{SCOPE_NOTE}</p>
      </Panel>

      {notCurrent(book.freshness) && (
        <div className="note bad" role="alert">
          <strong>Not current.</strong> {lastKnownSentence(book.freshness)}
        </div>
      )}

      <details>
        <summary>
          <b>How this page is wired</b> — source, reuse and the two cells that are not wired
        </summary>
        <ul>
          <li>
            One GET of the same reader the Holdings page uses (<code>/api/v2/portfolio/holdings</code>); the same
            adapter turns the envelope into this book. No second source, no derived column, no row arithmetic.
          </li>
          <li>
            Columns, headers, method note and limits are the approved preset’s own (<code>presets.ts</code>) — this
            page renders that preset, it does not restate it.
          </li>
          <li>
            Peer TTM median: “{peerMedianText()}”. Evidence: “{assessmentText()}”. Neither cell carries a status
            word, a cutoff, a ranking or a colour; the assessment contract is named, not approximated.
          </li>
          <li>
            Market cap is the served field (the wire is in millions, divided once for display). The provenance
            line under it is the row’s profile record — source and clock — because the row serves no
            market-cap-specific clock; that record clock is not a price clock.
          </li>
          <li>{SCOPE_NOTE}</li>
        </ul>
      </details>
    </section>
  )
}
