import { useState } from 'react'

export default function CsvImportPanel() {
  const [text, setText] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    const r = new FileReader()
    r.onload = () => setText(String(r.result || ''))
    r.readAsText(f)
  }

  const importCsv = async () => {
    setBusy(true); setMsg('')
    try {
      const r = await fetch('/api/v2/journal/import-csv', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ csv_text: text, filename: 'schwab_taxable_history.csv' }),
      }).then(x => x.json())
      setMsg(r.ok ? `✓ imported · ${JSON.stringify(r).slice(0, 120)}` : `⛔ ${r.error}`)
    } catch (e: any) { setMsg('⛔ ' + e.message) }
    finally { setBusy(false) }
  }

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>Import Schwab / ToS history CSV</div>
      <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8 }}>Schwab → Accounts → History → Export CSV. Filename should include taxable/roth/rollover for account detection.</div>
      <input type="file" accept=".csv,.txt" onChange={onFile} style={{ fontSize: 10, marginBottom: 8 }} />
      <textarea value={text} onChange={e => setText(e.target.value)} placeholder="Or paste CSV here…"
        style={{ width: '100%', minHeight: 80, fontSize: 9, fontFamily: 'monospace', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text1)', padding: 8 }} />
      <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center' }}>
        <button disabled={busy || !text.trim()} onClick={importCsv}
          style={{ fontSize: 10, padding: '6px 14px', borderRadius: 5, border: 'none', background: '#22c55e', color: '#fff', fontWeight: 700, cursor: 'pointer' }}>
          {busy ? 'Importing…' : 'Import & rebuild journal'}
        </button>
        {msg && <span style={{ fontSize: 9, color: msg.startsWith('✓') ? '#22c55e' : '#ef4444' }}>{msg}</span>}
      </div>
    </div>
  )
}