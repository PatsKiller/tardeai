/** Prospectus citations — not shown to the reader (operator 2026-10-27: "there's a lot of citations … We don't need to
 *  see it on the frontend … If it's been validated, that's good.").
 *  Prose renders clean text; each citation group leaves only a hidden marker carrying its fact ids in data-fact-id
 *  (the JSON keeps every citation for the gate, the layer-3 check and the accuracy auditor). The reader sees ONE
 *  validation badge near the header instead (ValidationBadge). Superscripts, per-section "Sources (n)" and the
 *  Sources appendix are gone; the exports keep their names so callers stay unchanged. */
import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { inlineMarkdown } from '../PolicyRuleParts'
import { cleanProse, splitFootnotes, type Footnote, type ProspectusSection } from '../../lib/prospectusModel'

type Ctx = { byId: Map<string, Footnote> }
const FootnoteCtx = createContext<Ctx>({ byId: new Map() })

export function FootnoteProvider({ notes, children }: { notes: Footnote[]; children: ReactNode }) {
  const byId = useMemo(() => new Map(notes.map(n => [n.id, n])), [notes])
  return <FootnoteCtx.Provider value={{ byId }}>{children}</FootnoteCtx.Provider>
}

export function useFootnotes(): Map<string, Footnote> { return useContext(FootnoteCtx).byId }

/** A citation group: invisible, kept as data for audits. */
export function FootnoteRef({ ids }: { notes?: Footnote[]; ids: string[] }) {
  return <span className="psp-cite" data-fact-id={ids.join(' ')} hidden />
}

/** Prose with markdown emphasis and muted "not reliable (…)" notes; citation groups leave only a hidden marker. */
export function CiteText({ text, md = true }: { text: string | null | undefined; md?: boolean }) {
  const byId = useFootnotes()
  const parts = splitFootnotes(cleanProse(text), byId)
  return <>{parts.map((p, i) => 'ids' in p
    ? <FootnoteRef key={i} ids={p.ids} />
    : p.muted ? <span key={i} className="psp-unreliable" data-testid="prospectus-unreliable">{p.text}</span>
      : <span key={i}>{md ? inlineMarkdown(p.text, `c${i}`) : p.text}</span>)}</>
}

/** Retired (no per-section source lists). */
export function SectionSources(_props: { s: ProspectusSection }) { return null }

/** Retired (no Sources appendix). */
export function SourcesAppendix(_props: { notes: Footnote[]; phone: boolean }) { return null }
