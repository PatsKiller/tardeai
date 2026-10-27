/** Prospectus citations as compact footnotes (design prospectus/v001.1, operator 2026-10-26: "what are these F with the
 *  numbers all over the pages? … internal pointers. Do those really need to be shown?").
 *  Internal fact ids (F7) never show: prose renders small superscript numbers 1..n (order of first use, per report);
 *  a tap or hover opens a popover with the source label and as-of date; each section has a collapsed "Sources (n)";
 *  one numbered "Sources" appendix ends the report (collapsed on phone). The fact id stays in data-fact-id. */
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { inlineMarkdown } from '../PolicyRuleParts'
import { cleanProse, footnoteLabel, splitFootnotes, whenEt, type Footnote, type ProspectusSection, sectionFootnotes } from '../../lib/prospectusModel'

type Open = { notes: Footnote[]; rect: DOMRect; key: string } | null
type Ctx = { byId: Map<string, Footnote>; open: Open; show: (o: Open) => void }
const FootnoteCtx = createContext<Ctx>({ byId: new Map(), open: null, show: () => {} })

export function FootnoteProvider({ notes, children }: { notes: Footnote[]; children: ReactNode }) {
  const byId = useMemo(() => new Map(notes.map(n => [n.id, n])), [notes])
  const [open, setOpen] = useState<Open>(null)
  const show = useCallback((o: Open) => setOpen(o), [])
  return (
    <FootnoteCtx.Provider value={{ byId, open, show }}>
      {children}
      {open && <FootnotePopover open={open} onClose={() => setOpen(null)} />}
    </FootnoteCtx.Provider>
  )
}

export function useFootnotes(): Map<string, Footnote> { return useContext(FootnoteCtx).byId }

function noteLine(n: Footnote): ReactNode {
  return (
    <>
      <span className="psp-fn-label">{n.label}{n.value ? <span className="psp-fn-value">: {n.value}</span> : null}</span>
      <span className="psp-muted">{n.source ? ` — ${n.source}` : ''}{n.as_of ? ` · ${whenEt(n.as_of)}` : ''}</span>
      {n.url ? <> <a className="psp-link" href={n.url} target="_blank" rel="noopener noreferrer">open</a></> : null}
    </>
  )
}

function FootnotePopover({ open, onClose }: { open: NonNullable<Open>; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const vw = window.innerWidth, vh = window.innerHeight, g = 16
    const w = Math.min(360, vw - 2 * g)
    const h = el.offsetHeight
    let left = open.rect.left + open.rect.width / 2 - w / 2
    left = Math.max(g, Math.min(left, vw - g - w))
    let top = open.rect.bottom + 8
    if (top + h > vh - g) top = Math.max(g, open.rect.top - h - 8)
    setPos({ left, top })
  }, [open])
  useEffect(() => {
    // Capture phase + stop: Escape closes the popover only, never the phone sheet underneath.
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    const onDown = (e: Event) => {
      const t = e.target as HTMLElement | null
      if (ref.current?.contains(t as Node) || t?.closest?.('.psp-fn')) return
      onClose()
    }
    const onScroll = () => onClose()
    window.addEventListener('keydown', onKey, true)
    document.addEventListener('pointerdown', onDown, true)
    window.addEventListener('scroll', onScroll, true)
    return () => { window.removeEventListener('keydown', onKey, true); document.removeEventListener('pointerdown', onDown, true); window.removeEventListener('scroll', onScroll, true) }
  }, [onClose])
  return createPortal(
    <div ref={ref} role="dialog" aria-label="Source" className="psp-fn-pop" data-testid="prospectus-fn-popover"
      style={{ left: pos?.left ?? -9999, top: pos?.top ?? -9999, width: `min(360px, calc(100vw - 32px))` }}>
      <ol className="psp-fn-pop-list">
        {open.notes.map(n => <li key={n.n} value={n.n} data-fact-id={n.id}>{noteLine(n)}</li>)}
      </ol>
    </div>, document.body)
}

/** One superscript footnote group ("3" or "3,4"): a button with a 44px hit area that opens the popover. */
export function FootnoteRef({ notes, ids }: { notes: Footnote[]; ids: string[] }) {
  const { open, show } = useContext(FootnoteCtx)
  const key = ids.join(',')
  const isOpen = open?.key === key
  const label = footnoteLabel(notes.map(n => n.n))
  const hoverable = typeof window !== 'undefined' && window.matchMedia?.('(hover: hover)').matches
  return (
    <sup className="psp-fn-sup">
      <button type="button" className="psp-fn" data-testid="prospectus-fn" data-fact-id={ids.join(' ')} aria-expanded={isOpen}
        aria-label={`Source${notes.length > 1 ? 's' : ''} ${notes.map(n => n.n).join(', ')}`}
        onClick={e => show(isOpen && !hoverable ? null : { notes, rect: e.currentTarget.getBoundingClientRect(), key })}
        onMouseEnter={hoverable ? e => show({ notes, rect: e.currentTarget.getBoundingClientRect(), key }) : undefined}>
        {label}
      </button>
    </sup>
  )
}

/** Prose with markdown emphasis, footnote numbers and muted "not reliable (…)" notes. */
export function CiteText({ text, md = true }: { text: string | null | undefined; md?: boolean }) {
  const byId = useFootnotes()
  const parts = splitFootnotes(cleanProse(text), byId)
  return <>{parts.map((p, i) => 'notes' in p
    ? <FootnoteRef key={i} notes={p.notes} ids={p.ids} />
    : p.muted ? <span key={i} className="psp-unreliable" data-testid="prospectus-unreliable">{p.text}</span>
      : <span key={i}>{md ? inlineMarkdown(p.text, `c${i}`) : p.text}</span>)}</>
}

function SourceList({ notes, testId }: { notes: Footnote[]; testId?: string }) {
  return (
    <ol className="psp-fn-list" data-testid={testId}>
      {notes.map(n => <li key={n.n} value={n.n} id={testId === 'prospectus-sources-list' ? `fn-${n.n}` : undefined} data-fact-id={n.id}>{noteLine(n)}</li>)}
    </ol>
  )
}

/** Collapsed per-section "Sources (n)". */
export function SectionSources({ s }: { s: ProspectusSection }) {
  const byId = useFootnotes()
  const used = sectionFootnotes(s, byId)
  if (!used.length) return null
  return (
    <details className="psp-srcs" data-testid="prospectus-section-sources">
      <summary className="psp-srcs-sum">Sources ({used.length})</summary>
      <SourceList notes={used} />
    </details>
  )
}

/** The report's one numbered Sources appendix (collapsed on phone, open on desktop). */
export function SourcesAppendix({ notes, phone }: { notes: Footnote[]; phone: boolean }) {
  if (!notes.length) return null
  return (
    <section className="psp-card psp-appendix" aria-label="Sources" data-testid="prospectus-sources">
      <details open={!phone} className="psp-app-d">
        <summary className="psp-srcs-sum psp-app-sum"><h2 className="psp-card-title">Sources <span className="psp-muted">({notes.length})</span></h2></summary>
        <SourceList notes={notes} testId="prospectus-sources-list" />
      </details>
    </section>
  )
}
