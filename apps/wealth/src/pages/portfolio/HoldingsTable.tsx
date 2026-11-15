// The Holdings table: one renderer per preset, every cell reading a SERVED field.
//
// Rules held here:
//   * the client never computes a value — no shares x price, no P/L arithmetic, no score, no row sums;
//   * a null renders as "N/A — <reason>", never as 0 (an unpriced row is not a worthless row);
//   * no cell carries meaning by colour alone: the protection cell is text + icon glyph + tooltip;
//   * a P/E cell is a valuation-assessment@1 status word or the served multiple — and an UNASSESSED
//     assessment that carries a value keeps the value (last known good), via `cells.peCellText`.

import type { CSSProperties, ReactNode } from 'react'
import type { Cue, CueLevel } from '../../contracts/cue'
import { cue } from '../../contracts/cue'
import { Tag, type Tone } from '../../components/primitives'
import { assessmentSummary, peCellText } from './cells'
import type { HoldingsRow, Protection } from './contract'
import { age, marketCapText, money, pct, price, shares, signedMoney, signedPct, unavailable } from './format'
import type { Preset } from './presets'

/**
 * The protection cell is v04's `.tag` chip (good / warn / bad), not a bespoke `.cue-*` class that no
 * stylesheet defines — measured 2026-11-15: `.cue` appears nowhere in v02.css or v04.css, so the cell
 * was rendering as coloured plain text. The word carries the meaning; the tooltip carries the reason,
 * the stop and the read clock.
 */
const CUE_TAG_TONE: Record<Cue['level'], Tone> = { GREEN: 'good', AMBER: 'warn', RED: 'bad', NEUTRAL: '' }

function ProtectionTag({ row }: { row: HoldingsRow }) {
  const c = protectionCue(row)
  if (!c) return unavailable('protection does not apply to cash')
  return (
    <Tag tone={CUE_TAG_TONE[c.level]} title={`${c.label}. ${c.tooltip}`}>
      {c.label}
    </Tag>
  )
}

const PROTECTION_CUE: Record<Protection['state'], { level: CueLevel; label: string; icon: Cue['icon'] }> = {
  PROTECTED: { level: 'GREEN', label: 'Protected', icon: 'ok' },
  GAP: { level: 'RED', label: 'Gap', icon: 'alert' },
  UNKNOWN: { level: 'NEUTRAL', label: 'Unknown', icon: 'unassessed' },
}

function protectionCue(row: HoldingsRow): Cue | null {
  const p = row.protection
  if (!p) return null
  const meta = PROTECTION_CUE[p.state]
  const stopText = p.stop === null ? 'no resting stop' : `stop ${price(p.stop)}`
  const readText = p.asOf === null ? 'read clock absent' : `read ${p.asOf}${p.stale ? ' (stale)' : ''}`
  return cue(meta.level, meta.label, meta.icon, `${p.reason}; ${stopText}; ${readText}; ${p.nextStep}`)
}

function valueCell(row: HoldingsRow): ReactNode {
  if (row.marketValue === null) return unavailable('unpriced — no price served')
  return row.worthless ? `${money(row.marketValue)} · worthless` : money(row.marketValue)
}

function cell(row: HoldingsRow, key: string): ReactNode {
  // A cash row is not a security: most columns do not apply. v04 prints `N/A` / `—` here, and a full
  // "N/A — protection does not apply to cash" in four columns is what pushed this table 233 px past its
  // container at 1440. The claim is unchanged; the reason moves one hover (and the row drawer) away.
  if (row.kind === 'CASH' && !['security', 'price', 'value', 'weight'].includes(key)) {
    return <span title="this column does not apply to a cash row">N/A</span>
  }
  switch (key) {
    case 'security': {
      // v04's ticker cell: the chip carries the symbol's initials, then symbol / name · account.
      const initials = row.symbol.replace(/[^A-Za-z0-9]/g, '').slice(0, 2).toUpperCase()
      return (
        <span className="ticker">
          <span className="ticker-icon" aria-hidden="true">
            {initials || '—'}
          </span>
          <span>
            <strong>{row.symbol}</strong>
            <br />
            <small>
              {row.name} · {row.accountLabel} · {row.accountKey}
            </small>
          </span>
        </span>
      )
    }
    case 'shares':
      return shares(row.shares)
    case 'price':
      return row.worthless ? unavailable('no price served for a worthless identifier') : price(row.price)
    case 'avgCost':
      return row.avgCost === null ? unavailable('no basis served') : money(row.avgCost)
    case 'value':
      return valueCell(row)
    case 'day':
      if (row.dayChange === null) return unavailable('no day change served')
      return (
        <>
          {signedMoney(row.dayChange)}
          <br />
          <small>{signedPct(row.dayChangePct)}</small>
        </>
      )
    case 'unrealized':
      // The basis and the change are two fields: name the one that is absent (F7).
      if (row.gainLoss === null) {
        return row.avgCost === null ? unavailable('no basis served, so no unrealized change') : unavailable('no unrealized change served')
      }
      return (
        <>
          {signedMoney(row.gainLoss)}
          <br />
          <small>{signedPct(row.gainLossPct)}</small>
        </>
      )
    case 'weight':
      return pct(row.portfolioPct)
    case 'protection': {
      return <ProtectionTag row={row} />
    }
    case 'peTrailing':
      return peCellText(row.valuation, 'trailing')
    case 'peForward':
      return peCellText(row.valuation, 'forward')
    case 'peerMedian':
      return unavailable('no reader serves a peer median')
    case 'marketCap':
      return marketCapText(row.marketCapB, row.kind === 'CASH' ? 'cash has no market cap' : 'not published for this instrument')
    case 'yield':
      return row.yieldPct === null ? unavailable('not published for this instrument') : pct(row.yieldPct)
    case 'evidence':
      return assessmentSummary(row.valuation)
    case 'held':
      return shares(row.shares)
    case 'stop':
      if (!row.protection) return unavailable('protection does not apply to cash')
      return row.protection.stop === null ? unavailable('no resting stop') : price(row.protection.stop)
    case 'stopBasis':
      return row.protection?.basis ?? unavailable('no basis recorded')
    case 'stopRead':
      return row.protection?.asOf
        ? `${row.protection.asOf}${row.protection.stale ? ' (stale)' : ''}`
        : unavailable('no read clock for this account')
    case 'protectionState': {
      return <ProtectionTag row={row} />
    }
    case 'protectionNext':
      return row.protection?.nextStep ?? unavailable('protection does not apply to cash')
    case 'method':
      return row.fib ? 'Fibonacci retracement · 52-week range' : unavailable('no ladder served for this row')
    case 'ladder':
      if (!row.fib) return unavailable('no ladder served for this row')
      if (row.fib.levels.length === 0) return `nearest only (${price(row.fib.nearestLevel)})`
      return row.fib.levels.map(l => `${Math.round(l.ratio * 1000) / 10}% ${price(l.price)}`).join(' · ')
    case 'nearestLevel':
      return row.fib ? price(row.fib.nearestLevel) : unavailable('no ladder served for this row')
    case 'fromHigh':
      return row.fib ? pct(row.fib.retracementFromHighPct) : unavailable('no ladder served for this row')
    case 'range':
      return row.fib
        ? `${price(row.fib.window.low)} – ${price(row.fib.window.high)} · as of ${row.fib.window.asOf}`
        : unavailable('no ladder served for this row')
    default:
      return unavailable(`no renderer for column ${key}`)
  }
}

// The row-open control has to read as the reference's plain ticker cell, not as a chrome button; the
// design sheets are reference-locked, so the reset lives here rather than in CSS. Focus stays visible.
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

export function HoldingsTable({ rows, preset, onRowOpen }: {
  rows: HoldingsRow[]
  preset: Preset
  /** Opens the row's detail drawer. Absent (fixture invariants): the identity cell is plain text. */
  onRowOpen?: (row: HoldingsRow) => void
}) {
  // The table keeps its intrinsic width (v02: min-width 720, nowrap cells); this scroll container
  // is what stops that width from widening the page, so every caller inherits containment.
  return (
    <div className="table-wrap"><table>
      <caption>
        {preset.label} preset · {rows.length} row{rows.length === 1 ? '' : 's'}
      </caption>
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
          // v04 makes the row itself the target (`tr[data-asset]`: pointer + hover); the button inside the
          // first cell is what a keyboard or a screen reader operates, so the row click is convenience only.
          <tr
            key={`${r.accountKey}:${r.symbol}`}
            className={r.kind === 'CASH' ? 'cash-row' : undefined}
            data-asset={`${r.accountKey}:${r.symbol}`}
            onClick={onRowOpen ? () => onRowOpen(r) : undefined}
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
                        onRowOpen(r)
                      }}
                      title="Open this row's detail"
                      style={FLAT_BUTTON}
                    >
                      {cell(r, c.key)}
                    </button>
                  ) : (
                    cell(r, c.key)
                  )}
                </th>
              ) : (
                <td key={c.key}>{cell(r, c.key)}</td>
              ),
            )}
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr>
          <td colSpan={preset.columns.length}>
            <p>{preset.methodNote}</p>
            {preset.limits.length > 0 && (
              <ul>
                {preset.limits.map(l => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            )}
          </td>
        </tr>
      </tfoot>
    </table></div>
  )
}

/** Kept for the page's freshness line and for callers that need the same wording. */
export function freshnessLine(ageSeconds: number | null, staleAfterSeconds: number | null, stale: boolean): string {
  // An age or a limit the response did not serve is said to be unserved — never rendered as 0 s.
  const aged = ageSeconds === null ? 'age not served' : `${age(ageSeconds)} old`
  const limit = staleAfterSeconds === null ? 'limit not served' : age(staleAfterSeconds)
  if (!stale) return `${aged} · stale after ${limit}`
  if (staleAfterSeconds === null)
    return `Last known good — ${aged}; the response served no stale limit (limit not served). These values are not current.`
  return `Last known good — ${aged}, past the ${limit} limit. These values are not current.`
}
