// Right-hand detail drawer, ported from the v02 overlay/drawer: role=dialog, aria-modal, Escape
// closes, Tab is trapped inside, focus returns to the opener, the page behind does not scroll, and a
// click on the dimmed overlay closes it. One drawer at a time, hosted by the shell (DrawerProvider).
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

export interface DrawerContent {
  title: ReactNode
  eyebrow?: ReactNode
  body: ReactNode
  /**
   * The element that opened the drawer, when the opener knows it (a mouse click on a table row leaves
   * `document.activeElement` at BODY, so focus could not return there — verdict 2026-11-15T0342Z B4). The drawer
   * focuses this element on close if it is still connected; otherwise it falls back to whatever was focused at open.
   */
  origin?: Element | null
}
interface DrawerApi { open: (c: DrawerContent) => void; close: () => void; isOpen: boolean }

const Ctx = createContext<DrawerApi | null>(null)

export function useDrawer(): DrawerApi {
  const api = useContext(Ctx)
  if (!api) throw new Error('useDrawer outside DrawerProvider')
  return api
}

const FOCUSABLE = 'button,a,input,textarea,select,summary,[tabindex]'

export function DrawerProvider({ children }: { children: ReactNode }) {
  const [content, setContent] = useState<DrawerContent | null>(null)
  const returnFocus = useRef<Element | null>(null)
  const drawerRef = useRef<HTMLElement | null>(null)

  const open = useCallback((c: DrawerContent) => {
    // The opener's own element wins: a row clicked with a mouse is not `document.activeElement`.
    const origin = c.origin ?? null
    if (!returnFocus.current) returnFocus.current = origin !== null && origin.isConnected ? origin : document.activeElement
    setContent(c)
  }, [])
  const close = useCallback(() => {
    setContent(null)
    const el = returnFocus.current as HTMLElement | null
    returnFocus.current = null
    if (el?.isConnected) el.focus()
  }, [])

  useEffect(() => {
    document.body.classList.toggle('no-scroll', !!content)
    if (!content) return
    drawerRef.current?.querySelector<HTMLElement>('.drawer-top button')?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { close(); return }
      if (e.key !== 'Tab' || !drawerRef.current) return
      const all = [...drawerRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)]
        .filter(x => !(x as HTMLButtonElement).disabled && x.getClientRects().length)
      if (!all.length) return
      const first = all[0], last = all[all.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [content, close])

  return (
    <Ctx.Provider value={{ open, close, isOpen: !!content }}>
      {children}
      <div className={content ? 'overlay open' : 'overlay'} onClick={e => { if (e.target === e.currentTarget) close() }}>
        {content ? (
          <section className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title" ref={drawerRef}>
            <header className="drawer-top">
              <div>{content.eyebrow ? <div className="eyebrow">{content.eyebrow}</div> : null}<h2 id="drawer-title">{content.title}</h2></div>
              <button aria-label="Close detail" onClick={close}>✕</button>
            </header>
            <div className="drawer-body">{content.body}</div>
          </section>
        ) : null}
      </div>
    </Ctx.Provider>
  )
}
