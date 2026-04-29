import { useState, useCallback } from 'react'

interface ImportModalProps { onClose: () => void }

type ImportType = 'schwab_positions' | 'schwab_transactions' | 'fidelity_positions'

const TYPES: { key: ImportType; label: string; desc: string; endpoint: string; accept: string }[] = [
  { key: 'schwab_positions', label: 'Schwab Positions', desc: 'CSV from Schwab positions export', endpoint: '/api/import', accept: '.csv' },
  { key: 'schwab_transactions', label: 'Schwab Transactions', desc: 'CSV from Schwab transaction history', endpoint: '/api/import', accept: '.csv' },
  { key: 'fidelity_positions', label: 'Fidelity Positions', desc: 'CSV from Fidelity positions export', endpoint: '/api/import', accept: '.csv' },
]

export default function ImportModal({ onClose }: ImportModalProps) {
  const [tab, setTab] = useState<ImportType>('schwab_positions')
  const [file, setFile] = useState<File | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)

  const handleUpload = useCallback(async () => {
    if (!file) return
    setUploading(true)
    setStatus('Uploading...')
    try {
      const text = await file.text()
      const typeInfo = TYPES.find(t => t.key === tab)!
      const resp = await fetch(typeInfo.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ csv_text: text, import_type: tab, filename: file.name }),
      })
      const data = await resp.json()
      if (data.ok) {
        setStatus(`Imported successfully. ${data.message || ''}`)
        setTimeout(() => window.location.reload(), 1500)
      } else {
        setStatus(`Error: ${data.error || 'Unknown error'}`)
      }
    } catch (e) {
      setStatus(`Upload failed: ${e}`)
    } finally {
      setUploading(false)
    }
  }, [file, tab])

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: '16px 20px', width: 440, maxHeight: '80vh', overflowY: 'auto' }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <h2 style={{ fontFamily: 'var(--sans)', fontSize: 14, fontWeight: 700, color: 'var(--text0)', margin: 0 }}>Import Account Data</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text3)', cursor: 'pointer', fontSize: 16, fontFamily: 'var(--mono)' }}>x</button>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 3, marginBottom: 12 }}>
          {TYPES.map(t => (
            <button key={t.key} onClick={() => { setTab(t.key); setFile(null); setStatus(null) }} style={{
              padding: '4px 10px', fontSize: 10, border: '1px solid var(--border)', borderRadius: 'var(--radius)',
              background: tab === t.key ? 'var(--accent-dim)' : 'var(--bg3)',
              color: tab === t.key ? 'var(--accent)' : 'var(--text2)',
              cursor: 'pointer', fontFamily: 'var(--mono)',
            }}>
              {t.label}
            </button>
          ))}
        </div>

        <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12 }}>
          {TYPES.find(t => t.key === tab)?.desc}
        </div>

        {/* File input */}
        <div style={{ padding: '16px', border: '1px dashed var(--border)', borderRadius: 'var(--radius-md)', textAlign: 'center', marginBottom: 12 }}>
          <input type="file" accept=".csv" onChange={e => setFile(e.target.files?.[0] || null)} style={{ fontSize: 11, color: 'var(--text1)', fontFamily: 'var(--mono)' }} />
          {file && <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 6 }}>{file.name} ({(file.size / 1024).toFixed(1)} KB)</div>}
        </div>

        {/* Upload button */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button onClick={handleUpload} disabled={!file || uploading} style={{
            padding: '6px 16px', fontSize: 11, fontWeight: 600,
            border: '1px solid var(--accent)', borderRadius: 'var(--radius)',
            background: 'var(--accent-dim)', color: 'var(--accent)',
            cursor: file && !uploading ? 'pointer' : 'not-allowed',
            fontFamily: 'var(--mono)', opacity: file && !uploading ? 1 : 0.5,
          }}>
            {uploading ? 'Uploading...' : 'Import'}
          </button>
          {status && (
            <span style={{ fontSize: 10, color: status.includes('Error') || status.includes('failed') ? 'var(--red)' : 'var(--green)' }}>{status}</span>
          )}
        </div>
      </div>
    </div>
  )
}
