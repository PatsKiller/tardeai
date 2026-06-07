import { useState } from 'react'
import { useApi } from '../hooks/useApi'

// Shared Hermes IDENTITY editor modal — used by System → Hermes (HermesPanel) and the /v3/hermes graph.
// Edits identity (model/provider) AND SOUL, each backup-first + server-side safety-validated.
// Hard guards (server): no gemma3:12b on default/tradeai, no qwen3:14b, Trade AI profiles stay local;
// tools are NOT editable here (tradeai/tradeai12b remain tool-less by design).

export const PROFILE_LABELS: Record<string, string> = {
  default: 'Global Hermes Identity',
  tradeai: 'Trade AI Advisory Identity',
  tradeai12b: 'Experimental 12B Trade AI Identity',
  dev: 'Development / Codex Identity',
  serverops: 'ServerOps Identity',
}

const inputStyle: React.CSSProperties = { fontSize: 12, padding: '5px 8px', background: 'var(--bg2)', color: 'var(--text1)', border: '1px solid var(--border)', borderRadius: 5, width: '100%' }
const btn = (bg: string): React.CSSProperties => ({ padding: '6px 14px', border: 'none', borderRadius: 6, background: bg, color: '#fff', fontWeight: 600, cursor: 'pointer' })

export default function HermesSoulEditor({ profile, onClose }: { profile: string; onClose: () => void }) {
  const { data: idData } = useApi<any>(`/api/v2/hermes/identity?profile=${profile}`, 0)
  const { data: soulData, loading } = useApi<any>(`/api/v2/hermes/soul?profile=${profile}`, 0)
  const [model, setModel] = useState<string | null>(null)
  const [provider, setProvider] = useState<string | null>(null)
  const [text, setText] = useState<string | null>(null)
  const [idMsg, setIdMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [soulMsg, setSoulMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  const modelV = model ?? idData?.model ?? ''
  const providerV = provider ?? idData?.provider ?? ''
  const content = text ?? soulData?.content ?? ''
  const isTradeAI = profile === 'tradeai' || profile === 'tradeai12b'

  async function post(url: string, payload: any, setMsg: (m: any) => void) {
    setBusy(true); setMsg(null)
    try {
      const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      const d = await r.json()
      if (r.ok && d.ok) setMsg({ ok: true, text: `Saved. Backup: ${d.backup || '(new file)'}` })
      else setMsg({ ok: false, text: (d.errors ? d.errors.join(' · ') : d.error) || 'save failed' })
    } catch (e: any) { setMsg({ ok: false, text: String(e) }) }
    setBusy(false)
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 20, width: 'min(860px,94vw)', maxHeight: '90vh', overflow: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>Hermes Identity Editor — {PROFILE_LABELS[profile] || profile}</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text3)', fontSize: 20, cursor: 'pointer' }}>×</button>
        </div>

        {/* Identity section (editable: model + provider) */}
        <div style={{ fontWeight: 700, fontSize: 12, margin: '10px 0 6px' }}>Identity</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <label style={{ fontSize: 10, color: 'var(--text3)' }}>Model
            <input style={inputStyle} value={modelV} onChange={e => setModel(e.target.value)} placeholder="e.g. gemma3:4b" /></label>
          <label style={{ fontSize: 10, color: 'var(--text3)' }}>Provider
            <input style={inputStyle} value={providerV} onChange={e => setProvider(e.target.value)} placeholder="custom" /></label>
        </div>
        <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 6 }}>
          Tools: <b style={{ color: /enabled:/.test(idData?.tools || '') ? '#f59e0b' : '#22c55e' }}>{idData?.tools || '…'}</b> (not editable here) ·
          config: <code>{idData?.config_path}</code> · SOUL <code>{idData?.soul_hash}</code>
        </div>
        <div style={{ fontSize: 10, color: idData?.local_only ? '#f59e0b' : 'var(--text3)', marginTop: 4 }}>⚠ {idData?.policy_note}</div>
        {idMsg && <div style={{ marginTop: 6, fontSize: 12, color: idMsg.ok ? '#22c55e' : '#ef4444' }}>{idMsg.text}</div>}
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
          <button disabled={busy} onClick={() => post('/api/v2/hermes/identity', { profile, model: modelV, provider: providerV }, setIdMsg)} style={btn('#60a5fa')}>{busy ? 'Saving…' : 'Save Identity'}</button>
        </div>

        {/* SOUL section */}
        <div style={{ fontWeight: 700, fontSize: 12, margin: '16px 0 6px' }}>SOUL / persona</div>
        {isTradeAI && <div style={{ fontSize: 10, color: '#f59e0b', marginBottom: 6 }}>Trade AI profile: must keep boundary lines (no trades/orders/stops/proposals; do not read raw secrets). Unsafe enabling language is rejected.</div>}
        {loading && text === null ? <p style={{ color: 'var(--text3)' }}>Loading…</p> : (
          <textarea value={content} onChange={e => setText(e.target.value)} spellCheck={false}
            style={{ width: '100%', minHeight: 300, fontFamily: 'monospace', fontSize: 12, padding: 10, background: 'var(--bg2)', color: 'var(--text1)', border: '1px solid var(--border)', borderRadius: 6, resize: 'vertical' }} />
        )}
        {soulMsg && <div style={{ marginTop: 6, fontSize: 12, color: soulMsg.ok ? '#22c55e' : '#ef4444' }}>{soulMsg.text}</div>}
        <div style={{ display: 'flex', gap: 8, marginTop: 10, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '6px 14px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg2)', color: 'var(--text3)', cursor: 'pointer' }}>Close</button>
          <button disabled={busy} onClick={() => post('/api/v2/hermes/soul', { profile, content }, setSoulMsg)} style={btn('#60a5fa')}>{busy ? 'Saving…' : 'Save SOUL'}</button>
        </div>
      </div>
    </div>
  )
}
