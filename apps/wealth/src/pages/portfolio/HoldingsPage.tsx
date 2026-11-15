// Portfolio › Holdings — the first real-data slice, built on an isolated typed FIXTURE and laid out to the
// approved v04 design (docs/wealth/design-reference/…_v04.html, sha256 1f8f87bb…).
//
// STATUS: the contract is PROPOSED (portfolio-holdings@2), so the DEFAULT path here is still the synthetic
// fixture and says so. The served book arrives through `HoldingsLive` → `liveProps` → `adapter`, which passes
// `book` explicitly; this file binds no reader itself and issues no request.
//
// v04's order is kept: heading (the shell's — there is no second <h1> here), one compact session/freshness
// line, the approved v0.5 analytics panel (filters, KPI strip, three charts — one selected view), the
// Holdings workspace, then the protection-gap panel. The
// plumbing the operator rejected as the main workspace — clocks, measure definitions, population, the
// per-account audit table — now lives in collapsed <details> blocks below the fold, keyboard operable, with
// the material warnings (stale, unverified, fixture) still visible above it.
//
// Truthfulness rules visible on screen:
//   * the fixture, when in use, says so above the table;
//   * a header count always names its scope (all rows / non-cash / cash / over the notional floor / under it) and the
//     population block states what the read removed before the counters — separately from the rows that are listed
//     and merely outside the counted scope, which are not omissions;
//   * every declared clock is shown with its role, and the document build clock is called out — it is not
//     the positions clock, and the age of one must not be read as the age of the other;
//   * book-level measures are the producer's; an UNKNOWN measure renders UNKNOWN, never a zero, and a receipt is
//     shown only where the ledger says verified (today: nowhere — the wire publishes `verified: false, receipt:
//     null` for all four, and rendering a receipt there would be an invention);
//   * per-account totals are the producer's; when none are served the block is absent, and the page never
//     sums rows to invent one;
//   * the session label comes from the session field (the rows carry none) and names its source;
//   * a stale book says how old it is and that the values are not current;
//   * a day-change column with no declared clock is labelled as such, not given one;
//   * loading, error and empty are three different states, and empty is never a table of zeros;
//   * the v0.5 KPI strip, the charts, the table and the CSV are ONE selected view: the approved selector's
//     totals over the rows the filters kept, labelled as display aggregates of published values — not
//     broker equity and not verified profit;
//   * sector is bound from served fields only (contract r6 §5): a cash or fund row is Funds & Cash, an
//     unavailable profile says so instead of printing the carried label, and null/empty is Unclassified;
//   * the account scope is a FILTER over served rows and nothing else (scope.ts): "All accounts" is the served
//     book, and under one account every book-level measure says "not served per account" — the page never sums
//     rows into a per-account total. The selection is shared with the top bar (TopBar.tsx): this page's account
//     select and the top bar's drive the same state, and this page's is a stable native control.

import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { useDrawer } from '../../components/Drawer'
import { ActionCard, Panel, Tag } from '../../components/primitives'
import type { HoldingsBook, HoldingsRow } from './contract'
import { ledgerLine } from './clockLedger'
import { FIXTURE_BOOK } from './fixtures'
import { HoldingsTable, csvFor, freshnessLine } from './HoldingsTable'
import { AnalyticsPanel } from './AnalyticsPanel'
import { accountOptions, displaySectorKey, normalizeBook, snapshotFor } from './analyticsAdapter'
import type { AccountChoice, AnalyticsRow } from './analyticsAdapter'
import { derivePortfolioView } from './analytics/portfolio-analytics.mjs'
import type { AnalyticsSnapshot, PortfolioView } from './analytics/portfolio-analytics.mjs'
import { PositionCards } from './PositionCards'
import { PRESETS, preset, type PresetId } from './presets'
import { lastKnownSentence, money, moneyTone, notCurrent, servedFreshnessLine, toneClass } from './format'
import { detailSections, detailHeading } from './detail'
import { rowsInScope, scopeLabel, scopedMeasure } from './scope'
import { useBookScope } from './snapshot'

export interface HoldingsPageProps {
  /**
   * Fixture today. At APPROVED_FOR_WIRING the default must become `null` ("No book has been supplied") so that a
   * wiring mistake fails to empty rather than to synthetic (review F10). The live route (`HoldingsLive`) always
   * passes an explicit `book`, so it can never fall through to this default.
   */
  book?: HoldingsBook | null
  loading?: boolean
  error?: string | null
  /**
   * What the reader is NOT claiming, in one sentence — last good with its age, not current, health unproven.
   * `liveProps.ts` sets it; a page that passes a book without it is claiming the book is current.
   */
  notice?: string | null
  /** The read's own clock in ms, for age cues on served timestamps. Absent: no age cue is claimed. */
  nowMs?: number | null
}

// v04's asset-detail tabs are `.tabs` of links; the design sheets are reference-locked and their rules only style
// `.tabs a`, so the button form carries the same declarations inline (tokens only — no hex outside the sheets).
const TAB_BASE: CSSProperties = {
  flex: 'none',
  padding: '0 0 11px',
  background: 'transparent',
  border: 0,
  borderRadius: 0,
  color: 'var(--muted)',
  fontSize: 13,
  whiteSpace: 'nowrap',
  cursor: 'pointer',
}
const TAB_ACTIVE: CSSProperties = { ...TAB_BASE, color: 'var(--gold)', borderBottom: '2px solid var(--gold)' }

/** An age cue for a served timestamp. Arithmetic on two instants only — no threshold, no verdict. */
function ageCue(iso: string | null, nowMs: number | null | undefined): string | null {
  if (iso === null || nowMs === null || nowMs === undefined) return null
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return null
  const days = Math.floor((nowMs - t) / 86_400_000)
  if (days <= 0) return 'recorded today'
  if (days < 60) return `recorded ${days} day${days === 1 ? '' : 's'} ago`
  return `recorded about ${Math.round(days / 30.44)} months ago`
}

/**
 * The drawer body: v04's four detail tabs over THIS row's own served fields, then the two tabs the route cannot
 * fill, named (verdict 2026-11-15T0342Z B3). Nothing recomputed; no other row appears.
 */
function DetailBody({ row }: { row: HoldingsRow }) {
  const { sections, unserved } = detailSections(row)
  const [tab, setTab] = useState(sections[0]?.title ?? '')
  const active = sections.find(s => s.title === tab) ?? sections[0]
  return (
    <>
      <nav className="tabs" role="tablist" aria-label="Row detail">
        {sections.map(s => {
          const on = s.title === active?.title
          return (
            <button
              key={s.title}
              type="button"
              role="tab"
              aria-selected={on}
              style={on ? TAB_ACTIVE : TAB_BASE}
              onClick={() => setTab(s.title)}
            >
              {s.title}
            </button>
          )
        })}
      </nav>
      <dl>
        {active?.fields.map(f => (
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
      {unserved.map(u => (
        <p key={u} className="small muted">
          {u}
        </p>
      ))}
    </>
  )
}

/**
 * The one selected view (v0.5), or a stated reason it could not be derived. The approved selector rejects a
 * row whose canonical identity is missing or duplicated (`validateRows`) — on this read that happens only if
 * the wire serves a row without an account or symbol. The page then says so and falls back to the plain table
 * instead of charting an identity it cannot keep.
 */
function buildAnalytics(book: HoldingsBook, scope: string, sector: string, query: string, currency: string) {
  const rows = normalizeBook(book)
  const accounts = accountOptions(rows)
  const snapshot = snapshotFor(book)
  const selectorScope = {
    account: scope === 'ALL' ? '' : scope,
    sector,
    query,
    currency: currency === '' ? null : currency,
  }
  try {
    return { rows, accounts, snapshot, view: derivePortfolioView(rows, selectorScope, snapshot), reason: null as string | null }
  } catch (e) {
    return { rows, accounts, snapshot, view: null as PortfolioView<AnalyticsRow> | null, reason: e instanceof Error ? e.message : String(e) }
  }
}

/** Sectors available under an account/currency — used to announce an impossible sector's reset. */
function sectorsFor(rows: AnalyticsRow[], snapshot: AnalyticsSnapshot, scope: string, currency: string): string[] {
  try {
    const view = derivePortfolioView(
      rows,
      { account: scope === 'ALL' ? '' : scope, sector: '', query: '', currency: currency === '' ? null : currency },
      snapshot,
    )
    return view.sectorOptions
  } catch {
    return []
  }
}

export function HoldingsPage({ book = FIXTURE_BOOK, loading = false, error = null, notice = null, nowMs = null }: HoldingsPageProps) {
  const [presetId, setPresetId] = useState<PresetId>('holdings')
  const [query, setQuery] = useState('')
  const [sector, setSector] = useState('')
  const [currency, setCurrency] = useState('')
  const [announcement, setAnnouncement] = useState('')
  const drawer = useDrawer()
  // One scope for the page and the top bar. Outside the shell's provider this is local state, so a unit render
  // still filters; inside it, the top bar's select drives this page (and this page's select drives it back).
  const { scope, setScope } = useBookScope()

  // Every hook above the early returns, unconditionally: the memo is computed only for a book that exists.
  const analytics = useMemo(
    () =>
      book === null
        ? { rows: [] as AnalyticsRow[], accounts: [] as AccountChoice[], snapshot: null, view: null as PortfolioView<AnalyticsRow> | null, reason: null as string | null }
        : buildAnalytics(book, scope, sector, query, currency),
    [book, scope, sector, query, currency],
  )

  // A filter that no longer exists in the book (an account change, or a snapshot refresh that dropped a
  // sector) is reset AND announced. Without the announcement the population would change silently.
  useEffect(() => {
    if (analytics.view === null || sector === '') return
    if (!analytics.view.sectorOptions.includes(sector)) {
      setSector('')
      setAnnouncement(`Sector reset because ${displaySectorKey(sector)} is not present in this account.`)
    }
  }, [analytics.view, sector])

  // Filter handlers. An ACCOUNT or CURRENCY change can make the selected sector impossible; it is cleared in the
  // SAME update as the change, so the table never renders an impossible slice for a frame, and the reset is
  // announced because the population changed without the reader asking. Sector and search changes are the
  // reader's own, so they withdraw a previous announcement.
  const changeAccount = (key: string) => {
    const next = key === '' ? 'ALL' : key
    setScope(next)
    setAnnouncement('')
    if (sector === '' || analytics.snapshot === null) return
    if (!sectorsFor(analytics.rows, analytics.snapshot, next, currency).includes(sector)) {
      setSector('')
      setAnnouncement(`Sector reset because ${displaySectorKey(sector)} is not present in this account.`)
    }
  }

  const changeCurrency = (next: string) => {
    setCurrency(next)
    setAnnouncement('')
    if (sector === '' || analytics.snapshot === null) return
    if (!sectorsFor(analytics.rows, analytics.snapshot, scope, next).includes(sector)) {
      setSector('')
      setAnnouncement(`Sector reset because ${displaySectorKey(sector)} is not present in this currency.`)
    }
  }

  const changeSector = (key: string) => {
    setSector(key)
    setAnnouncement('')
  }

  const changeSearch = (next: string) => {
    setQuery(next)
    setAnnouncement('')
  }

  const resetFilters = () => {
    setScope('ALL')
    setSector('')
    setQuery('')
    setCurrency('')
    setAnnouncement('All filters reset: every account and sector, no search.')
  }

  if (error !== null) {
    return (
      <section aria-label="Portfolio holdings">
        <div className="note bad" role="alert">
          <strong>Holdings could not be read.</strong> {error} No values are shown, because none were served.
        </div>
      </section>
    )
  }

  if (loading || book === null) {
    return (
      <section aria-label="Portfolio holdings" aria-busy={loading}>
        <p className="muted">{loading ? 'Reading the book…' : 'No book has been supplied.'}</p>
      </section>
    )
  }

  const active = preset(presetId)
  const needle = query.trim().toLowerCase()
  // The scope narrows the rows; the search narrows them again. Neither changes a served value.
  const inScope = rowsInScope(book, scope)
  // The v0.5 view is the ONE filter pass when it can be derived: account, sector, search and currency narrow the
  // same population, so the KPI strip, the charts, the table and the CSV cannot disagree about which rows they
  // describe. When the selector rejects the book's identity the page falls back to scope + search and says why.
  const view = analytics.view
  const fallbackRows = needle
    ? inScope.filter(r => `${r.symbol} ${r.name} ${r.accountLabel} ${r.accountKey}`.toLowerCase().includes(needle))
    : inScope
  const rows = view === null ? fallbackRows : view.rows.map(r => r.holding)

  const openRow = (row: HoldingsRow, origin?: HTMLElement) => {
    const h = detailHeading(row)
    drawer.open({ title: h.title, eyebrow: h.eyebrow, body: <DetailBody row={row} />, origin: origin ?? null })
  }

  // The export is the table's own cells: same rows, same preset, same cell() walker (HoldingsTable.csvFor), so
  // the file cannot disagree with the screen. Download only — no request, no write, no upload.
  const downloadCsv = () => {
    const url = URL.createObjectURL(new Blob([csvFor(rows, active)], { type: 'text/csv;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `holdings-${book.asOf}-${active.id}.csv`
    a.rel = 'noopener'
    document.body.appendChild(a)
    a.click()
    a.remove()
    requestAnimationFrame(() => URL.revokeObjectURL(url))
  }

  const scopeText = scopeLabel(book, scope)

  const sessionText =
    book.session.status === 'KNOWN'
      ? `Market session: ${book.session.phase ?? 'known'} · last open session ${book.session.latestOpenSession ?? 'unknown'}${
          book.session.source ? ` · source: ${book.session.source}` : ''
        } (the rows carry no session label)`
      : `Market session: UNKNOWN — ${book.session.reason}`

  const excludedText =
    book.population.excluded.length === 0
      ? 'none omitted'
      : book.population.excluded.map(e => `${e.count} ${e.label}`).join(' · ')

  // Named here so the disclosure can quote the served instant instead of describing the role in the abstract.
  const valuationClock = book.clocks.find(c => c.role === 'VALUATION') ?? null

  // The v0.5 KPI strip replaces v04's four-card metric grid: its totals are the approved selector's own over the
  // SELECTED rows, and each card says what it is. The one served book measure v04 drew from a canonical value
  // (account value) is still printed, with its verification and clock, in the Book measures block below.
  const priceMove = scopedMeasure(book, 'price_move_estimate', scope)
  // A signed CHANGE is coloured by direction only while the read is current; an UNKNOWN or a last-good read
  // keeps neutral ink (operator visual-semantic route 2026-11-15T1555Z).
  const priceMoveTone = notCurrent(book.freshness) ? 'flat' : moneyTone(priceMove.valueUsd)

  // Protection gaps, quoted from the stops read. Not a recommendation: the card says what the producer
  // already reports, in the producer's own words, and opens the row it is about.
  const gaps = inScope.filter(r => r.protection !== null && r.protection.state === 'GAP')

  return (
    <section aria-label="Portfolio holdings">
      {book.source === 'FIXTURE' && (
        <div className="note" role="note">
          <strong>Fixture data.</strong> Every value on this page is synthetic and no live reader is bound.
          portfolio-holdings@2 is proposed, not approved for wiring.
        </div>
      )}

      {notice !== null && (
        <div className="note warn" role="status">
          <strong>Read status.</strong> {notice}
        </div>
      )}

      <div className="session">
        <div>
          <strong className={book.session.status === 'KNOWN' ? undefined : 'text-warn'}>
            {book.session.status === 'KNOWN' ? (book.session.phase ?? 'Session known') : 'Session UNKNOWN'}
          </strong>
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
              : servedFreshnessLine(book.freshness.served)} · Marks as of{' '}
            {book.asOf} ({book.asOfClock} clock) ·{' '}
            {book.dayPnl.status === 'KNOWN'
              ? `day-change clock ${book.dayPnl.at ?? 'known'}`
              : 'day-change clock not declared by the producer'}
          </span>
        </div>
        <div className="session-controls">
          <span className="muted">Estimated price movement</span>
          <br />
          {priceMove.available ? (
            <>
              <strong className={toneClass(priceMoveTone) || undefined}>{money(priceMove.valueUsd)}</strong>{' '}
              <small className="muted">
                {priceMove.measure?.verified ? 'verified' : 'measured, not verified'} · as of{' '}
                {priceMove.measure?.asOf ?? 'clock not served'}
              </small>
            </>
          ) : (
            <>
              <strong>Unknown</strong> <small className="muted">{priceMove.reason}</small>
            </>
          )}
        </div>
      </div>

      {view !== null ? (
        <AnalyticsPanel
          view={view}
          accounts={analytics.accounts}
          scope={scope}
          sector={sector}
          query={query}
          currency={currency}
          announcement={announcement}
          onAccount={changeAccount}
          onSector={changeSector}
          onSearch={changeSearch}
          onCurrency={changeCurrency}
          onReset={resetFilters}
          onOpenHolding={openRow}
        />
      ) : (
        <div className="note bad" role="alert">
          <strong>Overview withheld.</strong> The selected view cannot be derived from this book: {analytics.reason}{' '}
          The rows below are filtered by account and search only; no total is printed over an identity the page
          cannot keep.
        </div>
      )}

      <Panel
        title="Holdings workspace"
        sub={`${rows.length} rows in the selected view · ${rows.filter(r => r.kind === 'CASH').length} cash · scope: ${scopeText} · ${
          book.source === 'FIXTURE' ? 'synthetic fixture' : 'served book'
        }`}
        right={
          <button
            type="button"
            className="small"
            onClick={() => document.getElementById('holdings-evidence')?.scrollIntoView({ block: 'start' })}
          >
            Accounting definitions →
          </button>
        }
      >
        <div className="toolbar">
          <div className="left">
            <div className="segmented" role="group" aria-label="Holding columns">
              {PRESETS.map(p => (
                <button key={p.id} type="button" className={p.id === presetId ? 'active' : ''} aria-pressed={p.id === presetId} onClick={() => setPresetId(p.id)}>
                  {p.label}
                </button>
              ))}
            </div>
            <button type="button" className="small" onClick={downloadCsv}>
              Export CSV
            </button>
          </div>
        </div>

        {rows.length === 0 ? (
          <p>
            <strong>No positions.</strong> {book.rows.length === 0 ? book.coverageNote : 'No row matches this search.'}
          </p>
        ) : (
          <>
            {/* v04 hides .holdings-table at ≤510 px and shows .position-cards instead; the class is the switch. */}
            <div className="holdings-table">
              <HoldingsTable rows={rows} preset={active} onRowOpen={openRow} />
            </div>
            <PositionCards rows={rows} onRowOpen={openRow} />
          </>
        )}

        <div className="table-foot">
          <span>
            Marks: {book.asOf} ({book.asOfClock} clock) · basis: remaining recorded cost · USD · day change: no
            declared per-row clock
          </span>
          <span>Technical diagnostics stay in details.</span>
        </div>
        <p className="small muted">{book.coverageNote}</p>
      </Panel>

      {/* One column: v0.5's sector panel above now carries the allocation v04's second panel drew, and a
          half-width panel beside nothing would reserve a column for no content. */}
      <div className="grid-equal" style={{ gridTemplateColumns: 'minmax(0, 1fr)' }}>
        <Panel
          title={`Protection gaps in ${scope === 'ALL' ? 'this book' : 'this account'}`}
          sub="Quoted from the stops read. Evidence precedes an investment proposal."
        >
          {gaps.length === 0 ? (
            <p className="muted">
              No row {scope === 'ALL' ? 'in this book' : 'in this scope'} is reported as a protection gap by the stops
              read. That is not a claim that every holding is covered — an UNKNOWN protection state is not a covered one.
            </p>
          ) : (
            <>
              {gaps.slice(0, 3).map(r => (
                <ActionCard
                  key={`${r.accountKey}:${r.symbol}`}
                  title={`${r.symbol} · protection gap`}
                  desc={`${r.protection?.reason ?? 'the stops read reports a gap'}. ${r.protection?.nextStep ?? ''}`.trim()}
                  meta={
                    <>
                      Served by the stops read · {r.protection?.asOf ?? 'read clock absent'}
                      {r.protection?.stale ? ' (stale)' : ''}
                      {ageCue(r.protection?.asOf ?? null, nowMs) !== null ? ` · ${ageCue(r.protection?.asOf ?? null, nowMs)}` : ''} ·{' '}
                      {r.accountLabel}
                    </>
                  }
                  cta={
                    <button type="button" className="small" onClick={() => openRow(r)}>
                      Review →
                    </button>
                  }
                />
              ))}
              {gaps.length > 3 && <p className="small muted">+{gaps.length - 3} more in the table above.</p>}
            </>
          )}
        </Panel>
      </div>

      {notCurrent(book.freshness) && (
        <div className="note warn" role="alert">
          <strong>Not current.</strong> {lastKnownSentence(book.freshness)}
        </div>
      )}

      <details id="holdings-evidence">
        <summary>
          <b>Evidence &amp; definitions</b> — clocks, book measures, population, session and source paths
        </summary>
        <dl>
          <dt>As of</dt>
          <dd>
            {book.asOf} · {book.asOfClock} clock ·{' '}
            {book.freshness.served === null
              ? freshnessLine(book.freshness.ageSeconds, book.freshness.staleAfterSeconds, book.freshness.stale)
              : servedFreshnessLine(book.freshness.served)}
          </dd>
          <dt>{book.counts.primaryScopeLabel}</dt>
          <dd>
            {book.counts.nonCashOverFloor} · all rows {book.counts.allRows} · securities {book.counts.nonCash} · cash{' '}
            {book.counts.cash} · under the floor {book.counts.heldUnderFloor}
          </dd>
          <dt>Population</dt>
          <dd>
            read {book.population.priceableRows} · in the book {book.population.renderedRows} · omitted: {excludedText}
            {book.population.floorUsd !== null && ` · notional floor ${money(book.population.floorUsd)}`}
          </dd>
          {book.population.listedNotCounted.length > 0 && (
            <dd>
              in the table, outside the counted scope:{' '}
              {book.population.listedNotCounted.map(l => `${l.count} ${l.reason} (${l.scope})`).join(' · ')} — these
              rows are rendered; they are not omitted
            </dd>
          )}
          <dt>Session</dt>
          <dd>{sessionText}</dd>
          <dt>Day change clock</dt>
          <dd>
            {book.dayPnl.status === 'KNOWN'
              ? `Declared at ${book.dayPnl.at ?? 'unknown'}`
              : `UNKNOWN — ${book.dayPnl.reason}`}
          </dd>
        </dl>

        {book.population.excluded.length > 0 && (
          <ul>
            {book.population.excluded.map(e => (
              <li key={e.kind}>
                <small>
                  {e.count} {e.label} omitted before the counters — {e.rule}
                </small>
              </li>
            ))}
          </ul>
        )}

        <h4>Declared clocks</h4>
        <dl>
          {book.clocks.map(c => (
            <div key={c.role}>
              {/* REQUEST is the response's own render time, not a producer clock: it says "Rendered at" (F-4). */}
              <dt>{c.role === 'REQUEST' ? 'Rendered at' : `${c.role} clock`}</dt>
              <dd>
                {c.at ?? 'UNKNOWN'} · {c.source}
                {c.isBuildClock && ' · document build clock — the positions clock is the one that ages the book'}
                {/* A withheld datum is printed as what it is. It is NOT the clock: the book is not aged from it,
                    and it never fills the `at` slot above (review 2026-11-15T0509Z §5.3). The sentence and both
                    of its conditions live in `ledgerLine`, which design-gate rule 8 pins this <dd> to call. */}
                {ledgerLine(c)}
              </dd>
            </div>
          ))}
        </dl>

        <h4>Book measures</h4>
        <dl>
          {book.measures.map(m => (
            <div key={m.id}>
              <dt>{m.label}</dt>
              <dd>
                {m.status === 'MEASURED'
                  ? `${money(m.valueUsd)} · as of ${m.asOf ?? 'unknown'} · ${
                      m.verified
                        ? `verified, receipt ${m.receiptId ?? 'missing'}`
                        : 'measured, not verified — the ledger publishes no receipt'
                    }`
                  : `UNKNOWN — ${m.reason}`}
                <br />
                <small>{m.definition}</small>
              </dd>
            </div>
          ))}
        </dl>

        {/* The ledger's frontend disclosures (HOLDINGS-CLOCK-FINDINGS-LEDGER-2026-11-15T0325Z): each is a fact
            about what a clock on this page does NOT say. They are stated here rather than left to inference. */}
        <h4>What these clocks do and do not say</h4>
        <dl>
          <div>
            <dt>Marks clock (F-1)</dt>
            <dd>
              The marks on this page are stamped {book.asOf} by the {book.asOfClock} clock — the field the producer
              put in <code>truth.as_of</code>. QUOTE is the last repriced quote; POSITIONS is an aggregate across
              rows (the wire marks it <code>mixed</code>) and can be older than any one quote. The label follows the
              clock that actually won, so it is never a fixed word printed over a different instant.
            </dd>
          </div>
          <div>
            <dt>Body age is not data age (F-3)</dt>
            <dd>
              {freshnessLine(book.freshness.ageSeconds, book.freshness.staleAfterSeconds, book.freshness.stale)} That
              age is of this response as the reader computed it; a recompute re-stamps it. It is not the age of the
              prices or positions inside, which carry their own clocks above and can differ from it by a day.
            </dd>
          </div>
          <div>
            <dt>VALUATION is stamped by the read (F-4)</dt>
            <dd>
              The VALUATION clock is {valuationClock?.at ?? 'not declared'}, the document’s <code>generated_at</code>,
              written when this response was built. It says when the document was generated, not when the valuation
              inputs were observed.
            </dd>
          </div>
          <div>
            <dt>A protection gap does not age (F-6)</dt>
            <dd>
              GAP means the stops read reports no resting stop for that row. A gap carries no age of its own on this
              route, so one recorded weeks ago and one recorded today render identically; the per-row stop-read clock
              is the only date attached to it.
            </dd>
          </div>
          <div>
            <dt>BUILD is not a freshness clock (F-9)</dt>
            <dd>
              BUILD is the position-list document build, declared so it cannot be mistaken for the book’s age. It
              ages nothing on this page.
            </dd>
          </div>
          <div>
            <dt>Day change has no declared clock</dt>
            <dd>
              The producer declares the per-row day-change clock UNKNOWN (<code>day_pnl</code>), so a day-change
              figure is not dated here and is not called a regular-session move.
            </dd>
          </div>
        </dl>

        <h4>Backend work to fulfill the cards this page shows as Unknown</h4>
        {/* No number on this page waits for a renderer: each Unknown above waits for a producer. The owner is a
            proposal, not an assignment — the operator decides who builds it.
            `matrix` is the reference's own prose-table class (v02/v04: `white-space:normal`, cells top-aligned and
            left). Without it the table inherits the shell's nowrap cell rule, and four columns of prose cannot fit
            992 px at 1280 — measured 1133/992 (141 px over) on the live payload, 2026-11-15. */}
        <div className="table-wrap"><table className="matrix">
          <caption>Fields with no producer on this read, and the work that would fill them</caption>
          <thead>
            <tr>
              <th scope="col">Field</th>
              <th scope="col">Producer needed</th>
              <th scope="col">Store</th>
              <th scope="col">Owner to be</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">Unrealized gain — whole book</th>
              <td>
                A book-level unrealized total, with its own clock. Not the overview’s “Open-position gain/loss vs.
                cost”: that one is a display aggregate of the published row values in the selected view (and says
                when it is partial), not a measure of the whole book.
              </td>
              <td>broker positions store, computed by the producer</td>
              <td>holdings reader repair (unassigned)</td>
            </tr>
            <tr>
              <th scope="row">YTD investment profit</th>
              <td>A YTD profit measure with a declared period start and clock</td>
              <td>performance history store</td>
              <td>performance producer (unassigned)</td>
            </tr>
            <tr>
              <th scope="row">Cash / book weight</th>
              <td>A served cash total per book and per account, with a clock</td>
              <td>broker positions store (cash rows are served; the total is not)</td>
              <td>holdings reader repair (unassigned)</td>
            </tr>
            <tr>
              <th scope="row">Per-account book measures</th>
              <td>A per-account split of account value and the price-move estimate</td>
              <td>measures block keyed by account</td>
              <td>measures producer (unassigned)</td>
            </tr>
            <tr>
              <th scope="row">Regular-session move</th>
              <td>A session-labelled move with a declared day-change clock</td>
              <td>session and quote store</td>
              <td>n8n 24/7 producer (P-1, unassigned)</td>
            </tr>
          </tbody>
        </table></div>
      </details>

      <details id="holdings-accounts">
        <summary>
          <b>Account details</b> — per-account totals as the producer publishes them
        </summary>
        {book.accounts === null ? (
          <p className="muted">
            No per-account totals were served on this read. The page does not sum the rows above to make one.
          </p>
        ) : (
          <>
            <p className="small muted">Totals as published by the producer. They are not summed from the rows above.</p>
            {/* v04/v02 give table min-width:720px and nowrap cells; the scroll container keeps that width off the page. */}
            <div className="table-wrap"><table>
              <caption>Per-account totals as served</caption>
              <thead>
                <tr>
                  <th scope="col">Account</th>
                  <th scope="col">Total</th>
                  <th scope="col">Cash</th>
                  <th scope="col">As of</th>
                </tr>
              </thead>
              <tbody>
                {book.accounts.map(a => (
                  <tr key={a.accountKey}>
                    <th scope="row">
                      {/* The display label, joined from the served holdings rows (adapter.ts → accountLabel.ts).
                          A raw key renders only when the read served no label anywhere — and it says so, rather
                          than passing for a label: the key is the one identifier that exists. */}
                      {a.accountLabel}
                      {a.accountLabel === a.accountKey ? <small className="muted">no display label served</small> : null}
                    </th>
                    <td>{a.totalUsd === null ? <span title="not served">N/A</span> : money(a.totalUsd)}</td>
                    <td>{a.cashUsd === null ? <span title="not served">N/A</span> : money(a.cashUsd)}</td>
                    <td>{a.asOf ?? 'unknown'}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          </>
        )}
      </details>

      <p>
        <small className="muted">
          <Tag>Read-only</Tag> No orders, no approvals, no writes. The overview's totals are display aggregates of
          published row values over the selected view — not broker equity, not verified profit; per-account totals
          remain the producer's and are never summed here. The account scope is shared with the top bar.
        </small>
      </p>
    </section>
  )
}
