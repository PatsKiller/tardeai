import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { addVocabItem, mergeVocab, type VocabConfig } from '../../lib/journalVocab'

const SELECT: CSSProperties = {
  flex: 1,
  fontSize: 14,
  padding: '10px 12px',
  borderRadius: 6,
  border: '1px solid var(--border)',
  background: 'var(--bg2)',
  color: 'var(--text0)',
}

const ADD_BTN: CSSProperties = {
  fontSize: 13,
  fontWeight: 700,
  padding: '10px 14px',
  borderRadius: 6,
  border: '1px solid rgba(96,165,250,.45)',
  background: 'rgba(96,165,250,.12)',
  color: '#93c5fd',
  cursor: 'pointer',
  whiteSpace: 'nowrap',
}

export default function JournalVocabPicker({
  config,
  value,
  onChange,
  compact,
}: {
  config: VocabConfig
  value: string
  onChange: (v: string) => void
  compact?: boolean
}) {
  const [addOpen, setAddOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [addErr, setAddErr] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [dbOptions, setDbOptions] = useState<string[]>([])

  useEffect(() => {
    if (!config.loadDbOptions) return
    config.loadDbOptions().then(setDbOptions).catch(() => {})
  }, [config])

  const options = useMemo(
    () => mergeVocab(config, [...dbOptions, ...(value ? [value] : [])]),
    [config, dbOptions, value, refresh],
  )

  const canonicalValue = useMemo(() => {
    if (!value) return ''
    return options.find(o => o.toLowerCase() === value.toLowerCase()) || value
  }, [value, options])

  const openAdd = () => {
    setNewName('')
    setAddErr('')
    setAddOpen(true)
  }

  const confirmAdd = () => {
    const added = addVocabItem(config, newName)
    if (!added) {
      setAddErr(config.emptyError)
      return
    }
    setRefresh(n => n + 1)
    onChange(added)
    setAddOpen(false)
  }

  const fs = compact ? 12 : 14
  const selectStyle: CSSProperties = compact
    ? { ...SELECT, fontSize: fs, padding: '6px 10px' }
    : SELECT
  const btnStyle: CSSProperties = compact
    ? { ...ADD_BTN, fontSize: 11, padding: '6px 10px' }
    : ADD_BTN

  return (
    <>
      <div style={{ display: 'flex', gap: 8, marginBottom: compact ? 8 : 12 }}>
        <select
          value={canonicalValue || ''}
          onChange={e => onChange(e.target.value)}
          style={selectStyle}
        >
          <option value="">{config.selectPlaceholder}</option>
          {options.map(f => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>
        <button type="button" onClick={openAdd} style={btnStyle}>+ Add new</button>
      </div>

      {addOpen && (
        <>
          <div
            onClick={() => setAddOpen(false)}
            style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.65)', zIndex: 1200 }}
          />
          <div style={{
            position: 'fixed', top: '28%', left: '50%', transform: 'translateX(-50%)',
            width: 420, maxWidth: '92vw', background: 'var(--bg0)', border: '1px solid var(--border)',
            borderRadius: 10, padding: 18, zIndex: 1201, boxShadow: '0 16px 48px rgba(0,0,0,.55)',
          }}>
            <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--text0)', marginBottom: 6 }}>
              {config.addTitle}
            </div>
            <div style={{ fontSize: 13, color: 'var(--text2)', marginBottom: 12, lineHeight: 1.4 }}>
              {config.addHint}
            </div>
            <input
              autoFocus
              value={newName}
              onChange={e => { setNewName(e.target.value); setAddErr('') }}
              onKeyDown={e => { if (e.key === 'Enter') confirmAdd(); if (e.key === 'Escape') setAddOpen(false) }}
              placeholder={config.addPlaceholder}
              style={{
                width: '100%', fontSize: 14, padding: '10px 12px', borderRadius: 6,
                border: `1px solid ${addErr ? '#ef4444' : 'var(--border)'}`,
                background: 'var(--bg2)', color: 'var(--text0)', marginBottom: addErr ? 6 : 14,
              }}
            />
            {addErr && <div style={{ fontSize: 12, color: '#ef4444', marginBottom: 10 }}>{addErr}</div>}
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button
                type="button"
                onClick={() => setAddOpen(false)}
                style={{ fontSize: 13, padding: '8px 14px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)', cursor: 'pointer' }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmAdd}
                style={{ fontSize: 13, fontWeight: 700, padding: '8px 16px', borderRadius: 6, border: 'none', background: '#60a5fa', color: '#fff', cursor: 'pointer' }}
              >
                {config.addConfirmLabel}
              </button>
            </div>
          </div>
        </>
      )}
    </>
  )
}