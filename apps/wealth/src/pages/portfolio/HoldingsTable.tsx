// The Holdings table: one renderer per preset, every cell reading a SERVED field.
//
// Rules held here:
//   * the client never computes a value — no shares x price, no P/L arithmetic, no score, no row sums;
//   * a null renders as "N/A — <reason>", never as 0 (an unpriced row is not a worthless row);
//   * no cell carries meaning by colour alone: the protection cell is text + icon glyph + tooltip;
//   * a P/E cell is a valuation-assessment@1 status word or the served multiple — and an UNASSESSED
//     assessment that carries a value keeps the value (last known good), via `cells.peCellText`.

import type { ReactNode } from 'react'
import type { Cue, CueLevel } from '../../contracts/cue'
import { cue } from '../../contracts/cue'
import { assessmentSummary, peCellText } from './cells'
import type { HoldingsRow, Protection } from './contract'
import { age, marketCapText, money, pct, price, shares, signedMoney, signedPct, unavailable } from './format'
import type { Preset } from './presets'

const ICON_GLYPH: Record<Cue['icon'], string> = {
  ok: '✓',
  caution: '!',
  alert: '✕',
  info: 'i',
  unassessed: '?',
}

// The four class names below must be styled by the shell slice (cc-opus-3). One line in its contract, not here.
function CueBadge({ c }: { c: Cue }) {
  return (
    <span className={`cue cue-${c.level.toLowerCase()}`} title={c.tooltip}>
      <span aria-hidden="true">{ICON_GLYPH[c.icon]} </span>
      {c.label}
    </span>
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
  switch (key) {
    case 'security':
      return (
        <>
          <strong>{row.symbol}</strong>
          <br />
          <small>
            {row.name} · {row.accountLabel} · {row.accountKey}
          </small>
        </>
      )
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
      const c = protectionCue(row)
      return c ? <CueBadge c={c} /> : unavailable('protection does not apply to cash')
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
      const c = protectionCue(row)
      return c ? <CueBadge c={c} /> : unavailable('protection does not apply to cash')
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

export function HoldingsTable({ rows, preset, onRowOpen }: {
  rows: HoldingsRow[]
  preset: Preset
  /** Opens the row's detail drawer. Absent (fixture invariants): the identity cell is plain text. */
  onRowOpen?: (row: HoldingsRow) => void
}) {
  return (
    <table>
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
          <tr key={`${r.accountKey}:${r.symbol}`}>
            {preset.columns.map((c, i) =>
              i === 0 ? (
                <th key={c.key} scope="row">
                  {onRowOpen && c.key === 'security' ? (
                    <button type="button" onClick={() => onRowOpen(r)} title="Open this row's detail">
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
    </table>
  )
}

/** Kept for the page's freshness line and for callers that need the same wording. */
export function freshnessLine(ageSeconds: number | null, staleAfterSeconds: number, stale: boolean): string {
  const limit = age(staleAfterSeconds)
  // An age the response did not serve is said to be unserved — never rendered as 0 s.
  const aged = ageSeconds === null ? 'age not served' : `${age(ageSeconds)} old`
  return stale
    ? `Last known good — ${aged}, past the ${limit} limit. These values are not current.`
    : `${aged} · stale after ${limit}`
}
