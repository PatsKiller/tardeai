import { useState } from 'react'
import ReadableTime from '../ReadableTime'
import type { ApprovalItem, ApprovalQueue } from '../../lib/operatorApprovals'

export type Reconcile = { state: 'LIVE' | 'SUPERSEDED' | 'WAITING'; evidence: string[]; reason: string; note?: string | null }
export type ReconciledItem = ApprovalItem & { reconcile?: Reconcile; version?: string; resolution?: string;
  resolved_at?: string; approval?: { state?: string; proof?: { created_at?: string } } }
export type QueueWithResolved = ApprovalQueue & { resolved?: ReconciledItem[] }

const LABEL: Record<string, string> = { LIVE: 'Already live', SUPERSEDED: 'Superseded' }

const RESOLUTION: Record<string, { label: string; reason: string }> = {
  policy_ratification_approved: { label: 'Approval recorded', reason: 'The exact policy version has a recorded approval.' },
  approval_recorded: { label: 'Approval recorded', reason: 'The coordinator recorded the approval for this item.' },
  superseded_by_active_policy: { label: 'Superseded', reason: 'A newer active policy supersedes this proposal.' },
  decision_resolved: { label: 'Decision resolved', reason: 'The coordinator marked this decision resolved.' },
  decision_cancelled: { label: 'Cancelled', reason: 'The coordinator cancelled this decision request.' },
  decision_superseded: { label: 'Superseded', reason: 'The coordinator marked this decision superseded.' },
}

/** Resolved decisions and reconciled activation packets remain readable as history. */
export default function ResolvedActivations({ items }: { items?: ReconciledItem[] }) {
  const [open, setOpen] = useState(false)
  const rows = items ?? []
  if (!rows.length) return null
  const activationOnly = rows.every(item => item.kind === 'ACTIVATE' && ['LIVE', 'SUPERSEDED'].includes(item.reconcile?.state ?? ''))
  return <section className="stack" data-testid="approvals-resolved" style={{ marginTop: 12 }}>
    <button type="button" aria-expanded={open} aria-controls="approvals-resolved-list" data-testid="approvals-resolved-toggle"
      onClick={() => setOpen(value => !value)} style={{ minHeight: 44, width: '100%', textAlign: 'left' }}>
      {open ? 'Hide' : 'Show'} resolved {activationOnly ? 'activations' : 'decisions'} ({rows.length}){activationOnly ? ' — already live or superseded' : ''}
    </button>
    {open && <div id="approvals-resolved-list" className="stack">
      {rows.map(item => <article key={item.id} className="rule" data-testid="approvals-resolved-row">
        <span className="badge">{LABEL[item.reconcile?.state ?? ''] ?? RESOLUTION[item.resolution ?? '']?.label ?? (item.approval?.state === 'approved' ? 'Approval recorded' : 'Resolved')}</span>
        <h2 style={{ fontSize: 15, margin: '8px 0 4px' }}>{item.title}</h2>
        <p style={{ margin: '0 0 4px' }}>{item.reconcile?.reason ?? RESOLUTION[item.resolution ?? '']?.reason ?? (item.approval?.state === 'approved' ? 'The exact version has a recorded approval.' : 'This request is resolved.')}</p>
        {item.source_sha && <p className="muted" style={{ margin: '0 0 4px' }}>Exact head: <code>{item.source_sha}</code></p>}
        {item.reconcile?.note && <p className="muted" style={{ margin: '0 0 4px' }}>{item.reconcile.note}</p>}
        <p className="muted" style={{ margin: 0 }}>
          Proposed by {item.proposed_by ?? 'unknown'}
          {item.created_at ? <> · <ReadableTime value={item.created_at} /></> : ' · date unknown'}
          {item.version ? <> · {item.kind === 'ACTIVATE' ? 'packet' : 'version'} <code>{item.version}</code></> : null}
        </p>
      </article>)}
    </div>}
  </section>
}
