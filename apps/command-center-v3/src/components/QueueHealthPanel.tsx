import { useCallback, useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'

const MUTED = '#94a3b8'
const TEXT0 = '#f8fafc'
const TEXT1 = '#dbeafe'
const GREEN = '#22c55e'
const AMBER = '#f59e0b'
const BLUE = '#60a5fa'
const RED = '#ef4444'

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 14 } as const
const chip = { fontSize: 9, fontWeight: 800, padding: '3px 8px', borderRadius: 5, textTransform: 'uppercase' as const, letterSpacing: '0.3px' }
const sevColor = (s: string) => s === 'high' ? RED : s === 'medium' ? AMBER : s === 'low' ? BLUE : MUTED
const actionColor = (a: string) => a === 'reject' ? RED : a === 'expire' ? AMBER : MUTED

type ClassRow = {
  proposal_id: number
  symbol?: string
  strategy_id?: string
  action?: string
  new_status?: string
  reasons?: string[]
  drift_pct?: number | null
  thesis_zone?: string | null
}

/**
 * #28 — Queue-health/audit panel. Consumes GET /api/v2/broker-proposals/audit
 * (pipeline-dysfunction report + dry-run broker-queue sweep preview). Lets the
 * operator re-queue a REJECTED/EXPIRED proposal back to PENDING.
 */
export default function QueueHealthPanel({ onRequeued }: { onRequeued?: () => void } = {}) {
  const [open, setOpen] = useState(false)
  // Poll only while the panel is open to avoid an extra background fetch on every tab visit.
  const { data, loading, error, refetch } = useApi<any>(
    '/api/v2/broker-proposals/audit',
    120_000,
    { enabled: open },
  )
  const [requeueBusy, setRequeueBusy] = useState<Record<number, boolean>>({})
  const [msg, setMsg] = useState('')

  const audit = data || {}
  const statusBreakdown: { status: string; n: number }[] = audit.status_breakdown ?? []
  const knownGaps: { id: string; severity: string; detail: string; fix?: string }[] = audit.known_gaps ?? []
  const staleRows: ClassRow[] = audit.broker_queue_stale ?? []
  const dupSymbols: { symbol: string; n: number; ids: number[] }[] = audit.duplicate_active_symbols ?? []
  const sweep = audit.broker_sweep_preview ?? {}
  const sweepProblems: ClassRow[] = (sweep.details ?? []).filter((d: ClassRow) => d.action && d.action !== 'keep')

  // Merge stale + sweep problem rows, de-duped by proposal_id — these are the requeue candidates.
  const problemRows = useMemo(() => {
    const byId = new Map<number, ClassRow>()
    for (const r of [...staleRows, ...sweepProblems]) {
      if (r?.proposal_id) byId.set(r.proposal_id, { ...(byId.get(r.proposal_id) || {}), ...r })
    }
    return Array.from(byId.values())
  }, [staleRows, sweepProblems])

  const requeue = useCallback(async (pid: number) => {
    setRequeueBusy(b => ({ ...b, [pid]: true }))
    setMsg('')
    try {
      const r = await fetch('/api/v2/broker-proposals/requeue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: pid }),
      }).then(x => x.json())
      const d = r.data ?? r
      if (r.ok && (d.success ?? true)) {
        setMsg(`✅ Re-queued #${pid} → PENDING`)
        refetch?.()
        onRequeued?.()
      } else {
        setMsg(`⛔ Re-queue #${pid}: ${d.message || d.error || r.error || 'failed'}`)
      }
    } catch (e: any) {
      setMsg(`⛔ Re-queue #${pid}: ${String(e).slice(0, 80)}`)
    } finally {
      setRequeueBusy(b => ({ ...b, [pid]: false }))
    }
  }, [refetch, onRequeued])

  const wouldExpire = Number(sweep.would_expire ?? 0)
  const wouldReject = Number(sweep.would_reject ?? 0)
  const sweepTone = (wouldExpire + wouldReject) > 0 ? AMBER : GREEN
  const highGaps = knownGaps.filter(g => g.severity === 'high').length

  return (
    <details style={card} open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary style={{ fontSize: 13, fontWeight: 800, color: TEXT0, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span>Queue Health · pipeline audit</span>
        {open && (
          <span
            role="button"
            tabIndex={0}
            aria-label="Refresh queue health audit"
            title="Refresh audit"
            onClick={(e) => { e.preventDefault(); refetch?.() }}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); refetch?.() } }}
            style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: MUTED, cursor: 'pointer' }}
          >↻ refresh</span>
        )}
        {!open && <span style={{ fontSize: 9, color: MUTED, fontWeight: 600 }}>(open to load · auto-refresh 120s)</span>}
        {audit.pending_count != null && (
          <span style={{ ...chip, background: 'rgba(96,165,250,.14)', color: BLUE }}>{audit.pending_count} pending</span>
        )}
        {(wouldExpire + wouldReject) > 0 && (
          <span style={{ ...chip, background: `${AMBER}1f`, color: AMBER }}>{wouldExpire + wouldReject} sweep-flagged</span>
        )}
        {highGaps > 0 && (
          <span style={{ ...chip, background: `${RED}1f`, color: RED }}>{highGaps} high gap{highGaps > 1 ? 's' : ''}</span>
        )}
      </summary>

      <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 12, fontSize: 11 }}>
        {loading && !data && <div style={{ color: MUTED }}>Loading audit…</div>}
        {error && !data && (
          <div style={{ color: AMBER }}>
            Audit unavailable ({error}) —{' '}
            <span role="button" tabIndex={0} aria-label="Retry audit"
              onClick={() => refetch?.()} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') refetch?.() }}
              style={{ color: BLUE, cursor: 'pointer', fontWeight: 700 }}>retry</span>
          </div>
        )}
        {msg && <div style={{ color: msg.startsWith('✅') ? GREEN : AMBER }}>{msg}</div>}

        {data && (
          <>
            {/* Counts row */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              <span style={{ ...chip, background: 'rgba(148,163,184,.12)', color: TEXT1 }}>
                broker queue {audit.broker_queue_count ?? 0}
              </span>
              <span style={{ ...chip, background: `${sweepTone}1a`, color: sweepTone }}>
                sweep · checked {sweep.checked ?? 0} · would expire {wouldExpire} · would reject {wouldReject}
              </span>
              {audit.audited_at && (
                <span style={{ ...chip, background: 'transparent', color: MUTED }}>audited {String(audit.audited_at).replace('T', ' ')}</span>
              )}
            </div>

            {/* Status breakdown */}
            {statusBreakdown.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {statusBreakdown.map(s => (
                  <span key={s.status} style={{ ...chip, background: 'rgba(2,6,23,.4)', color: TEXT1, border: '1px solid rgba(148,163,184,.15)' }}>
                    {s.status} <b style={{ color: TEXT0 }}>{s.n}</b>
                  </span>
                ))}
              </div>
            )}

            {/* Duplicate active symbols */}
            {dupSymbols.length > 0 && (
              <div style={{ fontSize: 10, color: MUTED }}>
                <b style={{ color: AMBER }}>Duplicate active symbols:</b>{' '}
                {dupSymbols.map(d => `${d.symbol} (×${d.n})`).join(' · ')}
              </div>
            )}

            {/* Problem / requeue candidates */}
            <div>
              <div style={{ fontSize: 10, fontWeight: 800, color: MUTED, textTransform: 'uppercase', letterSpacing: '0.3px', marginBottom: 6 }}>
                Sweep-flagged proposals ({problemRows.length})
              </div>
              {problemRows.length === 0 ? (
                <div style={{ fontSize: 10, color: GREEN }}>✓ No stale / superseded broker rows — queue is clean.</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {problemRows.map(r => (
                    <div key={r.proposal_id} style={{
                      display: 'flex', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap',
                      padding: '7px 10px', borderRadius: 8, background: 'rgba(2,6,23,.35)', border: '1px solid rgba(148,163,184,.15)',
                    }}>
                      <span style={{ fontFamily: 'ui-monospace, monospace', fontWeight: 800, color: TEXT0 }}>
                        {r.symbol || '—'} <span style={{ color: MUTED, fontWeight: 600 }}>#{r.proposal_id}</span>
                      </span>
                      {r.action && (
                        <span style={{ ...chip, background: `${actionColor(r.action)}1f`, color: actionColor(r.action) }}>
                          would {r.action}{r.new_status ? ` → ${r.new_status}` : ''}
                        </span>
                      )}
                      {r.drift_pct != null && (
                        <span style={{ fontSize: 9, color: MUTED }}>drift {Number(r.drift_pct) >= 0 ? '+' : ''}{Number(r.drift_pct).toFixed(1)}%</span>
                      )}
                      {(r.reasons || []).length > 0 && (
                        <span style={{ fontSize: 9.5, color: TEXT1, flex: '1 1 200px', lineHeight: 1.4 }}>
                          {(r.reasons || []).join(' · ')}
                        </span>
                      )}
                      <button
                        onClick={() => requeue(r.proposal_id)}
                        disabled={!!requeueBusy[r.proposal_id]}
                        aria-label={`Re-queue proposal ${r.proposal_id} to pending`}
                        title="Re-open this REJECTED/EXPIRED proposal back to PENDING"
                        style={{
                          marginLeft: 'auto', fontSize: 10, fontWeight: 800, padding: '4px 10px', borderRadius: 6,
                          border: `1px solid ${GREEN}`, background: 'rgba(34,197,94,.12)', color: GREEN,
                          cursor: requeueBusy[r.proposal_id] ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap',
                        }}
                      >
                        {requeueBusy[r.proposal_id] ? '…' : '↺ Re-queue'}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Known pipeline gaps */}
            {knownGaps.length > 0 && (
              <details>
                <summary style={{ fontSize: 10, fontWeight: 800, color: MUTED, textTransform: 'uppercase', letterSpacing: '0.3px', cursor: 'pointer' }}>
                  Known pipeline gaps ({knownGaps.length})
                </summary>
                <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 5 }}>
                  {knownGaps.map(g => (
                    <div key={g.id} style={{ fontSize: 9.5, color: TEXT1, lineHeight: 1.4, display: 'flex', gap: 8, alignItems: 'baseline' }}>
                      <span style={{ ...chip, background: `${sevColor(g.severity)}1a`, color: sevColor(g.severity) }}>{g.severity}</span>
                      <span><b style={{ color: TEXT0 }}>{g.id}</b> — {g.detail}{g.fix ? ` (fix: ${g.fix})` : ''}</span>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </>
        )}
      </div>
    </details>
  )
}
