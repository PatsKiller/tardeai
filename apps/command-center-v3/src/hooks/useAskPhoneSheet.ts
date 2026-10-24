import { useEffect, useRef, useState, type RefObject } from 'react'

let locks = 0
let previousOverflow = ''
const focusable = 'button:not(:disabled),a[href],input:not(:disabled),textarea:not(:disabled),select:not(:disabled),summary,[tabindex="0"]'

/** Phone presentation only: the existing route/request remains the source of thread identity. */
export function useAskPhoneSheet(active: boolean, element: RefObject<HTMLDivElement | null>, onBack: () => void) {
  const [phone, setPhone] = useState(() => window.matchMedia('(max-width: 820px)').matches)
  const back = useRef(onBack)
  back.current = onBack
  useEffect(() => {
    const media = window.matchMedia('(max-width: 820px)')
    const update = () => setPhone(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  useEffect(() => {
    if (!active || !phone || !element.current) return
    const sheet = element.current, before = document.activeElement as HTMLElement | null
    if (locks++ === 0) { previousOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden' }
    sheet.focus()
    const keydown = (event: KeyboardEvent) => {
      const top = [...document.querySelectorAll<HTMLElement>('[data-phone-sheet="true"]')].sort((a, b) => Number(getComputedStyle(b).zIndex) - Number(getComputedStyle(a).zIndex))[0]
      if (top !== sheet) return
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); back.current(); return }
      if (event.key !== 'Tab') return
      const items = [...sheet.querySelectorAll<HTMLElement>(focusable)].filter(node => node.getClientRects().length > 0)
      const first = items[0], last = items[items.length - 1]
      if (!first) { event.preventDefault(); sheet.focus() }
      else if (event.shiftKey && (document.activeElement === first || document.activeElement === sheet)) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && (document.activeElement === last || document.activeElement === sheet)) { event.preventDefault(); first.focus() }
    }
    window.addEventListener('keydown', keydown, true)
    return () => {
      window.removeEventListener('keydown', keydown, true)
      if (--locks === 0) document.body.style.overflow = previousOverflow
      if (before?.isConnected && (sheet.contains(document.activeElement) || document.activeElement === document.body)) before.focus()
    }
  }, [active, phone, element])
  return phone
}
