import { useEffect, useState } from 'react'

const MUTED = '#94a3b8'
const TEXT0 = '#dbeafe'

type Ev = { id?: number; event_type?: string; lifecycle_status?: string; message?: string; created_at?: string }

export default function ProposalLifecycleTimeline({ proposalId }: { proposalId: number }) {
  const [events, setEvents] = useState<Ev[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open || !proposalId) return
    setLoading(true)
    fetch(`/api/v2/paper-proposals/lifecycle-inspector?proposal_id=${proposalId}`)
      .then(r => r.json())
      .then(d => setEvents(d.lifecycle_events || d.events || []))
      .catch(() => setEvents([]))
      .finally(() => setLoading(false))
  }, [open, proposalId])

  return (
    <details open={open} onToggle={e => setOpen((e.target as HTMLDetailsElement).open)}
      style={{ marginTop: 8, fontSize: 10 }}>
      <summary style={{ cursor: 'pointer', color: MUTED, fontWeight: 700 }}>Lifecycle timeline</summary>
      {loading && <div style={{ color: MUTED, marginTop: 4 }}>Loading…</div>}
      {!loading && events.length === 0 && <div style={{ color: MUTED, marginTop: 4 }}>No lifecycle events</div>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 6 }}>
        {events.map(ev => (
          <div key={ev.id ?? `${ev.created_at}-${ev.event_type}`}
            style={{ padding: '4px 8px', borderRadius: 6, background: 'rgba(15,23,42,.45)', border: '1px solid rgba(148,163,184,.12)' }}>
            <span style={{ color: TEXT0, fontWeight: 700 }}>{ev.event_type || ev.lifecycle_status || 'event'}</span>
            <span style={{ color: MUTED, marginLeft: 8 }}>{ev.created_at ? new Date(ev.created_at).toLocaleString() : ''}</span>
            {ev.message && <div style={{ color: MUTED, marginTop: 2 }}>{ev.message}</div>}
          </div>
        ))}
      </div>
    </details>
  )
}