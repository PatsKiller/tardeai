// The Holdings table: one renderer per preset, every cell reading a SERVED field.
//
// Rules held here:
//   * the client never computes a value — no shares x price, no P/L arithmetic, no score, no row sums;
//   * a null renders as `N/A` with its reason in the cell's title and accessible name, never as 0 (an unpriced row
//     is not a worthless row). The full reason is also in the preset's notes under the table and in the row drawer;
//   * no cell carries meaning by colour alone: the protection cell is text + icon glyph + tooltip;
//   * a P/E cell is a valuation-assessment@1 status word or the served multiple — and an UNASSESSED
//     assessment that carries a value keeps the value (last known good), via `cells.peCellText`;
//   * the identity cell is bounded and does not print the internal account key (r2, verdict 2026-11-15T0342Z B1):
//     measured live, the unbounded name+label+key held this column at 516 px of a 1,409 px table in a 1,136 px box.

import { isValidElement } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import type { Cue, CueLevel } from '../../contracts/cue'
import { cue } from '../../contracts/cue'
import { Tag, type Tone } from '../../components/primitives'
import { assessmentSummary, peCellText } from './cells'
import type { HoldingsRow, Protection } from './contract'
import { age, marketCapText, money, moneyTone, multiple, pct, price, shares, signedMoney, signedPct, toneClass, unavailable } from './format'
import type { Preset } from './presets'

/**
 * The protection cell is v04's `.tag` chip (good / warn / bad), not a bespoke `.cue-*` class that no
 * stylesheet defines — measured 2026-11-15: `.cue` appears nowhere in v02.css or v04.css, so the cell
 * was rendering as coloured plain text. The word carries the meaning; the tooltip carries the reason,
 * the stop and the read clock.
 */
const CUE_TAG_TONE: Record<Cue['level'], Tone> = { GREEN: 'good', AMBER: 'warn', RED: 'bad', NEUTRAL: '' }

/**
 * The protection chip, returned as the element tree itself (not wrapped in a component) so the CSV export can
 * walk the very node the table renders and read its label — a component's children are opaque to that walk.
 * The rendered output is unchanged.
 */
function protectionCell(row: HoldingsRow): ReactNode {
  const c = protectionCue(row)
  if (!c) return compactMissing('protection does not apply to a cash row')
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
  const readText = p.asOf === null ? 'read clock absent' : `read ${p.asOf}${p.stale === true ? ' (stale)' : ''}`
  return cue(meta.level, meta.label, meta.icon, `${p.reason}; ${stopText}; ${readText}; ${p.nextStep}`)
}

// A real book's names are long (measured 2026-11-15 on the live payload: the unbounded identity cell was 516 px and
// the table 1,409 px inside a 1,136 px wrap). The design sheets are reference-locked, so the bound is applied here,
// not in CSS. The full name, account label and account key stay on the title and in the row drawer.
//
// The bound is 250, not 290: measured on the live payload at 1280 (wrap 976), a 290 px bound held this column at
// 312 px and left the Protection preset 30 px past the wrap. The reviewer's zero-overflow test covers 1280, so the
// bound is set where the widest preset fits.
const TRUNCATE: CSSProperties = { display: 'block', maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }

/**
 * A missing cell. The reason travels with the cell (title + aria-label) and in full under the table, but the cell
 * prints `N/A`: measured on the live payload, spelling the reason in every cell took the Overview table to 1,409 px
 * and the Fundamentals preset to 1,812 px against a 1,136 px wrap.
 */
function compactMissing(reason: string): ReactNode {
  return (
    <span title={reason} aria-label={`N/A — ${reason}`}>
      N/A
    </span>
  )
}

/**
 * `peCellText` / `assessmentSummary` return their reason inline (`N/A — no assessment served`), which is right for the
 * drawer and for the cell's accessible name but wrong for a nowrap column: measured live at 1280, the two P/E columns
 * held 180 px each on that sentence and pushed the Fundamentals preset 118 px past a 976 px wrap. The reason rides the
 * title/aria-label instead.
 */
function compactCell(text: string): ReactNode {
  const m = /^N\/A — (.+)$/.exec(text)
  return m ? compactMissing(m[1]) : text
}

/**
 * The wire serves a Fibonacci ladder but NO clock for it (`adapter.ts` leaves `fib` null rather than dating it with
 * the quote clock). A cell that said "no ladder is served" would be untrue: the ladder is served, the clock is not.
 */
const LADDER_NO_CLOCK = 'a ladder is served without a clock, so it is not dated here'

function valueCell(row: HoldingsRow): ReactNode {
  if (row.marketValue === null) return unavailable('unpriced — no price served')
  return row.worthless ? `${money(row.marketValue)} · worthless` : money(row.marketValue)
}

/**
 * A P/E cell: the SERVED provider multiple when the row carries one (wire `pe` / `forward_pe`), otherwise the
 * valuation-assessment@1 status word from `peCellText`. The two are different instruments of evidence, so the
 * cell names which one it is printing on hover instead of letting a bare multiple pass as an assessment.
 */
function peServed(row: HoldingsRow, which: 'peTrailing' | 'peForward'): ReactNode {
  const value = row.fundamentals?.[which] ?? null
  const wire = which === 'peTrailing' ? 'pe' : 'forward_pe'
  if (value !== null) {
    return (
      <span title={`served provider multiple · wire ${wire} · not a valuation-assessment@1 assessment`}>
        {multiple(value)}
      </span>
    )
  }
  if (row.valuation === null) return compactMissing(`no served ${wire} multiple and no assessment for this row`)
  return peCellText(row.valuation, which === 'peTrailing' ? 'trailing' : 'forward')
}

/** A served technical cell. Missing is "N/A — <reason>"; nothing here is compared to a threshold. */
function technical(value: number | null, fmt: (v: number) => string, why: string): ReactNode {
  return value === null ? unavailable(why) : fmt(value)
}

/**
 * The cash row's mark: a struck coin, drawn from the current text colour (the shell's `--green` via
 * `.cash-icon`), never a downloaded logo. Decorative for assistive tech — the row's own "CASH" symbol and the
 * table caption already say it is cash, and `rawText` drops `aria-hidden` nodes so the CSV is unchanged.
 */
export function CashMark() {
  return (
    <svg className="cash-icon" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
      <circle cx="10" cy="10" r="8.25" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M10 5.6v8.8M12.4 7.7c0-.9-1.1-1.5-2.4-1.5s-2.4.6-2.4 1.6c0 2.3 4.8 1.1 4.8 3.4 0 1-1.1 1.6-2.4 1.6s-2.4-.5-2.4-1.5"
        fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  )
}


function cell(row: HoldingsRow, key: string): ReactNode {
  // A cash row is not a security: most columns do not apply. v04 prints `N/A` / `—` here; the reason rides the
  // title, and the row drawer states it per field.
  if (row.kind === 'CASH' && !['security', 'price', 'value', 'weight'].includes(key)) {
    return compactMissing('this column does not apply to a cash row')
  }
  switch (key) {
    case 'security': {
      // v04's ticker cell led with a two-letter initials chip. Two letters are not an identity: they are a
      // decorative code that repeats the symbol beside them and reads as a logo (operator route
      // 2026-11-15T1555Z). A cash row instead carries a cash mark — it has no security identity to show; a
      // security carries its symbol, set as the row's handle, and its name in readable type. No logo is
      // fetched and no brand is implied. The internal account key is NOT printed in the cell (it identifies
      // the broker record, not the account); it is on the title and in the drawer.
      return (
        <span className="ticker">
          {row.kind === 'CASH' && <CashMark />}
          <span>
            <strong className="ticker-symbol">{row.symbol}</strong>
            <br />
            <small style={TRUNCATE} title={`${row.name} · ${row.accountLabel} · account ${row.accountKey}`}>
              <span className="ticker-name">{row.name}</span> · {row.accountLabel}
            </small>
          </span>
        </span>
      )
    }
    case 'shares':
      return shares(row.shares)
    case 'price':
    case 'mark':
      return row.worthless ? compactMissing('no price served for a worthless identifier') : price(row.price)
    case 'avgCost':
      return row.avgCost === null ? compactMissing('no basis served') : money(row.avgCost)
    case 'value':
      return valueCell(row)
    case 'day':
      if (row.dayChange === null) return compactMissing('no day change served')
      return (
        <>
          <span className={toneClass(moneyTone(row.dayChange)) || undefined}>{signedMoney(row.dayChange)}</span>
          <br />
          <small>{signedPct(row.dayChangePct)}</small>
        </>
      )
    case 'unrealized':
      // The basis and the change are two fields: name the one that is absent (F7).
      if (row.gainLoss === null) {
        return compactMissing(row.avgCost === null ? 'no basis served, so no unrealized change' : 'no unrealized change served')
      }
      return (
        <>
          <span className={toneClass(moneyTone(row.gainLoss)) || undefined}>{signedMoney(row.gainLoss)}</span>
          <br />
          <small>{signedPct(row.gainLossPct)}</small>
        </>
      )
    case 'weight':
      return pct(row.portfolioPct)
    case 'protection': {
      return protectionCell(row)
    }
    case 'peTrailing':
      return peServed(row, 'peTrailing')
    case 'peForward':
      return peServed(row, 'peForward')
    case 'rsi':
      return technical(row.fundamentals?.rsi ?? null, v => v.toFixed(1), 'no RSI served for this row')
    case 'sma20':
      return technical(row.fundamentals?.sma20Pct ?? null, v => pct(v), 'no SMA20 served for this row')
    case 'sma50':
      return technical(row.fundamentals?.sma50Pct ?? null, v => pct(v), 'no SMA50 served for this row')
    case 'sma200':
      return technical(row.fundamentals?.sma200Pct ?? null, v => pct(v), 'no SMA200 served for this row')
    case 'week52':
      return technical(row.fundamentals?.week52HighPct ?? null, v => pct(v), 'no 52-week high served for this row')
    case 'peerMedian':
      return compactMissing('no reader serves a peer median on any route')
    case 'marketCap':
      return row.marketCapB === null
        ? compactMissing(row.kind === 'CASH' ? 'cash has no market cap' : 'not published for this instrument')
        : marketCapText(row.marketCapB)
    case 'yield':
      return row.yieldPct === null ? compactMissing('not published for this instrument') : pct(row.yieldPct)
    case 'evidence':
      return row.valuation === null ? compactMissing('no valuation assessment is wired on this route') : compactCell(assessmentSummary(row.valuation))
    case 'held':
      return shares(row.shares)
    case 'stop':
      if (!row.protection) return compactMissing('protection does not apply to a cash row')
      return row.protection.stop === null ? compactMissing('no resting stop is on file for this account') : price(row.protection.stop)
    case 'downsideToStop':
      // v04 draws this column; the route serves no such field and the page never computes one.
      return compactMissing('downside to stop is not served; computing it would be a calculated field')
    case 'stopBasis':
      return row.protection?.basis ?? compactMissing('no stop basis was recorded for this account')
    case 'stopRead':
      return row.protection?.asOf
        ? `${row.protection.asOf}${row.protection.stale === true ? ' (stale)' : ''}`
        : compactMissing('no read clock was served for this account')
    case 'protectionState': {
      return protectionCell(row)
    }
    case 'protectionNext':
      return row.protection === null ? (
        compactMissing('protection does not apply to a cash row')
      ) : (
        // The producer's next step is a sentence. Measured on the live payload, rendering it unbounded took this
        // preset to 1,289 px inside a 1,136 px wrap; 160 px still left it 30 px past a 976 px wrap at 1280. The full
        // sentence stays on the title and in the drawer.
        <span style={{ ...TRUNCATE, maxWidth: 150 }} title={row.protection.nextStep}>
          {row.protection.nextStep}
        </span>
      )
    case 'method':
      return row.fib ? 'Fibonacci retracement · 52-week range' : compactMissing(LADDER_NO_CLOCK)
    case 'ladder':
      if (!row.fib) return compactMissing(LADDER_NO_CLOCK)
      if (row.fib.levels.length === 0) return `nearest only (${price(row.fib.nearestLevel)})`
      return row.fib.levels.map(l => `${Math.round(l.ratio * 1000) / 10}% ${price(l.price)}`).join(' · ')
    case 'nearestLevel':
      return row.fib ? price(row.fib.nearestLevel) : compactMissing(LADDER_NO_CLOCK)
    case 'fromHigh':
      return row.fib ? pct(row.fib.retracementFromHighPct) : compactMissing(LADDER_NO_CLOCK)
    case 'range':
      return row.fib
        ? `${price(row.fib.window.low)} – ${price(row.fib.window.high)} · as of ${row.fib.window.asOf}`
        : compactMissing(LADDER_NO_CLOCK)
    // v04's Levels column set, which this route cannot fill (verdict 2026-11-15T0342Z B2). Each names its own gap
    // rather than borrowing a served number for a claim nothing supports.
    case 'support':
      return compactMissing('no support field is served on this route')
    case 'resistance':
      return compactMissing('no resistance field is served on this route')
    case 'timeframe':
      return compactMissing('no timeframe field is served on this route')
    case 'nextReview':
      return compactMissing('no next-review field is served on this route')
    default:
      return compactMissing(`no renderer for column ${key}`)
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
  /**
   * Opens the row's detail drawer, with the element that opened it, so the drawer can return focus there (verdict
   * 2026-11-15T0342Z B4). Absent (fixture invariants): the identity cell is plain text.
   */
  onRowOpen?: (row: HoldingsRow, origin?: HTMLElement) => void
}) {
  // The table keeps its intrinsic width (v02: min-width 720, nowrap cells); this scroll container
  // is what stops that width from widening the page, so every caller inherits containment.
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
          // v04 makes the row itself the target (`tr[data-asset]`: pointer + hover); it is focusable with
          // tabIndex -1 so the drawer can hand focus back to it, while the button inside the first cell is what a
          // keyboard or a screen reader operates (the row click is convenience only).
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
          {/* The reference's `td{white-space:nowrap}` is right for a data cell and wrong for this one: a colSpan
              footnote set nowrap sets the TABLE's min width from its prose (measured 2026-11-15: 1,606 px of footnote
              forced a 1,628 px table into a 1,136 px wrap). It wraps here and nowhere else. */}
          <td colSpan={preset.columns.length} style={{ whiteSpace: 'normal' }}>
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

// ---- CSV export ----------------------------------------------------------------------------------------------
// The export is built from the SAME `cell()` output the table renders — one formatter, one column map — so the
// file and the screen cannot disagree about a value or a row (INTEGRATION.md: one selected population feeds
// the table and the export). No fetch, no second read, no derived column.

function rawText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === 'boolean') return ''
  if (typeof node === 'string') return node
  if (typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(rawText).join(' ')
  if (!isValidElement(node)) return ''
  const props = node.props as { children?: ReactNode; 'aria-hidden'?: boolean | string }
  // A decorative node (an icon marked aria-hidden) is not read by a screen reader either, so it is not cell text.
  if (props['aria-hidden'] === true || props['aria-hidden'] === 'true') return ''
  if (node.type === 'br') return ' '
  return rawText(props.children)
}

/**
 * What a cell says, as text. `<br/>` becomes one space — the two visual lines join — and whitespace collapses,
 * so the CSV cell is the readable equivalent of the two-line cell above it.
 */
export function cellText(node: ReactNode): string {
  return rawText(node).replace(/\s+/g, ' ').trim()
}

/** RFC 4180 quoting: quote a value containing a comma, a quote or a line break; double its quotes. */
function csvField(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}

/** The rows the table is showing, in the preset's columns, as CSV. */
export function csvFor(rows: HoldingsRow[], preset: Preset): string {
  const lines = [preset.columns.map(c => csvField(c.header)).join(',')]
  for (const r of rows) lines.push(preset.columns.map(c => csvField(cellText(cell(r, c.key)))).join(','))
  return `${lines.join('\r\n')}\r\n`
}
