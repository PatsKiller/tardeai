/** LQ-20261107-1282 (mockup v3) — held/watchlist chips with an arrow and a percentage for the close, plus a SECOND value
 *  for what has printed since (overnight / pre-market / after-hours / futures open), and the futures / overseas row that
 *  replaces "futures feed pending".
 *
 *  Advisory only: nothing here sizes, orders, stops or weights. Mobile first: the chips are two per row at 390-412 px
 *  and fill the width from there; the futures row scrolls sideways rather than shrinking below a readable size.
 */
import type { CSSProperties } from 'react'
import { RADIUS, TOKENS, TYPE, FONT, toneVars } from '../../lib/designTokens'
import { movesModel, type MarketLevel, type MoveChip } from '../../lib/sinceCloseMoves'
import type { SinceCloseWire } from '../../lib/sinceClose'

const up = toneVars('success')
const dn = toneVars('danger')
const warn = toneVars('warning')
const info = toneVars('info')

const S = {
  h3: { margin: 0, fontSize: TYPE.sm, fontWeight: 800, letterSpacing: '.05em', textTransform: 'uppercase',
    color: TOKENS.text[3] } as CSSProperties,
  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 8 } as CSSProperties,
  chip: { borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`, padding: '8px 10px', minWidth: 0,
    display: 'grid', gap: 2, fontVariantNumeric: 'tabular-nums' } as CSSProperties,
  top: { display: 'flex', justifyContent: 'space-between', gap: 6, fontWeight: 700, fontSize: 14 } as CSSProperties,
  row: { display: 'flex', justifyContent: 'space-between', gap: 6, fontSize: 12 } as CSSProperties,
  now: { fontSize: 12, color: TOKENS.text[2], borderTop: `1px dashed ${TOKENS.border}`, paddingTop: 3, marginTop: 2 } as CSSProperties,
  sym: { fontWeight: 700, color: TOKENS.text[0] } as CSSProperties,
  pct: { fontFamily: FONT.mono, fontWeight: 700 } as CSSProperties,
  meta: { fontSize: TYPE.base, color: TOKENS.text[3], fontFamily: FONT.mono } as CSSProperties,
  nowList: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 8 } as CSSProperties,
  level: { background: TOKENS.bg[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: '6px 10px',
    minWidth: 0, display: 'grid', gap: 2, fontVariantNumeric: 'tabular-nums' } as CSSProperties,
}

const tone = (pct: number | null | undefined) => (pct == null || !Number.isFinite(pct) || pct === 0 ? TOKENS.text[2] : pct > 0 ? up.color : dn.color)

function Value({ pct, text }: { pct: number | null; text: string }) {
  return (
    <span style={{ ...S.pct, color: tone(pct) }} data-tone={pct == null || pct === 0 ? 'flat' : pct > 0 ? 'up' : 'down'}>
      {text}
    </span>
  )
}

export function MoveChipBox({ c }: { c: MoveChip }) {
  const fill = c.closePct > 0 ? up.bg : c.closePct < 0 ? dn.bg : TOKENS.bg[0]
  return (
    <div style={{ ...S.chip, background: fill }} data-testid={`sc-chip-${c.symbol}`} data-held={c.held ? '1' : '0'}>
      <div style={S.top}>
        <span style={S.sym}>{c.symbol}</span>
        <Value pct={c.closePct} text={`${c.closeArrow} ${c.closeText}`} />
      </div>
      <div style={S.row}>
        <span style={S.meta}>close</span>
        <span style={{ color: tone(c.dollars), fontFamily: FONT.mono }} data-testid={`sc-chip-${c.symbol}-dollars`}>{c.dollarsText}</span>
      </div>
      {c.ext ? (
        <div style={S.now} data-testid={`sc-chip-${c.symbol}-now`} data-state={c.ext.state}>
          <span style={{ color: c.ext.state === 'print' ? TOKENS.text[2] : TOKENS.text[3] }}>
            now ({c.ext.label}){' '}
          </span>
          <span style={{ color: tone(c.ext.pct), fontWeight: 700 }}>
            {c.ext.state === 'print' ? `${c.ext.arrow} ${c.ext.pctText}` : c.ext.priceText}
          </span>
          <span style={{ color: TOKENS.text[3] }}>
            {' '}{c.ext.basisText}{c.ext.printText ? ` · ${c.ext.printText}` : ''}
          </span>
        </div>
      ) : c.note ? (
        <div style={{ ...S.now, color: TOKENS.text[3] }} data-testid={`sc-chip-${c.symbol}-none`}>{c.note}</div>
      ) : null}
    </div>
  )
}

function LevelBox({ l }: { l: MarketLevel }) {
  return (
    <div style={S.level} data-testid={`sc-level-${l.symbol}`} data-level-only={l.levelOnly ? '1' : '0'}>
      <span style={S.meta}>{l.label}</span>
      {l.levelOnly
        ? <span style={{ ...S.pct, fontSize: 14, color: TOKENS.text[1] }} data-tone="level">{l.levelText}</span>
        : <Value pct={l.pct} text={`${l.arrow} ${l.pctText}`} />}
      <span style={S.meta}>{l.levelOnly ? 'level only' : ''}{l.printText ? `${l.levelOnly ? ' · ' : ''}${l.printText}` : ''}</span>
    </div>
  )
}

export default function SinceCloseMoves({ wire }: { wire: SinceCloseWire | null | undefined }) {
  const m = movesModel(wire)
  if (!wire || (m.held.length === 0 && m.watch.length === 0 && m.levels.length === 0 && m.overseas.length === 0)) return null
  const closeTag = wire.window_now?.close_tag ?? wire.window?.close_tag ?? 'last close'
  const bigWatch = m.watch.filter(w => Math.abs(w.ext?.pct ?? w.closePct) >= 3)
  return (
    <>
      {m.held.length > 0 && (
        <div data-testid="since-close-moves" data-layout="grid" style={{ display: 'grid', gap: 8 }}>
          <h3 style={S.h3}>Your holdings · sorted by $ moved since {closeTag}</h3>
          <div style={S.grid}>
            {m.held.map(c => <MoveChipBox key={c.symbol} c={c} />)}
          </div>
        </div>
      )}
      {bigWatch.length > 0 && (
        <div data-testid="since-close-watch" style={{ display: 'grid', gap: 8 }}>
          <h3 style={S.h3}>Watchlist movers</h3>
          <div style={S.grid}>
            {bigWatch.map(c => <MoveChipBox key={c.symbol} c={c} />)}
          </div>
        </div>
      )}
      <div data-testid="since-close-futures" data-status={m.levelsStatus} style={{ display: 'grid', gap: 8 }}>
        <h3 style={S.h3}>
          Futures / overseas · vs {closeTag}
          {m.asOfText ? <span style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}> · {m.asOfText}</span> : null}
        </h3>
        {m.levelsStatus === 'available' && m.levels.length > 0 ? (
          <div style={S.nowList}>{m.levels.map(l => <LevelBox key={l.symbol} l={l} />)}</div>
        ) : (
          <p style={{ margin: 0, fontSize: 13, color: TOKENS.text[2] }}>{m.pendingText}</p>
        )}
        {m.overseas.length > 0 && (
          <div style={S.nowList} data-testid="since-close-overseas-rows">
            {m.overseas.map(r => (
              <div key={r.label} style={S.level} data-testid={`sc-overseas-${r.label}`}>
                <span style={S.meta}>{r.label}</span>
                <span style={{ ...S.pct, fontSize: 13, color: TOKENS.text[2] }} data-level={r.text}>{r.text}</span>
              </div>
            ))}
          </div>
        )}
        {m.overseasText && (
          <p style={{ margin: 0, fontSize: 12, color: TOKENS.text[3] }} data-testid="since-close-overseas">{m.overseasText}</p>
        )}
        {m.levelsStatus === 'available' && m.levels.length === 0 && (
          <p style={{ margin: 0, fontSize: 12, color: warn.color }}>no futures or index print since the close</p>
        )}
        {m.levels.some(l => l.levelOnly) && (
          <p style={{ margin: 0, fontSize: 12, color: info.color }} data-testid="since-close-level-note">
            A level with no arrow is real: the provider dated no reference to the close, so no percentage is shown.
          </p>
        )}
      </div>
    </>
  )
}
