// Portfolio analytics v0.5 — the React port of the APPROVED package's above-the-table composition.
//
// Source: campaign-8h2-20261114/handoff/SOURCE-PORTFOLIO-ANALYTICS-V05-20261115T0340Z/ (portfolio-analytics.mjs
// sha256 98b826d3…, portfolio-analytics.css sha256 562c34a1…). The markup, class names, copy and empty states
// follow the package's `draw()`; the DATA comes from the same approved selector (`derivePortfolioView`, imported
// byte-identically) through `analyticsAdapter.ts`. This file renders; it computes no total of its own.
//
// Why a React component and not `createPortfolioAnalytics`: the package's DOM component owns its root and
// rebuilds it with innerHTML on every filter change. The operator addendum (2026-11-15T1500Z) requires the
// account/sector controls to be framework-owned and NOT recreated on render, with focus and selection
// preserved — a rebuilt root loses both. So the pure selector is imported and the markup is ported here; the
// package's DOM renderer is never mounted.
//
// Rails held by construction: no fetch, no timer, no broker call, no write. Every number is a display
// aggregate of published row values (INTEGRATION.md: "client sums are display aggregates of published values,
// never stored verified profit"), and the copy says so where the number is printed.

import type { PortfolioView } from './analytics/portfolio-analytics.mjs'
import type { AccountChoice, AnalyticsRow } from './analyticsAdapter'
import { coverageText, displaySectorKey, moneyText, percentText, signedMoneyText } from './analyticsAdapter'
import './analytics/analytics.css'

export interface AnalyticsPanelProps {
  /** The one selected view. The page derived it from the SAME rows the table and the CSV use. */
  view: PortfolioView<AnalyticsRow>
  /** Every account in the book, for the select (the view's own rows are already filtered). */
  accounts: AccountChoice[]
  /** `'ALL'` or a served account key — the same state the shell's top bar renders. */
  scope: string
  /** A selector bucket key, or '' for all sectors. */
  sector: string
  query: string
  /** '' means "the one served currency"; only offered when the read serves more than one. */
  currency: string
  /** A sentence for the live region after a reset a reader did not ask for, or after Reset. */
  announcement: string
  onAccount: (key: string) => void
  onSector: (key: string) => void
  onSearch: (query: string) => void
  onCurrency: (currency: string) => void
  onReset: () => void
}

const EMPTY_NO_MATCH = 'No holdings match this view. Clear a filter to continue.'
const EMPTY_NEGATIVE =
  'Signed exposures present. Net/gross allocation needs an approved definition; positions remain available below.'
const EMPTY_ALLOCATION =
  'Allocation unavailable: choose one currency and provide positive canonical position values.'
const EMPTY_CURRENCY_CHART = 'Select one currency. No FX values are invented.'
const EMPTY_NO_VALUE = 'No supported position values in this view.'
const EMPTY_NO_PNL = 'Unrealized P&L is not supplied for the selected investments. No price-move substitute is used.'
const EMPTY_CURRENCY_PNL = 'Choose one currency to compare canonical unrealized gains.'

/** The package's own caption: label over the selector's key, so the reader never sees the internal bucket name. */
function sectorLabel(key: string): string {
  return displaySectorKey(key)
}

function Empty({ message }: { message: string }) {
  return <div className="wm-pa-empty">{message}</div>
}

function SectorChart({ view, onSector }: { view: PortfolioView<AnalyticsRow>; onSector: (key: string) => void }) {
  if (view.rows.length === 0) return <Empty message={EMPTY_NO_MATCH} />
  if (!view.allocationValid) return <Empty message={view.negative ? EMPTY_NEGATIVE : EMPTY_ALLOCATION} />
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
        aria-label={`Sector allocation, ${coverageText(view.coverage.valued, view.coverage.total)}`}
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
        {view.sectors.map(s => (
          <button key={s.key} type="button" onClick={() => onSector(s.key)} aria-label={`Filter sector: ${sectorLabel(s.label)}`}>
            <span className="wm-pa-dot" style={{ background: s.color }} />
            <span>{sectorLabel(s.label)}</span>
            <b>{s.known ? percentText(s.weight) : 'Unknown'}</b>
          </button>
        ))}
      </div>
    </div>
  )
}

function HoldingBars({ view }: { view: PortfolioView<AnalyticsRow> }) {
  if (!view.currencyValid) return <Empty message={EMPTY_CURRENCY_CHART} />
  const rows = view.holdings.filter(h => h.known)
  if (rows.length === 0) return <Empty message={EMPTY_NO_VALUE} />
  const max = Math.max(...rows.map(h => Math.abs(h.value)), 1)
  const top = rows.slice(0, 4)
  const rest = rows.slice(4)
  return (
    <>
      <div className="wm-pa-bars">
        {top.map(h => (
          <div key={h.key} className="wm-pa-bar-row">
            <div className="wm-pa-bar-caption">
              <strong>{h.label}</strong>
              <span>
                {moneyText(h.value, view.scope.currency, true)} <small>{percentText(h.weight)}</small>
              </span>
            </div>
            <div className="wm-pa-track">
              <span
                style={{
                  width: `${(Math.abs(h.value) / max) * 100}%`,
                  background: h.value < 0 ? 'var(--wm-pa-red)' : 'var(--wm-pa-blue)',
                }}
              />
            </div>
          </div>
        ))}
      </div>
      {rest.length > 0 && (
        <details className="wm-pa-more">
          <summary>All {rows.length} valued securities</summary>
          {rest.map(h => (
            <p key={h.key}>
              <span>{h.label}</span>
              <b>{moneyText(h.value, view.scope.currency, true)}</b>
            </p>
          ))}
        </details>
      )}
    </>
  )
}

function PnlBars({ view }: { view: PortfolioView<AnalyticsRow> }) {
  if (!view.currencyValid) return <Empty message={EMPTY_CURRENCY_PNL} />
  if (view.contributions.length === 0) return <Empty message={EMPTY_NO_PNL} />
  const rows = view.contributions
  const max = Math.max(...rows.map(h => Math.abs(h.pnl)), 1)
  return (
    <>
      <div className="wm-pa-bars">
        {rows.slice(0, 4).map(h => (
          <div key={h.key} className="wm-pa-bar-row">
            <div className="wm-pa-bar-caption">
              <strong>{h.label}</strong>
              <span className={h.pnl < 0 ? 'wm-pa-negative' : 'wm-pa-positive'}>
                {signedMoneyText(h.pnl, view.scope.currency)}
                {h.pnlKnown < h.count ? ' · partial' : ''}
              </span>
            </div>
            <div className="wm-pa-diverge">
              <span className="wm-pa-zero" />
              <span
                className={`wm-pa-pnl-bar ${h.pnl < 0 ? 'wm-pa-loss' : 'wm-pa-gain'}`}
                style={{ width: `${(Math.abs(h.pnl) / max) * 50}%` }}
              />
            </div>
          </div>
        ))}
      </div>
      <p className="wm-pa-foot">
        {view.coverage.pnl}/{view.coverage.nonCash} investment rows have published P&L. Unrealized, not daily or
        verified period profit.
      </p>
    </>
  )
}

export function AnalyticsPanel({
  view,
  accounts,
  scope,
  sector,
  query,
  currency,
  announcement,
  onAccount,
  onSector,
  onSearch,
  onCurrency,
  onReset,
}: AnalyticsPanelProps) {
  const account = scope === 'ALL' ? '' : scope
  const warning =
    view.snapshot.status === 'fresh' ? null : `${view.snapshot.status ?? 'Unknown freshness'}${view.snapshot.reason ? ` · ${view.snapshot.reason}` : ''}`
  const largest = view.holdings.find(h => h.known)
  const cashBySector = view.scope.sector !== '' && view.scope.sector !== 'Cash & sweep'

  return (
    <section className="wm-pa" aria-label="Portfolio overview and filters">
      <header className="wm-pa-heading">
        <div>
          <span className="wm-pa-eyebrow">YOUR BOOK · ONE SELECTED VIEW</span>
          <h2>Portfolio at a glance</h2>
        </div>
        <span className="wm-pa-clock">
          {view.snapshot.session ?? 'Session unknown'} · {view.snapshot.observedAt ?? 'Source time unknown'}
        </span>
      </header>

      <div className="wm-pa-filterbar">
        <label>
          Account
          {/* A native, controlled select: the same element across renders, so focus and the open list survive a
              filter change. Its state is the page's scope — the same one the shell's top bar renders. */}
          <select value={account} onChange={e => onAccount(e.target.value)}>
            <option value="">All accounts</option>
            {accounts.map(a => (
              <option key={a.key} value={a.key}>
                {a.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Sector
          <select value={sector} onChange={e => onSector(e.target.value)}>
            <option value="">All sectors</option>
            {view.sectorOptions.map(s => (
              <option key={s} value={s}>
                {sectorLabel(s)}
              </option>
            ))}
          </select>
        </label>
        {view.currencies.length > 1 && (
          <label>
            Currency
            <select value={currency} onChange={e => onCurrency(e.target.value)}>
              <option value="">Choose currency</option>
              {view.currencies.map(c => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="wm-pa-search">
          Find a holding
          <input
            type="search"
            value={query}
            onChange={e => onSearch(e.target.value)}
            placeholder="Symbol, name or account"
            autoComplete="off"
          />
        </label>
        <button type="button" onClick={onReset}>
          Reset filters
        </button>
      </div>

      <div className="wm-pa-status" aria-live="polite">
        {view.rows.length} matching rows · {view.securityCount} investment securities ·{' '}
        {coverageText(view.coverage.valued, view.coverage.total)}
        {warning !== null && <span className="wm-pa-warning">{warning}</span>}
        {announcement !== '' && <> · {announcement}</>}
      </div>

      <div className="wm-pa-kpis">
        <article>
          <span>Selected position value{view.coverage.valued < view.coverage.total ? ' · partial' : ''}</span>
          <strong>{view.currencyValid ? moneyText(view.total, view.scope.currency) : 'Unknown'}</strong>
          <small>Published row values · includes selected cash</small>
        </article>
        <article>
          <span>Unrealized gain / loss{view.coverage.pnl < view.coverage.nonCash ? ' · partial' : ''}</span>
          <strong className={view.pnl !== null && view.pnl < 0 ? 'wm-pa-negative' : view.pnl !== null && view.pnl > 0 ? 'wm-pa-positive' : ''}>
            {view.currencyValid ? moneyText(view.pnl, view.scope.currency) : 'Unknown'}
          </strong>
          <small>
            {view.coverage.pnl}/{view.coverage.nonCash} investment rows · not period profit
          </small>
        </article>
        <article>
          <span>Cash in selected view{view.coverage.cash < view.coverage.cashTotal ? ' · partial' : ''}</span>
          <strong>{view.currencyValid ? moneyText(view.cash, view.scope.currency) : 'Unknown'}</strong>
          <small>{cashBySector ? 'Excluded by sector filter' : 'Cash rows only · not account equity'}</small>
        </article>
        <article>
          <span>Largest valued exposure</span>
          <strong>{largest?.label ?? 'Unknown'}</strong>
          <small>{view.allocationValid && largest ? `${percentText(largest.weight)} of known selected value` : 'Weight unavailable'}</small>
        </article>
      </div>

      <div className="wm-pa-chartgrid">
        <article className="wm-pa-panel">
          <div className="wm-pa-panelhead">
            <h3>Sector allocation</h3>
            <span>Click to filter</span>
          </div>
          <SectorChart view={view} onSector={onSector} />
          <p className="wm-pa-foot">
            Direct instrument classification. Funds are not constituent look-through; funds and cash share the
            Funds &amp; Cash bucket. {view.coverage.valued < view.coverage.total ? 'Percentages use known values only.' : ''}
          </p>
        </article>
        <article className="wm-pa-panel">
          <div className="wm-pa-panelhead">
            <h3>Largest holdings</h3>
            <span>Selected value</span>
          </div>
          <HoldingBars view={view} />
        </article>
        <article className="wm-pa-panel">
          <div className="wm-pa-panelhead">
            <h3>Unrealized contributors</h3>
            <span>Gain / loss</span>
          </div>
          <PnlBars view={view} />
        </article>
      </div>

      <p className="wm-pa-context">
        Charts, holding rows and export share these filters. Changing sector rebases weights to the selected slice.
        Selected-view totals are display aggregates of published row values — not broker equity and not verified
        profit. Account equity and historical returns are separate measures. One currency (USD) is served; no FX is
        applied.
      </p>
    </section>
  )
}
