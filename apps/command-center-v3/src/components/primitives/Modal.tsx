/** Shared modal primitive (Investment Command Center, 2026-10-08) — overlay, Escape to close, focus trap-lite,
 *  body scroll lock, design tokens only. ~58 surfaces hand-roll a `position: fixed` overlay; new modals use this. */
import { useEffect, useRef, type ReactNode } from 'react'
import { RADIUS, SHADOW } from '../../lib/designTokens'

export default function Modal({ open, onClose, title, width = 1040, children, footer, testId }: {
  open: boolean
  onClose: () => void
  title?: ReactNode
  width?: number
  children: ReactNode
  footer?: ReactNode
  testId?: string
}) {
  const panel = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    panel.current?.focus()
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = prev }
  }, [open, onClose])
  if (!open) return null
  return (
    <div onClick={onClose} role="presentation"
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.62)', zIndex: 1200, display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: '4vh 12px', overflowY: 'auto' }}>
      <div ref={panel} tabIndex={-1} role="dialog" aria-modal="true" data-testid={testId} onClick={(e) => e.stopPropagation()}
        style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: RADIUS.lg, boxShadow: SHADOW[3], width, maxWidth: '96vw', outline: 'none' }}>
        {title != null && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, padding: '14px 18px', borderBottom: '1px solid var(--border)' }}>
            <div style={{ minWidth: 0, flex: 1 }}>{title}</div>
            <button type="button" onClick={onClose} aria-label="Close"
              style={{ border: '1px solid var(--border)', background: 'transparent', color: 'var(--text2)', cursor: 'pointer', borderRadius: RADIUS.sm, padding: '2px 10px', fontSize: 14 }}>×</button>
          </div>
        )}
        <div style={{ padding: 18 }}>{children}</div>
        {footer && <div style={{ padding: '10px 18px', borderTop: '1px solid var(--border)' }}>{footer}</div>}
      </div>
    </div>
  )
}
