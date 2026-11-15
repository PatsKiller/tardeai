// The Fundamentals table: the Holdings `fundamentals` preset's eight columns, rendered over the adapter's rows.
//
// The columns, headers, method note and limits come from `presets.ts` itself — this file renders the approved
// preset, it does not restate it. What it adds is the route's two fixed cells and the market-cap provenance line:
//
//   * Peer TTM median and Evidence print `not wired — valuation-assessment@1` (evidence.ts owns the literal and
//     the reasons); neither cell applies a status, a cutoff or a colour;
//   * Market cap prints the served cap and, under it, the profile record's source and clock — the only provenance
//     the row carries (see evidence.MARKET_CAP_PROVENANCE_NOTE).
//
// Rules inherited from the reviewed Holdings table, because they are the preset's decisions:
//   * a cash row takes the preset's cash rule for every column but identity and price;
//   * a null is `N/A` with its full reason on the title and the accessible name, never a 0;
//   * the identity cell is bounded (the reviewed 250 px bound) and does not print the internal account key in
//     the cell; the full name, label and key stay on the title and in the row detail;
//   * every table sits in a `.table-wrap` (design-fidelity rule 5).

import type { CSSProperties, ReactNode } from 'react'
import type { HoldingsRow } from '../portfolio/contract'
import type { Preset } from '../portfolio/presets'
import {
  CASH_COLUMN,
  MARKET_CAP_PROVENANCE_NOTE,
  assessmentNote,
  assessmentText,
  marketCapProvenance,
  marketCapText,
  peerMedianNote,
  peerMedianText,
  peNote,
  peText,
  priceText,
  yieldText,
} from './evidence'

/**
 * The reviewed Holdings identity cell bounds its name at 250 px. This preset has two columns that cannot be
 * shortened (each prints the route's literal), so the bound is narrower here — measured at 1280: at 250 the two
 * literal columns broke mid-word; at 150 the full literal costs two clean lines and the name stays ellipsised.
 */
const TRUNCATE: CSSProperties = {
  display: 'block',
  maxWidth: 150,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
}

/**
 * The two fixed literals may BREAK between their words — the text is unchanged, the column is not 224 px wide
 * on a phrase nothing can shorten. A `<wbr>` before the contract token breaks the line there; the token itself
 * stays nowrap, so the column is never narrower than the word a reviewer greps for. Measured at 1280: nowrap
 * literals held each column 224 px and scrolled the Evidence column off the page; with this break each literal
 * costs two clean lines and the table fits its wrap.
 */
function literalCell(text: string, note: string): ReactNode {
  const cut = text.lastIndexOf(' ')
  const head = text.slice(0, cut)
  const token = text.slice(cut + 1)
  return (
    <span style={{ whiteSpace: 'normal' }} title={note}>
      {head}{' '}
      <wbr />
      <span style={{ whiteSpace: 'nowrap' }}>{token}</span>
    </span>
  )
}

const FLAT_BUTTON: CSSProperties = {
  background: 'transparent',
  border: 0,
  padding: 0,
  margin: 0,
  color: 'inherit',
  font: 'inherit',
  textAlign: 'left',
  cursor: 'pointer',
}

/** A missing cell: the token prints, the reason rides the title and the accessible name (the reviewed rule). */
function compactMissing(reason: string): ReactNode {
  return (
    <span title={reason} aria-label={`N/A — ${reason}`}>
      N/A
    </span>
  )
}

/** `peText`/`yieldText` state their reason inline; the cell prints `N/A` and keeps the sentence on the title. */
function compactCell(text: string): ReactNode {
  const m = /^N\/A — (.+)$/.exec(text)
  return m ? compactMissing(m[1]) : text
}

function identityCell(row: HoldingsRow): ReactNode {
  const initials = row.symbol.replace(/[^A-Za-z0-9]/g, '').slice(0, 2).toUpperCase()
  return (
    <span className="ticker">
      <span className="ticker-icon" aria-hidden="true">
        {initials || '—'}
      </span>
      <span>
        <strong>{row.symbol}</strong>
        <br />
        <small style={TRUNCATE} title={`${row.name} · ${row.accountLabel} · account ${row.accountKey}`}>
          {row.name} · {row.accountLabel}
        </small>
      </span>
    </span>
  )
}

/** A served cap with its provenance line; an absent cap is a reason, and carries no provenance to print. */
function marketCapCell(row: HoldingsRow): ReactNode {
  const text = marketCapText(row)
  if (text.startsWith('N/A — ')) return compactMissing(text.slice('N/A — '.length))
  return (
    <span title={`market cap served on the row · ${marketCapProvenance(row)}`}>
      {text}
      <br />
      <small style={{ whiteSpace: 'normal', overflowWrap: 'anywhere' }}>{marketCapProvenance(row)}</small>
    </span>
  )
}

/** One cell of the approved preset. No other column renders, and nothing here derives a value. */
export function fundamentalsCell(row: HoldingsRow, key: string): ReactNode {
  if (row.kind === 'CASH' && key !== 'security' && key !== 'price') return compactMissing(CASH_COLUMN)
  switch (key) {
    case 'security':
      return identityCell(row)
    case 'price':
      return compactCell(priceText(row))
    case 'peTrailing':
      return (
        <span title={peNote(row, 'peTrailing')}>{compactCell(peText(row, 'peTrailing'))}</span>
      )
    case 'peForward':
      return (
        <span title={peNote(row, 'peForward')}>{compactCell(peText(row, 'peForward'))}</span>
      )
    case 'peerMedian':
      return literalCell(peerMedianText(), peerMedianNote())
    case 'marketCap':
      return marketCapCell(row)
    case 'yield':
      return compactCell(yieldText(row))
    case 'evidence':
      return literalCell(assessmentText(), assessmentNote())
    default:
      return compactMissing(`no renderer for column ${key}`)
  }
}

export function FundamentalsTable({ rows, preset, onRowOpen }: {
  rows: HoldingsRow[]
  preset: Preset
  /** Opens the row's own detail drawer; the element that opened it is handed back for focus return. */
  onRowOpen?: (row: HoldingsRow, origin?: HTMLElement) => void
}) {
  return (
    <div className="table-wrap"><table>
      <thead>
        <tr>
          {preset.columns.map(c => (
            <th key={c.key} scope="col">
              {c.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map(r => (
          <tr
            key={`${r.accountKey}:${r.symbol}`}
            className={r.kind === 'CASH' ? 'cash-row' : undefined}
            data-asset={`${r.accountKey}:${r.symbol}`}
            tabIndex={-1}
            onClick={onRowOpen ? e => onRowOpen(r, e.currentTarget) : undefined}
          >
            {preset.columns.map((c, i) =>
              i === 0 ? (
                <th key={c.key} scope="row">
                  {onRowOpen && c.key === 'security' ? (
                    <button
                      type="button"
                      className="quiet"
                      onClick={e => {
                        e.stopPropagation()
                        onRowOpen(r, e.currentTarget)
                      }}
                      title="Open this row's detail"
                      style={FLAT_BUTTON}
                    >
                      {fundamentalsCell(r, c.key)}
                    </button>
                  ) : (
                    fundamentalsCell(r, c.key)
                  )}
                </th>
              ) : (
                <td key={c.key}>{fundamentalsCell(r, c.key)}</td>
              ),
            )}
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr>
          {/* The footnote wraps: the reference's nowrap belongs to data cells, and a prose footnote would set
              the table's minimum width from its longest sentence (the reviewed table's measured defect). */}
          <td colSpan={preset.columns.length} style={{ whiteSpace: 'normal' }}>
            <p>{preset.methodNote}</p>
            {preset.limits.length > 0 && (
              <ul>
                {preset.limits.map(l => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            )}
            <p className="small muted">{MARKET_CAP_PROVENANCE_NOTE}</p>
          </td>
        </tr>
      </tfoot>
    </table></div>
  )
}
