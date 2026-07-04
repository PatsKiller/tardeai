import { useState, type CSSProperties, type MouseEvent, type ReactNode } from 'react'
import { WL, heroStateStyle, verdictWord, numStyle } from '../../lib/watchlistCardTokens'

// Shared card primitives (Phase A of the Proposals/Holdings redesign spec, 2026-07-04).
// Extracted VERBATIM from the locked Security Card v3 (VerdictBanner, LadderLine) and the
// proposal/stop trust work (TrustLine, AgeChip) so the three decision surfaces render the
// same grammar from one source. Zero visual change to the watchlist card is the contract —
// styles here must not drift without a new approved spec.

export type BannerButton = { label: string; onClick: (e: MouseEvent) => void; style: CSSProperties }
export type BannerMenuItem = { label: string; onClick: (e: MouseEvent) => void }

/** The single tinted line of a card: verdict word · hero text · ellipsized why · chip · actions · ••• */
export function VerdictBanner(props: {
  verdict: string
  urgency?: string | null
  heroText: string
  whyLine?: string | null
  whyTitle?: string
  chip?: { text: string; color: string; tooltip?: string } | null
  primary?: BannerButton | null
  secondary?: BannerButton | null
  menuItems?: BannerMenuItem[]
  menuButtonStyle: CSSProperties
}) {
  const { verdict, urgency, heroText, whyLine, whyTitle, chip, primary, secondary, menuItems, menuButtonStyle } = props
  const [menuOpen, setMenuOpen] = useState(false)
  const heroState = heroStateStyle(verdict as any, urgency as any)
  return (
    <div
      onClick={e => e.stopPropagation()}
      style={{
        margin: '0 16px 10px',
        borderRadius: 7,
        padding: '8px 14px',
        background: heroState.bg,
        border: `1px solid ${heroState.border}`,
        display: 'flex',
        gap: 12,
        alignItems: 'center',
        minWidth: 0,
        flexWrap: 'wrap',
      }}
    >
      <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.11em', color: heroState.accent, whiteSpace: 'nowrap' }}>
        {verdictWord(verdict as any)}
      </span>
      <span style={{ fontSize: 14.5, fontWeight: 800, whiteSpace: 'nowrap' }}>{heroText}</span>
      {whyLine ? (
        <span
          title={whyTitle ?? whyLine}
          style={{ fontSize: 11, color: WL.text.secondary, flex: 1, minWidth: 80, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
        >{whyLine}</span>
      ) : <span style={{ flex: 1 }} />}
      {chip && (
        <span title={chip.tooltip} style={{ ...numStyle, fontSize: 12, fontWeight: 800, color: chip.color, whiteSpace: 'nowrap' }}>{chip.text}</span>
      )}
      {primary && (
        <button onClick={primary.onClick} style={{ ...primary.style, fontWeight: 800 }}>{primary.label}</button>
      )}
      {secondary && (
        <button onClick={secondary.onClick} style={secondary.style}>{secondary.label}</button>
      )}
      {(menuItems?.length ?? 0) > 0 && (
        <div style={{ position: 'relative' }}>
          <button
            onClick={e => { e.stopPropagation(); setMenuOpen(v => !v) }}
            title="More actions"
            style={{ ...menuButtonStyle, minWidth: 0, fontWeight: 800 }}
          >•••</button>
          {menuOpen && (
            <div style={{
              position: 'absolute', right: 0, top: 'calc(100% + 4px)', zIndex: 30,
              background: '#16202f', border: `1px solid ${WL.surface.edge}`, borderRadius: 8,
              boxShadow: '0 10px 28px rgba(0,0,0,.4)', minWidth: 160, padding: 4,
              display: 'flex', flexDirection: 'column',
            }}>
              {menuItems!.map(m => (
                <button
                  key={m.label}
                  onClick={e => { setMenuOpen(false); m.onClick(e) }}
                  style={{
                    fontSize: 11.5, fontWeight: 600, color: WL.text.secondary, textAlign: 'left',
                    background: 'transparent', border: 'none', cursor: 'pointer',
                    padding: '7px 10px', borderRadius: 5, whiteSpace: 'nowrap',
                  }}
                >{m.label}</button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export type LadderStep = { label: string; px: number; action: string }

/** Compact T1/T2/T3 strip with focus highlight and split annotation. */
export function LadderLine(props: {
  steps: LadderStep[]
  focusIdx?: number
  stepTooltip?: (label: string, px: number, action: string) => string
  note?: string
  style?: CSSProperties
}) {
  const { steps, focusIdx = -1, stepTooltip, note = '⅓/⅓/runner · +1R → stop to breakeven', style } = props
  return (
    <div style={{ ...numStyle, fontSize: 11.5, color: WL.text.secondary, marginTop: 7, ...style }}>
      {steps.map((s, i) => {
        const short = s.label.split(' ')[0]
        const active = i === focusIdx
        return (
          <span key={i} title={stepTooltip?.(s.label, s.px, s.action)} style={{ marginRight: 12 }}>
            <span style={{ fontSize: 10, fontWeight: 700, color: active ? WL.signal.amber : WL.text.dim, marginRight: 4 }}>{short}</span>
            {s.px.toFixed(2)}
          </span>
        )
      })}
      <span style={{ fontFamily: 'inherit', fontSize: 10, color: WL.text.dim, fontVariantNumeric: 'normal' }}>{note}</span>
    </div>
  )
}

export type TrustBit = { text: ReactNode; amber?: boolean }

/** Dim one-liner of trust context (held/earnings/vol) with amber emphasis per bit. */
export function TrustLine({ bits, style }: { bits: TrustBit[]; style?: CSSProperties }) {
  if (!bits.length) return null
  return (
    <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 8, lineHeight: 1.5, ...style }}>
      {bits.map((b, i) => (
        <span key={i} style={b.amber ? { color: '#f59e0b', fontWeight: 700 } : undefined}>
          {i > 0 ? ' · ' : ''}{b.text}
        </span>
      ))}
    </div>
  )
}

/** Age of an LLM-derived field: "prefix 3d old ⚠" — amber past warnAfterHours. */
export function AgeChip(props: { ts: string | null | undefined; prefix: string; warnAfterHours: number; style?: CSSProperties }) {
  const { ts, prefix, warnAfterHours, style } = props
  if (!ts) return null
  const t = new Date(ts).getTime()
  if (!Number.isFinite(t)) return null
  const h = (Date.now() - t) / 3_600_000
  const label = h < 48 ? `${Math.round(h)}h` : `${Math.floor(h / 24)}d`
  const stale = h > warnAfterHours
  return (
    <span style={stale ? { color: '#f59e0b', fontWeight: 700, ...style } : style}>
      {prefix} {label} old{stale ? ' ⚠' : ''}
    </span>
  )
}
