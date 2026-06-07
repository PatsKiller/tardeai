import { useState, useEffect } from 'react'
import { useApi } from '../hooks/useApi'

// Shared Hermes IDENTITY editor — profile switcher + editable identity (model/provider via dropdowns,
// label/purpose/description) + SOUL. Each save is backup-first + server-side safety-guarded.
// Used by System → Hermes (HermesPanel) and the /v3/hermes graph. Tools are NOT editable here
// (tradeai/tradeai12b stay tool-less); cloud/unsafe models blocked server-side.

export const PROFILE_LABELS: Record<string, string> = {
  default: 'Global Hermes Identity', tradeai: 'Trade AI Advisory Identity',
  tradeai12b: 'Experimental 12B Trade AI Identity', dev: 'Development / Codex Identity', serverops: 'ServerOps Identity',
}
const inS: React.CSSProperties = { fontSize: 12, padding: '5px 8px', background: 'var(--bg2)', color: 'var(--text1)', border: '1px solid var(--border)', borderRadius: 5, width: '100%' }
const lblS: React.CSSProperties = { fontSize: 10, color: 'var(--text3)' }

export default function HermesSoulEditor({ profile, onClose }: { profile: string; onClose: () => void }) {
  const [sel, setSel] = useState(profile)
  const { data: allData } = useApi<any>('/api/v2/hermes/identity?profile=__all__', 0)
  const { data: soulData, loading } = useApi<any>(`/api/v2/hermes/soul?profile=${sel}`, 0)
  const ids: any[] = allData?.identities || []
  const cur: any = ids.find(i => i.profile === sel) || {}

  // edit buffers (null = use fetched value); reset on profile switch
  const [model, setModel] = useState<string | null>(null)
  const [provider, setProvider] = useState<string | null>(null)
  const [label, setLabel] = useState<string | null>(null)
  const [purpose, setPurpose] = useState<string | null>(null)
  const [desc, setDesc] = useState<string | null>(null)
  const [soul, setSoul] = useState<string | null>(null)
  const [idMsg, setIdMsg] = useState<any>(null)
  const [soulMsg, setSoulMsg] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { setModel(null); setProvider(null); setLabel(null); setPurpose(null); setDesc(null); setSoul(null); setIdMsg(null); setSoulMsg(null) }, [sel])

  const mV = model ?? cur.model ?? ''
  const pV = provider ?? cur.provider ?? ''
  const content = soul ?? soulData?.content ?? ''
  const isTA = sel === 'tradeai' || sel === 'tradeai12b'
  const modelOpts: string[] = Array.from(new Set([...(cur.available_models || []), cur.model].filter(Boolean)))

  async function post(url: string, payload: any, setMsg: (m: any) => void) {
    setBusy(true); setMsg(null)
    try {
      const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      const d = await r.json()
      setMsg(r.ok && d.ok ? { ok: true, text: `Saved. ${d.backup ? 'Backup: ' + d.backup : ''}` } : { ok: false, text: (d.errors ? d.errors.join(' · ') : d.error) || 'save failed' })
    } catch (e: any) { setMsg({ ok: false, text: String(e) }) }
    setBusy(false)
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 18, width: 'min(960px,95vw)', maxHeight: '90vh', overflow: 'auto', display: 'flex', gap: 16 }}>
        {/* Left: identity switcher */}
        <div style={{ width: 180, flexShrink: 0, borderRight: '1px solid var(--border)', paddingRight: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 8 }}>Identities</div>
          {ids.map(i => (
            <button key={i.profile} onClick={() => setSel(i.profile)} style={{
              display: 'block', width: '100%', textAlign: 'left', marginBottom: 4, padding: '6px 8px', borderRadius: 6, cursor: 'pointer',
              border: '1px solid ' + (sel === i.profile ? '#60a5fa' : 'var(--border)'),
              background: sel === i.profile ? 'rgba(96,165,250,.12)' : 'var(--bg2)', color: 'var(--text1)' }}>
              <div style={{ fontWeight: 600, fontSize: 12 }}>{i.profile}</div>
              <div style={{ fontSize: 9, color: 'var(--text3)' }}>{i.model || 'unset'} · {/enabled:/.test(i.tools) ? '⚠ tools' : 'no tools'}</div>
            </button>
          ))}
        </div>

        {/* Right: editor */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <h3 style={{ margin: 0, fontSize: 15 }}>Identity Editor — {PROFILE_LABELS[sel] || sel}</h3>
            <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text3)', fontSize: 20, cursor: 'pointer' }}>×</button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <label style={lblS}>Model
              <select style={inS} value={mV} onChange={e => setModel(e.target.value)}>
                {modelOpts.length === 0 && <option value="">(unset)</option>}
                {cur.model && <option value="">(unset)</option>}
                {modelOpts.map(m => <option key={m} value={m}>{m}</option>)}
              </select></label>
            <label style={lblS}>Provider
              <select style={inS} value={pV} onChange={e => setProvider(e.target.value)}>
                <option value="">(unset)</option>
                {(cur.available_providers || ['custom']).map((p: string) => <option key={p} value={p}>{p}</option>)}
              </select></label>
            <label style={lblS}>Label / Name
              <input style={inS} value={label ?? cur.label ?? ''} onChange={e => setLabel(e.target.value)} /></label>
            <label style={lblS}>Role / Purpose
              <input style={inS} value={purpose ?? cur.purpose ?? ''} onChange={e => setPurpose(e.target.value)} /></label>
          </div>
          <label style={{ ...lblS, display: 'block', marginTop: 8 }}>Description
            <textarea style={{ ...inS, minHeight: 48, fontFamily: 'inherit' }} value={desc ?? cur.description ?? ''} onChange={e => setDesc(e.target.value)} /></label>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 6 }}>
            Tools: <b style={{ color: /enabled:/.test(cur.tools || '') ? '#f59e0b' : '#22c55e' }}>{cur.tools || '…'}</b> (not editable here) · <code>{cur.config_path}</code> · SOUL <code>{cur.soul_hash}</code>
          </div>
          <div style={{ fontSize: 10, color: cur.local_only ? '#f59e0b' : 'var(--text3)', marginTop: 4 }}>⚠ {cur.policy_note}</div>
          {idMsg && <div style={{ marginTop: 6, fontSize: 12, color: idMsg.ok ? '#22c55e' : '#ef4444' }}>{idMsg.text}</div>}
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
            <button disabled={busy} onClick={() => post('/api/v2/hermes/identity', { profile: sel, model: mV, provider: pV, label: label ?? cur.label, purpose: purpose ?? cur.purpose, description: desc ?? cur.description }, setIdMsg)}
              style={{ padding: '6px 14px', border: 'none', borderRadius: 6, background: '#60a5fa', color: '#fff', fontWeight: 600, cursor: 'pointer' }}>{busy ? 'Saving…' : 'Save Identity'}</button>
          </div>

          <div style={{ fontWeight: 700, fontSize: 12, margin: '14px 0 6px' }}>SOUL / persona</div>
          {isTA && <div style={{ fontSize: 10, color: '#f59e0b', marginBottom: 6 }}>Trade AI profile: keep boundary lines (no trades/orders/stops/proposals; no raw secrets). Unsafe enabling language rejected.</div>}
          {loading && soul === null ? <p style={{ color: 'var(--text3)' }}>Loading…</p> : (
            <textarea value={content} onChange={e => setSoul(e.target.value)} spellCheck={false}
              style={{ width: '100%', minHeight: 260, fontFamily: 'monospace', fontSize: 12, padding: 10, background: 'var(--bg2)', color: 'var(--text1)', border: '1px solid var(--border)', borderRadius: 6, resize: 'vertical' }} />
          )}
          {soulMsg && <div style={{ marginTop: 6, fontSize: 12, color: soulMsg.ok ? '#22c55e' : '#ef4444' }}>{soulMsg.text}</div>}
          <div style={{ display: 'flex', gap: 8, marginTop: 10, justifyContent: 'flex-end' }}>
            <button onClick={onClose} style={{ padding: '6px 14px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg2)', color: 'var(--text3)', cursor: 'pointer' }}>Close</button>
            <button disabled={busy} onClick={() => post('/api/v2/hermes/soul', { profile: sel, content }, setSoulMsg)}
              style={{ padding: '6px 14px', border: 'none', borderRadius: 6, background: '#60a5fa', color: '#fff', fontWeight: 600, cursor: 'pointer' }}>{busy ? 'Saving…' : 'Save SOUL'}</button>
          </div>
        </div>
      </div>
    </div>
  )
}
