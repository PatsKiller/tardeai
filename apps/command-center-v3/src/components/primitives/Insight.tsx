/** Insight primitives (PR2, 2026-09-27): InsightLine and TakeawayBanner.
 *
 *  Both render ONLY a server-supplied Insight object (scripts/lib/ui_insight.py, PR3):
 *  { headline, tone, drivers[], source: 'rule'|'llm', as_of, provenance }. The frontend never
 *  composes the sentence or picks a tone from a threshold (AGENTS §13). */
import type { CSSProperties, ReactNode } from 'react'
import { RADIUS, TOKENS, TYPE, toneVars, type Tone } from '../../lib/designTokens'
import { Chip } from './Chip'

export type Insight = {
  headline: string
  tone: Tone
  drivers?: string[]
  source?: 'rule' | 'llm' | string
  as_of?: string | null
  provenance?: string | null
  decision?: { outcome?: string; confidence?: string; decision_id?: string } | null
}

export function InsightLine({ insight, style }: { insight: Insight; style?: CSSProperties }) {
  const t = toneVars(insight.tone)
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', fontSize: TYPE.sm, color: TOKENS.text[1], ...style }}>
      <span aria-hidden style={{ width: 3, alignSelf: 'stretch', background: t.color, borderRadius: RADIUS.sm }} />
      <span style={{ flex: 1, minWidth: 0 }}>{insight.headline}</span>
      {insight.source === 'llm' && <Chip tone="ai" size="sm">AI</Chip>}
      {insight.as_of && <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3], whiteSpace: 'nowrap' }}>{insight.as_of}</span>}
    </div>
  )
}

/** The first thing a card says: headline, drivers, decision chip, actions. */
export function TakeawayBanner({ insight, actions, style }: { insight: Insight; actions?: ReactNode; style?: CSSProperties }) {
  const t = toneVars(insight.tone)
  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap', padding: '8px 12px',
      background: t.bg, border: `1px solid ${t.border}`, borderLeft: `3px solid ${t.color}`, borderRadius: RADIUS.md, ...style }}>
      <div style={{ flex: 1, minWidth: 200 }}>
        <div style={{ fontSize: TYPE.md, fontWeight: 800, color: TOKENS.text[0], lineHeight: 1.35 }}>{insight.headline}</div>
        {insight.drivers && insight.drivers.length > 0 && (
          <ul style={{ margin: '4px 0 0', paddingLeft: 16, fontSize: TYPE.sm, color: TOKENS.text[1], lineHeight: 1.45 }}>
            {insight.drivers.slice(0, 4).map((d, i) => <li key={i}>{d}</li>)}
          </ul>
        )}
        <div style={{ marginTop: 4, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', fontSize: TYPE.xs, color: TOKENS.text[3] }}>
          {insight.decision?.outcome && <Chip tone={insight.tone} variant="outline">{String(insight.decision.outcome).replace(/_/g, ' ')}{insight.decision.confidence ? ` · ${insight.decision.confidence}` : ''}</Chip>}
          {insight.source === 'llm' ? <Chip tone="ai">AI</Chip> : insight.source === 'rule' ? <Chip tone="neutral" variant="outline">rule</Chip> : null}
          {insight.as_of && <span>as of {insight.as_of}</span>}
          {insight.provenance && <span>· {insight.provenance}</span>}
        </div>
      </div>
      {actions && <div style={{ display: 'flex', gap: 6, alignItems: 'center' }} onClick={e => e.stopPropagation()}>{actions}</div>}
    </div>
  )
}
