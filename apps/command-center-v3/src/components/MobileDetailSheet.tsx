import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import DetailHeader from './DetailHeader'
import './MobileDetailSheet.css'

/** Page-owned phone detail, with a URL entry so browser Back restores the list. */
export function useMobilePageDetail(queryKey = 'detail') {
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 820px)').matches)
  useEffect(() => {
    const media = window.matchMedia('(max-width: 820px)')
    const update = () => setMobile(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()
  const open = (id: string) => {
    const next = new URLSearchParams(params)
    next.set(queryKey, id)
    setParams(next, {state: {...location.state, w9DetailOpened: true}})
  }
  const close = () => {
    if (location.state?.w9DetailOpened) navigate(-1)
    else {
      const next = new URLSearchParams(params)
      next.delete(queryKey)
      setParams(next, {replace: true})
    }
  }
  return {mobile, id: params.get(queryKey), open, close}
}

/** Full-screen phone detail. The header is the shared DetailHeader: "‹ {list}" · title · ✕ (nav/v001 §5).
 *  `backLabel` names the list it returns to; it defaults to the current menu page. */
export function MobileDetailSheet({title, onBack, backLabel, children}: {title: string; onBack: () => void; backLabel?: string; children: ReactNode}) {
  const sheet = useRef<HTMLElement>(null)
  useEffect(() => {
    const previousFocus = document.activeElement
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const focusTarget = sheet.current?.querySelector<HTMLElement>('[data-detail-focus]')
    if (focusTarget) focusTarget.focus()
    else sheet.current?.focus()
    return () => {
      document.body.style.overflow = overflow
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus()
    }
  }, [])
  return createPortal(<section ref={sheet} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}
    className="mobile-detail-sheet" onKeyDown={event => {
      if (event.key === 'Escape') onBack()
      if (event.key === 'Tab') {
        const focusable = [...(sheet.current?.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea, [tabindex="0"]') || [])]
          .filter(node => !node.hasAttribute('disabled') && node.getClientRects().length)
        const first = focusable[0], last = focusable[focusable.length - 1]
        if (event.shiftKey && (document.activeElement === first || document.activeElement === sheet.current)) {event.preventDefault(); last?.focus()}
        if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus()}
      }
    }}>
    <DetailHeader title={title} titleAs="span" back={backLabel} onClose={onBack} />
    <div className="mobile-detail-body">{children}</div>
  </section>, document.body)
}
