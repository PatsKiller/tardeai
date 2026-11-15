// Portfolio › Fundamentals — the reviewed Holdings preset, reused on its own nav page.
//
// Source of truth for this page is NOT a new reader: it is the same served book the Holdings page renders
// (`HoldingsLive` → `holdingsProps` → `adaptHoldings`), read once by `FundamentalsLive`, rendered through the
// approved `fundamentals` preset in `presets.ts`. Nothing here computes a value, applies a threshold, ranks,
// colours or judges: the cells are words about served fields.
//
// What the route fixes (LEAD-ROUTE-FUNDAMENTALS-NAV-WIRING-20261115T1613Z, then G1/G2 in
// LEAD-ASSIGN-FUNDAMENTALS-COMPACT-SCOPE-20261115T1919Z):
//   * the eight preset columns, and the same P/E, forward P/E and market-cap readings the preset shows;
//   * Peer TTM median and Evidence print a short truthful `Not available`; the contract that would serve them
//     (valuation-assessment@1) is named in the row drawer's evidence and in this page's disclosure, not spelled
//     out in every cell. No assessment status is derived for, or printed into, those two columns;
//   * market cap carries its provenance: the row's profile record source and clock (the only clock the row has);
//   * one compact evidence line above the table, and a disclosure that carries the technical text — the served
//     numbers, the truthful unknowns and the peer/valuation gaps are unchanged.
//
// Scope (G1): the account control is the SHELL's one selection (`useBookScope`); sector and search are filters
// over these same rows, applied by the approved selector (`filter.ts` → `derivePortfolioView`). No second book,
// no second read: `filterFundamentals` only decides which served rows remain, and returns the original row
// objects. The workspace header states the filter, so the page never looks like an unfiltered book.

import { useEffect, useMemo, useState } from 'react'
import { useDrawer } from '../../components/Drawer'
import { Panel } from '../../components/primitives'
import type { HoldingsBook, HoldingsRow } from '../portfolio/contract'
import { detailHeading, detailSections } from '../portfolio/detail'
import { FIXTURE_BOOK } from '../portfolio/fixtures'
import { lastKnownSentence, notCurrent, servedFreshnessLine } from '../portfolio/format'
import { freshnessLine } from '../portfolio/HoldingsTable'
import { preset } from '../portfolio/presets'
import { displaySectorKey, freshnessCopy, snapshotFor } from '../portfolio/analyticsAdapter'
import { scopeLabel } from '../portfolio/scope'
import { useBookScope } from '../portfolio/snapshot'
import { FundamentalsTable } from './FundamentalsTable'
import {
  MARKET_CAP_PROVENANCE_NOTE,
  assessmentNote,
  assessmentText,
  evidenceCopy,
  peerMedianNote,
  peerMedianText,
} from './evidence'
import { EMPTY_NO_MATCH, filterFundamentals } from './filter'
import type { FundamentalsView } from './filter'
import '../portfolio/analytics/analytics.css'

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

/** One sentence, where the filter is: the account control IS the shell's selection, not a page-local copy. */
const SCOPE_NOTE =
  'The account control is the top bar’s portfolio scope — this page renders no second one; sector and search ' +
  'filter these same served rows. No second read and no second book: every value below is a field of the one ' +
  'book this page read.'

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

export function FundamentalsPage({
  book = FIXTURE_BOOK,
  loading = false,
  error = null,
  notice = null,
}: FundamentalsPageProps) {
  const drawer = useDrawer()
  const { scope } = useBookScope()
  const [sector, setSector] = useState('')
  const [query, setQuery] = useState('')
  const [announcement, setAnnouncement] = useState('')

  // Every hook above the early returns, unconditionally: the view is computed only for a book that exists.
  const filtered = useMemo<FundamentalsView | null>(
    () => (book === null ? null : filterFundamentals(book, { scope, sector, query })),
    [book, scope, sector, query],
  )

  // A sector that the selected account no longer contains is reset AND announced — the population must not
  // change silently (the Holdings page's rule, kept here because this page has the same filter).
  const sectorOptions = filtered?.sectorOptions ?? null
  useEffect(() => {
    if (sectorOptions === null || sector === '') return
    if (!sectorOptions.includes(sector)) {
      setSector('')
      setAnnouncement(`Sector reset because ${displaySectorKey(sector)} is not present in this account.`)
    }
  }, [sectorOptions, sector])

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
  const view: FundamentalsView = filtered ?? filterFundamentals(book, { scope, sector, query })
  const rows = view.rows
  const snapshot = snapshotFor(book)
  const fresh = freshnessCopy(snapshot)
  const readState = evidenceCopy(notice, snapshot, fresh.line)
  const filterText = `${scopeLabel(book, scope)}${sector !== '' ? ` · ${displaySectorKey(sector)}` : ''}${
    query.trim() !== '' ? ` · matching “${query.trim()}”` : ''
  }`

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

      {/* G2: the session strip is ONE line of served state. The session's own reason and the freshness sentence
          are facts about this read, not decoration — they move to the disclosure below, where they stay reachable,
          instead of taking four lines above the table on a phone. */}
      <div className="session">
        <div>
          <strong>{book.session.status === 'KNOWN' ? (book.session.phase ?? 'Session known') : 'Session UNKNOWN'}</strong>
          {' · '}
          <span className="muted">
            Marks as of {book.asOf} ({book.asOfClock} clock)
          </span>
        </div>
      </div>

      {/* G1/G2: the shared filterbar, and ONE compact evidence line. The long producer text is behind the
          disclosure below, not repeated here. */}
      <div className="wm-pa">
        <div className="wm-pa-filterbar">
          {/* The account scope is the SHELL's one control (the top bar's #account, live on this route because
              bookView.isBookRoute admits it). The page states the selection and does not render a second one. */}
          <span className="wm-pa-scope">
            Account: <b>{scopeLabel(book, scope)}</b> <small className="muted">— chosen in the top bar</small>
          </span>
          <label>
            Sector
            <select
              value={sector}
              onChange={e => {
                setSector(e.target.value)
                setAnnouncement('') // the reader's own next action withdraws the previous announcement
              }}
            >
              <option value="">All sectors</option>
              {view.sectorOptions.map(s => (
                <option key={s} value={s}>
                  {displaySectorKey(s)}
                </option>
              ))}
            </select>
          </label>
          <label className="wm-pa-search">
            Find a holding
            <input
              type="search"
              value={query}
              onChange={e => {
                setQuery(e.target.value)
                setAnnouncement('')
              }}
              placeholder="Symbol, name or account"
              autoComplete="off"
            />
          </label>
          <button
            type="button"
            onClick={() => {
              setSector('')
              setQuery('')
              setAnnouncement('Filters reset: all sectors. The account scope is the top bar’s.')
            }}
          >
            Reset filters
          </button>
        </div>
        <div className="wm-pa-status" aria-live="polite">
          <span>
            {rows.length} of {view.bookRows} rows · {filterText}
          </span>
          {readState.line !== null && <span className="wm-pa-warning">{readState.line}</span>}
          {announcement !== '' && <span>· {announcement}</span>}
        </div>
      </div>

      <Panel title="Fundamentals workspace" sub={`${rows.length} of ${book.rows.length} rows · ${filterText} · ${sourceText}`}>
        {book.rows.length === 0 ? (
          <p>
            <strong>No positions.</strong> {book.coverageNote}
          </p>
        ) : rows.length === 0 ? (
          <p>
            <strong>{EMPTY_NO_MATCH}</strong>
          </p>
        ) : view.refused !== null ? (
          <p>
            <strong>This view cannot be filtered as asked.</strong> {view.refused} No row is printed over a
            selection the page cannot keep.
          </p>
        ) : (
          <FundamentalsTable rows={rows} preset={active} onRowOpen={openRow} />
        )}

        <div className="table-foot">
          <span>
            Marks: {book.asOf} ({book.asOfClock} clock) · market cap provenance: each row’s profile record
            {' '}(source and record clock, under the cap) · USD · day change: no declared per-row clock
          </span>
          <span>
            A P/E is a served provider multiple where the read serves one; where it serves none the cell prints
            the row’s own valuation status instead — a fund’s fund metric, or a last-known value marked
            Unassessed — and the hover names which.
          </span>
        </div>
        <p className="small muted">{book.coverageNote}</p>
      </Panel>

      <details>
        <summary>
          <b>How this page is wired</b> — source, scope, this read’s session and status, and the two gaps
        </summary>
        <ul>
          <li>
            One GET of the same reader the Holdings page uses (<code>/api/v2/portfolio/holdings</code>); the same
            adapter turns the envelope into this book. No second source, no derived column, no row arithmetic.
          </li>
          <li>
            <b>This read’s session.</b>{' '}
            {book.session.status === 'KNOWN'
              ? `last completed regular session ${book.session.latestOpenSession ?? 'not stated'}${
                  book.session.source ? ` · source: ${book.session.source}` : ''
                }`
              : book.session.reason}{' '}
            <b>Freshness.</b>{' '}
            {book.freshness.served === null
              ? freshnessLine(book.freshness.ageSeconds, book.freshness.staleAfterSeconds, book.freshness.stale)
              : servedFreshnessLine(book.freshness.served)}
          </li>
          <li>{SCOPE_NOTE}</li>
          <li>
            Columns, headers, method note and limits are the approved preset’s own (<code>presets.ts</code>) — this
            page renders that preset, it does not restate it. On this page the Evidence column prints “Not
            available” instead of a contract status; a status a row DOES serve is shown in its row drawer, and —
            where the read serves no company multiple — in the P/E cell itself: a fund prints its fund metric
            there.
          </li>
          <li>
            Peer TTM median: “{peerMedianText()}” — {peerMedianNote()}. Evidence: “{assessmentText()}” —{' '}
            {assessmentNote()}. Neither cell carries a status word, a cutoff, a ranking or a colour.
          </li>
          <li>
            Market cap is the served field (the wire is in millions, divided once for display).{' '}
            {MARKET_CAP_PROVENANCE_NOTE}
          </li>
          {readState.detail !== null && (
            <li>
              <b>This read’s status.</b> {readState.detail}
            </li>
          )}
          {notCurrent(book.freshness) && <li>{lastKnownSentence(book.freshness)}</li>}
        </ul>
      </details>
    </section>
  )
}
