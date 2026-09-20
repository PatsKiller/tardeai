import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react'
import { BB, T } from '../lib/watchTokens'

/**
 * Operator control for off-peak LLM routing.
 *
 * DeepSeek bills peak hours at roughly double off-peak, so work that is not
 * time-sensitive is queued for the next off-peak window instead of being paid for now.
 * This modal is where the operator decides which callers are exempt from that.
 *
 * The tiers are behaviours, not labels:
 *   critical  spend now, any hour
 *   standard  spend now inside the off-peak window; queue for the next one outside it
 *   deferred  always queue, never spend on demand
 *
 * `tier_source` matters: a caller nobody has classified shows as a default, never as a
 * decision someone made. Only rows the operator actually changed are sent on save.
 */

export type CallerRow = {
  process_id: string
  name: string
  category?: string
  lane_policy?: string
  daily_cost_cap_usd?: number | null
  tier: string
  tier_source: 'operator' | 'registry' | 'default'
}

type QueueSummary = {
  pending?: number
  next_run_after?: string | null
  window_open_now?: boolean
  enabled?: boolean
  counts?: Record<string, number>
}

type Props = { open: boolean; onClose: () => void; onSaved?: () => void }

const TIER_META: Record<string, { color: string; hint: string }> = {
  critical: { color: BB.orange, hint: 'Spends at any hour, including peak rates.' },
  standard: { color: BB.green, hint: 'Runs in the off-peak window; queued outside it.' },
  deferred: { color: T.link, hint: 'Always queued for the next off-peak window.' },
}

export default function LlmRoutingModal({ open, onClose, onSaved }: Props) {
  const [rows, setRows] = useState<CallerRow[]>([])
  const [tiers, setTiers] = useState<string[]>(['critical', 'standard', 'deferred'])
  const [queue, setQueue] = useState<QueueSummary>({})
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')

  const load = useCallback(async () => {
    setErr('')
    try {
      const r = await fetch('/api/v2/consumption/caller-priorities', { cache: 'no-store' })
      const j = await r.json()
      const d = j?.data ?? j
      setRows(d?.callers ?? [])
      setTiers(d?.tiers ?? ['critical', 'standard', 'deferred'])
      setQueue(d?.queue ?? {})
      setEdits({})
    } catch (e: any) {
      setErr(String(e?.message || e))
    }
  }, [])

  useEffect(() => { if (open) { void load() } }, [open, load])

  // Only what actually changed. Saving every row would rewrite every caller's
  // `tier_source` to "operator" and destroy the distinction the page is built on.
  const dirty = useMemo(
    () => Object.entries(edits).filter(([pid, t]) => rows.find(r => r.process_id === pid)?.tier !== t),
    [edits, rows],
  )

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return rows
    return rows.filter(r =>
      r.process_id.toLowerCase().includes(q) ||
      (r.name || '').toLowerCase().includes(q) ||
      (r.category || '').toLowerCase().includes(q))
  }, [rows, filter])

  async function save() {
    if (!dirty.length) return
    setBusy(true); setErr(''); setNote('')
    try {
      const r = await fetch('/api/v2/consumption/caller-priorities', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          updated_by: 'operator',
          updates: dirty.map(([process_id, tier]) => ({ process_id, tier })),
        }),
      })
      const j = await r.json()
      const d = j?.data ?? j
      if (!r.ok || d?.ok === false) throw new Error(d?.error || `save failed (${r.status})`)
      const rejected = (d?.rejected ?? []).length
      setNote(`Saved ${(d?.saved ?? []).length} caller(s)${rejected ? `, ${rejected} rejected` : ''}.`)
      await load()
      onSaved?.()
    } catch (e: any) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  const overlay: CSSProperties = {
    position: 'fixed', inset: 0, background: 'rgba(2, 6, 23, 0.72)', zIndex: 1000,
    display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
  }
  const panel: CSSProperties = {
    background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 10,
    width: 'min(980px, 96vw)', maxHeight: '88vh', display: 'flex', flexDirection: 'column',
    color: BB.text0, fontSize: 13,
  }
  const th: CSSProperties = {
    textAlign: 'left', padding: '6px 8px', color: BB.text3, fontWeight: 600,
    borderBottom: `1px solid ${BB.border}`, position: 'sticky', top: 0, background: BB.bg,
  }
  const td: CSSProperties = { padding: '6px 8px', borderBottom: `1px solid ${BB.border}` }

  return (
    <div style={overlay} onClick={onClose} role="presentation">
      <div style={panel} onClick={e => e.stopPropagation()} role="dialog"
           aria-modal="true" aria-label="LLM off-peak routing">
        <div style={{ padding: '12px 14px', borderBottom: `1px solid ${BB.border}` }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <strong>LLM Routing — off-peak priority</strong>
            <button onClick={onClose} style={{ background: 'none', border: 'none', color: BB.text3,
                                               cursor: 'pointer', fontSize: 18 }}>×</button>
          </div>
          <div style={{ color: BB.text3, marginTop: 6, lineHeight: 1.5 }}>
            DeepSeek bills peak hours at roughly double off-peak. Work that is not
            time-sensitive is queued for the next off-peak window rather than paid for now.
            Operator-initiated asks always run immediately, whatever a caller is set to.
          </div>
          <div style={{ marginTop: 8, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
            <span style={{ color: queue.enabled ? BB.green : BB.orange }}>
              deferral {queue.enabled ? 'ARMED' : 'not armed (LLM_DEFER_OFFPEAK unset)'}
            </span>
            <span style={{ color: BB.text3 }}>
              window {queue.window_open_now ? 'OPEN' : 'closed'}
            </span>
            <span style={{ color: BB.text3 }}>queued: {queue.pending ?? 0}</span>
            {queue.next_run_after && (
              <span style={{ color: BB.text3 }}>next drain: {queue.next_run_after}</span>
            )}
          </div>
        </div>

        <div style={{ padding: '8px 14px', borderBottom: `1px solid ${BB.border}` }}>
          <input value={filter} onChange={e => setFilter(e.target.value)}
                 placeholder="filter by caller, name or category"
                 style={{ width: '100%', background: BB.bgPanel, color: BB.text0,
                          border: `1px solid ${BB.border}`, borderRadius: 6, padding: '6px 8px' }} />
        </div>

        <div style={{ overflow: 'auto', flex: 1 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={th}>Caller</th>
                <th style={th}>Category</th>
                <th style={th}>Cap $/day</th>
                <th style={th}>Set by</th>
                <th style={th}>Priority</th>
              </tr>
            </thead>
            <tbody>
              {shown.map(r => {
                const cur = edits[r.process_id] ?? r.tier
                const changed = cur !== r.tier
                return (
                  <tr key={r.process_id} style={{ background: changed ? BB.bgShift : undefined }}>
                    <td style={td}>
                      <div>{r.name}</div>
                      <div style={{ color: BB.text3, fontSize: 11 }}>{r.process_id}</div>
                    </td>
                    <td style={{ ...td, color: BB.text3 }}>{r.category || '—'}</td>
                    <td style={{ ...td, color: BB.text3 }}>
                      {r.daily_cost_cap_usd == null ? '—' : `$${Number(r.daily_cost_cap_usd).toFixed(2)}`}
                    </td>
                    <td style={{ ...td, color: r.tier_source === 'operator' ? BB.text0 : BB.text3 }}>
                      {r.tier_source}
                    </td>
                    <td style={td}>
                      <select value={cur} disabled={busy}
                              onChange={e => setEdits(p => ({ ...p, [r.process_id]: e.target.value }))}
                              style={{ background: BB.bgPanel, color: TIER_META[cur]?.color ?? BB.text0,
                                       border: `1px solid ${BB.border}`, borderRadius: 6, padding: '4px 6px' }}>
                        {tiers.map(t => <option key={t} value={t}>{t}</option>)}
                      </select>
                      <div style={{ color: BB.text3, fontSize: 11, marginTop: 2 }}>
                        {TIER_META[cur]?.hint}
                      </div>
                    </td>
                  </tr>
                )
              })}
              {!shown.length && (
                <tr><td style={{ ...td, color: BB.text3 }} colSpan={5}>No callers match.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div style={{ padding: '10px 14px', borderTop: `1px solid ${BB.border}`,
                      display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ color: dirty.length ? BB.orange : BB.text3 }}>
            {dirty.length ? `${dirty.length} unsaved change(s)` : 'no changes'}
          </span>
          {err && <span style={{ color: BB.red }}>{err}</span>}
          {note && <span style={{ color: BB.green }}>{note}</span>}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <button onClick={onClose} disabled={busy}
                    style={{ background: BB.border, color: BB.text0, border: 'none',
                             borderRadius: 6, padding: '6px 12px', cursor: 'pointer' }}>
              Close
            </button>
            <button onClick={save} disabled={busy || !dirty.length}
                    style={{ background: dirty.length ? T.link : BB.border, color: BB.text0,
                             border: 'none', borderRadius: 6, padding: '6px 12px',
                             cursor: dirty.length ? 'pointer' : 'default' }}>
              {busy ? 'Saving…' : 'Save priorities'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
