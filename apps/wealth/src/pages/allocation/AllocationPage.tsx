// Portfolio › Allocation — the nav view that reuses the REVIEWED v0.5 selector, not a second analytics engine.
//
// Base: LIVE `ca4e75d07`. This page does not re-derive anything the Holdings analytics panel already decided:
// `buildAllocationModel` (allocationView.ts) calls the same approved selector twice — once over the whole read
// (the BOOK basis) and once over the filters (the SELECTED basis) — and this file only labels, formats and
// lays out. No new source, no new formula, no second definition of "weight".
//
// What the page must not leave ambiguous (RELEASE-ACCEPTANCE-LEDGER row D: "selected 100% vs unlabelled book
// weight" — FAIL): a bare percentage. So every weight here is printed under a column header that NAMES its
// denominator ("Weight of book" / "Weight of selected view"), the two valued totals are stated in the panel
// foot, and the statement under the filters says which figure divides by what. The charts carry the reviewed
// package's own sentences about what they include (direct classification, funds and cash in one sleeve).
//
// Truthfulness rules held by construction:
//   * no fetch, no timer, no write, no broker call: the page renders props (AllocationLive owns the one GET);
//   * a sleeve with rows but no published value prints "Unknown", never $0.00 and never 0%;
//   * a sleeve absent from a non-empty selection prints "None in view" and 0% only when the selector says
//     the selection's allocation is valid — otherwise "—";
//   * the empty, loading, error, unreadable-book and withheld states are five different states, and none of
//     them is a table of zeros;
//   * the account scope is the shell's one selection (`useBookScope`), so the page and the top bar cannot
//     disagree; sector and search are this page's own filters, exactly as on Holdings.

import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import type { HoldingsBook } from '../portfolio/contract'
import { accountFallbackLabel, stableAccountRef } from '../portfolio/accountLabel'
import {
  accountOptions,
  coverageText,
  displaySectorKey,
  freshnessCopy,
  gainLossMeasureLabel,
  moneyText,
  normalizeBook,
  percentText,
  snapshotFor,
} from '../portfolio/analyticsAdapter'
import type { AccountChoice, AnalyticsRow } from '../portfolio/analyticsAdapter'
import type { PortfolioView } from '../portfolio/analytics/portfolio-analytics.mjs'
import { useBookScope } from '../portfolio/snapshot'
import { buildAllocationModel, readStatus } from './allocationView'
import type { AllocationModel, SleeveBasis, Sleeve } from './allocationView'
import { derivePortfolioView } from '../portfolio/analytics/portfolio-analytics.mjs'
import {
  SERVED_PCT_NOTE,
  VALUE_BASIS,
  WEIGHT_BASIS,
  accountSlices,
  drillChips,
  isDrilled,
  reconcileWithHoldings,
  rowSlices,
  toggleAccount,
  toggleSector,
} from './drillView'
import '../portfolio/analytics/analytics.css'
import './allocation.css'

export interface AllocationPageProps {
  /** The served book, exactly as it arrived; null says no book was supplied (and prints no weight). */
  book?: HoldingsBook | null
  loading?: boolean
  error?: string | null
  /** What the reader is NOT claiming, in one sentence — `liveProps.ts` sets last-known-good with its age. */
  notice?: string | null
  /** The read's own clock in ms (unused for arithmetic here; kept so the route can pass it like Holdings). */
  nowMs?: number | null
  /** Initial drill, for a static render of an already-drilled page (tests, shared links). Clicks change it. */
  initialSector?: string
  initialQuery?: string
}

// The reviewed AnalyticsPanel's empty states, unchanged: the same selector withholding the same weights must
// say the same thing on both pages.
const EMPTY_NO_MATCH = 'No holdings match this view. Clear a filter to continue.'
const EMPTY_NEGATIVE =
  'Signed exposures present. Net/gross allocation needs an approved definition; positions remain available below.'
const EMPTY_ALLOCATION =
  'Allocation unavailable: choose one currency and provide positive canonical position values.'

const NUM: CSSProperties = { textAlign: 'right', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }

type Derived =
  | { accounts: AccountChoice[]; model: AllocationModel<AnalyticsRow>; reason: null }
  | { accounts: AccountChoice[]; model: null; reason: string }

/** Normalize + derive, and turn a selector refusal into a stated reason rather than a blank page. */
function derive(book: HoldingsBook, scope: string, sector: string, query: string): Derived {
  const rows: AnalyticsRow[] = normalizeBook(book)
  const accounts = accountOptions(rows)
  try {
    return { accounts, model: buildAllocationModel(rows, snapshotFor(book), { scope, sector, query }), reason: null }
  } catch (e: unknown) {
    return { accounts, model: null, reason: e instanceof Error ? e.message : String(e) }
  }
}

/** The reviewed `SectorChart` markup, copied from `portfolio/AnalyticsPanel.tsx` so the same chart renders the
 *  same way (classes, copy and empty states); the data is the selector's own `sectors`. */
function SleeveChart({
  view,
  active,
  onSector,
}: {
  view: PortfolioView<AnalyticsRow>
  active: string
  onSector: (key: string) => void
}) {
  if (view.rows.length === 0) return <div className="wm-pa-empty">{EMPTY_NO_MATCH}</div>
  if (!view.allocationValid)
    return <div className="wm-pa-empty">{view.negative ? EMPTY_NEGATIVE : EMPTY_ALLOCATION}</div>
  let offset = 0
  const arcs = view.sectors
    .filter(s => s.known && s.value > 0)
    .map(s => {
      const amount = (s.weight ?? 0) * 100
      const start = offset
      offset += amount
      return { key: s.key, color: s.color, amount, start }
    })
  return (
    <div className="wm-pa-sector-layout">
      <svg
        className="wm-pa-donut"
        viewBox="0 0 120 120"
        role="img"
        aria-label={`Sleeve allocation of the selected view, ${coverageText(view.coverage.valued, view.coverage.total)}`}
      >
        <g transform="rotate(-90 60 60)">
          {arcs.map(a => (
            <circle
              key={a.key}
              r="42"
              cx="60"
              cy="60"
              pathLength={100}
              stroke={a.color}
              strokeDasharray={`${a.amount} ${100 - a.amount}`}
              strokeDashoffset={-a.start}
            />
          ))}
        </g>
        <text x="60" y="57" className="wm-pa-donut-value">
          {view.securityCount}
        </text>
        <text x="60" y="72" className="wm-pa-donut-label">
          securities
        </text>
      </svg>
      <div className="wm-pa-legend">
        <p className="alloc-basis" data-basis="selected">
          {WEIGHT_BASIS.selected}: each percent is the sleeve’s value over the selected view’s valued total.
        </p>
        {view.sectors.map(s => (
          <button
            key={s.key}
            type="button"
            onClick={() => onSector(s.key)}
            aria-pressed={active === s.key}
            aria-label={`${active === s.key ? 'Clear sleeve filter' : 'Filter sleeve'}: ${displaySectorKey(s.key)}`}
          >
            <span className="wm-pa-dot" style={{ background: s.color }} />
            <span>{displaySectorKey(s.key)}</span>
            <b title={`${WEIGHT_BASIS.selected}`}>{s.known ? percentText(s.weight) : 'Unknown'}</b>
          </button>
        ))}
      </div>
    </div>
  )
}

/** An amount in the selected view's currency. `null` is an unpublished value, never $0.00. */
function amountText(b: SleeveBasis, currency: string | null): string {
  return b.amount === null ? 'Unknown' : moneyText(b.amount, currency)
}

/** A weight that names its denominator by column. 'Unknown' = rows present, nothing valued; '—' = withheld. */
function weightText(b: SleeveBasis): string {
  if (b.weight !== null) return percentText(b.weight)
  return b.count > 0 && b.valued === 0 ? 'Unknown' : '—'
}

/** What the reader sees for a sleeve with no row in the selection: an absence, not an unpriced value. */
function selectedAmountText(s: Sleeve, currency: string | null): string {
  if (s.selected.amount === null) return 'Unknown'
  if (!s.inSelection) return 'None in view'
  return moneyText(s.selected.amount, currency)
}

export function AllocationPage({
  book = null,
  loading = false,
  error = null,
  notice = null,
  nowMs = null,
  initialSector = '',
  initialQuery = '',
}: AllocationPageProps) {
  const [sector, setSector] = useState(initialSector)
  const [query, setQuery] = useState(initialQuery)
  const [announcement, setAnnouncement] = useState('')
  const { scope, setScope } = useBookScope()

  // Every hook above the early returns, unconditionally: the model is computed only for a book that exists.
  const derived = useMemo(
    () => (book === null ? null : derive(book, scope, sector, query)),
    [book, scope, sector, query],
  )

  // A sector that the current scope no longer contains is reset AND announced — the population must not
  // change silently (the Holdings page's rule, kept here because this page has the same filter).
  const sectorOptions = derived?.model?.view.sectorOptions ?? null
  useEffect(() => {
    if (sectorOptions === null || sector === '') return
    if (!sectorOptions.includes(sector)) {
      setSector('')
      setAnnouncement(`Sleeve reset because ${displaySectorKey(sector)} is not present in this account.`)
    }
  }, [sectorOptions, sector])

  if (error !== null) {
    return (
      <div className="note bad" role="alert">
        <strong>Allocation could not be read.</strong> {error} No weight is printed, because no book was served
        on this page.
      </div>
    )
  }
  if (loading) return <p className="muted">Reading the book…</p>
  if (book === null) {
    return (
      <p className="muted">
        <strong>No book has been supplied.</strong> Allocation is derived from the served book; with none served
        this page prints no weight.
      </p>
    )
  }
  if (derived === null || derived.model === null) {
    return (
      <div className="note bad" role="alert">
        <strong>Allocation withheld.</strong> The selected view cannot be derived from this book:{' '}
        {derived === null ? 'no model was built' : derived.reason} No weight is printed over an identity this
        page cannot keep.
      </div>
    )
  }

  const { accounts, model } = derived
  const bookView = model.bookView
  const view = model.view
  const currency = view.scope.currency
  // RC3 (lead route 2026-11-15T1754Z): the strip speaks the panel's OWN freshness vocabulary instead of
  // echoing `snapshot.status` + `snapshot.reason`. `freshnessCopy` gates the "Last known good …" copy on a
  // validated receipt OBJECT and otherwise says "Last available snapshot · freshness unverified", so an
  // unverified read can never be dressed as a good one here. The overall verdict and the data's as-of stay
  // beside it (the header clock), as the reviewed panel prints them.
  //
  // W2 rebase (route 2026-11-15T1833Z): that sentence is the strip's ONE source — it is passed here instead
  // of the page keeping a second copy — and the producer's notice, its reason and this read's clock go behind
  // the disclosure. `readStatus` still falls back to the notice's lead clause when the adapter is silent
  // (a health-unproven read), so the strip never says nothing over an unmeasured one.
  const fresh = freshnessCopy(view.snapshot)
  const readState = readStatus(notice, view.snapshot, fresh.line)
  const accountLabel = scope === 'ALL' ? 'all accounts' : (accounts.find(a => a.key === scope)?.label ?? accountFallbackLabel(stableAccountRef(scope)))
  const bookAccountCount = accounts.length
  const drill = { sector, scope, query }
  const chips = drillChips(drill, displaySectorKey, k => accounts.find(a => a.key === k)?.label ?? accountFallbackLabel(stableAccountRef(k)))
  const resetDrill = () => {
    setScope('ALL')
    setSector('')
    setQuery('')
    setAnnouncement('Drill reset: all accounts, all sleeves, no search.')
  }
  const normalizedRows = normalizeBook(book)
  const bookSnapshot = snapshotFor(book)
  const accountRowsView = accountSlices(
    accounts,
    key => derivePortfolioView(normalizedRows, { account: key, sector: '', query: '', currency: null }, bookSnapshot) as PortfolioView<AnalyticsRow>,
    bookView,
  )
  const rowList = rowSlices(view, bookView, r => (r.isCash ? 'Cash & sweep' : r.sector && r.sector.trim() !== '' ? r.sector.trim() : 'Unclassified'))
  const recon = reconcileWithHoldings(normalizedRows, bookView.currencyValid ? bookView.total : null, bookView.coverage)
  const reconSelected = reconcileWithHoldings(view.rows, view.currencyValid ? view.total : null, view.coverage)

  return (
    <section className="wm-pa" aria-label="Allocation">
      <header className="wm-pa-heading">
        <div>
          <span className="wm-pa-eyebrow">PORTFOLIO · ALLOCATION</span>
          <h2>Where the book is allocated</h2>
        </div>
        <span className="wm-pa-clock">
          {view.snapshot.session ?? 'Session unknown'} · Data as of {fresh.dataAsOf} · freshness {fresh.overall}
        </span>
      </header>

      <div className="wm-pa-filterbar">
        <label>
          Account
          {/* The shell's one scope: the same state the top bar renders, so the two cannot disagree. */}
          <select value={scope === 'ALL' ? '' : scope} onChange={e => setScope(e.target.value === '' ? 'ALL' : e.target.value)}>
            <option value="">All accounts</option>
            {accounts.map(a => (
              <option key={a.key} value={a.key}>
                {a.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Sleeve
          <select value={sector} onChange={e => setSector(e.target.value)}>
            <option value="">All sleeves</option>
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
            onChange={e => setQuery(e.target.value)}
            placeholder="Symbol, name or account"
            autoComplete="off"
          />
        </label>
        <button
          type="button"
          onClick={resetDrill}
        >
          Reset filters
        </button>
      </div>

      {isDrilled(drill) && (
        <div className="alloc-drill" role="group" aria-label="Active drill filters" data-drill="active">
          <span className="alloc-drill-lead">
            Showing {view.rows.length} of {bookView.rows.length} rows, filtered by
          </span>
          {chips.map(c => (
            <span key={c.kind} className="alloc-chip" data-chip={c.kind}>
              {c.label}
            </span>
          ))}
          <button type="button" className="alloc-reset" data-reset="drill" onClick={resetDrill}>
            Reset drill
          </button>
        </div>
      )}

      <div className="wm-pa-status" aria-live="polite">
        {view.rows.length} matching rows · {view.securityCount} investment securities ·{' '}
        {coverageText(view.coverage.valued, view.coverage.total)}
        {readState.warning !== null && <span className="wm-pa-warning">{readState.warning}</span>}
        {announcement !== '' && <> · {announcement}</>}
      </div>

      {/* Ledger row D, stated once where the filters are: two denominators, each named at its column.
          Progressive detail (route 2026-11-15T1745Z, item 1): the statement stays one glanceable summary,
          and the full methodology — plus this read's own technical reason — opens on demand. Native
          <details>, so it is keyboard- and screen-reader-operable; no coverage, number or receipt changes. */}
      <details className="note blue alloc-methodology">
        <summary>
          <strong>Two denominators, both named where used.</strong> How each weight is computed
          {readState.detail !== null ? ' · this read’s status' : ''}
        </summary>
        <p>
          <em>Weight of book</em> divides by the whole read —{' '}
          {coverageText(bookView.coverage.valued, bookView.coverage.total)} across {bookAccountCount}{' '}
          {bookAccountCount === 1 ? 'account' : 'accounts'}, every sleeve, cash included:{' '}
          {bookView.currencyValid ? moneyText(bookView.total, bookView.scope.currency) : 'total unknown'}.{' '}
          <em>Weight of selected view</em> divides by the rows these filters keep —{' '}
          {coverageText(view.coverage.valued, view.coverage.total)}:{' '}
          {view.currencyValid ? moneyText(view.total, view.scope.currency) : 'total unknown'}. A percentage
          without one of those names is not printed on this page.
        </p>
        {readState.detail !== null && <p className="alloc-read-detail">{readState.detail}</p>}
      </details>

      <div className="wm-pa-kpis">
        <article>
          <span>
            Book value · whole read
            {bookView.coverage.valued < bookView.coverage.total ? ' · partial' : ''}
          </span>
          <strong>{bookView.currencyValid ? moneyText(bookView.total, bookView.scope.currency) : 'Unknown'}</strong>
          <small>All accounts, all sleeves · includes cash · the denominator of “weight of book”</small>
        </article>
        <article>
          <span>
            Selected view value
            {view.coverage.valued < view.coverage.total ? ' · partial' : ''}
          </span>
          <strong>{view.currencyValid ? moneyText(view.total, view.scope.currency) : 'Unknown'}</strong>
          <small>
            {coverageText(view.coverage.valued, view.coverage.total)} · {accountLabel} · the denominator of
            “weight of selected view”
          </small>
        </article>
        <article>
          <span>
            Cash in selected view
            {view.coverage.cash < view.coverage.cashTotal ? ' · partial' : ''}
          </span>
          {/*
            The selector defines cash over an EMPTY selection as 0 (`cashRows.length === 0 && currencyValid ? 0`)
            and the reviewed panel prints it. Beside a total the same view withholds (null → "Unknown"), $0.00
            would read as a measured zero over nothing selected, so this page withholds it in that one state. A
            non-empty selection with no cash rows keeps the selector's 0 — there the absence IS measured, and the
            table says "None in view" for the sleeve.
          */}
          <strong>{view.rows.length === 0 ? 'Unknown' : view.currencyValid ? moneyText(view.cash, view.scope.currency) : 'Unknown'}</strong>
          <small>
            {view.rows.length === 0
              ? 'no rows in view · cash is not measured here'
              : 'Cash rows only · not account equity · shares the Funds & Cash sleeve'}
          </small>
        </article>
        <article>
          <span>{gainLossMeasureLabel(view.coverage.pnl < view.coverage.nonCash)}</span>
          <strong
            className={
              view.pnl !== null && view.pnl < 0 ? 'wm-pa-negative' : view.pnl !== null && view.pnl > 0 ? 'wm-pa-positive' : ''
            }
          >
            {view.currencyValid ? moneyText(view.pnl, view.scope.currency) : 'Unknown'}
          </strong>
          <small>
            {view.coverage.pnl}/{view.coverage.nonCash} investment rows · not period profit
          </small>
        </article>
      </div>

      <div className="alloc-pair">
        <article className="wm-pa-panel">
          <div className="wm-pa-panelhead">
            <h3>Sleeve allocation</h3>
            <span>{WEIGHT_BASIS.selected} · click a sleeve to filter</span>
          </div>
          <SleeveChart view={view} active={sector} onSector={k => setSector(toggleSector(sector, k))} />
          <p className="wm-pa-foot">
            Percentages are of the selected view ({coverageText(view.coverage.valued, view.coverage.total)}),
            not of the book — the sleeves table states both. Direct instrument classification. Funds
            are not constituent look-through; funds and cash share the Funds &amp; Cash sleeve.
            {view.coverage.valued < view.coverage.total ? ' Percentages use known values only.' : ''}
          </p>
        </article>

        <article className="wm-pa-panel">
          <div className="wm-pa-panelhead">
            <h3>Investment sleeves</h3>
            <span>Book and selected view</span>
          </div>
          {model.sleeves.length === 0 ? (
            <div className="wm-pa-empty">{EMPTY_NO_MATCH}</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Sleeve</th>
                    <th scope="col" style={NUM}>
                      Book amount
                    </th>
                    <th scope="col" style={NUM}>
                      {WEIGHT_BASIS.book}
                    </th>
                    <th scope="col" style={NUM}>
                      Selected amount
                    </th>
                    <th scope="col" style={NUM}>
                      {WEIGHT_BASIS.selected}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {model.sleeves.map(s => (
                    <tr key={s.key}>
                      <td>
                        <button
                          type="button"
                          className="alloc-link"
                          aria-pressed={sector === s.key}
                          aria-label={`${sector === s.key ? 'Clear sleeve filter' : 'Filter sleeve'}: ${displaySectorKey(s.key)}`}
                          onClick={() => setSector(toggleSector(sector, s.key))}
                        >
                          {displaySectorKey(s.key)}
                        </button>
                      </td>
                      <td style={NUM} title={`${s.book.valued}/${s.book.count} book rows valued`}>
                        {amountText(s.book, bookView.scope.currency)}
                      </td>
                      <td style={NUM}>{weightText(s.book)}</td>
                      <td
                        style={NUM}
                        title={`${s.selected.valued}/${s.selected.count} selected rows valued`}
                      >
                        {selectedAmountText(s, currency)}
                      </td>
                      <td style={NUM}>{weightText(s.selected)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="wm-pa-foot">
            Valued totals: the book columns divide by{' '}
            {bookView.currencyValid ? moneyText(bookView.total, bookView.scope.currency) : 'an unknown total'} over{' '}
            {coverageText(bookView.coverage.valued, bookView.coverage.total)}; the selected columns divide by{' '}
            {view.currencyValid ? moneyText(view.total, view.scope.currency) : 'an unknown total'} over{' '}
            {coverageText(view.coverage.valued, view.coverage.total)}. The two are different denominators and are
            not compared column-to-column. “Unknown” means the sleeve's rows publish no position value, or that
            view has no valued denominator at all; “—” means that view's weights are withheld; “None in view” with
            0% means no row of that sleeve is in the selection — a measured absence. An amount covers only the
            rows that publish a value (the cell's title carries the count).
          </p>
        </article>
      </div>

      <div className="alloc-pair">
        <article className="wm-pa-panel" data-panel="accounts">
          <div className="wm-pa-panelhead">
            <h3>Accounts</h3>
            <span>{WEIGHT_BASIS.book} · click an account to filter</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Account</th>
                  <th scope="col" style={NUM}>
                    Value
                  </th>
                  <th scope="col" style={NUM}>
                    {WEIGHT_BASIS.book}
                  </th>
                  <th scope="col" style={NUM}>
                    Rows valued
                  </th>
                </tr>
              </thead>
              <tbody>
                {accountRowsView.map(a => (
                  <tr key={a.key}>
                    <td>
                      <button
                        type="button"
                        className="alloc-link"
                        aria-pressed={scope === a.key}
                        aria-label={`${scope === a.key ? 'Clear account filter' : 'Filter account'}: ${a.label}`}
                        onClick={() => setScope(toggleAccount(scope, a.key))}
                      >
                        {a.label}
                      </button>
                    </td>
                    <td style={NUM}>{a.amount === null ? 'Unknown' : moneyText(a.amount, bookView.scope.currency)}</td>
                    <td style={NUM}>{a.weightOfBook === null ? (a.valued === 0 ? 'Unknown' : '—') : percentText(a.weightOfBook)}</td>
                    <td style={NUM}>
                      {a.valued}/{a.count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="wm-pa-foot">
            Each account’s value is the sum of its rows’ published market value; its weight divides by the book
            total above. Value basis: {VALUE_BASIS}.
          </p>
        </article>

        <article className="wm-pa-panel" data-panel="rows">
          <div className="wm-pa-panelhead">
            <h3>Holdings in this view</h3>
            <span>
              {rowList.length} of {bookView.rows.length} rows
            </span>
          </div>
          {rowList.length === 0 ? (
            <div className="wm-pa-empty">{EMPTY_NO_MATCH}</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Holding</th>
                    <th scope="col">Account</th>
                    <th scope="col">Sleeve</th>
                    <th scope="col" style={NUM}>
                      Value
                    </th>
                    <th scope="col" style={NUM}>
                      {WEIGHT_BASIS.book}
                    </th>
                    <th scope="col" style={NUM}>
                      {WEIGHT_BASIS.selected}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rowList.map(r => (
                    <tr key={r.rowId} data-row={r.symbol}>
                      <td>{r.symbol}</td>
                      <td>{r.accountLabel}</td>
                      <td>{displaySectorKey(r.sleeveKey)}</td>
                      <td style={NUM}>{r.value === null ? 'Unknown' : moneyText(r.value, currency)}</td>
                      <td style={NUM}>{r.weightOfBook === null ? (r.value === null ? 'Unknown' : '—') : percentText(r.weightOfBook)}</td>
                      <td style={NUM}>{r.weightOfSelected === null ? (r.value === null ? 'Unknown' : '—') : percentText(r.weightOfSelected)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="wm-pa-foot">
            These are the rows the filters kept, so a drill changes this list and every figure above together.
            A weight is the row’s published value over the named total; “Unknown” = no published value.
          </p>
        </article>
      </div>

      <section className="note blue alloc-recon" data-recon={recon.status} aria-label="Reconciliation with Holdings">
        <p>
          <strong>Value basis, one for the whole page.</strong> {VALUE_BASIS}. Allocation total{' '}
          {recon.allocationTotal === null ? 'Unknown' : moneyText(recon.allocationTotal, bookView.scope.currency)}
          {' · '}Holdings total on the same basis{' '}
          {recon.holdingsTotal === null ? 'Unknown' : moneyText(recon.holdingsTotal, bookView.scope.currency)}
          {recon.difference !== null && recon.status === 'differs' ? ` · difference ${moneyText(recon.difference, bookView.scope.currency)}` : ''}.
        </p>
        <p data-recon-text="book">{recon.text}</p>
        {isDrilled(drill) && (
          <p data-recon-text="selected">
            Selected view: {reconSelected.text.replace(/^Reconciles to the Holdings total/, 'Reconciles to the Holdings sum of the same rows')}
          </p>
        )}
        <p>{SERVED_PCT_NOTE}</p>
      </section>

      <p className="wm-pa-context">
        Both columns come from the one reviewed selector the Holdings page renders — this page derives no total,
        weight or classification of its own. Amounts are display aggregates of published row values, not broker
        equity and not verified profit. Account scope is the shell's single selection; changing it here changes
        it on Holdings, because one selection must not mean two different books. Session and read time:{' '}
        {view.snapshot.session ?? 'unknown'} · {view.snapshot.observedAt ?? 'unknown'}.
      </p>
    </section>
  )
}
