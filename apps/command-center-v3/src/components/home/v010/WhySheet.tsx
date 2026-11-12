import { useEffect, useRef, type RefObject } from 'react'
import './WhySheet.css'

const SHEET_FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Shared behaviour for the v010 full-screen sheets while `open`:
 *  - Escape closes; Tab / Shift+Tab stay inside the dialog (focus trap);
 *  - focus moves to `initial` on open and back to the opener on close;
 *  - the page behind is scroll-locked: <html> overflow hidden, <body> overflow clip, so nothing
 *    in the app shell under the scrim (e.g. a wide header banner) can widen or scroll the page.
 *    The previous inline values are restored on close.
 */
export function useSheetA11y(open: boolean, onClose: () => void, dialog: RefObject<HTMLElement>, initial: RefObject<HTMLElement>) {
  // Callers pass an inline onClose; keep it in a ref so a parent re-render (data refresh) does not
  // re-run the effect and pull focus back to the close button.
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    if (!open) return
    const html = document.documentElement
    const body = document.body
    const prev = { html: html.style.overflow, body: body.style.overflow }
    html.style.overflow = 'hidden'
    body.style.overflow = 'clip'
    const opener = document.activeElement as HTMLElement | null
    initial.current?.focus()

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); closeRef.current(); return }
      if (e.key !== 'Tab' || !dialog.current) return
      const items = [...dialog.current.querySelectorAll<HTMLElement>(SHEET_FOCUSABLE)].filter(el => el.getClientRects().length > 0)
      if (items.length === 0) { e.preventDefault(); return }
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (!dialog.current.contains(active)) { e.preventDefault(); first.focus() }
      else if (e.shiftKey && active === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      html.style.overflow = prev.html
      body.style.overflow = prev.body
      if (opener && opener.isConnected) opener.focus()
    }
  }, [open, dialog, initial])
}

export type TradeReadyState = 'YES' | 'NO' | 'UNKNOWN'
export interface WhyBlocker { category: string; detail: string; targetId?: string; needsBackend?: boolean }
export interface WhyInput { name: string; state: 'OK'|'STALE'|'UNKNOWN'|'TIMED OUT'|'WARN'|'GAP'|'NOT AVAILABLE'; ageText?: string; needsBackend?: boolean }

interface Props { open: boolean; onClose: () => void; verdict: TradeReadyState; blockers: WhyBlocker[]; inputs: WhyInput[]; onGoTo?: (targetId: string) => void }

const NB = <span className="v010-why-tag" title="Backend support not yet available">NEEDS BACKEND</span>

function chipClass(s: WhyInput['state']): string {
  if (s === 'OK') return 'ok'
  if (s === 'WARN' || s === 'STALE') return 'warn'
  if (s === 'UNKNOWN' || s === 'TIMED OUT' || s === 'GAP') return 'bad'
  return ''
}

export default function WhySheet({ open, onClose, verdict, blockers, inputs, onGoTo }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  useSheetA11y(open, onClose, dialogRef, closeRef)
  if (!open) return null

  const title = verdict === 'NO' ? 'Trade-ready: NO · Blocked by:'
    : verdict === 'UNKNOWN' ? 'Trade-ready: UNKNOWN · Could not read:' : 'Trade-ready: YES'
  const unread = inputs.filter(i => i.state !== 'OK')

  return (
    <div className="v010-why-scrim" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="v010-why" ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="v010-why-title" id="sheet-why">
        <div className="v010-why-head">
          <h2 className="v010-why-title" id="v010-why-title">{title}</h2>
          <button type="button" ref={closeRef} className="v010-why-close" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        {verdict === 'NO' && (
          blockers.length === 0
            ? <p className="v010-why-note">No blocker detail available. {NB}</p>
            : <ol className="v010-why-list">
                {blockers.map((b, i) => (
                  <li className="v010-why-item" key={`${b.category}-${i}`}>
                    <div className="v010-why-txt">
                      <span className="v010-why-cat">{i + 1}. {b.category}</span>
                      <span className="v010-why-detail">{b.detail}</span>
                      {b.needsBackend && NB}
                    </div>
                    {b.targetId && onGoTo && (
                      <button type="button" className="v010-why-go" onClick={() => onGoTo(b.targetId as string)}>Go to</button>
                    )}
                  </li>
                ))}
              </ol>
        )}
        {verdict === 'UNKNOWN' && (
          <>
            <p className="v010-why-note">UNKNOWN always overrides YES: if any input cannot be read, we do not call it ready.</p>
            {unread.length === 0
              ? <p className="v010-why-note">No unreadable input reported. {NB}</p>
              : <ul className="v010-why-list">{unread.map(inputRow)}</ul>}
          </>
        )}
        {verdict === 'YES' && (
          <ul className="v010-why-list">{inputs.map(inputRow)}</ul>
        )}
      </div>
    </div>
  )
}

function inputRow(i: WhyInput, idx: number) {
  return (
    <li className="v010-why-item" key={`${i.name}-${idx}`}>
      <div className="v010-why-txt">
        <span className="v010-why-cat">{i.name}</span>
        {i.ageText && <span className="v010-why-age">{i.ageText}</span>}
        {i.needsBackend && NB}
      </div>
      <span className={`v010-why-chip ${chipClass(i.state)}`}>{i.state}</span>
    </li>
  )
}
