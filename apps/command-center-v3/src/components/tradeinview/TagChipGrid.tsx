import { useMemo, useState, type CSSProperties } from 'react'
import { addVocabItem, mergeVocab, type VocabConfig } from '../../lib/journalVocab'

const CHIP = (on: boolean, color: string): CSSProperties => ({
  fontSize: 13,
  fontWeight: on ? 700 : 500,
  padding: '6px 12px',
  borderRadius: 8,
  border: `1px solid ${on ? color : 'var(--border)'}`,
  background: on ? color + '33' : 'var(--bg1)',
  color: on ? color : 'var(--text1)',
  cursor: 'pointer',
  lineHeight: 1.2,
})

export default function TagChipGrid({
  label,
  groups,
  flat,
  config,
  selected,
  onChange,
  color,
}: {
  label?: string
  groups?: { label: string; items: string[] }[]
  flat?: string[]
  config?: VocabConfig
  selected: string[]
  onChange: (tags: string[]) => void
  color: string
}) {
  const [addOpen, setAddOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [addErr, setAddErr] = useState('')
  const [refresh, setRefresh] = useState(0)

  const allItems = useMemo(() => {
    const base = groups ? groups.flatMap(g => g.items) : (flat || [])
    const merged = config ? mergeVocab(config, [...base, ...selected]) : [...new Set([...base, ...selected])]
    return merged
  }, [groups, flat, config, selected, refresh])

  const tog = (v: string) => {
    onChange(selected.includes(v) ? selected.filter(x => x !== v) : [...selected, v])
  }

  const confirmAdd = () => {
    if (!config) return
    const added = addVocabItem(config, newName)
    if (!added) {
      setAddErr(config.emptyError)
      return
    }
    setRefresh(n => n + 1)
    onChange([...selected, added])
    setAddOpen(false)
    setNewName('')
  }

  const renderChip = (item: string) => (
    <button key={item} type="button" onClick={() => tog(item)} style={CHIP(selected.includes(item), color)}>
      {item}
    </button>
  )

  return (
    <div style={{ marginBottom: 14 }}>
      {label && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text1)' }}>{label}</span>
          {config && (
            <button
              type="button"
              onClick={() => { setAddOpen(true); setAddErr(''); setNewName('') }}
              style={{ fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 6, border: '1px solid rgba(96,165,250,.4)', background: 'rgba(96,165,250,.1)', color: '#93c5fd', cursor: 'pointer' }}
            >
              + Add custom
            </button>
          )}
        </div>
      )}
      {groups ? groups.map(g => (
        <div key={g.label} style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text2)', marginBottom: 6 }}>{g.label}</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>{g.items.map(renderChip)}</div>
        </div>
      )) : (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>{allItems.map(renderChip)}</div>
      )}
      {/* Custom tags not in any group */}
      {groups && config && selected.filter(s => !groups.some(g => g.items.includes(s))).length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text2)', marginBottom: 6 }}>Custom</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {selected.filter(s => !groups.some(g => g.items.includes(s))).map(renderChip)}
          </div>
        </div>
      )}
      {addOpen && config && (
        <>
          <div onClick={() => setAddOpen(false)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.65)', zIndex: 1200 }} />
          <div style={{ position: 'fixed', top: '30%', left: '50%', transform: 'translateX(-50%)', width: 400, maxWidth: '92vw', background: 'var(--bg0)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, zIndex: 1201 }}>
            <div style={{ fontSize: 15, fontWeight: 800, marginBottom: 8 }}>{config.addTitle}</div>
            <input
              autoFocus
              value={newName}
              onChange={e => { setNewName(e.target.value); setAddErr('') }}
              onKeyDown={e => { if (e.key === 'Enter') confirmAdd(); if (e.key === 'Escape') setAddOpen(false) }}
              placeholder={config.addPlaceholder}
              style={{ width: '100%', fontSize: 14, padding: '10px 12px', borderRadius: 6, border: `1px solid ${addErr ? '#ef4444' : 'var(--border)'}`, background: 'var(--bg2)', color: 'var(--text0)', marginBottom: 10 }}
            />
            {addErr && <div style={{ fontSize: 12, color: '#ef4444', marginBottom: 8 }}>{addErr}</div>}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" onClick={() => setAddOpen(false)} style={{ fontSize: 13, padding: '8px 14px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', cursor: 'pointer' }}>Cancel</button>
              <button type="button" onClick={confirmAdd} style={{ fontSize: 13, fontWeight: 700, padding: '8px 16px', borderRadius: 6, border: 'none', background: '#60a5fa', color: '#fff', cursor: 'pointer' }}>{config.addConfirmLabel}</button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}