// Portfolio › Holdings — the first real-data slice, built on an isolated typed FIXTURE and laid out to the
// approved v04 design (docs/wealth/design-reference/…_v04.html, sha256 1f8f87bb…).
//
// STATUS: the contract is PROPOSED (portfolio-holdings@2), so the DEFAULT path here is still the synthetic
// fixture and says so. The served book arrives through `HoldingsLive` → `liveProps` → `adapter`, which passes
// `book` explicitly; this file binds no reader itself and issues no request.
//
// v04's order is kept: heading (the shell's — there is no second <h1> here), one compact session/freshness
// line, the four-card summary strip, the Holdings workspace, then the two decision/allocation panels. The
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
//   * the three v04 summary cards with no canonical source (unrealized total, YTD profit, cash total) print
//     Unknown and the reason, because this page never sums rows to fill a card.

import { useState } from 'react'
import type { CSSProperties } from 'react'
import { useDrawer } from '../../components/Drawer'
import { ActionCard, Metric, MetricGrid, Note, Panel, Tag } from '../../components/primitives'
import type { HoldingsBook, HoldingsRow } from './contract'
import { FIXTURE_BOOK } from './fixtures'
import { HoldingsTable, freshnessLine } from './HoldingsTable'
import { PositionCards } from './PositionCards'
import { PRESETS, preset, type PresetId } from './presets'
import { age, money, pct } from './format'
import { detailHeading, detailSections } from './detail'

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

// Allocation bands. Tokens only (the design gate forbids a stray hex outside the reference-locked sheets);
// a row's colour is assigned by its position in the served book, so the same book always draws the same ring.
const SLICE_TOKENS = ['var(--gold)', 'var(--blue)', 'var(--purple)', 'var(--green)', 'var(--red)'] as const

export function HoldingsPage({ book = FIXTURE_BOOK, loading = false, error = null, notice = null, nowMs = null }: HoldingsPageProps) {
  const [presetId, setPresetId] = useState<PresetId>('holdings')
  const [query, setQuery] = useState('')
  const drawer = useDrawer()

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
  const rows = needle
    ? book.rows.filter(r => `${r.symbol} ${r.name} ${r.accountLabel} ${r.accountKey}`.toLowerCase().includes(needle))
    : book.rows

  const openRow = (row: HoldingsRow, origin?: HTMLElement) => {
    const h = detailHeading(row)
    drawer.open({ title: h.title, eyebrow: h.eyebrow, body: <DetailBody row={row} />, origin: origin ?? null })
  }

  const accountKeys = [...new Set(book.rows.map(r => r.accountKey))]
  const scopeText = `all accounts${accountKeys.length > 0 ? ` (${accountKeys.length})` : ''}`

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

  // The one account-value card v04 draws from a canonical value. Everything else on the strip has no served
  // source and says so: the page never derives a total from the rows below it.
  const accountValue = book.measures.find(m => m.id === 'account_value') ?? null
  const accountValueCard =
    accountValue !== null && accountValue.status === 'MEASURED' && accountValue.valueUsd !== null
      ? {
          value: money(accountValue.valueUsd),
          sub: `${
            accountValue.verified
              ? `Verified, receipt ${accountValue.receiptId ?? 'missing'}`
              : 'Measured, not verified — the ledger publishes no receipt'
          } · as of ${accountValue.asOf ?? 'clock not served'}`,
        }
      : { value: 'Unknown', sub: accountValue === null ? 'No account-value measure is served.' : accountValue.reason }

  const priceMove = book.measures.find(m => m.id === 'price_move_estimate') ?? null

  // Protection gaps, quoted from the stops read. Not a recommendation: the card says what the producer
  // already reports, in the producer's own words, and opens the row it is about.
  const gaps = book.rows.filter(r => r.protection !== null && r.protection.state === 'GAP')

  const weightTotal = book.rows.reduce((sum, r) => sum + r.portfolioPct, 0)
  // This sum is a COMPLETENESS CHECK, not a displayed quantity: it decides only whether the ring closes.
  // portfolioPct is percent-of-book by contract (the wire's rows sum to 100.0), and a ring drawn over a book
  // that does not would silently misstate every band after the gap. It is quoted on screen only in the case
  // where it fails, as the reason the ring is withheld — never as a measure of value. Bars are drawn from
  // each row's served weight either way.
  const ringCloses = book.rows.length > 0 && Math.abs(weightTotal - 100) <= 0.05
  let running = 0
  const stops = book.rows
    .map((r, i) => {
      const from = running
      running += r.portfolioPct
      return `${SLICE_TOKENS[i % SLICE_TOKENS.length]} ${from.toFixed(2)}% ${running.toFixed(2)}%`
    })
    .join(', ')

  return (
    <section aria-label="Portfolio holdings">
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
            {freshnessLine(book.freshness.ageSeconds, book.freshness.staleAfterSeconds, book.freshness.stale)} · Marks as of{' '}
            {book.asOf} ({book.asOfClock} clock) ·{' '}
            {book.dayPnl.status === 'KNOWN'
              ? `day-change clock ${book.dayPnl.at ?? 'known'}`
              : 'day-change clock not declared by the producer'}
          </span>
        </div>
        <div className="session-controls">
          <span className="muted">Estimated price movement</span>
          <br />
          {priceMove !== null && priceMove.status === 'MEASURED' && priceMove.valueUsd !== null ? (
            <>
              <strong>{money(priceMove.valueUsd)}</strong>{' '}
              <small className="muted">
                {priceMove.verified ? 'verified' : 'measured, not verified'} · as of {priceMove.asOf ?? 'clock not served'}
              </small>
            </>
          ) : (
            <strong>Unknown</strong>
          )}
        </div>
      </div>

      <MetricGrid>
        <Metric label="Account value" value={accountValueCard.value} sub={accountValueCard.sub} />
        <Metric label="Unrealized gain" value="Unknown" sub="No served unrealized total; this page never sums rows." />
        <Metric label="YTD investment profit" value="Unknown" sub="No YTD measure is served on any read of this book." />
        <Metric label="Cash / book weight" value="Unknown" sub="No served cash total; cash is listed per account." />
      </MetricGrid>

      <Note tone="blue">
        Same account, security, session and snapshot in the row and the detail. Select a holding to review its cost,
        levels and protection.
      </Note>

      <Panel
        title="Holdings workspace"
        sub={`${book.counts.nonCash} securities · cash listed per account · book scope: ${scopeText} · ${
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
            {/* v04's own control: placeholder + aria-label, no visible label text beside the box. */}
            <input
              id="holdings-search"
              type="search"
              aria-label="Search holdings"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Find a holding…"
            />
            <div className="segmented" role="group" aria-label="Holding columns">
              {PRESETS.map(p => (
                <button key={p.id} type="button" className={p.id === presetId ? 'active' : ''} aria-pressed={p.id === presetId} onClick={() => setPresetId(p.id)}>
                  {p.label}
                </button>
              ))}
            </div>
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

      <div className="grid-equal">
        <Panel title="Protection gaps in this book" sub="Quoted from the stops read. Evidence precedes an investment proposal.">
          {gaps.length === 0 ? (
            <p className="muted">
              No row in this book is reported as a protection gap by the stops read. That is not a claim that every
              holding is covered — an UNKNOWN protection state is not a covered one.
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

        <Panel title="Where capital is allocated" sub="Book scope; each band is one row's served percent of the cash-inclusive book.">
          {book.rows.length === 0 ? (
            <p className="muted">No rows are served, so there is no allocation to draw.</p>
          ) : (
            <div className="donut-row">
              {ringCloses ? (
                <div className="donut" role="img" aria-label="Served allocation of the book, including cash" style={{ background: `conic-gradient(${stops})` }}>
                  <span>
                    <strong>{book.counts.nonCash}</strong>securities
                    <br />
                    {book.counts.cash} cash
                  </span>
                </div>
              ) : (
                <p className="muted">
                  The served weights total {pct(weightTotal, 1)}, not 100%, so the ring is not drawn: a closed ring
                  would misstate every band after the gap. The served weights are listed beside it.
                </p>
              )}
              <div className="bar-list">
                {book.rows.map((r, i) => (
                  <div className="bar-row" key={`${r.accountKey}:${r.symbol}`}>
                    <div className="row-between">
                      <span>{r.kind === 'CASH' ? `Cash · ${r.accountLabel}` : r.symbol}</span>
                      <span className="mono">{pct(r.portfolioPct, 1)}</span>
                    </div>
                    <div className="bar-track">
                      <div
                        className="bar-fill"
                        style={{ width: `${Math.max(0, Math.min(100, r.portfolioPct))}%`, background: SLICE_TOKENS[i % SLICE_TOKENS.length] }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Panel>
      </div>

      {book.freshness.stale && (
        <div className="note bad" role="alert">
          <strong>Not current.</strong> This is last-known-good data,{' '}
          {book.freshness.ageSeconds === null ? 'of unknown age' : `${age(book.freshness.ageSeconds)} old`}, past the{' '}
          {book.freshness.staleAfterSeconds === null
            ? 'stale limit — limit not served.'
            : `${age(book.freshness.staleAfterSeconds)} limit.`}
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
            {freshnessLine(book.freshness.ageSeconds, book.freshness.staleAfterSeconds, book.freshness.stale)}
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
              <dt>{c.role} clock</dt>
              <dd>
                {c.at ?? 'UNKNOWN'} · {c.source}
                {c.isBuildClock && ' · document build clock — the positions clock is the one that ages the book'}
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
                      {a.accountLabel}
                      {a.accountLabel === a.accountKey ? null : ` · ${a.accountKey}`}
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
          <Tag>Read-only</Tag> No orders, no approvals, no writes. Cash rows are listed per account and never added
          together; the summary cards that v04 fills from an aggregate print Unknown because no aggregate is served.
        </small>
      </p>
    </section>
  )
}
