/** Learning loop PR1 — "From recommendation …" / "Your own trade" for one closed trade (TradeInView).
 * Display only: lib/recommendationOrigin.ts decides the words and the tone; this file only lays them out in tokens. */
import { RADIUS, TOKENS, TYPE, toneVars } from '../../lib/designTokens'
import { recommendationOrigin, type RecBlock } from '../../lib/recommendationOrigin'

type Props = { rec?: RecBlock | null; status?: string | null }

export function RecommendationOriginChip({ rec, status }: Props) {
  const o = recommendationOrigin(rec, status)
  const t = toneVars(o.tone)
  return (
    <span title={o.headline} style={{ fontSize: TYPE.xs, fontWeight: 700, padding: '2px 7px', borderRadius: RADIUS.sm,
      background: t.bg, color: t.color, border: `1px solid ${t.border}` }}>
      {o.chip}
    </span>
  )
}

export default function RecommendationOriginCard({ rec, status }: Props) {
  const o = recommendationOrigin(rec, status)
  const t = toneVars(o.tone)
  const cell = (label: string, value: string, title?: string) => (
    <div key={label} title={title} style={{ background: TOKENS.bg[1], padding: 8, borderRadius: RADIUS.sm }}>
      <div style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>{label}</div>
      <div style={{ fontSize: TYPE.base, fontWeight: 600, color: TOKENS.text[0] }}>{value}</div>
    </div>
  )
  return (
    <div style={{ border: `1px solid ${t.border}`, background: t.bg, borderRadius: RADIUS.md, padding: 12, marginBottom: 12 }}>
      <div style={{ fontSize: TYPE.md, fontWeight: 700, color: t.color }}>{o.headline}</div>
      {o.confidenceLabel && (
        <div style={{ fontSize: TYPE.sm, color: TOKENS.text[1], marginTop: 4 }}>Link confidence: {o.confidenceLabel}</div>
      )}
      {o.plan && <div style={{ fontSize: TYPE.sm, color: TOKENS.text[1], marginTop: 4, fontFamily: 'monospace' }}>{o.plan}</div>}
      {o.kind !== 'unknown' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 8, marginTop: 10 }}>
          {cell('R achieved', o.rAchieved, o.rNote ?? undefined)}
          {o.kind === 'recommendation' && cell('Planned R:R', o.plannedRr)}
          {o.outcome && cell('Outcome', o.outcome)}
        </div>
      )}
      {o.rNote && <div style={{ fontSize: TYPE.xs, color: TOKENS.text[2], marginTop: 6 }}>{o.rNote}</div>}
      {o.recId && <div style={{ fontSize: TYPE.xs, color: TOKENS.text[3], marginTop: 6, fontFamily: 'monospace' }}>{o.recId}</div>}
    </div>
  )
}
