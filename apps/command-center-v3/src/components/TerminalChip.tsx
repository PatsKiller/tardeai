/** Watch Desk v4 (A6): the ONE chip vocabulary. Four classes, visually distinct
 * by construction — state pills state, metric chips drill, action chips act,
 * count bubbles count. Colors only from the semantic palette; no new hues. */
import { useState, type ReactNode } from 'react'
import { BB, TYPE, statePill, metricChip, actionChip, countBubble } from '../lib/watchTokens'

export type ChipKind = 'state' | 'metric' | 'action' | 'count'

export function Chip(props: {
  kind: ChipKind
  children: ReactNode
  tone?: 'green' | 'amber' | 'red' | 'slate'
  onClick?: () => void
  title?: string
  warn?: boolean
}) {
  const { kind, children, tone = 'slate', onClick, title, warn } = props
  if (kind === 'state') {
    // State pills state, they don't do — never clickable by contract.
    return <span style={statePill(tone)} title={title}>{children}</span>
  }
  if (kind === 'metric') {
    return (
      <span style={metricChip(!!onClick)} title={title} onClick={onClick}>
        {children}
      </span>
    )
  }
  if (kind === 'action') {
    return (
      <button style={actionChip()} title={title} onClick={onClick}>
        {children}
      </button>
    )
  }
  return <span style={countBubble(warn)} title={title}>{children}</span>
}

/** Max-3 state pills per row; overflow renders "+N" with a hover list (A6). */
export function StatePills(props: { pills: Array<{ label: string; tone?: 'green' | 'amber' | 'red' | 'slate'; title?: string }> }) {
  const { pills } = props
  const shown = pills.slice(0, 3)
  const hidden = pills.slice(3)
  return (
    <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
      {shown.map((p, i) => <Chip key={i} kind="state" tone={p.tone}>{p.label}</Chip>)}
      {hidden.length > 0 && (
        <span style={{ fontSize: TYPE.xs, color: BB.text3, cursor: 'default' }}
              title={hidden.map(p => p.label).join(' · ')}>+{hidden.length}</span>
      )}
    </span>
  )
}

/** A6 legend popover — linked from each tab header ("What do these chips mean?"). */
export function ChipLegend() {
  const [open, setOpen] = useState(false)
  return (
    <span style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{ fontSize: TYPE.xs, color: BB.text3, background: 'transparent', border: 'none', cursor: 'pointer', textDecoration: 'underline dotted' }}>
        chips?
      </button>
      {open && (
        <div style={{ position: 'absolute', right: 0, top: 18, zIndex: 60, width: 340, background: BB.bgPanel,
                      border: `1px solid ${BB.border}`, borderRadius: 2, padding: '8px 10px', fontSize: TYPE.xs,
                      color: BB.text2, lineHeight: 1.6, boxShadow: '0 8px 24px rgba(0,0,0,0.5)' }}>
          <div style={{ fontWeight: 800, color: BB.text0, marginBottom: 4 }}>CHIP VOCABULARY</div>
          <div><Chip kind="state" tone="green">HELD</Chip> state pill — a fact about the row; never clickable.</div>
          <div style={{ marginTop: 4 }}><Chip kind="metric">α +2.1% (n=14)</Chip> metric chip — mono value; click drills or filters; hover shows definition + as-of.</div>
          <div style={{ marginTop: 4 }}><Chip kind="action">Stage</Chip> action chip — only these are pressable-as-chips; solid amber is the one primary action.</div>
          <div style={{ marginTop: 4 }}><Chip kind="count">12</Chip> count bubble — live count from the same corpus as the view.</div>
          <div style={{ marginTop: 6, color: BB.text3 }}>Rail: <span style={{ color: BB.green }}>green</span> favorable · <span style={{ color: BB.amber }}>amber</span> attention · <span style={{ color: BB.red }}>red</span> breach · slate neutral.</div>
        </div>
      )}
    </span>
  )
}
