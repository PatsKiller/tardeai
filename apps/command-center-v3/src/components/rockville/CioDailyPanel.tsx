/**
 * Rockville CIO Daily Synthesis panel (above symbol cards).
 * Displays truthful provenance — NEVER defaults missing fields to DeepSeek.
 */
import { useState } from 'react'
import { BB, TYPE } from '../../lib/watchTokens'

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
    provider?: string | null
    model?: string | null
    policy?: string | null
    thinking?: boolean | null
    effort?: string | null
    execution?: string | null
    artifact_type?: string | null
    provider_call_occurred?: boolean | null
    request_id?: string | null
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

function isProviderCompleted(art?: CioArtifact | null): boolean {
  if (!art) return false
  const p = art.provenance || {}
  if (p.provider_call_occurred === false) return false
  if (art.status === 'NO_MATERIAL_CHANGE') return false
  if (p.policy === 'NO_CALL') return false
  // Require real provider evidence — never invent
  return Boolean(p.provider && p.model && p.request_id && p.provider_call_occurred)
}

export default function CioDailyPanel({
  artifact, status, onDeepReview, onViewPrior, onViewEvidence, onViewChanges,
}: Props) {
  const [confirmDeep, setConfirmDeep] = useState(false)
  const stance = artifact?.executive_stance
  const queue = artifact?.operator_priority_queue || []
  const prov = artifact?.provenance || {}
  const st = status || artifact?.status || 'NONE'
  const noCall = st === 'NO_MATERIAL_CHANGE' || prov.policy === 'NO_CALL' || prov.provider_call_occurred === false || !isProviderCompleted(artifact)
  const providerDone = isProviderCompleted(artifact)
  const when = artifact?.generated_at
    ? new Date(artifact.generated_at).toLocaleString('en-US', {
        hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York', timeZoneName: 'short',
      })
    : '—'

  return (
    <div
      data-rockville-cio
      data-cio-status={st}
      data-provider-call={providerDone ? 'true' : 'false'}
      style={{
        background: BB.bgPanel,
        border: `1px solid ${BB.border}`,
        borderRadius: 12,
        padding: 14,
        marginBottom: 14,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div style={{ fontSize: TYPE.base, fontWeight: 900, color: BB.text0 }}>
            CIO DAILY SYNTHESIS
          </div>
          <div style={{ fontSize: TYPE.sm, color: BB.text3, marginTop: 2 }}>
            {noCall
              ? `CIO STATUS: ${st || 'NO MATERIAL CHANGE'} · Generated ${when}`
              : `Generated ${when} · Provider artifact`}
          </div>
        </div>
        <div style={{ fontSize: TYPE.sm, color: BB.text2 }}>
          {artifact?.changed_symbol_count ?? 0} material symbol changes · {artifact?.held_position_change_count ?? 0} held-position changes
        </div>
      </div>

      {artifact?.failure_code && (
        <div style={{ marginTop: 8, fontSize: TYPE.sm, color: BB.red, fontWeight: 700 }}>
          Provider failure: {artifact.failure_code} (no silent fallback)
        </div>
      )}

      <div style={{ marginTop: 10 }}>
        <div style={{ fontSize: TYPE.sm, fontWeight: 800, color: BB.text3, letterSpacing: 0.4 }}>TODAY&apos;S POSTURE</div>
        <div style={{ fontSize: TYPE.base, fontWeight: 800, color: BB.text0, marginTop: 4 }}>
          {(stance?.posture || 'INSUFFICIENT_EVIDENCE').replace(/_/g, ' ')}
        </div>
        <div style={{ fontSize: TYPE.base, color: BB.text1, marginTop: 4, lineHeight: 1.45 }}>
          {stance?.summary || 'No CIO artifact yet. Shadow scheduler runs at 4:20 PM ET on material change only.'}
        </div>
      </div>

      {/* Provenance truth panel */}
      <div
        style={{
          marginTop: 10,
          padding: 10,
          borderRadius: 8,
          border: `1px solid ${BB.border}`,
          background: BB.bgShift,
          fontSize: TYPE.sm,
          color: BB.text2,
          lineHeight: 1.45,
        }}
        data-cio-provenance={noCall ? 'no_call' : 'provider'}
      >
        {noCall ? (
          <>
            <div style={{ fontWeight: 800, color: BB.text0 }}>NO PROVIDER CALL</div>
            <div>Execution: {prov.execution || 'deterministic scheduler'}</div>
            <div>Provider: NONE</div>
            <div>Model: NONE</div>
            <div>Policy: {prov.policy || 'NO_CALL'}</div>
            <div>Request ID: NONE</div>
            <div>Artifact type: {prov.artifact_type || 'no-change decision'}</div>
            <div>Cost: ${Number(artifact?.usage?.actual_cost_usd ?? 0).toFixed(2)}</div>
          </>
        ) : (
          <>
            <div style={{ fontWeight: 800, color: BB.text0 }}>PROVIDER CALL COMPLETED</div>
            <div>Provider: {prov.provider}</div>
            <div>Model: {prov.model}</div>
            <div>Policy: {prov.policy}</div>
            <div>Thinking: {prov.thinking ? 'yes' : 'no'}{prov.effort ? ` · effort ${prov.effort}` : ''}</div>
            <div>Request ID: {prov.request_id}</div>
            <div>Cost: ${Number(artifact?.usage?.actual_cost_usd ?? 0).toFixed(4)}</div>
          </>
        )}
      </div>

      {queue.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: TYPE.sm, fontWeight: 800, color: BB.text3 }}>TOP OPERATOR ACTIONS</div>
          <ol style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: TYPE.base, color: BB.text1 }}>
            {queue.slice(0, 5).map((q, i) => (
              <li key={i} style={{ marginBottom: 4 }}>
                <b>{q.symbol}</b> — {q.next_operator_action} <span style={{ color: BB.text3 }}>({q.state})</span>
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
              fontSize: TYPE.xs, fontWeight: 800, padding: '6px 10px', borderRadius: 6,
              border: `1px solid ${BB.border}`, background: BB.bgShift, color: BB.text1, cursor: 'pointer',
            }}
          >
            {b.label}
          </button>
        ))}
        <button
          type="button"
          disabled
          title="DEEP REVIEW GATED — ROLLOUT NOT ENABLED"
          style={{
            fontSize: TYPE.xs, fontWeight: 800, padding: '6px 10px', borderRadius: 6,
            border: `1px solid ${BB.border}`, background: BB.bgShift, color: BB.text3,
            cursor: 'not-allowed', opacity: 0.65,
          }}
        >
          DEEP REVIEW GATED — ROLLOUT NOT ENABLED
        </button>
      </div>

      {confirmDeep && null}
    </div>
  )
}
