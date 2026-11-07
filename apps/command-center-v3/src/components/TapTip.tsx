import { useState, type CSSProperties, type ReactNode } from 'react'
import { RADIUS, TOKENS, TYPE } from '../lib/designTokens'

// A hover, focus and tap tooltip for a status badge (operator 2026-11-07: "need tool tips given out the details").
// `title` carries the same text for the native hover tip and for screen readers; the box is the tap version for a phone.
const BOX: CSSProperties = {
  position: 'absolute', top: '100%', marginTop: 4, zIndex: 20, width: 'max-content', maxWidth: 'min(280px, 70vw)', boxSizing: 'border-box',
  padding: '8px 10px', borderRadius: RADIUS.sm, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[2], color: TOKENS.text[0],
  fontSize: TYPE.sm, fontWeight: 400, lineHeight: 1.4, textAlign: 'left', whiteSpace: 'pre-line', overflowWrap: 'anywhere',
}

export function TapTip({ tip, align = 'left', children }: { tip: string; align?: 'left' | 'right'; children: ReactNode }) {
  const [hover, setHover] = useState(false)
  const [tapped, setTapped] = useState(false)
  const open = hover || tapped
  return <span style={{ position: 'relative', display: 'inline-block', maxWidth: '100%' }} title={tip} tabIndex={0} data-testid="tap-tip"
    onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)} onFocus={() => setHover(true)}
    onBlur={() => { setHover(false); setTapped(false) }} onClick={() => setTapped(t => !t)}
    onKeyDown={e => { if (e.key === 'Escape') { setHover(false); setTapped(false) } }}>
    {children}
    {open && <span role="tooltip" data-testid="tap-tip-box" style={{ ...BOX, [align]: 0 }}>{tip}</span>}
  </span>
}
