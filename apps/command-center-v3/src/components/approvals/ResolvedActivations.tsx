import { useState } from 'react'
import ReadableTime from '../ReadableTime'
import type { ApprovalItem, ApprovalQueue } from '../../lib/operatorApprovals'

export type Reconcile = { state: 'LIVE' | 'SUPERSEDED' | 'WAITING'; evidence: string[]; reason: string; note?: string | null }
export type ReconciledItem = ApprovalItem & { reconcile?: Reconcile; version?: string }
export type QueueWithResolved = ApprovalQueue & { resolved?: ReconciledItem[] }

const LABEL: Record<string, string> = { LIVE: 'Already live', SUPERSEDED: 'Superseded' }

/** Activation packets the server reconciled as already applied or superseded. Kept, behind a toggle, never deleted. */
export default function ResolvedActivations({ items }: { items?: ReconciledItem[] }) {
  const [open, setOpen] = useState(false)
  const rows = items ?? []
  if (!rows.length) return null
  return <section className="stack" data-testid="approvals-resolved" style={{ marginTop: 12 }}>
    <button type="button" aria-expanded={open} aria-controls="approvals-resolved-list" data-testid="approvals-resolved-toggle"
      onClick={() => setOpen(value => !value)} style={{ minHeight: 44, width: '100%', textAlign: 'left' }}>
      {open ? 'Hide' : 'Show'} resolved activations ({rows.length}) — already live or superseded
    </button>
    {open && <div id="approvals-resolved-list" className="stack">
      {rows.map(item => <article key={item.id} className="rule" data-testid="approvals-resolved-row">
        <span className="badge">{LABEL[item.reconcile?.state ?? ''] ?? 'Resolved'}</span>
        <h2 style={{ fontSize: 15, margin: '8px 0 4px' }}>{item.title}</h2>
        <p style={{ margin: '0 0 4px' }}>{item.reconcile?.reason}</p>
        {item.reconcile?.note && <p className="muted" style={{ margin: '0 0 4px' }}>{item.reconcile.note}</p>}
        <p className="muted" style={{ margin: 0 }}>
          Proposed by {item.proposed_by ?? 'unknown'}
          {item.created_at ? <> · <ReadableTime value={item.created_at} /></> : ' · date unknown'}
          {item.version ? <> · packet <code>{item.version}</code></> : null}
        </p>
      </article>)}
    </div>}
  </section>
}
