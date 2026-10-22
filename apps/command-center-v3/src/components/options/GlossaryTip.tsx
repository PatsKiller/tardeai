/** Glossary tooltips for the Options desk (2026-10-22).
 *
 *  Every term and number on the desk is wrapped in one of these. Each is keyboard-focusable (or
 *  attaches to the focusable control it explains), carries aria-describedby pointing at an
 *  always-present visually-hidden description, and opens a bubble on hover, focus or tap; Escape
 *  closes it. The text comes only from src/lib/optionsGlossary.ts.
 */
import { useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { FONT, RADIUS, SHADOW, TOKENS, TYPE } from '../../lib/designTokens'
import { glossary, glossaryText, NOT_SERVED } from '../../lib/optionsGlossary'

const srOnly: CSSProperties = {
  position: 'absolute', width: 1, height: 1, padding: 0, margin: -1, overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap', border: 0,
}

const bubble: CSSProperties = {
  position: 'absolute', zIndex: 70, top: 'calc(100% + 6px)', left: 0, minWidth: 240, maxWidth: 360,
  background: TOKENS.bg[1], color: TOKENS.text[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md,
  boxShadow: SHADOW[2], padding: '10px 12px', fontSize: TYPE.sm, lineHeight: 1.45, fontWeight: 500, textAlign: 'left',
  whiteSpace: 'normal', fontFamily: FONT.sans, textTransform: 'none', letterSpacing: 'normal', cursor: 'default',
}

const place = (flip: boolean): CSSProperties => (flip ? { ...bubble, left: 'auto', right: 0, maxWidth: 'min(360px, 92vw)' } : { ...bubble, maxWidth: 'min(360px, 92vw)' })

export function GlossaryBody({ k, extra }: { k: string; extra?: string }) {
  const g = glossary(k)
  const row = (label: string, text?: string) => text ? <span style={{ display: 'block', marginTop: 4 }}><b style={{ color: TOKENS.text[0] }}>{label}:</b> {text}</span> : null
  return (
    <span style={{ display: 'block' }}>
      <span style={{ display: 'block', fontWeight: 800, color: TOKENS.text[0] }}>{g.term}</span>
      <span style={{ display: 'block', marginTop: 2 }}>{g.plain}</span>
      {extra && <span style={{ display: 'block', marginTop: 4, color: TOKENS.text[0] }}>{extra}</span>}
      {row('How it is calculated', g.formula)}
      {row('Computed by', g.computedBy)}
      {row('Data', g.source)}
      {row('What this means for you', g.forYou)}
    </span>
  )
}

function useBubble() {
  const [open, setOpenRaw] = useState(false)
  const [flip, setFlip] = useState(false)
  const ref = useRef<HTMLSpanElement | null>(null)
  const setOpen = (v: boolean | ((o: boolean) => boolean)) => {
    const r = ref.current?.getBoundingClientRect()
    if (r && typeof window !== 'undefined') setFlip(r.left + 372 > window.innerWidth)
    setOpenRaw(v)
  }
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('keydown', onKey); document.addEventListener('mousedown', onDoc)
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('mousedown', onDoc) }
  }, [open])
  return { open, setOpen, ref, flip }
}

/** A focusable term: text or a number with its glossary entry. `extra` adds a line specific to this value. */
export function Term({ k, children, extra, style, testId }: { k: string; children: ReactNode; extra?: string; style?: CSSProperties; testId?: string }) {
  const { open, setOpen, ref, flip } = useBubble()
  const id = useId()
  return (
    <span ref={ref} data-glossary-key={k} data-testid={testId}
      style={{ position: 'relative', display: 'inline-flex', alignItems: 'baseline', ...style }}>
      <span tabIndex={0} aria-describedby={id}
        onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
        onClick={e => { e.stopPropagation(); setOpen(o => !o) }}
        style={{ cursor: 'help', textDecoration: 'underline dotted', textDecorationColor: TOKENS.text[3], textUnderlineOffset: 3, outline: 'none', borderRadius: RADIUS.sm }}>
        {children}
      </span>
      <span id={id} style={srOnly}>{glossaryText(k)}{extra ? ` ${extra}` : ''}</span>
      {open && <span role="tooltip" style={place(flip)}><GlossaryBody k={k} extra={extra} /></span>}
    </span>
  )
}

/** A value the server did not send: "—" with the not-provided explanation, still focusable. */
export function Missing({ k }: { k: string }) {
  return <Term k={k} extra={NOT_SERVED}>—</Term>
}

/** Explains an interactive control (button, toggle) without nesting focusables: the control gets
 *  aria-describedby and the bubble opens while it is hovered or focused. */
export function ControlTip({ k, extra, children, style }: {
  k: string
  extra?: string
  style?: CSSProperties
  children: (describe: { 'aria-describedby': string; onFocus: () => void; onBlur: () => void; onMouseEnter: () => void; onMouseLeave: () => void }) => ReactNode
}) {
  const { open, setOpen, ref, flip } = useBubble()
  const id = useId()
  return (
    <span ref={ref} data-glossary-key={k} style={{ position: 'relative', display: 'block', ...style }}>
      {children({ 'aria-describedby': id, onFocus: () => setOpen(true), onBlur: () => setOpen(false), onMouseEnter: () => setOpen(true), onMouseLeave: () => setOpen(false) })}
      <span id={id} style={srOnly}>{glossaryText(k)}{extra ? ` ${extra}` : ''}</span>
      {open && <span role="tooltip" style={place(flip)}><GlossaryBody k={k} extra={extra} /></span>}
    </span>
  )
}
