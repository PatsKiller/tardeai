// The phone treatment, ported from v04's own `.position-cards` block: at ≤510 px the reference hides the
// desktop `.holdings-table` and shows one card per holding. This file is that card.
//
// Every number is a served field, exactly as in the table: nothing is summed, nothing is derived from
// shares × price, and a missing value renders "N/A — <reason>", never 0. A cash row keeps its own value —
// v04 collapses cash to one line, which is a sum this book cannot make because it can carry a cash row per
// account.

import type { ReactNode } from 'react'
import { Tag, type Tone } from '../../components/primitives'
import { CashMark } from './HoldingsTable'
import type { HoldingsRow, Protection } from './contract'
import { money, moneyTone, pct, price, shares, signedMoney, signedPct, toneClass, unavailable } from './format'

const PROTECTION_TAG: Record<Protection['state'], { tone: Tone; label: string }> = {
  PROTECTED: { tone: 'good', label: 'Protected' },
  GAP: { tone: 'bad', label: 'Gap' },
  // Amber, never green: an unknown protection state is not a covered one.
  UNKNOWN: { tone: 'warn', label: 'Unknown' },
}

function unrealized(row: HoldingsRow): ReactNode {
  if (row.gainLoss === null) {
    return row.avgCost === null
      ? unavailable('no basis served, so no unrealized change')
      : unavailable('no unrealized change served')
  }
  // The signed change carries its direction in colour; the text still states it (one policy, format.ts).
  return (
    <span className={toneClass(moneyTone(row.gainLoss)) || undefined}>
      {signedMoney(row.gainLoss)} · {signedPct(row.gainLossPct, 1)}
    </span>
  )
}

function CashCard({ row }: { row: HoldingsRow }) {
  // The served value of this cash row, with the account it sits in. No two cash rows are added together.
  // The mark is the same one the desktop table draws (one identity, two surfaces); no logo is fetched.
  return (
    <article className="position-card row-between">
      <b className="cash-card-head">
        <CashMark />
        Cash &amp; sweep · {row.accountLabel}
      </b>
      <b>{money(row.marketValue)}</b>
    </article>
  )
}

function PositionCard({ row, onOpen }: { row: HoldingsRow; onOpen?: (row: HoldingsRow) => void }) {
  if (row.kind === 'CASH') return <CashCard row={row} />
  const tag = row.protection ? PROTECTION_TAG[row.protection.state] : null
  return (
    <article className="position-card">
      <div className="row-between">
        <b className="ticker-symbol">{row.symbol}</b>
        <small className="muted">
          <span className="ticker-name">{row.name}</span> · {row.accountLabel}
        </small>
        {tag ? <Tag tone={tag.tone} title={row.protection?.reason}>{tag.label}</Tag> : null}
      </div>
      <div className="numbers">
        <div>
          <small>Current mark</small>
          <b>{row.worthless ? unavailable('no price served for a worthless identifier') : price(row.price)}</b>
        </div>
        <div>
          <small>Average cost / share</small>
          <b>{row.avgCost === null ? unavailable('no basis served') : money(row.avgCost)}</b>
        </div>
        <div>
          <small>Market value</small>
          <b>{row.marketValue === null ? unavailable('unpriced — no price served') : money(row.marketValue)}</b>
        </div>
        <div>
          <small>Unrealized gain / loss</small>
          <b>{unrealized(row)}</b>
        </div>
      </div>
      <div className="row-between">
        <span className="small muted">
          {shares(row.shares)} shares · {pct(row.portfolioPct, 1)} weight
        </span>
        {onOpen ? (
          <button type="button" className="small" onClick={() => onOpen(row)}>
            Details →
          </button>
        ) : null}
      </div>
    </article>
  )
}

export function PositionCards({ rows, onRowOpen }: { rows: HoldingsRow[]; onRowOpen?: (row: HoldingsRow) => void }) {
  return (
    <div className="position-cards">
      {rows.map(r => (
        <PositionCard key={`${r.accountKey}:${r.symbol}`} row={r} onOpen={onRowOpen} />
      ))}
    </div>
  )
}
