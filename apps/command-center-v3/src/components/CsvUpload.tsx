import { useState } from 'react'

// File-upload tile for remote (Tailscale) operators who can't drop files on the box. Reads the CSV as text
// client-side and POSTs it to /api/v2/upload-csv, which saves it to a whitelisted imports/ dir.
const DESTS = [
  { id: 'schwab_gainloss', label: 'Schwab Gain/Loss or Positions (cost basis)' },
  { id: 'schwab_history', label: 'Schwab transaction history' },
  { id: 'tos_watchlists', label: 'thinkorswim watchlist' },
]

export default function CsvUpload() {
  const [dest, setDest] = useState('schwab_gainloss')
  const [file, setFile] = useState<File | null>(null)
  const [status, setStatus] = useState<string>('')
  const [busy, setBusy] = useState(false)

  const upload = async () => {
    if (!file) { setStatus('pick a file first'); return }
    setBusy(true); setStatus('reading…')
    try {
      const content = await file.text()
      setStatus('uploading…')
      const r = await fetch('/api/v2/upload-csv', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dest, filename: file.name, content }),
      })
      const j = await r.json()
      const d = j?.data ?? j
      setStatus(d?.ok ? `✓ saved ${d.saved} (${d.rows} rows) — ingesting on next cron, or tell AI to ingest now`
        : `✗ ${d?.error || 'upload failed'}`)
    } catch (e: any) {
      setStatus(`✗ ${String(e?.message || e).slice(0, 120)}`)
    }
    setBusy(false)
  }

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 12, maxWidth: 'min(560px, 95vw)' }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Upload CSV (Schwab / ToS exports)</div>
      <div style={{ fontSize: 10, color: 'var(--text3)', margin: '4px 0 12px' }}>For remote sessions — drop an export here instead of onto the server. Saved to a whitelisted import folder; .csv/.txt only.</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <select value={dest} onChange={e => setDest(e.target.value)}
          style={{ fontSize: 11, padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)' }}>
          {DESTS.map(d => <option key={d.id} value={d.id}>{d.label}</option>)}
        </select>
        <input type="file" accept=".csv,.txt" onChange={e => { setFile(e.target.files?.[0] || null); setStatus('') }}
          style={{ fontSize: 11, color: 'var(--text2)' }} />
        <button onClick={upload} disabled={busy || !file}
          style={{ fontSize: 11, fontWeight: 700, padding: '6px 14px', borderRadius: 6, border: '1px solid var(--border)', background: busy || !file ? 'var(--bg2)' : '#1d4ed8', color: busy || !file ? 'var(--text3)' : '#fff', cursor: busy || !file ? 'default' : 'pointer' }}>
          {busy ? '…' : 'Upload'}
        </button>
      </div>
      {status && <div style={{ fontSize: 10, marginTop: 10, color: status.startsWith('✓') ? '#22c55e' : status.startsWith('✗') ? '#ef4444' : 'var(--text3)' }}>{status}</div>}
    </div>
  )
}
