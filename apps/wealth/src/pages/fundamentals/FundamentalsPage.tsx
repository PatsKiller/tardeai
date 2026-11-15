// Portfolio › Fundamentals — WB-1: the operator reference's workspace, ported into the app.
//
// Layout source: the operator's approved reference (`Main.dc.html`, WB-1 amendment
// LEAD-AMEND-WB1-EXACT-LAYOUT-NOW-20261115T1936Z, binding rulings RULING-FUNDAMENTALS-WORKSPACE-TIER2-…T1934Z /
// T1936Z / T1938Z). It is a LOCAL-ONLY design document: its real positions, account names and any brackets are
// NOT carried here — every value below is a served field of this book or the reference's muted `N/A`.
//
// Structure, top to bottom, is the reference's: header (title, one served meta line, the "Not wired" box), the
// five-card rollup strip, the lens/Group-by toolbar, the Equities table, the Funds table, the collapsed cash line,
// and the one-sentence foot note. The filters (sector, search, reset) are the only controls the reference does not
// draw; G1's filter is reused, in the reference's own 44 px control idiom, because the account scope must stay the
// shell's single selection.
//
// What this page does NOT do: no second reader, no second book, no derived column in a cell. The rollup cards that
// need a Tier 2 formula (equity sleeve P/E, book beta, book yield · income) and the largest-sector card print
// `Unknown` in WB-1 — WB-2 owns those formulas, each tagged `derived` with its one-line disclosure. The reference
// keeps the yield card in place and in style, showing its missing source; it does not disappear.
//
// The rows come from `filterFundamentals` (G1: the approved selector), are grouped and ordered by `workspace.ts`
// (no summed percentages, no averaged ratios), and are printed by `WorkspaceTables.tsx`.

import { useEffect, useMemo, useState } from 'react'
import { useDrawer } from '../../components/Drawer'
import type { HoldingsBook, HoldingsRow } from '../portfolio/contract'
import { detailHeading, detailSections } from '../portfolio/detail'
import { FIXTURE_BOOK } from '../portfolio/fixtures'
import { lastKnownSentence, notCurrent, servedFreshnessLine } from '../portfolio/format'
import { freshnessLine } from '../portfolio/HoldingsTable'
import { displaySectorKey, freshnessCopy, snapshotFor } from '../portfolio/analyticsAdapter'
import { scopeLabel } from '../portfolio/scope'
import { useBookScope } from '../portfolio/snapshot'
import { MARKET_CAP_PROVENANCE_NOTE, evidenceCopy } from './evidence'
import { EMPTY_NO_MATCH, filterFundamentals } from './filter'
import type { FundamentalsView } from './filter'
import { GROUPS, LENSES, buildWorkspace, coverageOf, equityColumns, fundColumns } from './workspace'
import type { Coverage, GroupBy, Lens } from './workspace'
import { CashLineRow, SectionTable } from './WorkspaceTables'
import '../portfolio/analytics/analytics.css'
import './workspace.css'

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

/** The reference's own sentence beside the title, adapted to what this read serves. */
const NOT_WIRED = 'Not wired: valuation-assessment@1 (peer median, assessment, evidence). Those columns are hidden until a reader serves them, instead of printing the notice on every row.'

/** The one Tier 3 sentence the ruling asks for — the producer gaps, named once, never as placeholder tiles. */
const NOT_SERVED =
  'Not served by this read: valuation-assessment@1 (peer and own-history median, assessment), a book yield/income ' +
  'aggregate (each row’s own yield IS served; the aggregate belongs to WB-2), and fund expense ratio, SEC yield ' +
  'and duration — producer gaps, named once here, not per row.'

/** The reference's foot sentence, kept verbatim except for the mock's own production note, which is dropped. */
const FOOT =
  'Printed as served unless tagged derived (arithmetic on served fields, no threshold, no colour verdict). ' +
  '▲ appears only where a record’s clock is older than the quote clock.'

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

/**
 * The five cards, in the reference's order and wording — the three formula sublines are the reference's sentences
 * alone: the WB-2 deferral is stated in the page's disclosure, so the card face needs no extra clause.
 * Unknown is a printed value, never a blank.
 */
function RollupStrip({ coverage }: { coverage: Coverage }) {
  const cards = [
    { label: 'Equity sleeve P/E', value: 'Unknown', sub: 'weight-harmonic, trailing → forward', derived: true },
    { label: 'Book beta', value: 'Unknown', sub: 'weight-averaged, cash at 0', derived: true },
    {
      label: 'Book yield · income',
      value: 'Unknown',
      // The live book DOES serve yields, so the card states how many rather than claiming none exist. The aggregate
      // is Unknown because WB-2 owns the income formula — an absent aggregate, never a "no yields today" claim.
      sub: `served on ${coverage.withYield} of ${coverage.rows} rows; aggregate Unknown (WB-2 owns the income formula)`,
      derived: true,
    },
    { label: 'Largest sector', value: 'Unknown', sub: 'served sector × served weight', derived: false },
    {
      label: 'Coverage',
      // Counts and denominator are the SAME population: the book. Never a filtered numerator over a book total.
      value: `${coverage.withMultiple} of ${coverage.rows} rows`,
      // "older", not "stale": D7 proves the record predates the quote, not that a freshness rule was violated.
      sub: `with a served multiple · ${coverage.olderRecords} ${coverage.olderRecords === 1 ? 'record' : 'records'} older than the quote`,
      derived: false,
    },
  ]
  return (
    <div className="fw-cards">
      {cards.map(c => (
        <div className="fw-card" key={c.label}>
          <div className="fw-card-label">
            {c.label}
            {c.derived && (
              <span className="fw-tag" title="arithmetic on served fields — no threshold, no colour verdict">
                derived
              </span>
            )}
          </div>
          <div className="fw-card-value">{c.value}</div>
          <div className="fw-card-sub">{c.sub}</div>
        </div>
      ))}
    </div>
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
  const [lens, setLens] = useState<Lens>('valuation')
  const [groupBy, setGroupBy] = useState<GroupBy>('security')
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

  const view: FundamentalsView = filtered ?? filterFundamentals(book, { scope, sector, query })
  const rows = view.rows
  const workspace = buildWorkspace(rows, groupBy)
  const snapshot = snapshotFor(book)
  const fresh = freshnessCopy(snapshot)
  const readState = evidenceCopy(notice, snapshot, fresh.line)
  const sourceText = book.source === 'FIXTURE' ? 'synthetic fixture' : 'served book'
  const filteredView = scope !== 'ALL' || sector !== '' || query.trim() !== ''
  const shareLabel = filteredView ? 'view' : 'book'

  const openRow = (row: HoldingsRow, origin?: HTMLElement) => {
    const h = detailHeading(row)
    drawer.open({ title: h.title, eyebrow: h.eyebrow, body: <DetailBody row={row} />, origin: origin ?? null })
  }

  return (
    <section aria-label="Portfolio fundamentals" className="fw">
      {book.source === 'FIXTURE' && (
        <div className="note" role="note">
          <strong>Fixture data.</strong> Every value on this page is synthetic and no live reader is bound.
          portfolio-holdings@2 is proposed, not approved for wiring.
        </div>
      )}

      <div className="fw-head">
        <div>
          {/* The document's one <h1> is the shell's crumb ("Portfolio / Fundamentals"), as on every book page
              (HoldingsPage states the rule). A second <h1> here duplicated the top-level heading, so the
              reference's workspace title is the H2 beneath it, in the reference's own type. */}
          <h2 className="fw-title">Fundamentals workspace</h2>
          <p className="fw-subhead" aria-live="polite" data-testid="workspace-meta">
            {filteredView ? `${rows.length} of ${view.bookRows} rows` : `${view.bookRows} rows`} ·{' '}
            {scopeLabel(book, scope)} · {sourceText} · marks as of {book.asOf} ({book.asOfClock ?? 'clock not served'} clock)
            {announcement !== '' && <> · {announcement}</>}
          </p>
        </div>
        <p className="fw-notwired">{NOT_WIRED}</p>
      </div>

      {/* A read that is not current, or whose health the producer did not state, must never look calm. */}
      {readState.line !== null && (
        <p className="fw-warning" role="alert" data-testid="workspace-warning">
          {readState.line}
        </p>
      )}

      <RollupStrip coverage={coverageOf(book.rows)} />

      <div className="fw-toolbar">
        <div className="fw-buttons" role="group" aria-label="Lens">
          {LENSES.map(l => (
            <button
              key={l.key}
              type="button"
              className="fw-btn"
              aria-pressed={lens === l.key}
              onClick={() => setLens(l.key)}
            >
              {l.label}
            </button>
          ))}
        </div>
        <div className="fw-buttons">
          <label className="fw-field">
            <span className="fw-label">Sector</span>
            <select
              className="fw-select"
              value={sector}
              onChange={e => {
                setSector(e.target.value)
                setAnnouncement('')
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
          <input
            className="fw-input"
            type="search"
            aria-label="Find a holding"
            placeholder="Find a holding"
            value={query}
            autoComplete="off"
            onChange={e => {
              setQuery(e.target.value)
              setAnnouncement('')
            }}
          />
          <button
            type="button"
            className="fw-btn fw-btn-group"
            onClick={() => {
              setSector('')
              setQuery('')
              setAnnouncement('Filters reset: all sectors. The account scope is the top bar’s.')
            }}
          >
            Reset filters
          </button>
          <span className="fw-label">Group by</span>
          <div className="fw-buttons" role="group" aria-label="Group by">
            {GROUPS.map(g => (
              <button
                key={g.key}
                type="button"
                className="fw-btn fw-btn-group"
                aria-pressed={groupBy === g.key}
                onClick={() => setGroupBy(g.key)}
              >
                {g.label}
              </button>
            ))}
          </div>
          <span className="fw-sortlabel">Sorted by weight ▾</span>
        </div>
      </div>

      {book.rows.length === 0 ? (
        <div className="fw-tablecard">
          <p className="fw-empty">
            <strong>No positions.</strong> {book.coverageNote}
          </p>
        </div>
      ) : rows.length === 0 ? (
        <div className="fw-tablecard">
          <p className="fw-empty">
            <strong>{EMPTY_NO_MATCH}</strong>
          </p>
        </div>
      ) : view.refused !== null ? (
        <div className="fw-tablecard">
          <p className="fw-empty">
            <strong>This view cannot be filtered as asked.</strong> {view.refused} No row is printed over a
            selection the page cannot keep.
          </p>
        </div>
      ) : (
        <>
          <SectionTable
            section={workspace.equities}
            columns={equityColumns(lens)}
            shareOf={shareLabel}
            viewValue={workspace.value}
            onRowOpen={openRow}
          />
          <SectionTable
            section={workspace.funds}
            columns={fundColumns(lens)}
            shareOf={shareLabel}
            viewValue={workspace.value}
            onRowOpen={openRow}
          />
          <CashLineRow section={workspace.cash} viewValue={workspace.value} shareOf={shareLabel} onRowOpen={openRow} />
        </>
      )}

      <p className="fw-foot">{FOOT}</p>
      <p className="fw-foot">{NOT_SERVED}</p>
      <p className="fw-foot">{book.coverageNote}</p>

      <details className="fw-details">
        <summary>
          <b>How this page is wired</b> — source, scope, this read’s session and status, and the gaps
        </summary>
        <ul>
          <li>
            One GET of the same reader the Holdings page uses (<code>/api/v2/portfolio/holdings</code>); the same
            adapter turns the envelope into this book. No second source and no second book.
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
            <b>Grouping and ordering.</b> Rows group by the selector’s stable security identity (the symbol — this
            route serves no CUSIP) and the declared contract currency; a security held in several accounts is one
            display row whose accounts and quantities are sublines. No percentage is summed and no cost, P/E or
            beta is averaged: the sublines carry each account’s own served weight, gain/loss and protection (each
            label its own detail action), and the ratio cells (P/E, PEG, beta, yield, YTD, trend) come from the
            group’s largest-weight row. Order is by served weight, largest first.
          </li>
          <li>
            <b>Derived values.</b> Only two marks on this page are arithmetic on served fields: the Equities share
            and the cash line’s share of the book (Σ served market value over Σ served market value in view), each
            tagged <span className="fw-tag">derived</span>. The three Tier 2 rollup cards print{' '}
            <b>Unknown</b> in WB-1: their formulas (value-weighted harmonic P/E, weight-averaged beta, implied EPS
            growth) are deterministic adapter arithmetic delivered in WB-2 with their own tests.
          </li>
          <li>
            <b>The ▲ mark.</b> Shown only where a row’s record clock is older than its quote clock; the record’s
            own date rides beside it. No age threshold and no colour verdict is derived from it.
          </li>
          <li>{MARKET_CAP_PROVENANCE_NOTE}</li>
          <li>{NOT_SERVED}</li>
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
