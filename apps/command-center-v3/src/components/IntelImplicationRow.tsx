// A visible conclusion, its uncertainty and the next step, with the full thesis one tap away (FQ-040).
// Tokens only: every colour, size and radius comes from designTokens, never a literal.
import { useState, type CSSProperties, type ReactNode } from 'react'
import { RADIUS, TOKENS, TYPE } from '../lib/designTokens'
import { implicationModel, rowTitle, type ImplicationSource } from '../lib/intelImplication'

const TONE = {
  critical: TOKENS.danger, warning: TOKENS.warning, positive: TOKENS.success, info: TOKENS.info,
} as const

export type IntelImplicationRowProps = {
  item: ImplicationSource & { severity?: string | null }
  /** the page's own next-step sentence — passed in so the two never diverge */
  nextStep: string
  /** called when the operator wants the full record (the drill-down), never from the toggle */
  onOpen?: () => void
}

const rowStyle: CSSProperties = { borderBottom: `1px solid ${TOKENS.borderSubtle}`, padding: '9px 0', display: 'grid', gap: 4, minWidth: 0 }
const text = (size: number, color: string, weight?: number): CSSProperties => ({ fontSize: size, color, fontWeight: weight, overflowWrap: 'anywhere' })

export function IntelImplicationRow({ item, nextStep, onOpen }: IntelImplicationRowProps): ReactNode {
  const [open, setOpen] = useState(false)
  const m = implicationModel(item, nextStep)
  const tone = TONE[(item.severity ?? 'info') as keyof typeof TONE] ?? TOKENS.text[2]
  return (
    <div data-testid="intel-implication" data-verdict={m.conclusionKind} style={rowStyle}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'baseline', minWidth: 0 }}>
        <span data-testid="intel-implication-conclusion" style={text(TYPE.sm, tone, 800)}>{rowTitle(m, item.symbol)}</span>
      </div>
      <span data-testid="intel-implication-uncertainty" style={text(TYPE.xs, TOKENS.text[2], 700)}>{m.uncertainty}</span>
      <span data-testid="intel-implication-next" style={text(TYPE.sm, TOKENS.text[1])}>{m.nextStep}</span>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <button type="button" data-testid="intel-implication-toggle" aria-expanded={open}
          onClick={() => setOpen(v => !v)}
          style={{ minHeight: 44, background: 'none', border: 'none', padding: 0, cursor: 'pointer',
            color: TOKENS.primary, fontSize: TYPE.xs, fontWeight: 700 }}>
          {open ? 'Hide the full report' : 'Read the full report →'}
        </button>
        {onOpen ? <button type="button" onClick={onOpen}
          style={{ minHeight: 44, background: 'none', border: 'none', padding: 0, cursor: 'pointer',
            color: TOKENS.text[2], fontSize: TYPE.xs, fontWeight: 700 }}>Open the source record</button> : null}
      </div>
      {open ? (
        <div data-testid="intel-implication-full" style={{ display: 'grid', gap: 6, marginTop: 2, padding: 8,
          background: TOKENS.bg[2], borderRadius: RADIUS.md }}>
          <span style={text(TYPE.sm, TOKENS.text[0])}>{m.headline}</span>
          {m.summary ? <span style={text(TYPE.sm, TOKENS.text[1])}>{m.summary}</span> : null}
          {m.identifiers.length ? (
            <dl data-testid="intel-implication-identifiers" style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '2px 8px', margin: 0 }}>
              {m.identifiers.map(([k, v]) => [
                <dt key={`${k}-k`} style={text(TYPE.xs, TOKENS.text[2], 800)}>{k}</dt>,
                <dd key={`${k}-v`} style={{ ...text(TYPE.xs, TOKENS.text[2]), margin: 0 }}>{v}</dd>,
              ])}
            </dl>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

export default IntelImplicationRow
