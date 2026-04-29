import { useState, useCallback } from 'react'

interface ImportModalProps { onClose: () => void }

type ImportType = 'schwab_positions' | 'schwab_transactions' | 'fidelity_positions'

interface ImportResult {
  ok: boolean; message?: string; error?: string
  positions_written?: number; count?: number
}

const TYPES: { key: ImportType; label: string; desc: string; endpoint: string; accept: string }[] = [
  { key: 'schwab_positions', label: 'Schwab Positions', desc: 'CSV from Schwab positions export — replaces current account holdings', endpoint: '/api/import', accept: '.csv' },
  { key: 'schwab_transactions', label: 'Schwab Transactions', desc: 'CSV from Schwab transaction history — appends new trades to journal', endpoint: '/api/import', accept: '.csv' },
  { key: 'fidelity_positions', label: 'Fidelity Positions', desc: 'CSV from Fidelity positions export — replaces 401k holdings', endpoint: '/api/import', accept: '.csv' },
]

export default function ImportModal({ onClose }: ImportModalProps) {
  const [tab, setTab] = useState<ImportType>('schwab_positions')
  const [file, setFile] = useState<File | null>(null)
  const [status, setStatus] = useState<'idle' | 'uploading' | 'success' | 'error'>('idle')
  const [resultData, setResultData] = useState<ImportResult | null>(null)
  const [errorMsg, setErrorMsg] = useState('')
  const [reconciliation, setReconciliation] = useState<{ before?: { positions: number; total_value: number }; after?: { positions: number; total_value: number }; delta_value?: number } | null>(null)

  const handleUpload = useCallback(async () => {
    if (!file) return
    setStatus('uploading')
    setResultData(null)
    setErrorMsg('')
    try {
      const text = await file.text()
      const typeInfo = TYPES.find(t => t.key === tab)!
      const resp = await fetch(typeInfo.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ csv_text: text, import_type: tab, filename: file.name }),
      })
      const data: ImportResult = await resp.json()
      setResultData(data)
      if (data.ok) {
        setStatus('success')
        // Fetch reconciliation data
        try {
          const recResp = await fetch('/api/v2/ops/last-import')
          const recData = await recResp.json()
          if (recData?.data?.has_result && recData.data.result) {
            setReconciliation(recData.data.result)
          }
        } catch {}
        setTimeout(() => window.location.reload(), 4000)
      } else {
        setStatus('error')
        setErrorMsg(data.error || 'Unknown error')
      }
    } catch (e) {
      setStatus('error')
      setErrorMsg(`Upload failed: ${e}`)
    }
  }, [file, tab])

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: '16px 20px', width: 460, maxHeight: '80vh', overflowY: 'auto' }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <h2 style={{ fontFamily: 'var(--sans)', fontSize: 14, fontWeight: 700, color: 'var(--text0)', margin: 0 }}>Import Account Data</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text3)', cursor: 'pointer', fontSize: 16, fontFamily: 'var(--mono)' }}>x</button>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 3, marginBottom: 12 }}>
          {TYPES.map(t => (
            <button key={t.key} onClick={() => { setTab(t.key); setFile(null); setStatus('idle'); setResultData(null) }} style={{
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
          <input type="file" accept=".csv" onChange={e => { setFile(e.target.files?.[0] || null); setStatus('idle'); setResultData(null) }} style={{ fontSize: 11, color: 'var(--text1)', fontFamily: 'var(--mono)' }} />
          {file && <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 6 }}>{file.name} ({(file.size / 1024).toFixed(1)} KB)</div>}
        </div>

        {/* Upload button */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
          <button onClick={handleUpload} disabled={!file || status === 'uploading'} style={{
            padding: '6px 16px', fontSize: 11, fontWeight: 600,
            border: '1px solid var(--accent)', borderRadius: 'var(--radius)',
            background: 'var(--accent-dim)', color: 'var(--accent)',
            cursor: file && status !== 'uploading' ? 'pointer' : 'not-allowed',
            fontFamily: 'var(--mono)', opacity: file && status !== 'uploading' ? 1 : 0.5,
          }}>
            {status === 'uploading' ? 'Uploading...' : 'Import'}
          </button>
        </div>

        {/* Result feedback */}
        {status === 'success' && resultData && (
          <div style={{ padding: '10px 12px', background: 'var(--green-dim)', border: '1px solid var(--green)', borderRadius: 'var(--radius)', marginBottom: 8 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--green)', marginBottom: 4 }}>Import successful</div>
            <div style={{ fontSize: 10, color: 'var(--text1)' }}>
              {resultData.message || 'Data written to portfolio.'}
              {resultData.positions_written != null && <span> · {resultData.positions_written} positions written</span>}
              {resultData.count != null && <span> · {resultData.count} rows processed</span>}
            </div>
            {reconciliation && reconciliation.before && reconciliation.after && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginTop: 8, fontSize: 10 }}>
                <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Before</div><div style={{ color: 'var(--text1)' }}>{reconciliation.before.positions} pos · ${reconciliation.before.total_value.toLocaleString()}</div></div>
                <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>After</div><div style={{ color: 'var(--text0)', fontWeight: 600 }}>{reconciliation.after.positions} pos · ${reconciliation.after.total_value.toLocaleString()}</div></div>
                <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Delta</div><div style={{ color: (reconciliation.delta_value ?? 0) >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>{(reconciliation.delta_value ?? 0) >= 0 ? '+' : ''}${(reconciliation.delta_value ?? 0).toLocaleString()}</div></div>
              </div>
            )}
            <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>Page will refresh in 4 seconds to show updated data.</div>
          </div>
        )}

        {status === 'error' && (
          <div style={{ padding: '10px 12px', background: 'var(--red-dim)', border: '1px solid var(--red)', borderRadius: 'var(--radius)', marginBottom: 8 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--red)', marginBottom: 4 }}>Import failed</div>
            <div style={{ fontSize: 10, color: 'var(--text1)' }}>{errorMsg}</div>
          </div>
        )}

        {/* What happens on import */}
        <div style={{ fontSize: 9, color: 'var(--text3)', padding: '6px 0', borderTop: '1px solid var(--border-subtle)' }}>
          {tab.includes('positions') ? 'Positions import replaces all holdings for the target account. A backup is created before replacement.' : 'Transaction import appends new trades to the journal. Existing trades are not affected.'}
        </div>
      </div>
    </div>
  )
}
