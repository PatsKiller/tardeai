import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'

export interface TaskItem {
  id: number
  source: string
  category: string
  symbol: string
  title: string
  description: string
  priority: string
  status: string
  recommendation?: string
  confidence?: number
  due_by?: string
  linked_route?: string
  followup?: string
  decided_at?: string
  created_at?: string
  provenance?: Record<string, unknown>
}

interface Props {
  task: TaskItem | null
  onClose: () => void
  onDecided?: (taskId: number, status: string) => void
}

const S = { sans: 'var(--sans)' as const }

const PRIORITY_COLOR: Record<string, string> = { urgent: 'var(--red)', high: 'var(--amber)', normal: 'var(--accent)', low: 'var(--text3)' }
const STATUS_LABEL: Record<string, string> = {
  pending_john: 'Needs John', decided_action: 'Resolved', deferred: 'Deferred',
  rejected: 'Rejected', revisit_later: 'Revisit', closed: 'Closed',
  failed_stop_review: 'Auto-Review Failed', failed_automation: 'Automation Failed',
}
const CATEGORY_LABEL: Record<string, string> = {
  failed_stop_review: 'Failed Stop Review', failed_automation: 'Failed Automation',
  covered_call_decision: 'Covered Call', rotation_decision: 'Rotation',
  recovery_reentry_decision: 'Recovery Re-entry', risk_decision: 'Risk',
  thesis_decision: 'Thesis', general: 'General',
}

function humanize(v?: string) { return v ? (STATUS_LABEL[v] || CATEGORY_LABEL[v] || v.replace(/_/g, ' ').replace(/\b\w/g, s => s.toUpperCase())) : '—' }

export default function TaskDetailDrawer({ task, onClose, onDecided }: Props) {
  const nav = useNavigate()
  const [note, setNote] = useState('')
  const [deciding, setDeciding] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)

  const handleDecision = useCallback(async (status: string) => {
    if (!task) return
    if (!note.trim()) { alert('A rationale note is required for all decisions.'); return }
    setDeciding(status)
    try {
      const endpoint = task.source === 'action_queue' ? '/api/v2/approvals/decision' : '/api/v2/john/decide'
      const body = task.source === 'action_queue'
        ? { queue_id: task.id, decision: status === 'decided_action' ? 'approved' : 'rejected', note: note.trim() }
        : { id: task.id, status, decision: status, reasoning: note.trim() }
      const r = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const d = await r.json()
      if (d.ok) {
        setResult(humanize(status))
        onDecided?.(task.id, status)
        setTimeout(() => onClose(), 1200)
      } else {
        alert(d.error || 'Decision failed')
      }
    } catch { alert('Network error') }
    setDeciding(null)
  }, [task, note, onClose, onDecided])

  if (!task) return null

  const prov = task.provenance || {}
  const priColor = PRIORITY_COLOR[task.priority] || 'var(--text3)'
  const isFailed = task.category === 'failed_stop_review' || task.category === 'failed_automation'
  const resolvedPrice = Number(prov.resolved_price || prov.resolved_current_price || 0)
  const stopPrice = Number(prov.stop_price || 0)
  const marketValue = Number(prov.market_value || 0)
  const failureReason = String(prov.failure_reason || '')

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.55)', zIndex: 1100, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '20px 24px', width: 500, maxHeight: '85vh', overflowY: 'auto', fontFamily: S.sans }} onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 9, fontWeight: 800, padding: '2px 8px', borderRadius: 4, textTransform: 'uppercase', background: `color-mix(in srgb, ${priColor} 15%, transparent)`, color: priColor }}>{task.priority}</span>
            {isFailed && <span style={{ fontSize: 8, fontWeight: 700, padding: '2px 6px', borderRadius: 3, background: 'var(--red-dim)', color: 'var(--red)' }}>AUTO-REVIEW FAILED</span>}
            <span style={{ fontSize: 8, fontWeight: 600, padding: '2px 6px', borderRadius: 3, background: 'var(--bg3)', color: 'var(--text3)' }}>{humanize(task.category)}</span>
          </div>
          <button onClick={onClose} style={{ fontSize: 14, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'transparent', color: 'var(--text3)', cursor: 'pointer' }}>×</button>
        </div>

        {/* Symbol + Title */}
        {task.symbol && <div style={{ fontSize: 22, fontWeight: 800, color: '#fff', marginBottom: 4 }}>{task.symbol}</div>}
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10, lineHeight: 1.3 }}>{task.title}</div>

        {/* Description */}
        <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.6, marginBottom: 14, padding: '10px 12px', background: 'var(--bg3)', borderRadius: 6, borderLeft: `3px solid ${priColor}` }}>{task.description}</div>

        {/* Stop/Price context */}
        {(resolvedPrice > 0 || stopPrice > 0 || marketValue > 0) && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 14 }}>
            {resolvedPrice > 0 && <MetricBox label="Current Price" value={`$${resolvedPrice.toFixed(2)}`} />}
            {stopPrice > 0 && <MetricBox label="Stop Price" value={`$${stopPrice.toFixed(2)}`} color="var(--red)" />}
            {marketValue > 0 && <MetricBox label="Position Value" value={`$${marketValue.toLocaleString()}`} />}
          </div>
        )}

        {/* Failure reason */}
        {isFailed && failureReason && (
          <div style={{ fontSize: 10, color: 'var(--red)', padding: '6px 10px', background: 'var(--red-dim)', borderRadius: 4, marginBottom: 12, lineHeight: 1.4 }}>
            Failure: {failureReason}
          </div>
        )}

        {/* Follow-up */}
        {task.followup && <div style={{ fontSize: 11, color: 'var(--green)', fontWeight: 700, marginBottom: 8 }}>Next: {task.followup}</div>}

        {/* Due */}
        {task.due_by && <div style={{ fontSize: 10, color: priColor, marginBottom: 10 }}>Due: {task.due_by}</div>}

        {/* Route links */}
        {task.linked_route && (
          <div style={{ display: 'flex', gap: 6, marginBottom: 14 }}>
            <button onClick={() => nav(task.linked_route!)} style={routeBtn}>Open Risk Manager</button>
            <button onClick={() => nav('/recovery')} style={routeBtn}>Recovery Watch</button>
            <button onClick={() => nav('/approvals')} style={routeBtn}>All Tasks</button>
          </div>
        )}

        {/* Result banner */}
        {result && (
          <div style={{ padding: '8px 12px', background: 'var(--green-dim)', border: '1px solid var(--green)', borderRadius: 6, marginBottom: 12, fontSize: 11, fontWeight: 700, color: 'var(--green)', textAlign: 'center' }}>
            Decision saved: {result}
          </div>
        )}

        {/* Decision controls */}
        {!result && (
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 12, background: 'rgba(255,255,255,0.02)', margin: '0 -24px -20px', padding: '14px 24px 20px', borderRadius: '0 0 10px 10px' }}>
            <div style={{ fontSize: 10, color: 'var(--amber)', fontWeight: 700, marginBottom: 6 }}>Decision note required</div>
            <textarea value={note} onChange={e => setNote(e.target.value)}
              placeholder="Type your rationale here before clicking Resolve, Defer, or Reject..."
              rows={3} style={{ width: '100%', padding: '10px 12px', fontSize: 11, background: 'var(--bg1)', border: `1px solid ${note.trim() ? 'var(--green)' : 'var(--amber)'}`, borderRadius: 8, color: 'var(--text1)', fontFamily: 'var(--mono)', resize: 'vertical', outline: 'none', transition: 'border-color 120ms' }} />
            <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
              <DecisionBtn label="Resolve" color="var(--green)" status="decided_action" deciding={deciding} onClick={handleDecision} />
              <DecisionBtn label="Defer" color="var(--amber)" status="deferred" deciding={deciding} onClick={handleDecision} />
              <DecisionBtn label="Reject" color="var(--red)" status="rejected" deciding={deciding} onClick={handleDecision} />
            </div>
          </div>
        )}

        {/* Provenance footer */}
        <div style={{ marginTop: 14, padding: '6px 8px', background: 'var(--bg3)', borderRadius: 4, fontSize: 9, color: 'var(--text3)' }}>
          Source: {task.source?.replace(/_/g, ' ')} · Created: {task.created_at?.slice(0, 16) || '—'} · ID: {task.id}
        </div>
      </div>
    </div>
  )
}

function MetricBox({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ padding: '8px 10px', background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 6 }}>
      <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 3, fontFamily: 'var(--sans)' }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 800, color: color || 'var(--text0)', fontFamily: 'var(--sans)' }}>{value}</div>
    </div>
  )
}

function DecisionBtn({ label, color, status, deciding, onClick }: { label: string; color: string; status: string; deciding: string | null; onClick: (s: string) => void }) {
  return (
    <button onClick={() => onClick(status)} disabled={deciding !== null}
      style={{ flex: 1, padding: '8px 14px', fontSize: 11, fontWeight: 800, fontFamily: 'var(--sans)',
        border: `1px solid ${color}`, borderRadius: 6,
        background: `color-mix(in srgb, ${color} 10%, transparent)`,
        color, cursor: deciding ? 'wait' : 'pointer', opacity: deciding && deciding !== status ? 0.4 : 1,
      }}>
      {deciding === status ? 'Saving...' : label}
    </button>
  )
}

const routeBtn: React.CSSProperties = { fontSize: 9, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg3)', color: 'var(--accent)', cursor: 'pointer', fontFamily: 'var(--sans)' }
