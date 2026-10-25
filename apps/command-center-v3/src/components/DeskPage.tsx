import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { BB, T, TYPE } from '../lib/watchTokens'
import { RADIUS } from '../lib/designTokens'

export type DeskTab = { id: string; label: string }
export type DeskSource = {
  id: string
  label: string
  asOf?: string | null
  laneIds?: string[]
  maxAgeHours?: number
  gap?: string
}
export type DeskDecision = { id: string; title: string; detail?: string; href?: string }
export type DeskWriter = {
  lane_id: string
  state: 'ACTIVE' | 'PAUSED' | 'RETIRED' | 'NONE' | null
  last_success_at: string | null
  evidence_source: string | null
  evidence_as_of: string | null
  reason: string | null
}
type SourcePayload = { observed_at: string; writers: DeskWriter[] }
// useApi already unwraps the server's {ok, data} envelope; accept either shape so an
// unwrapped body is never mistaken for a failed read.
type SourceResponse = SourcePayload | { ok: boolean; data?: SourcePayload }

/** Shared with pages that already conditionally render their panels. */
export function useDeskTab(tabs: readonly DeskTab[], defaultTab = tabs[0]?.id ?? '', aliases: Record<string, string> = {}): [string, (id: string) => void] {
  const location = useLocation()
  const navigate = useNavigate()
  const raw = new URLSearchParams(location.search).get('tab')
  const fallback = tabs.some(tab => tab.id === defaultTab) ? defaultTab : tabs[0]?.id ?? ''
  const requested = raw ? aliases[raw] ?? aliases[raw.toLowerCase()] ?? raw : fallback
  const active = tabs.find(tab => tab.id.toLowerCase() === requested.toLowerCase() || tab.label.toLowerCase() === requested.toLowerCase())?.id ?? fallback
  const change = (id: string, replace = false) => {
    if (!tabs.some(tab => tab.id === id)) return
    const next = new URLSearchParams(location.search)
    next.set('tab', id)
    navigate({ pathname: location.pathname, search: next.toString(), hash: location.hash }, { replace })
  }
  useEffect(() => {
    if (tabs.length && raw !== active) change(active, true)
  }, [location.pathname, location.search, location.hash, active])
  return [active, change]
}

const panel: CSSProperties = { background: BB.bgPanel, border: `1px solid ${BB.border}`, borderRadius: RADIUS.lg, padding: 16, minWidth: 0 }

export function DeskGap({ title, reason, children }: { title: string; reason: string; children?: ReactNode }) {
  return <aside role="note" style={{ ...panel, borderStyle: 'dashed', color: BB.amber }}>
    <strong>{title}</strong><div style={{ marginTop: 4, fontSize: TYPE.base }}>{reason}</div>{children}
  </aside>
}

function clock(value: string | null | undefined, now: number): { text: string; hours?: number; gap?: string } {
  if (!value) return { text: 'update time unavailable', gap: 'The source has no recorded update time.' }
  // A date-only value is not an instant and must not become an invented midnight clock.
  const at = /T.*(?:Z|[+-]\d\d:\d\d)$/.test(value) ? Date.parse(value) : NaN
  if (!Number.isFinite(at)) return { text: 'update time unavailable', gap: 'The source update time is incomplete or invalid.' }
  if (at > now) return { text: 'update time needs review', gap: 'The source update time is in the future.' }
  const minutes = Math.floor((now - at) / 60_000)
  const text = minutes < 60 ? `${minutes}m ago` : minutes < 1440 ? `${Math.floor(minutes / 60)}h ago` : `${Math.floor(minutes / 1440)}d ago`
  return { text, hours: minutes / 60 }
}

export type DeskPageProps = {
  title: string
  purpose: string
  tabs?: readonly DeskTab[]
  defaultTab?: string
  tabAliases?: Record<string, string>
  sources: readonly DeskSource[]
  decisions?: readonly DeskDecision[]
  decisionGap?: string
  children: ReactNode | ((activeTab: string) => ReactNode)
}

/** No page facts are computed here: callers supply source timestamps and decisions. */
export default function DeskPage({ title, purpose, tabs = [], defaultTab, tabAliases, sources, decisions, decisionGap, children }: DeskPageProps) {
  const [active, setTab] = useDeskTab(tabs, defaultTab, tabAliases)
  // On a phone the source clocks and decisions sit between the tabs and the content; after a tab tap,
  // bring the selected content into view so the tap visibly does something (mobile-first standard 1).
  const contentRef = useRef<HTMLDivElement>(null)
  const tapped = useRef(false)
  useEffect(() => {
    if (!tapped.current) return
    tapped.current = false
    const el = contentRef.current
    if (el && el.getBoundingClientRect().top > window.innerHeight * 0.5) el.scrollIntoView({ block: 'start' })
  }, [active])
  const [now, setNow] = useState(Date.now)
  useEffect(() => { const id = window.setInterval(() => setNow(Date.now()), 60_000); return () => window.clearInterval(id) }, [])
  const laneIds = [...new Set(sources.flatMap(source => source.laneIds ?? []))].sort()
  const { data, loading, error, stale, refetch } = useApi<SourceResponse>(`/api/v2/desk-sources?lanes=${encodeURIComponent(laneIds.join(','))}`, 60_000, { enabled: laneIds.length > 0 })
  const payload: SourcePayload | undefined = data && 'writers' in data ? data : (data as { data?: SourcePayload } | null)?.data
  const sourceReadFailed = Boolean(data) && (('ok' in (data as object) && (data as { ok: boolean }).ok !== true) || !Array.isArray(payload?.writers))
  const writerRows = Array.isArray(payload?.writers) ? payload!.writers : []
  const writers = new Map(writerRows.filter(writer => writer && typeof writer.lane_id === 'string').map(writer => [writer.lane_id, writer]))
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0, color: BB.text1 }}>
    <header><h1 style={{ margin: 0, fontSize: TYPE.xl, color: BB.text0 }}>{title}</h1>
      <p style={{ margin: '6px 0 0', color: BB.text3, fontSize: TYPE.md }}>{purpose}</p></header>
    {tabs.length > 0 && <nav aria-label={`${title} views`} style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      {tabs.map(tab => <button key={tab.id} type="button" aria-pressed={active === tab.id} onClick={() => { tapped.current = tab.id !== active; setTab(tab.id) }} style={{
        minHeight: 44, minWidth: 44, padding: '8px 12px', borderRadius: RADIUS.md, cursor: 'pointer', fontSize: TYPE.base,
        border: `1px solid ${active === tab.id ? T.link : BB.border}`, color: active === tab.id ? T.link : BB.text2, background: BB.bgPanel,
      }}>{tab.label}</button>)}
    </nav>}
    <section aria-label="Source clocks" style={panel}>
      <h2 style={{ margin: '0 0 12px', fontSize: TYPE.md }}>Source clocks</h2>
      {(error || stale || sourceReadFailed) && <DeskGap title="Writer clocks unavailable" reason="The latest execution evidence could not be loaded. Any retained clocks are historical.">
        <button type="button" onClick={refetch} style={{ minHeight: 44, width: '100%', marginTop: 8 }}>Retry writer clocks</button>
      </DeskGap>}
      {sources.length === 0 && <DeskGap title="Source evidence unavailable" reason="This view has not supplied source clocks." />}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 240px), 1fr))', gap: 12 }}>
        {sources.map(source => {
          const age = clock(source.asOf, now)
          const sourceWriters = (source.laneIds ?? []).map(id => writers.get(id))
          const staleSource = source.maxAgeHours !== undefined && age.hours !== undefined && age.hours > source.maxAgeHours
          const gap = source.gap || age.gap || (staleSource ? 'This source is older than the freshness window for this view.' : null)
          return <article key={source.id} style={{ ...panel, padding: 12 }}>
            <strong>{source.label}</strong><div style={{ color: gap ? BB.amber : BB.text2, marginTop: 6 }}>Updated {age.text}</div>
            {source.asOf && <time dateTime={source.asOf} style={{ fontSize: TYPE.sm, color: BB.text3, overflowWrap: 'anywhere' }}>{source.asOf}</time>}
            {sourceWriters.length === 0 && <p style={{ color: BB.amber, fontSize: TYPE.base }}>Writer not identified for this source.</p>}
            {sourceWriters.map((writer, index) => <div key={source.laneIds![index]} style={{ borderTop: `1px solid ${BB.border}`, paddingTop: 8, marginTop: 8, fontSize: TYPE.base }}>
              <div style={{ color: writer?.state === 'ACTIVE' ? BB.text2 : BB.amber }}>Writer {writer?.state ?? (loading ? 'loading' : 'state unavailable')}{sourceWriters.length > 1 ? ` · ${index + 1}` : ''}</div>
              <div>Last successful run: {writer?.last_success_at ? clock(writer.last_success_at, now).text : 'not measured'}</div>
              {writer?.last_success_at && <time dateTime={writer.last_success_at} style={{ color: BB.text3, fontSize: TYPE.sm, overflowWrap: 'anywhere' }}>{writer.last_success_at}</time>}
              {writer?.evidence_as_of && <div style={{ color: BB.text3, fontSize: TYPE.sm }}>Evidence captured {clock(writer.evidence_as_of, now).text}</div>}
              {(writer?.reason || !writer) && <div style={{ color: BB.amber, marginTop: 4 }}>{writer?.reason ?? (loading ? 'Loading execution evidence.' : 'Execution evidence is unavailable for this writer.')}</div>}
            </div>)}
            {gap && <div role="note" style={{ color: BB.amber, borderTop: `1px dashed ${BB.border}`, paddingTop: 8, marginTop: 8, fontSize: TYPE.base }}>{gap}</div>}
          </article>
        })}
      </div>
    </section>
    <section aria-label="Decisions for you" style={panel}>
      <h2 style={{ fontSize: TYPE.md, margin: '0 0 8px' }}>Decisions for you</h2>
      {decisions?.length ? <ul style={{ paddingLeft: 20, margin: 0 }}>{decisions.map(decision => <li key={decision.id} style={{ marginTop: 8 }}>
        {!decision.href && <strong>{decision.title}</strong>}
        {decision.detail && <div style={{ fontSize: TYPE.base, color: BB.text3, marginTop: 4 }}>{decision.detail}</div>}
        {decision.href && <Link style={{ color: T.link, display: 'flex', alignItems: 'center', minHeight: 44, width: '100%' }} to={decision.href}>{decision.title}</Link>}
      </li>)}</ul> : <p style={{ color: BB.text3, margin: 0 }}>{decisionGap ?? 'Decision evidence has not been supplied for this view.'}</p>}
    </section>
    <div ref={contentRef} style={{ scrollMarginTop: 8 }}>{typeof children === 'function' ? children(active) : children}</div>
  </div>
}
