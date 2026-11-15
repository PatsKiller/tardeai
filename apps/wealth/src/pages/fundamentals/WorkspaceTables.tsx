// WB-1: the reference's two tables — Equities and Funds — rendered from the served rows.
//
// Every cell prints a SERVED field, or the reference's muted `N/A`. Nothing here averages, sums a percentage,
// applies a threshold or derives a colour verdict; the ONLY computed values are the weight bar's width (a second
// rendering of the served weight) and the section share, which the page tags `derived` (served market values over
// the view's served value — see workspace.ts).
//
// Two deliberate departures from the reference's markup, both named in the WB-1 READY:
//   * the identity cell's symbol is a real <button> (so the row drawer is reachable by keyboard); it is styled as
//     the reference's plain <strong>, so the port looks identical;
//   * columns the reference draws but this read cannot serve print the muted `N/A` with the reason on the cell
//     (expense ratio, SEC yield, duration — Tier 3 producer gaps), never a blank or a placeholder value.

import type { ReactNode } from 'react'
import type { HoldingsRow, Protection } from '../portfolio/contract'
import { decimal, marketCapText, multiple, pct, price, shares, signedMoney, signedPct } from '../portfolio/format'
import { stopSentence } from '../portfolio/HoldingsTable'
import type { CashLine, ColumnKey, Group, Section, ValueTotal } from './workspace'
import { COLUMN_LABEL, EQUITY_MIN_WIDTH, FUND_MIN_WIDTH, barWidth, recordOlderThanQuote, shortStamp, valuedText } from './workspace'

/** The reference's muted `N/A`; the reason rides on the cell's title and accessible name, never printed twice. */
function na(reason: string): ReactNode {
  return (
    <span className="fw-ph" title={reason} aria-label={`N/A — ${reason}`}>
      N/A
    </span>
  )
}

function orNa(value: string | null, reason: string): ReactNode {
  return value === null ? na(reason) : value
}

const PROTECTION_LABEL = { PROTECTED: 'Protected', GAP: 'Gap', UNKNOWN: 'Unknown' } as const

/** `MM-DD` of a served instant, or the reason there is none; never "today" and never an age in days. */
function readStamp(iso: string | null): string {
  return shortStamp(iso) ?? 'clock not served'
}

interface CellCtx {
  maxWeight: number | null
  fund: boolean
}

function identityCell(g: Group, ctx: CellCtx, onOpen?: (row: HoldingsRow) => void): ReactNode {
  const open = onOpen === undefined ? null : onOpen
  return (
    <>
      <strong className="fw-sym">
        {open === null ? (
          g.symbol
        ) : (
          <button
            type="button"
            className="fw-rowopen"
            title="Open this row's detail"
            aria-label={`Open ${g.symbol} details`}
            onClick={e => {
              e.stopPropagation()
              open(g.lead)
            }}
          >
            {g.symbol}
          </button>
        )}
      </strong>
      {g.sectorText !== null && (
        <span className="fw-ph">
          {' · '}
          {/* The reference draws this line unbounded on a standalone 1384 px canvas. Inside the shell the content
              column is 1176 px at 1440 (the app's nav), and an unbounded classification line took this table to
              1280 px — past the wrap, cutting the Protection column. The bound is the Holdings table's own rule
              (a bound + full text on the title); it is applied here, not in CSS elsewhere. */}
          <span className="fw-sector" title={g.sectorText}>
            {g.sectorText}
          </span>
        </span>
      )}
      {g.lines.map(l => (
        <span className="fw-sub" key={`${l.row.accountKey}:${l.row.symbol}`}>
          {l.accountLabel} ·{' '}
          {/* The reference's equity subline is `account · N sh · $price`; its fund subline is `account · $price`
              (a fund is bought in dollars, and Main.dc.html draws it that way). */}
          {ctx.fund ? null : `${shares(l.row.shares)} sh · `}
          {orNa(l.row.price === null ? null : price(l.row.price), 'no price served')}
        </span>
      ))}
    </>
  )
}

function weightCell(g: Group, ctx: CellCtx): ReactNode {
  if (g.weightPct !== null) {
    const cap =
      !ctx.fund && g.lead.marketCapB !== null
        ? ` · cap ${marketCapText(g.lead.marketCapB)}`
        : ''
    const stale = recordOlderThanQuote(g.lead) ? shortStamp(g.lead.profileUpdatedAt) : null
    return (
      <>
        {/* The reference draws the 44 px bar in the equities table only; a fund's weight cell is `%` + value. */}
        {ctx.fund ? null : (
          <span className="fw-bar" aria-hidden="true">
            <i style={{ width: `${barWidth(g.weightPct, ctx.maxWeight)}px` }} />
          </span>
        )}
        {pct(g.weightPct)}
        <span className="fw-sub">
          {orNa(g.valueUsd === null ? null : `$${g.valueUsd.toLocaleString('en-US', { maximumFractionDigits: 0 })}`, 'value not served')}
          {cap}
          {stale !== null && (
            <>
              {' '}
              <span className="fw-stale" title={`this row's record clock (${g.lead.profileUpdatedAt}) is older than its quote clock`}>
                ▲ record {stale}
              </span>
            </>
          )}
        </span>
      </>
    )
  }
  // Several accounts hold this security. The ruling forbids a summed percentage, so the cell states the account
  // count and each account's own served weight and value — no figure here is invented by adding two rows.
  return (
    <>
      <span className="fw-ph">{g.lines.length} accounts</span>
      {g.lines.map(l => (
        <span className="fw-sub" key={`${l.row.accountKey}:${l.row.symbol}`}>
          {l.accountLabel} · {pct(l.weightPct)} · {orNa(l.valueUsd === null ? null : `$${l.valueUsd.toLocaleString('en-US', { maximumFractionDigits: 0 })}`, 'value not served')}
        </span>
      ))}
    </>
  )
}

function peCell(g: Group): ReactNode {
  const f = g.lead.fundamentals
  const t = f?.peTrailing ?? null
  const fwd = f?.peForward ?? null
  if (t === null && fwd === null) return na('no served trailing or forward multiple for this row')
  return (
    <>
      {orNa(t === null ? null : multiple(t), 'no trailing multiple served')} → {orNa(fwd === null ? null : multiple(fwd), 'no forward multiple served')}
    </>
  )
}

function trendCell(g: Group): ReactNode {
  const f = g.lead.fundamentals
  const vs200 = f?.sma200Pct ?? null
  const off = f?.week52HighPct ?? null
  const rsi = f?.rsi ?? null
  const subs: string[] = []
  if (off !== null) subs.push(`${signedPct(off)} off 52w high`)
  if (rsi !== null) subs.push(`RSI ${rsi.toFixed(1)}`)
  if (vs200 === null) return na('no 200-day trend is served for this row')
  return (
    <>
      {signedPct(vs200)} vs 200d
      {subs.length > 0 && <span className="fw-sub">{subs.join(' · ')}</span>}
    </>
  )
}

function gainCell(g: Group): ReactNode {
  const r = g.lead
  const subs: string[] = []
  if (r.gainLoss !== null) subs.push(signedMoney(r.gainLoss))
  if (r.avgCost !== null) subs.push(`cost $${r.avgCost.toFixed(2)}`)
  if (r.gainLossPct === null) return na('no unrealized change is served for this row')
  return (
    <>
      {signedPct(r.gainLossPct)}
      {subs.length > 0 && <span className="fw-sub">{subs.join(' · ')}</span>}
    </>
  )
}

/**
 * The state word, then the short truth about the stop. The reference draws `Protected · resting GTC stop · read
 * 11-14`, and on the served book that row's stop is recorded but NOT active — "resting GTC stop" would read as
 * active protection, which the lead's checklist rules a defect, so the subline says `pending activation` instead
 * (the full sentence, the served basis, the reason and the next step all ride on the title). The word "Protected"
 * is the served state value, the same word the Holdings page's protection chip prints for the same row.
 */
function protectionSub(p: Protection): string {
  if (p.stop !== null) return `stop ${price(p.stop)}`
  if (p.state === 'PROTECTED') return 'pending activation'
  if (p.state === 'GAP') return 'no resting stop'
  return 'stop state unknown'
}

function protectionCell(g: Group): ReactNode {
  const p = g.lead.protection
  if (p === null) return na('protection does not apply to a cash row')
  const stale = p.stale === true
  const title = [stopSentence(p), p.basis ?? 'basis not served', p.reason, p.nextStep].filter(s => s !== '').join(' · ')
  return (
    <span title={title}>
      {PROTECTION_LABEL[p.state]}
      <span className={stale ? 'fw-sub fw-stale' : 'fw-sub'}>
        {protectionSub(p)}
        {stale ? ' (stale)' : ''} · read {readStamp(p.asOf)}
      </span>
    </span>
  )
}

function cell(key: ColumnKey, g: Group, ctx: CellCtx, onOpen?: (row: HoldingsRow) => void): ReactNode {
  switch (key) {
    case 'identity':
      return identityCell(g, ctx, onOpen)
    case 'weight':
      return weightCell(g, ctx)
    case 'pe':
      return peCell(g)
    case 'peg': {
      const peg = g.lead.fundamentals?.peg ?? null
      return orNa(peg === null ? null : decimal(peg), 'no PEG is served for this row')
    }
    case 'ytd': {
      const ytd = g.lead.fundamentals?.perfYtdPct ?? null
      return orNa(ytd === null ? null : signedPct(ytd), 'no year-to-date change is served for this row')
    }
    case 'trend':
      return trendCell(g)
    case 'beta': {
      const beta = g.lead.fundamentals?.beta ?? null
      return orNa(beta === null ? null : decimal(beta), 'no beta is served for this row')
    }
    case 'yield':
      return g.lead.yieldPct === null ? na('yield is not published for this instrument') : pct(g.lead.yieldPct)
    case 'gain':
      return gainCell(g)
    case 'protection':
      return protectionCell(g)
    case 'expense':
      return na('expense ratio is not served by this read — the wire carries no fund-fee field')
    case 'shortFloat': {
      const sf = g.lead.fundamentals?.shortFloatPct ?? null
      return sf === null ? na('short float is not served for this row') : pct(sf)
    }
    case 'ownership': {
      const f = g.lead.fundamentals
      if (f === null || f.insiderOwnPct === null || f.instOwnPct === null) return na('insider and institutional ownership are not served for this row')
      return `${pct(f.insiderOwnPct)} / ${pct(f.instOwnPct)}`
    }
  }
}

export interface SectionTableProps {
  section: Section
  columns: ColumnKey[]
  /** The word this table's share is measured against: `book` on the whole view, `view` behind a filter. */
  shareOf: 'book' | 'view'
  viewValue: ValueTotal
  onRowOpen?: (row: HoldingsRow) => void
}

/** One table card: the reference's section header, its columns, and one row per display group. */
export function SectionTable({ section, columns, shareOf, viewValue, onRowOpen }: SectionTableProps) {
  const fund = section.kind === 'fund'
  const ctx: CellCtx = { maxWeight: section.maxWeight, fund }
  const share = section.sharePct
  const heads = columns.map(k => (fund && k === 'identity' ? 'Fund · account' : COLUMN_LABEL[k]))
  return (
    <div className="fw-tablecard table-wrap">
      <div className="fw-section-head">
        {fund ? (
          // The reference's own fund header, verbatim — no count: a one-fund section would otherwise read "1 funds".
          <>
            Funds <span className="fw-count">· ETFs and mutual funds get fund columns, not empty P/E cells</span>
          </>
        ) : (
          <>
            Equities{' '}
            <span className="fw-count">
              · {section.groups.length} {section.groups.length === 1 ? 'position' : 'positions'} ·{' '}
              {share === null ? 'no valued rows to divide by' : `${share.toFixed(1)}% of ${shareOf}`}
              {share !== null && (
                <span
                  className="fw-tag"
                  title={`Σ served market value in this section / Σ served market value in view, ${valuedText(viewValue)}; no percentages are summed`}
                >
                  derived
                </span>
              )}
            </span>
          </>
        )}
      </div>
      {/* The table's floor is the reference's, kept as a floor: `min(W, 100%)` holds every column's metric and
          stops the table from standing 4 px wider than the shell's content column (1176 at 1440) — measured. */}
      {section.groups.length === 0 ? (
        <p className="fw-empty">No {fund ? 'fund' : 'equity'} rows in this view.</p>
      ) : (
        <table style={{ minWidth: `min(${fund ? FUND_MIN_WIDTH : EQUITY_MIN_WIDTH}px, 100%)` }}>
          <thead>
            <tr>
              {columns.map((k, i) => (
                <th key={k} scope="col">
                  {heads[i]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {section.groups.map(g => (
              <tr
                key={g.key}
                data-group={g.key}
                onClick={onRowOpen === undefined ? undefined : () => onRowOpen(g.lead)}
              >
                {columns.map(k => (
                  <td key={k}>{cell(k, g, ctx, onRowOpen)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

/** The reference's collapsed cash line: one flex row, the account count, the share and the total. */
export function CashLineRow({
  section,
  viewValue,
  shareOf,
  onRowOpen,
}: {
  section: CashLine
  viewValue: ValueTotal
  /** The word the share is measured against: the reference's `book`, or `view` behind a filter. */
  shareOf: 'book' | 'view'
  onRowOpen?: (row: HoldingsRow) => void
}) {
  const share = section.sharePct
  return (
    <details className="fw-cash">
      <summary>
        <span>
          <strong>Cash &amp; cash investments</strong>{' '}
          <span className="fw-ph">
            · {section.rows.length} {section.rows.length === 1 ? 'row' : 'rows'} across accounts, collapsed
          </span>
        </span>
        <span>
          {share === null ? 'share not served' : `${share.toFixed(1)}% of ${shareOf}`}
          <span
            className="fw-tag"
            title={`Σ served market value of the cash rows / Σ served market value in view, ${valuedText(viewValue)}`}
          >
            derived
          </span>{' '}
          ·{' '}
          {section.value.valued === 0
            ? na('a cash row has no served value, so no total is printed')
            : `$${section.value.usd.toLocaleString('en-US', { maximumFractionDigits: 0 })}`}
        </span>
      </summary>
      <div className="fw-cash-body">
        <ul>
          {section.rows.map(r => (
            <li key={`${r.accountKey}:${r.symbol}`}>
              <button
                type="button"
                className="fw-rowopen"
                onClick={() => onRowOpen?.(r)}
                aria-label={`Open ${r.symbol} details`}
              >
                {r.name || r.symbol}
              </button>{' '}
              · {r.accountLabel} ·{' '}
              {r.marketValue === null ? na('value not served') : `$${r.marketValue.toFixed(2)}`}
            </li>
          ))}
        </ul>
      </div>
    </details>
  )
}
