import { useState, useEffect } from 'react'

export type FilterPayload = { account?: string; timeRange?: string; logQuick?: string; logSearch?: string }

export default function SavedFilterBar({
  current, onApply,
}: { current: FilterPayload; onApply: (p: FilterPayload) => void }) {
  const [filters, setFilters] = useState<any[]>([])
  const [name, setName] = useState('')

  const load = () => fetch('/api/v2/journal/saved-filters').then(r => r.json()).then(j => {
    setFilters(j?.filters || j?.data?.filters || [])
  })

  useEffect(() => { load() }, [])

  const save = async () => {
    if (!name.trim()) return
    await fetch('/api/v2/journal/saved-filters', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim(), payload: current }),
    })
    setName('')
    load()
  }

  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
      <span style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 600 }}>SAVED VIEWS:</span>
      {filters.map((f: any) => (
        <button key={f.id} onClick={() => onApply(f.payload || {})}
          style={{ fontSize: 9, padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: '#60a5fa', cursor: 'pointer' }}>
          {f.name}
        </button>
      ))}
      <input value={name} onChange={e => setName(e.target.value)} placeholder="save current…"
        style={{ fontSize: 9, padding: '2px 6px', width: 100, borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
      <button onClick={save} style={{ fontSize: 9, padding: '2px 8px', borderRadius: 4, border: 'none', background: '#60a5fa', color: '#fff', cursor: 'pointer' }}>Save</button>
    </div>
  )
}