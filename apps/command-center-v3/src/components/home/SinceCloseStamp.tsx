/** LQ-20261107-1253 amendments 3/4 + 1260/1261 — the UPDATED badge, per-source age chips and the schedule chip row.
 *  Every chip is the source's own clock from the snapshot (never the build time). Amber means stale or a missed slot. */
import { useEffect, useState, type CSSProperties } from 'react'
import { RADIUS, TOKENS, TYPE, FONT, toneVars } from '../../lib/designTokens'
import { stampModel, agoText, badgeText, type StampWire } from '../../lib/sinceCloseStamp'

const ok = toneVars('success')
const warn = toneVars('warning')
const info = toneVars('info')

/** Re-render every 30 s so "N min ago", done/next slots and the missed-slot alarm follow the client clock. */
export function useNow(everyMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), everyMs)
    return () => clearInterval(t)
  }, [everyMs])
  return now
}

const badge = (bad: boolean): CSSProperties => ({
  display: 'inline-flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap', padding: '4px 10px', borderRadius: RADIUS.md, fontWeight: 800,
  fontSize: 15, letterSpacing: '.03em', fontFamily: FONT.mono, color: bad ? warn.color : ok.color, background: bad ? warn.bg : ok.bg, border: `1px solid ${bad ? warn.border : ok.border}`,
})

/** The same badge, reused on the action list as "AS OF". */
export function AsOfBadge({ stamp, nowMs, label = 'AS OF' }: { stamp: StampWire | null | undefined; nowMs: number; label?: string }) {
  const m = stampModel(stamp, nowMs)
  if (!m || !stamp) return null
  return (
    <span data-testid="stamp-asof" data-warn={m.missed ? 'true' : 'false'} style={{ ...badge(m.missed), fontSize: 12 }}>
      {badgeText(stamp.updated_at).replace('UPDATED', label)}<span style={{ fontWeight: 500 }}>{m.ago}</span>
    </span>
  )
}

/** ``head``: the UPDATED badge, ago, next run and any missed-slot alarm (top of the card). ``detail``: per-source ages and
 *  today's schedule (under the action list). */
export default function SinceCloseStamp({ stamp, nowMs, part = 'head' }: { stamp: StampWire | null | undefined; nowMs: number; part?: 'head' | 'detail' }) {
  const m = stampModel(stamp, nowMs)
  if (!m || !stamp) return null
  return (
    <div data-testid={part === 'head' ? 'since-close-stamp' : 'since-close-stamp-detail'} style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
      {part === 'head' && <>
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <span data-testid="stamp-badge" data-warn={m.missed ? 'true' : 'false'} style={badge(m.missed)}>{m.badge}</span>
        <span data-testid="stamp-ago" style={{ fontSize: 13, color: TOKENS.text[2], fontFamily: FONT.mono }}>{m.ago}</span>
        <span data-testid="stamp-next" style={{ fontSize: 12, color: TOKENS.text[3], fontFamily: FONT.mono }}>{m.nextText}</span>
      </div>
      {m.missedText && <div data-testid="stamp-missed" role="alert" style={{ fontSize: 13, fontWeight: 700, color: warn.color }}>⚠ {m.missedText}</div>}
      </>}
      {part === 'detail' && <>
      <div data-testid="stamp-sources" style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {m.chips.map(c => (
          <span key={c.key} data-testid={`stamp-src-${c.key}`} data-warn={c.warn ? 'true' : 'false'} title={c.note ?? c.at_text ?? undefined}
            style={{ fontSize: 12, padding: '3px 8px', borderRadius: RADIUS.md, border: `1px solid ${c.warn ? warn.border : TOKENS.border}`, background: c.warn ? warn.bg : TOKENS.bg[0], color: c.warn ? warn.color : TOKENS.text[1], whiteSpace: 'nowrap' }}>
            <b>{c.label}</b> {c.warn ? c.warn_text : c.age_text}{c.at_text && !c.warn ? <span style={{ color: TOKENS.text[3] }}> · {c.at_text}</span> : null}
          </span>
        ))}
      </div>
      <div data-testid="stamp-schedule" style={{ display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: TYPE.sm, color: TOKENS.text[3], fontWeight: 800, letterSpacing: '.05em', textTransform: 'uppercase' }}>Today</span>
        {m.slots.map(s => (
          <span key={s.at} data-testid={`slot-${s.state}`} title={s.cio ? 'CIO brief re-runs here too' : undefined}
            style={{
              fontSize: 11, padding: '2px 7px', borderRadius: RADIUS.md, fontFamily: FONT.mono, whiteSpace: 'nowrap',
              border: `1px solid ${s.state === 'next' ? info.border : s.state === 'missed' ? warn.border : TOKENS.border}`,
              background: s.state === 'next' ? info.bg : s.state === 'missed' ? warn.bg : 'transparent',
              color: s.state === 'next' ? info.color : s.state === 'missed' ? warn.color : s.state === 'done' ? TOKENS.text[2] : TOKENS.text[3],
              fontWeight: s.state === 'next' ? 800 : 500,
            }}>
            {s.state === 'done' ? '● ' : s.state === 'missed' ? '⚠ ' : ''}{s.text}{s.cio ? ' ·CIO' : ''}
          </span>
        ))}
      </div>
      </>}
    </div>
  )
}

export { agoText }
