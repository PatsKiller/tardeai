/** WS-B — the per-security workflow strip. Renders the fixed node order from lib/watchWorkflowModel.ts,
 *  one status pill per stage, derived from real payload fields only. Display-only: no fetch, write or
 *  decision. Mobile: the strip scrolls horizontally so the full order stays available without wrapping. */

import { type CSSProperties } from 'react'
import { RADIUS, TOKENS, TYPE, toneVars, type Tone } from '../../lib/designTokens'
import { TOOLTIPS, type ProspectRow } from '../../lib/watchProspectsModel'
import { workflowStrip, type WorkflowState } from '../../lib/watchWorkflowModel'

const stateTone = (s: WorkflowState): Tone =>
  s === 'LIVE' ? 'success' : s === 'PARTIAL' ? 'warning' : 'neutral'

const stateStyle: CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: TYPE.sm, fontWeight: 700,
  letterSpacing: '.04em', whiteSpace: 'nowrap',
}

export default function WatchWorkflowStrip({ row }: { row: ProspectRow }) {
  const nodes = workflowStrip(row)
  return (
    <section data-testid="watch-workflow-strip" aria-label="Per-security workflow"
      style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <span style={{ fontSize: TYPE.xs, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: TOKENS.text[2] }}
        title={TOOLTIPS.workflow}>
        Workflow
      </span>
      <div data-testid="watch-workflow-nodes"
        style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 4, maxWidth: '100%', scrollbarWidth: 'thin' }}>
        {nodes.map(n => {
          const tone = stateTone(n.state)
          const t = toneVars(tone)
          return (
            <span key={n.key} data-testid="watch-workflow-node" data-key={n.key} data-state={n.state}
              title={`${n.label} — ${n.state}: ${n.note}`}
              style={{
                ...stateStyle, flex: '0 0 auto', color: t.color,
                background: tone === 'neutral' ? TOKENS.bg[2] : t.bg,
                border: `1px solid ${tone === 'neutral' ? TOKENS.border : t.border}`,
                borderRadius: RADIUS.pill, padding: '2px 8px', cursor: 'help',
              }}>
              <span aria-hidden="true" style={{ width: 6, height: 6, borderRadius: 999, background: t.color, display: 'inline-block' }} />
              <span>{n.label}</span>
              <span style={{ fontWeight: 400, opacity: 0.85 }}>{n.state}</span>
            </span>
          )
        })}
      </div>
    </section>
  )
}
