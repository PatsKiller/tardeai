/**
 * Rockville CIO Daily Synthesis panel (above symbol cards).
 * Displays provenance; does not route models itself.
 */
import { useState } from 'react'

export type CioArtifact = {
  artifact_id?: string
  market_date?: string
  generated_at?: string
  status?: string
  changed_symbol_count?: number
  unchanged_symbol_count?: number
  held_position_change_count?: number
  executive_stance?: {
    posture?: string
    summary?: string
    confidence?: number
  }
  operator_priority_queue?: Array<{
    symbol: string
    state: string
    priority: number
    what_changed: string
    why_it_matters: string
    next_operator_action: string
  }>
  provenance?: {
    provider?: string
    model?: string
    policy?: string
    thinking?: boolean
    effort?: string
  }
  usage?: { actual_cost_usd?: number | null }
  failure_code?: string | null
}

type Props = {
  artifact?: CioArtifact | null
  status?: string
  onDeepReview?: () => void
  onViewPrior?: () => void
  onViewEvidence?: () => void
  onViewChanges?: () => void
}

export default function CioDailyPanel({
  artifact, status, onDeepReview, onViewPrior, onViewEvidence, onViewChanges,
}: Props) {
  const [confirmDeep, setConfirmDeep] = useState(false)
  const stance = artifact?.executive_stance
  const queue = artifact?.operator_priority_queue || []
  const model = artifact?.provenance?.model || 'deepseek-v4-pro'
  const when = artifact?.generated_at
    ? new Date(artifact.generated_at).toLocaleString('en-US', {
        hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York', timeZoneName: 'short',
      })
    : '—'

  return (
    <div
      data-rockville-cio
      style={{
        background: 'var(--bg1)',
        border: '1px solid var(--border)',
        borderRadius: 12,
        padding: 14,
        marginBottom: 14,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 900, color: 'var(--text0)' }}>
            CIO DAILY SYNTHESIS
          </div>
          <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 2 }}>
            Generated {when} · DeepSeek V4 Pro · Thinking High · {status || artifact?.status || 'NONE'}
          </div>
        </div>
        <div style={{ fontSize: 11, color: 'var(--text2)' }}>
          {artifact?.changed_symbol_count ?? 0} material symbol changes · {artifact?.held_position_change_count ?? 0} held-position changes
        </div>
      </div>

      {artifact?.failure_code && (
        <div style={{ marginTop: 8, fontSize: 11, color: '#ef4444', fontWeight: 700 }}>
          Provider failure: {artifact.failure_code} (no silent fallback)
        </div>
      )}

      <div style={{ marginTop: 10 }}>
        <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text3)', letterSpacing: 0.4 }}>TODAY&apos;S POSTURE</div>
        <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', marginTop: 4 }}>
          {(stance?.posture || 'INSUFFICIENT_EVIDENCE').replace(/_/g, ' ')}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text1)', marginTop: 4, lineHeight: 1.45 }}>
          {stance?.summary || 'No CIO artifact yet. Shadow scheduler runs at 4:20 PM ET on material change only.'}
        </div>
      </div>

      {queue.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text3)' }}>TOP OPERATOR ACTIONS</div>
          <ol style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12, color: 'var(--text1)' }}>
            {queue.slice(0, 5).map((q, i) => (
              <li key={i} style={{ marginBottom: 4 }}>
                <b>{q.symbol}</b> — {q.next_operator_action} <span style={{ color: 'var(--text3)' }}>({q.state})</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
        {[
          { label: 'VIEW CHANGES', fn: onViewChanges },
          { label: 'VIEW EVIDENCE', fn: onViewEvidence },
          { label: 'VIEW PRIOR DIGEST', fn: onViewPrior },
        ].map(b => (
          <button
            key={b.label}
            type="button"
            onClick={b.fn}
            style={{
              fontSize: 10, fontWeight: 800, padding: '6px 10px', borderRadius: 6,
              border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)', cursor: 'pointer',
            }}
          >
            {b.label}
          </button>
        ))}
        <button
          type="button"
          onClick={() => setConfirmDeep(true)}
          style={{
            fontSize: 10, fontWeight: 800, padding: '6px 10px', borderRadius: 6,
            border: '1px solid #a78bfa66', background: '#a78bfa18', color: '#c4b5fd', cursor: 'pointer',
          }}
        >
          REQUEST DEEP REVIEW
        </button>
      </div>

      {confirmDeep && (
        <div style={{ marginTop: 10, padding: 10, borderRadius: 8, border: '1px solid #a78bfa66', background: 'var(--bg2)' }}>
          <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)' }}>Confirm CIO Deep Review</div>
          <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4 }}>
            Policy CIO_DEEP_REVIEW · model {model} · thinking max · est. cost ~$0.15 (not charged until confirmed + flag on)
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button
              type="button"
              onClick={() => { setConfirmDeep(false); onDeepReview?.() }}
              style={{ fontSize: 10, fontWeight: 800, padding: '6px 10px', borderRadius: 6, border: 'none', background: '#a78bfa', color: '#111', cursor: 'pointer' }}
            >
              CONFIRM
            </button>
            <button
              type="button"
              onClick={() => setConfirmDeep(false)}
              style={{ fontSize: 10, fontWeight: 700, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text2)', cursor: 'pointer' }}
            >
              CANCEL
            </button>
          </div>
        </div>
      )}

      <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 8 }}>
        Provenance: {artifact?.provenance?.provider || 'deepseek'} · {model} · {artifact?.provenance?.policy || 'CIO_DAILY_PRO'}
        {artifact?.usage?.actual_cost_usd != null ? ` · $${artifact.usage.actual_cost_usd}` : ''}
      </div>
    </div>
  )
}
