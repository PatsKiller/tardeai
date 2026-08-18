import { useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'

const panel: CSSProperties = {
  background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14,
}
const label: CSSProperties = {
  fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: .5, fontWeight: 750,
}

function Badge({ children, tone = 'slate' }: { children: string; tone?: string }) {
  const color = tone === 'green' ? 'var(--green)' : tone === 'amber' ? 'var(--amber)' : tone === 'red' ? 'var(--red)' : 'var(--text2)'
  return <span style={{ fontSize: 10, fontWeight: 800, color, border: '1px solid var(--border)', borderRadius: 999, padding: '2px 7px' }}>{children}</span>
}

export default function ClosedLoopPanel() {
  const { data, loading, error } = useApi<any>('/api/v3/intelligence', 30_000)
  const { data: queue } = useApi<any>('/api/v3/intelligence/queue', 30_000)
  const [open, setOpen] = useState<string | null>(null)
  const { data: one } = useApi<any>(
    open ? `/api/v3/intelligence/lineage/${encodeURIComponent(open)}` : '/api/v3/intelligence/authority',
    undefined,
    { enabled: !!open },
  )
  const lineages = data?.lineages || []
  const byStatus = data?.by_status || {}
  const ch = data?.challenges || {}
  return (
    <div data-testid="closed-loop-panel">
      <div style={{ ...panel, marginBottom: 12 }}>
        <div style={{ fontWeight: 800 }}>Closed-loop lineage</div>
        <div style={{ marginTop: 4, fontSize: 12, color: 'var(--text3)' }}>
          IntelligenceLineage@v1 · READ_ONLY_ADVISORY · never invents market P&amp;L · MEMORY_BEHAVIOR_INFLUENCE=0
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
          <Badge>{`lineages ${String(data?.lineage_count ?? 0)}`}</Badge>
          <Badge tone="amber">{`pending challenges ${String(data?.pending_challenges ?? ch.pending ?? 0)}`}</Badge>
          <Badge>{`challenge events ${String(data?.challenge_events ?? ch.events ?? 0)}`}</Badge>
          <Badge>{`streams ${String(data?.unique_streams ?? ch.unique_streams ?? 0)}`}</Badge>
          {Object.entries(byStatus).map(([k, v]) => <Badge key={k}>{`${k} ${String(v)}`}</Badge>)}
        </div>
        <div style={{ ...label, marginTop: 10 }}>
          snapshot {data?.generated_at || 'MISSING'} · latest {data?.latest_lineage_id || 'MISSING'}
        </div>
        {queue && (
          <div style={{ marginTop: 10, fontSize: 12 }}>
            queue pending={String(queue.pending ?? '—')} oldest_h={String(queue.oldest_age_hours ?? '—')}
            {' · '}reasons {JSON.stringify(queue.by_reason || {})}
          </div>
        )}
      </div>
      {loading && <div style={panel}>Loading lineage…</div>}
      {error && <div style={{ ...panel, color: 'var(--amber)' }}>{String(error)}</div>}
      <div style={panel}>
        <div style={label}>Lineages rebuilt from live CIO evidence (real IDs only)</div>
        <div style={{ overflowX: 'auto', marginTop: 8 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr>{['symbol', 'status', 'lineage_id', 'research req', 'memory', 'case', 'outcome'].map(c => (
                <th key={c} style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text3)', fontSize: 10 }}>{c}</th>
              ))}</tr>
            </thead>
            <tbody>
              {lineages.slice(0, 80).map((r: any) => (
                <tr key={r.lineage_id} onClick={() => setOpen(r.lineage_id)} style={{ cursor: 'pointer' }}>
                  <td style={{ padding: '6px 8px', borderTop: '1px solid var(--border-subtle)' }}>{r.symbol}</td>
                  <td style={{ padding: '6px 8px', borderTop: '1px solid var(--border-subtle)' }}>{r.status}</td>
                  <td style={{ padding: '6px 8px', borderTop: '1px solid var(--border-subtle)', fontFamily: 'ui-monospace, monospace' }}>{r.lineage_id}</td>
                  <td style={{ padding: '6px 8px', borderTop: '1px solid var(--border-subtle)' }}>{(r.research_request_ids || []).length}</td>
                  <td style={{ padding: '6px 8px', borderTop: '1px solid var(--border-subtle)' }}>{(r.memory_ids || []).length}</td>
                  <td style={{ padding: '6px 8px', borderTop: '1px solid var(--border-subtle)' }}>{r.cio_case_id || '—'}</td>
                  <td style={{ padding: '6px 8px', borderTop: '1px solid var(--border-subtle)' }}>{r.outcome_id || '—'}</td>
                </tr>
              ))}
              {lineages.length === 0 && !loading && (
                <tr><td colSpan={7} style={{ padding: 12, color: 'var(--text3)' }}>No snapshot yet. Observer rebuilds on the 18:30 outcome-scorer timer, or run closed_loop_reconcile.py.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      {open && one?.lineage && (
        <pre style={{ ...panel, marginTop: 12, fontSize: 11, whiteSpace: 'pre-wrap', overflowX: 'auto' }}>
          {JSON.stringify(one.lineage, null, 2)}
        </pre>
      )}
    </div>
  )
}
