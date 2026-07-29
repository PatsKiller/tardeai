import { useEffect, useState } from 'react'
import { BB, T } from '../../lib/watchTokens'

const panel = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 2 }
const input = { background: 'var(--bg2)', color: 'var(--text0)', border: '1px solid var(--border)', borderRadius: 2, padding: '5px 7px', fontSize: 11 }

type Row = {
  alert_type: string
  general_telegram: 'OFF' | 'IMMEDIATE' | 'DIGEST'
  approval_telegram: 'OFF' | 'IMMEDIATE'
  command_center: boolean
  digest_bucket: 'RISK' | 'TRADING' | 'OPS'
  ttl_seconds: number
  dedupe_window_seconds: number
  escalate_after_seconds?: number | null
  sound_enabled: boolean
  row_version: number
  trailing_volume: number
  last_delivery_at?: string | null
  last_suppression_reason?: string | null
}

export default function AlertSettingsModal({ onClose }: { onClose: () => void }) {
  const [rows, setRows] = useState<Row[]>([])
  const [selected, setSelected] = useState<Row | null>(null)
  const [draft, setDraft] = useState<Row | null>(null)
  const [preview, setPreview] = useState<any>(null)
  const [status, setStatus] = useState('')

  const load = async () => {
    const [settings, projection] = await Promise.all([
      fetch('/api/v3/alerts/settings?days=7', { cache: 'no-store' }).then(r => r.json()),
      fetch('/api/v3/alerts/settings/preview?days=7', { cache: 'no-store' }).then(r => r.json()).catch(() => null),
    ])
    const next = settings?.settings || []
    setRows(next)
    setPreview(projection)
    if (!selected && next[0]) { setSelected(next[0]); setDraft({ ...next[0] }) }
  }

  useEffect(() => { void load() }, []) // eslint-disable-line

  const choose = (r: Row) => { setSelected(r); setDraft({ ...r }); setStatus('') }
  const patch = (k: keyof Row, v: any) => setDraft(d => d ? { ...d, [k]: v } : d)
  const save = async () => {
    if (!draft) return
    setStatus('saving')
    const r = await fetch('/api/v3/alerts/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...draft, updated_by: 'command_center_v3' }),
    }).then(x => x.json())
    if (!r.ok) { setStatus((r.errors || [r.error || 'save failed']).join(' · ')); return }
    setStatus('saved')
    await load()
  }
  const testSend = async () => {
    if (!draft) return
    setStatus('synthetic test queued')
    const r = await fetch('/api/v3/alerts/test-send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ alert_type: draft.alert_type }),
    }).then(x => x.json())
    setStatus(r.ok ? 'synthetic test event queued' : (r.errors || ['test failed']).join(' · '))
  }

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(0,0,0,.72)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div onClick={e => e.stopPropagation()} style={{ ...panel, width: 'min(1120px,96vw)', maxHeight: '90vh', overflow: 'hidden', display: 'grid', gridTemplateColumns: '320px 1fr' }}>
        <div style={{ borderRight: '1px solid var(--border)', minHeight: 520, overflowY: 'auto' }}>
          <div style={{ padding: 14, borderBottom: '1px solid var(--border)' }}>
            <div style={{ fontSize: 15, fontWeight: 900, color: 'var(--text0)' }}>Alert Settings</div>
            <div style={{ fontSize: 10.5, color: 'var(--text3)', marginTop: 3 }}>server policy · trailing seven-day volume</div>
          </div>
          {rows.map(r => (
            <button key={r.alert_type} onClick={() => choose(r)} style={{ display: 'block', width: '100%', textAlign: 'left', padding: '9px 12px', border: 'none', borderBottom: '1px solid var(--border)', background: selected?.alert_type === r.alert_type ? `${T.link}18` : 'transparent', color: 'var(--text1)', cursor: 'pointer' }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: selected?.alert_type === r.alert_type ? T.link : 'var(--text0)' }}>{r.alert_type}</div>
              <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>{r.trailing_volume || 0} events · {r.general_telegram}/{r.approval_telegram}</div>
            </button>
          ))}
        </div>
        <div style={{ padding: 16, overflowY: 'auto' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <div style={{ fontSize: 16, fontWeight: 900, color: 'var(--text0)' }}>{draft?.alert_type || 'Select alert type'}</div>
            <span style={{ fontSize: 10, color: 'var(--text3)' }}>row v{draft?.row_version ?? '-'}</span>
            <span style={{ flex: 1 }} />
            <button onClick={onClose} style={{ ...input, cursor: 'pointer' }}>Close</button>
          </div>

          {draft && (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,minmax(160px,1fr))', gap: 10, marginTop: 16 }}>
                <Field label="General Telegram"><select value={draft.general_telegram} onChange={e => patch('general_telegram', e.target.value)} style={input as any}><option>OFF</option><option>IMMEDIATE</option><option>DIGEST</option></select></Field>
                <Field label="Approval Telegram"><select value={draft.approval_telegram} onChange={e => patch('approval_telegram', e.target.value)} style={input as any}><option>OFF</option><option>IMMEDIATE</option></select></Field>
                <Field label="Command Center"><input type="checkbox" checked={draft.command_center} onChange={e => patch('command_center', e.target.checked)} /></Field>
                <Field label="Digest bucket"><select value={draft.digest_bucket} onChange={e => patch('digest_bucket', e.target.value)} style={input as any}><option>RISK</option><option>TRADING</option><option>OPS</option></select></Field>
                <Field label="TTL seconds"><input type="number" value={draft.ttl_seconds} onChange={e => patch('ttl_seconds', Number(e.target.value))} style={input as any} /></Field>
                <Field label="Dedupe seconds"><input type="number" value={draft.dedupe_window_seconds} onChange={e => patch('dedupe_window_seconds', Number(e.target.value))} style={input as any} /></Field>
                <Field label="Escalate seconds"><input type="number" value={draft.escalate_after_seconds || ''} onChange={e => patch('escalate_after_seconds', e.target.value ? Number(e.target.value) : null)} style={input as any} /></Field>
                <Field label="Sound"><input type="checkbox" checked={draft.sound_enabled} onChange={e => patch('sound_enabled', e.target.checked)} /></Field>
                <Field label="Last delivery"><span style={{ color: 'var(--text2)' }}>{draft.last_delivery_at ? new Date(draft.last_delivery_at).toLocaleString() : 'none'}</span></Field>
                <Field label="Suppression"><span style={{ color: 'var(--text2)' }}>{draft.last_suppression_reason || 'none'}</span></Field>
                <Field label="7d volume"><span style={{ color: 'var(--text0)', fontWeight: 800 }}>{draft.trailing_volume || 0}</span></Field>
              </div>

              <div style={{ ...panel, padding: 12, marginTop: 14, fontSize: 11, color: 'var(--text2)' }}>
                Preview: {JSON.stringify(preview?.before || {})} → {JSON.stringify(preview?.after || {})}
              </div>

              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 14 }}>
                <button onClick={testSend} style={{ ...input, color: T.link, cursor: 'pointer' }}>Synthetic Test</button>
                <button onClick={save} style={{ ...input, background: BB.green, color: 'var(--bg0)', fontWeight: 900, cursor: 'pointer' }}>Save</button>
              </div>
              {status && <div style={{ marginTop: 10, fontSize: 11, color: status === 'saved' ? BB.green : BB.orange }}>{status}</div>}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: any }) {
  return <label style={{ display: 'flex', flexDirection: 'column', gap: 5, fontSize: 10, color: 'var(--text3)', fontWeight: 700, textTransform: 'uppercase' }}>{label}<span style={{ fontSize: 11, color: 'var(--text1)', textTransform: 'none' }}>{children}</span></label>
}
