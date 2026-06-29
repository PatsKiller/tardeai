import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { getOperator, getToken } from '../lib/adminWrite'

// Finviz Screener Governance — view every Finviz screener (operator presets + DB-discovered), its
// strategy family, cadence class, when it runs next, last-run + row count, and whether it feeds the
// targeted momentum-scalp lane. Operator can edit cadence/notes, enable/disable, or trigger a SOURCE-ONLY
// run-now. NO screener is GO-eligible by itself; run-now fetches Finviz only — it never trades or bypasses
// a gate. All edits are audited (operator/timestamp/before-after) by admin_write_guard.

interface Screener {
  screener_id: string; preset_id?: string; name?: string; strategy_family?: string
  time_sensitivity?: string; cadence_class?: string; active?: boolean; url?: string
  last_run?: string | null; next_run?: string; rows_last_run?: number | null
  go_eligible_by_itself?: boolean; classification_status?: string; in_scalp_lane?: boolean
}

const FAM_COLOR: Record<string, string> = {
  momentum_scalp: '#ef4444', gapper: '#f97316', momentum: '#f59e0b',
  swing: '#60a5fa', value: '#22c55e', income: '#a855f7', fundamental: '#34d399',
}
async function adminPost(path: string, body: any): Promise<any> {
  const r = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...body, operator: getOperator(), token: getToken() }),
  })
  return r.json()
}

export default function FinvizScreenerPanel() {
  const { data, refetch } = useApi<any>('/api/admin/finviz-screeners', 120_000)
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [edit, setEdit] = useState<Screener | null>(null)
  const [editCadence, setEditCadence] = useState('')
  const [editNotes, setEditNotes] = useState('')

  if (!data) return <div style={{ padding: 20, color: 'var(--text3)' }}>Loading Finviz screener governance…</div>
  const screeners: Screener[] = data.screeners ?? []
  const scalpIds: string[] = data.scalp_lane_screener_ids ?? []

  async function act(s: Screener, action: 'enable' | 'disable' | 'run-now') {
    setBusy(`${s.screener_id}:${action}`); setMsg(null)
    try {
      const r = await adminPost(`/api/admin/finviz-screeners/${s.screener_id}/${action}`, {})
      if (r.ok) {
        setMsg(action === 'run-now'
          ? `run-now ${s.screener_id}: ${r.unique_symbols ?? 0} symbols (source fetch only — no trade)`
          : `${s.screener_id} ${action}d`)
        refetch()
      } else setMsg(`error: ${r.error}`)
    } catch (e: any) { setMsg(`error: ${e?.message}`) }
    setBusy(null)
  }
  async function saveEdit() {
    if (!edit) return
    setBusy(`${edit.screener_id}:update`); setMsg(null)
    try {
      const r = await adminPost(`/api/admin/finviz-screeners/${edit.screener_id}/update`,
        { cadence_class: editCadence || undefined, notes: editNotes || undefined })
      setMsg(r.ok ? `${edit.screener_id} updated` : `error: ${r.error}`)
      if (r.ok) { setEdit(null); refetch() }
    } catch (e: any) { setMsg(`error: ${e?.message}`) }
    setBusy(null)
  }

  const presets = screeners.filter(s => s.preset_id)
  const discovered = screeners.filter(s => !s.preset_id)

  const row = (s: Screener) => {
    const fc = FAM_COLOR[s.strategy_family ?? ''] ?? 'var(--text3)'
    const k = (a: string) => `${s.screener_id}:${a}`
    return (
      <tr key={s.screener_id} style={{ borderBottom: '1px solid var(--border)' }}>
        <td style={{ padding: '6px 8px' }}>
          <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text0)' }}>
            {s.name ?? s.screener_id}
            {s.in_scalp_lane && <span style={{ marginLeft: 6, fontSize: 8.5, fontWeight: 800, padding: '1px 5px', borderRadius: 4, color: '#ef4444', background: 'rgba(239,68,68,.14)' }}>SCALP LANE</span>}
          </div>
          <div style={{ fontSize: 9, color: 'var(--text3)', fontFamily: 'monospace' }}>
            {s.screener_id}{s.url && <a href={s.url} target="_blank" rel="noreferrer" style={{ marginLeft: 6, color: '#60a5fa' }}>finviz↗</a>}
          </div>
        </td>
        <td style={{ padding: '6px 8px' }}>
          <span style={{ fontSize: 9.5, fontWeight: 700, color: fc }}>{s.strategy_family ?? '—'}</span>
          <div style={{ fontSize: 8.5, color: 'var(--text3)' }}>{s.time_sensitivity ?? ''}</div>
        </td>
        <td style={{ padding: '6px 8px', fontSize: 10, color: 'var(--text2)' }}>{s.cadence_class ?? '—'}</td>
        <td style={{ padding: '6px 8px', fontSize: 9.5, color: 'var(--text3)' }}>{s.next_run ?? '—'}</td>
        <td style={{ padding: '6px 8px', fontSize: 9.5, color: 'var(--text3)' }}>
          {s.last_run ? s.last_run.slice(0, 16).replace('T', ' ') : '—'}
          {s.rows_last_run != null && <span style={{ marginLeft: 5, color: 'var(--text2)' }}>({s.rows_last_run})</span>}
        </td>
        <td style={{ padding: '6px 8px' }}>
          <span style={{ fontSize: 9, fontWeight: 800, padding: '1px 6px', borderRadius: 5, color: s.active ? '#22c55e' : 'var(--text3)', background: s.active ? 'rgba(34,197,94,.12)' : 'var(--bg2)' }}>
            {s.active ? 'ACTIVE' : 'OFF'}
          </span>
        </td>
        <td style={{ padding: '6px 8px', whiteSpace: 'nowrap' }}>
          <button onClick={() => act(s, 'run-now')} disabled={busy === k('run-now')} title="Source fetch only — never trades"
            style={btn('#60a5fa')}>{busy === k('run-now') ? '…' : 'run now'}</button>
          <button onClick={() => act(s, s.active ? 'disable' : 'enable')} disabled={!!busy}
            style={btn(s.active ? '#f59e0b' : '#22c55e')}>{s.active ? 'disable' : 'enable'}</button>
          <button onClick={() => { setEdit(s); setEditCadence(s.cadence_class ?? ''); setEditNotes('') }} disabled={!!busy}
            style={btn('var(--text2)')}>edit</button>
        </td>
      </tr>
    )
  }

  const table = (title: string, rows: Screener[], sub: string) => (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 11.5, fontWeight: 800, color: 'var(--text1)', margin: '4px 0' }}>{title} <span style={{ fontWeight: 400, color: 'var(--text3)' }}>· {sub}</span></div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr style={{ fontSize: 9, color: 'var(--text3)', textAlign: 'left' }}>
          <th style={{ padding: '4px 8px' }}>Screener</th><th>Family</th><th>Cadence class</th><th>Next run</th><th>Last run (rows)</th><th>State</th><th>Actions</th>
        </tr></thead>
        <tbody>{rows.map(row)}</tbody>
      </table>
    </div>
  )

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 800, color: 'var(--text0)' }}>Finviz Screener Governance</div>
          <div style={{ fontSize: 10.5, color: 'var(--text3)', marginTop: 2 }}>
            {data.count} screeners. The momentum-scalp 5-min lane uses ONLY the {scalpIds.length} targeted scalp/gapper screens
            (<span style={{ fontFamily: 'monospace' }}>{scalpIds.join(', ')}</span>) — never the broad all-active runner.
            Discovery only — no screener is GO-eligible by itself. run-now is source-fetch only (no trade, no gate bypass); edits audited.
          </div>
        </div>
        <button onClick={() => refetch()} style={btn('var(--text2)')}>refresh</button>
      </div>
      {msg && <div style={{ fontSize: 10.5, padding: '6px 10px', borderRadius: 6, marginBottom: 10, color: msg.startsWith('error') ? '#ef4444' : '#22c55e', background: msg.startsWith('error') ? 'rgba(239,68,68,.1)' : 'rgba(34,197,94,.1)' }}>{msg}</div>}

      {table('Operator presets', presets, 'purpose-built scalp/gapper/swing screens (registry-managed)')}
      {table('DB-discovered screeners', discovered, 'classified by strategy family + cadence class')}

      {edit && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }} onClick={() => setEdit(null)}>
          <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 18, width: 420 }}>
            <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', marginBottom: 4 }}>Edit screener metadata</div>
            <div style={{ fontSize: 9.5, color: 'var(--text3)', fontFamily: 'monospace', marginBottom: 12 }}>{edit.screener_id} — {edit.name}</div>
            <label style={{ fontSize: 10, color: 'var(--text2)' }}>Cadence class</label>
            <select value={editCadence} onChange={e => setEditCadence(e.target.value)} style={inp}>
              {['scalp_fast', 'scout_intraday', 'swing_intraday', 'swing_daily', 'fundamental_daily', 'income_weekly', 'experimental_disabled'].map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <label style={{ fontSize: 10, color: 'var(--text2)', marginTop: 10, display: 'block' }}>Notes</label>
            <input value={editNotes} onChange={e => setEditNotes(e.target.value)} placeholder="governance note (optional)" style={inp} />
            <div style={{ fontSize: 9, color: 'var(--text3)', margin: '10px 0' }}>Metadata only — cannot create a trade or bypass any gate. Change is audited (operator/timestamp/before→after).</div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={() => setEdit(null)} style={btn('var(--text2)')}>cancel</button>
              <button onClick={saveEdit} disabled={!!busy} style={btn('#60a5fa')}>{busy ? 'saving…' : 'save (audited)'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function btn(c: string): React.CSSProperties {
  return { fontSize: 9.5, fontWeight: 700, padding: '3px 8px', marginRight: 5, borderRadius: 5, border: `1px solid ${c}`, color: c, background: 'transparent', cursor: 'pointer' }
}
const inp: React.CSSProperties = { width: '100%', marginTop: 4, padding: '6px 8px', fontSize: 11, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }
