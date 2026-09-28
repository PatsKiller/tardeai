/** Progressive disclosure (PR2, 2026-09-27): Collapsible, Accordion, ShowMore, Drawer.
 *  `persistKey` remembers the open state per viewer (localStorage) and per operator
 *  (the existing /api/v2/ui/prefs store, key ui.collapsible.<persistKey>). */
import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { RADIUS, SHADOW, TOKENS, TYPE } from '../../lib/designTokens'

function readOpen(persistKey: string | undefined, fallback: boolean): boolean {
  if (!persistKey) return fallback
  try { const v = localStorage.getItem(`cc.collapsible.${persistKey}`); if (v === '1' || v === '0') return v === '1' } catch { /* ignore */ }
  return fallback
}
function writeOpen(persistKey: string | undefined, open: boolean) {
  if (!persistKey) return
  try { localStorage.setItem(`cc.collapsible.${persistKey}`, open ? '1' : '0') } catch { /* ignore */ }
  fetch('/api/v2/ui/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key: `ui.collapsible.${persistKey}`, value: open ? '1' : '0' }) }).catch(() => { /* best effort */ })
}

export function Collapsible({ title, summary, defaultOpen = false, persistKey, count, right, children, style }: {
  title: ReactNode
  /** one-line summary shown while closed (the "insight" of the section) */
  summary?: ReactNode
  defaultOpen?: boolean
  persistKey?: string
  count?: number | string
  right?: ReactNode
  children: ReactNode
  style?: CSSProperties
}) {
  const [open, setOpen] = useState(() => readOpen(persistKey, defaultOpen))
  const toggle = () => setOpen(o => { writeOpen(persistKey, !o); return !o })
  return (
    <section style={{ borderTop: `1px solid ${TOKENS.borderSubtle}`, ...style }}>
      <button
        type="button" aria-expanded={open} onClick={toggle}
        style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0', background: 'transparent',
          border: 'none', color: TOKENS.text[0], cursor: 'pointer', textAlign: 'left', fontFamily: 'inherit' }}
      >
        <span aria-hidden style={{ fontSize: TYPE.xs, color: TOKENS.text[3], width: 10 }}>{open ? '▾' : '▸'}</span>
        <span style={{ fontSize: TYPE.base, fontWeight: 800 }}>{title}</span>
        {count !== undefined && <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>({count})</span>}
        {!open && summary && <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2], flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{summary}</span>}
        {right && <span style={{ marginLeft: 'auto' }} onClick={e => e.stopPropagation()}>{right}</span>}
      </button>
      {open && <div style={{ paddingBottom: 10 }}>{children}</div>}
    </section>
  )
}

export function Accordion({ items, single = false, persistKey }: {
  items: Array<{ key: string; title: ReactNode; summary?: ReactNode; count?: number | string; defaultOpen?: boolean; content: ReactNode }>
  single?: boolean
  persistKey?: string
}) {
  const [openKey, setOpenKey] = useState<string | null>(() => items.find(i => i.defaultOpen)?.key ?? null)
  if (!single) {
    return <div>{items.map(i => <Collapsible key={i.key} title={i.title} summary={i.summary} count={i.count} defaultOpen={i.defaultOpen}
      persistKey={persistKey ? `${persistKey}.${i.key}` : undefined}>{i.content}</Collapsible>)}</div>
  }
  return (
    <div>
      {items.map(i => (
        <section key={i.key} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
          <button type="button" aria-expanded={openKey === i.key} onClick={() => setOpenKey(k => (k === i.key ? null : i.key))}
            style={{ width: '100%', display: 'flex', gap: 8, padding: '8px 0', background: 'transparent', border: 'none', color: TOKENS.text[0], cursor: 'pointer', textAlign: 'left', fontFamily: 'inherit' }}>
            <span aria-hidden style={{ fontSize: TYPE.xs, color: TOKENS.text[3], width: 10 }}>{openKey === i.key ? '▾' : '▸'}</span>
            <span style={{ fontSize: TYPE.base, fontWeight: 800 }}>{i.title}</span>
            {openKey !== i.key && i.summary && <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>{i.summary}</span>}
          </button>
          {openKey === i.key && <div style={{ paddingBottom: 10 }}>{i.content}</div>}
        </section>
      ))}
    </div>
  )
}

/** Clamp long text to N lines with a "Show more / less" control. */
export function ShowMore({ lines = 3, children, style }: { lines?: number; children: ReactNode; style?: CSSProperties }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={style}>
      <div style={open ? undefined : { display: '-webkit-box', WebkitLineClamp: lines, WebkitBoxOrient: 'vertical', overflow: 'hidden' } as CSSProperties}>{children}</div>
      <button type="button" onClick={() => setOpen(o => !o)}
        style={{ background: 'transparent', border: 'none', color: TOKENS.info, cursor: 'pointer', fontSize: TYPE.xs, fontWeight: 700, padding: '2px 0', fontFamily: 'inherit' }}>
        {open ? 'Show less' : 'Show more'}
      </button>
    </div>
  )
}

/** Slide-in detail panel. The caller owns `open`. */
export function Drawer({ open, onClose, title, width = 520, children }: {
  open: boolean
  onClose: () => void
  title: ReactNode
  width?: number
  children: ReactNode
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div role="dialog" aria-modal="true" onClick={onClose}
      style={{ position: 'fixed', inset: 0, zIndex: 80, background: 'rgba(0,0,0,.45)', display: 'flex', justifyContent: 'flex-end' }}>
      <div onClick={e => e.stopPropagation()}
        style={{ width, maxWidth: '100%', height: '100%', overflow: 'auto', background: TOKENS.bg[1], borderLeft: `1px solid ${TOKENS.border}`,
          boxShadow: SHADOW[3], padding: 16, borderRadius: RADIUS.md }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <div style={{ fontSize: TYPE.md, fontWeight: 800, color: TOKENS.text[0] }}>{title}</div>
          <button type="button" onClick={onClose} aria-label="Close"
            style={{ background: 'transparent', border: `1px solid ${TOKENS.border}`, color: TOKENS.text[2], borderRadius: RADIUS.sm, cursor: 'pointer', padding: '2px 8px', fontFamily: 'inherit' }}>✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}
