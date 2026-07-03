import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

export type ThresholdProposal = {
  id: string
  threshold_id?: string
  label?: string
  current_value?: number
  proposed_value?: number
  direction?: string
  reasoning?: string
  expected_impact?: string
  evidence?: {
    confidence?: string
    metric_contributions?: Record<string, number>
    score_delta?: number
    sample_days?: number
  }
  _override_value?: number
}

type Action = 'approve' | 'reject'

const CONFIDENCE_COLOR: Record<string, string> = {
  high: '#22c55e',
  medium: '#f59e0b',
  low: '#ef4444',
}

function formatThresholdValue(tid: string | undefined, value: number) {
  if (tid?.includes('divergence') || tid?.startsWith('stop_quality')) {
    return `${(value * 100).toFixed(1)}pp`
  }
  return value.toFixed(3)
}

function directionLabel(direction?: string) {
  const d = String(direction ?? '').toLowerCase()
  if (d === 'tighten') return 'Tightening'
  if (d === 'loosen') return 'Loosening'
  return 'Adjustment'
}

function directionColor(direction?: string, isApprove = true) {
  const d = String(direction ?? '').toLowerCase()
  if (d === 'loosen') return isApprove ? '#f59e0b' : '#ef4444'
  if (d === 'tighten') return '#60a5fa'
  return 'var(--text2)'
}

function topMetricContributions(contributions?: Record<string, number> | null, limit = 4) {
  if (!contributions) return []
  return Object.entries(contributions)
    .sort((a, b) => Math.abs(Number(b[1])) - Math.abs(Number(a[1])))
    .slice(0, limit)
}

async function postThresholdProposalAction(
  proposalId: string,
  action: Action,
  body: Record<string, unknown>,
) {
  const r = await fetch(`/api/v2/hermes/thresholds/proposals/${proposalId}/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const json = await r.json()
  if (!r.ok && !json.reason) {
    return { ...json, ok: false, reason: json.error ?? `HTTP ${r.status}` }
  }
  return json
}

export default function ThresholdProposalModal({
  proposal,
  action,
  onClose,
  onSuccess,
  onError,
}: {
  proposal: ThresholdProposal
  action: Action
  onClose: () => void
  onSuccess: (message: string) => void
  onError?: (message: string) => void
}) {
  const isApprove = action === 'approve'
  const isLoosening = String(proposal.direction ?? '').toLowerCase() === 'loosen'
  const [notes, setNotes] = useState(isApprove ? (proposal.reasoning ?? '') : '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const confirmRef = useRef<HTMLButtonElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const evidence = proposal.evidence ?? {}
  const confidence = evidence.confidence
  const metricRows = useMemo(() => topMetricContributions(evidence.metric_contributions), [evidence.metric_contributions])

  const canSubmit = isApprove || notes.trim().length >= 3

  const confirm = useCallback(async () => {
    if (!canSubmit || busy) return
    setBusy(true)
    setError(null)
    const trimmed = notes.trim()
    const body: Record<string, unknown> = {
      by: 'operator_ui',
      notes: trimmed || undefined,
      reason: trimmed || undefined,
    }
    if (isApprove) {
      body.force_apply = true
      if (proposal._override_value != null) body.override_value = proposal._override_value
    } else {
      body.reason = trimmed
    }

    try {
      const res = await postThresholdProposalAction(proposal.id, action, body)
      if (res.ok) {
        const msg = isApprove
          ? (res.applied === false ? 'Proposal logged (review mode — not applied)' : 'Proposal approved')
          : 'Proposal rejected'
        onSuccess(msg)
        onClose()
      } else {
        const errMsg = res.error ?? res.reason ?? `${isApprove ? 'Approve' : 'Reject'} failed`
        setError(errMsg)
        onError?.(errMsg)
      }
    } catch (e) {
      const errMsg = String(e)
      setError(errMsg)
      onError?.(errMsg)
    } finally {
      setBusy(false)
    }
  }, [action, busy, canSubmit, isApprove, notes, onClose, onError, onSuccess, proposal])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) {
        e.preventDefault()
        onClose()
      }
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && canSubmit && !busy) {
        e.preventDefault()
        confirm()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, canSubmit, confirm, onClose])

  useEffect(() => {
    textareaRef.current?.focus()
  }, [])

  const title = isApprove ? 'Approve Threshold Change' : 'Reject Threshold Proposal'
  const dirLabel = directionLabel(proposal.direction)
  const dirColor = directionColor(proposal.direction, isApprove)

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="threshold-proposal-modal-title"
      style={{
        position: 'fixed', inset: 0, zIndex: 1100, background: 'rgba(0,0,0,.72)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
      }}
      onClick={() => { if (!busy) onClose() }}
    >
      <div
        style={{
          background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12,
          maxWidth: 520, width: '100%', maxHeight: '90vh', overflow: 'auto', padding: 20,
          boxShadow: '0 12px 40px rgba(0,0,0,.45)',
        }}
        onClick={e => e.stopPropagation()}
      >
        <div id="threshold-proposal-modal-title" style={{
          fontSize: 16, fontWeight: 800, color: isApprove ? 'var(--text0)' : '#ef4444', marginBottom: 4,
        }}>
          {title}
        </div>
        <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 14 }}>
          {proposal.id}
          {' · '}Esc to cancel
          {canSubmit && ' · Ctrl+Enter to confirm'}
        </div>

        {/* Change summary */}
        <div style={{
          padding: '12px 14px', background: 'var(--bg2)', borderRadius: 10, marginBottom: 12,
          borderLeft: `3px solid ${isApprove ? '#22c55e' : '#f59e0b'}`,
        }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>
            {proposal.label ?? proposal.threshold_id}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
            <span style={{ fontSize: 12, fontFamily: 'monospace', color: 'var(--text3)' }}>
              {formatThresholdValue(proposal.threshold_id, Number(proposal.current_value ?? 0))}
            </span>
            <span style={{ color: 'var(--text3)', fontSize: 14 }}>→</span>
            <span style={{
              fontSize: 14, fontWeight: 800, fontFamily: 'monospace',
              color: isApprove ? '#22c55e' : '#f59e0b',
              padding: '2px 8px', borderRadius: 4,
              background: isApprove ? 'rgba(34,197,94,.12)' : 'rgba(245,158,11,.12)',
            }}>
              {formatThresholdValue(proposal.threshold_id, Number(proposal.proposed_value ?? 0))}
            </span>
            <span style={{
              fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em',
              color: dirColor, padding: '3px 8px', borderRadius: 4,
              background: `${dirColor}18`, border: `1px solid ${dirColor}44`,
            }}>
              {dirLabel}
            </span>
          </div>
        </div>

        {isApprove && isLoosening && (
          <div style={{
            fontSize: 11, color: '#f59e0b', marginBottom: 12, padding: '10px 12px',
            background: 'rgba(245,158,11,.1)', border: '1px solid rgba(245,158,11,.35)', borderRadius: 8,
            lineHeight: 1.45,
          }}>
            <b>Loosening warning:</b> This change relaxes a conservative threshold. Loosening requires stronger
            evidence in scoring v2 and carries higher closed-loop risk — confirm you have reviewed the evidence below.
          </div>
        )}

        {/* Evidence (approve) or summary (reject) */}
        <div style={{
          fontSize: 10, color: 'var(--text3)', marginBottom: 10, padding: '10px 12px',
          background: 'var(--bg2)', borderRadius: 8, lineHeight: 1.5,
        }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6, textTransform: 'uppercase' }}>
            {isApprove ? 'Evidence' : 'Proposed change'}
          </div>
          {confidence && (
            <div style={{ marginBottom: 6 }}>
              Confidence{' '}
              <span style={{
                fontWeight: 700, color: CONFIDENCE_COLOR[String(confidence).toLowerCase()] ?? '#f59e0b',
              }}>
                {String(confidence).toUpperCase()}
              </span>
              {evidence.sample_days != null && (
                <span style={{ marginLeft: 8 }}>· {evidence.sample_days} sample days</span>
              )}
              {evidence.score_delta != null && (
                <span style={{ marginLeft: 8 }}>· Δ score {Number(evidence.score_delta).toFixed(4)}</span>
              )}
            </div>
          )}
          {proposal.reasoning && (
            <div style={{ color: 'var(--text2)', marginBottom: 6 }}>{proposal.reasoning}</div>
          )}
          {metricRows.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <span style={{ color: 'var(--text2)', fontWeight: 600 }}>Top metrics: </span>
              {metricRows.map(([k, v]) => (
                <span key={k} style={{ marginRight: 8 }}>
                  {k.replace(/_/g, ' ')} <b>{Number(v).toFixed(3)}</b>
                </span>
              ))}
            </div>
          )}
          {proposal.expected_impact && (
            <div>
              <span style={{ color: 'var(--text2)', fontWeight: 600 }}>Expected impact: </span>
              {proposal.expected_impact}
            </div>
          )}
        </div>

        <label style={{ fontSize: 10, color: 'var(--text2)', display: 'block', marginBottom: 6 }}>
          {isApprove ? 'Notes / reason for approval (optional)' : 'Reason for rejection (required)'}
        </label>
        <textarea
          ref={textareaRef}
          value={notes}
          onChange={e => setNotes(e.target.value)}
          placeholder={isApprove
            ? 'Add operator notes — pre-filled from learner reasoning'
            : 'Why reject this proposal? (min 3 characters)'}
          rows={4}
          disabled={busy}
          style={{
            width: '100%', boxSizing: 'border-box', fontSize: 11, padding: '8px 10px',
            borderRadius: 6, border: `1px solid ${!isApprove && notes.trim().length < 3 ? 'rgba(239,68,68,.4)' : 'var(--border)'}`,
            background: 'var(--bg2)', color: 'var(--text0)', resize: 'vertical', marginBottom: 8,
          }}
        />
        {!isApprove && notes.trim().length < 3 && (
          <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8 }}>
            Please provide a brief rejection reason (at least 3 characters).
          </div>
        )}

        {error && (
          <div style={{
            fontSize: 11, color: '#ef4444', marginBottom: 10, padding: '8px 10px',
            background: 'rgba(239,68,68,.08)', border: '1px solid rgba(239,68,68,.3)', borderRadius: 6,
          }}>
            {error}
          </div>
        )}

        {busy && (
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>
            {isApprove ? 'Applying threshold change…' : 'Recording rejection…'}
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            style={{
              fontSize: 11, padding: '8px 14px', borderRadius: 6, border: '1px solid var(--border)',
              background: 'var(--bg2)', color: 'var(--text2)', cursor: busy ? 'wait' : 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={confirm}
            disabled={busy || !canSubmit}
            style={{
              fontSize: 11, padding: '8px 18px', borderRadius: 6, border: 'none', fontWeight: 700,
              background: !canSubmit ? 'var(--bg2)' : isApprove ? '#22c55e' : '#ef4444',
              color: !canSubmit ? 'var(--text3)' : isApprove ? '#000' : '#fff',
              cursor: busy || !canSubmit ? 'not-allowed' : 'pointer', opacity: busy ? 0.7 : 1,
            }}
          >
            {busy ? 'Working…' : isApprove ? 'Approve' : 'Reject'}
          </button>
        </div>
      </div>
    </div>
  )
}