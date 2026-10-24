import { useEffect, useRef, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { TOKENS, RADIUS } from '../lib/designTokens'

export function useW7Detail() {
  const [params, setParams] = useSearchParams()
  return {
    selected: params.get('detail'),
    open: (key: string) => { const next = new URLSearchParams(params); next.set('detail', key); setParams(next) },
    close: () => { const next = new URLSearchParams(params); next.delete('detail'); setParams(next, { replace: true }) },
  }
}

/** A route-backed sheet: selecting a row always produces a visible result on a phone. */
export default function W7DetailSheet({ title, children, onClose }: { title: string, children: ReactNode, onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    ref.current?.focus()
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = overflow; previous?.focus() }
  }, [])
  return <div role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref} className="w7-detail-sheet" onKeyDown={e => {
    if (e.key === 'Escape') onClose()
    if (e.key === 'Tab') {
      const nodes = ref.current?.querySelectorAll<HTMLElement>('button,a[href],select,[tabindex="0"]')
      if (!nodes?.length) return
      const first = nodes[0], last = nodes[nodes.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
  }}>
    <style>{`.w7-detail-sheet{position:fixed;inset:24px;max-width:760px;margin:auto;z-index:1000;overflow:auto;background:var(--bg-1);border:1px solid var(--border-color);border-radius:var(--radius-lg);padding:20px;color:var(--text-0);box-shadow:0 0 0 100vmax var(--bg-0)}@media(max-width:820px){.w7-detail-sheet{inset:0;border-radius:var(--radius-sm);max-width:none;padding:16px;padding-bottom:max(16px,env(safe-area-inset-bottom))}}`}</style>
    <button onClick={onClose} style={{ minHeight: 44, minWidth: 80, padding: '10px 16px', background: TOKENS.bg[2], color: TOKENS.text[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md }}>← Back</button>
    <h2 style={{ fontSize: 18 }}>{title}</h2>{children}
  </div>
}
