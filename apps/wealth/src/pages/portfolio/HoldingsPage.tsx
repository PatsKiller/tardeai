// Portfolio › Holdings — the first real-data slice, built on an isolated typed FIXTURE.
//
// STATUS: the contract is PROPOSED (portfolio-holdings@2), so the DEFAULT path here is still the synthetic fixture
// and says so. The served book arrives through `HoldingsLive` → `liveProps` → `adapter`, which passes `book`
// explicitly; this file binds no reader itself and issues no request. The default prop becomes `null` when the
// contract is approved (see README, F10).
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
//   * loading, error and empty are three different states, and empty is never a table of zeros.

import { useState } from 'react'
import { useDrawer } from '../../components/Drawer'
import type { HoldingsBook, HoldingsRow } from './contract'
import { FIXTURE_BOOK } from './fixtures'
import { HoldingsTable, freshnessLine } from './HoldingsTable'
import { PRESETS, preset, type PresetId } from './presets'
import { age, money } from './format'
import { detailFields, detailHeading } from './detail'

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
}

/** The drawer body: this row's own served fields and their provenance, nothing recomputed and no other row. */
function DetailBody({ row }: { row: HoldingsRow }) {
  return (
    <dl>
      {detailFields(row).map(f => (
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
  )
}

export function HoldingsPage({ book = FIXTURE_BOOK, loading = false, error = null, notice = null }: HoldingsPageProps) {
  const [presetId, setPresetId] = useState<PresetId>('holdings')
  const [query, setQuery] = useState('')
  const drawer = useDrawer()

  if (error !== null) {
    return (
      <section aria-labelledby="h-portfolio-holdings">
        <h1 id="h-portfolio-holdings">Holdings</h1>
        <p role="alert">
          <strong>Holdings could not be read.</strong> {error}
        </p>
        <p>No values are shown, because none were served.</p>
      </section>
    )
  }

  if (loading || book === null) {
    return (
      <section aria-labelledby="h-portfolio-holdings" aria-busy={loading}>
        <h1 id="h-portfolio-holdings">Holdings</h1>
        <p>{loading ? 'Reading the book…' : 'No book has been supplied.'}</p>
      </section>
    )
  }

  const active = preset(presetId)
  const needle = query.trim().toLowerCase()
  const rows = needle
    ? book.rows.filter(r => `${r.symbol} ${r.name} ${r.accountLabel} ${r.accountKey}`.toLowerCase().includes(needle))
    : book.rows

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

  return (
    <section aria-labelledby="h-portfolio-holdings">
      <h1 id="h-portfolio-holdings">Holdings</h1>

      {book.source === 'FIXTURE' && (
        <p role="note">
          <strong>Fixture data.</strong> Every value on this page is synthetic and no live reader is bound.
          portfolio-holdings@2 is proposed, not approved for wiring.
        </p>
      )}

      {notice !== null && (
        <p role="status">
          <strong>Read status.</strong> {notice}
        </p>
      )}

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

      {book.freshness.stale && (
        <p role="alert">
          <strong>Not current.</strong> This is last-known-good data,{' '}
          {book.freshness.ageSeconds === null ? 'of unknown age' : `${age(book.freshness.ageSeconds)} old`}, past the{' '}
          {book.freshness.staleAfterSeconds === null
            ? 'stale limit — limit not served.'
            : `${age(book.freshness.staleAfterSeconds)} limit.`}
        </p>
      )}

      <h2>Book measures</h2>
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

      {book.accounts !== null && (
        <>
          <h2>Per account</h2>
          <table>
            <caption>
              Totals as published by the producer. They are not summed from the rows below.
            </caption>
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
                    {a.accountLabel} · {a.accountKey}
                  </th>
                  <td>{money(a.totalUsd)}</td>
                  <td>{money(a.cashUsd)}</td>
                  <td>{a.asOf ?? 'unknown'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <div role="toolbar" aria-label="Holdings view">
        <p>
          <label htmlFor="holdings-search">Search security or account</label>{' '}
          <input
            id="holdings-search"
            type="search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="symbol, name or account"
          />
        </p>
        <p>
          Preset:{' '}
          {PRESETS.map(p => (
            <button key={p.id} type="button" aria-pressed={p.id === presetId} onClick={() => setPresetId(p.id)}>
              {p.label}
            </button>
          ))}
        </p>
      </div>

      {rows.length === 0 ? (
        <p>
          <strong>No positions.</strong> {book.rows.length === 0 ? book.coverageNote : 'No row matches this search.'}
        </p>
      ) : (
        <HoldingsTable
          rows={rows}
          preset={active}
          onRowOpen={row => {
            const h = detailHeading(row)
            drawer.open({ title: h.title, eyebrow: h.eyebrow, body: <DetailBody row={row} /> })
          }}
        />
      )}

      <p>
        <small>{book.coverageNote}</small>
      </p>
    </section>
  )
}
