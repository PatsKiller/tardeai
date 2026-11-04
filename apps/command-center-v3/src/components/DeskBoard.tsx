import { type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { BB, T, TYPE } from '../lib/watchTokens'
import { RADIUS } from '../lib/designTokens'
import DeskPage, { DeskGap, type DeskDecision, type DeskSource, type DeskTab } from './DeskPage'
import W7DetailSheet, { useW7Detail } from './W7DetailSheet'
import { useApi } from '../hooks/useApi'
import { deriveSurfaceState, isRecord, isText, isOptionalText, isTextList, surfaceGap, type SurfaceShape } from '../lib/surfaceState'
import { SurfaceGap, useReportSurfaceState } from './SurfaceGap'

/**
 * Boards 1–4 render a server projection (`/api/v2/desks/<desk>`). Every label and
 * value on a row comes from that projection, which names its store and writes
 * explicit gap text ("not on file", "not measured"); this component formats
 * nothing and computes no fact. Rows are links or open a route-backed detail
 * sheet (full screen on a phone, with ← Back). Read-only: no request but GET.
 */
export type DeskRowField = { label: string; value: string }
export type DeskRowDetail = { title: string; fields: DeskRowField[]; source?: string; href?: string; href_label?: string }
export type DeskRow = { id: string; label: string; value: string; tone?: 'good' | 'warn' | 'bad' | 'info' | null; href?: string; detail?: DeskRowDetail }
export type DeskPanel = { id: string; title: string; sub?: string; span?: number; rows: DeskRow[]; gap?: string | null; empty?: string }
export type DeskProjection = {
  ok?: boolean
  desk: string
  as_of: string
  sources: { id: string; label: string; as_of: string | null; lane_ids: string[]; max_age_hours?: number; gap?: string | null }[]
  decisions: DeskDecision[]
  decision_gap?: string | null
  tabs: Record<string, { panels: DeskPanel[] }>
  errors?: string[]
}

// Validate the complete render boundary before any .map(), text child or selected detail can consume it.
// Extractor try/catch alone cannot protect the later render callbacks.
function isDeskDecision(value: unknown): boolean {
  return isRecord(value) && isText(value.id) && isText(value.title) && isOptionalText(value.detail)
    && isOptionalText(value.href) && (value.diagnostics == null || (isRecord(value.diagnostics)
      && isText(value.diagnostics.title) && isOptionalText(value.diagnostics.detail)))
}
function isDeskRow(value: unknown): boolean {
  if (!isRecord(value) || !isText(value.id) || !isText(value.label) || !isText(value.value)
    || !isOptionalText(value.href) || !isOptionalText(value.tone)) return false
  const detail = value.detail
  return detail == null || (isRecord(detail) && isText(detail.title) && Array.isArray(detail.fields)
    && detail.fields.every(f => isRecord(f) && isText(f.label) && isText(f.value))
    && isOptionalText(detail.source) && isOptionalText(detail.href) && isOptionalText(detail.href_label))
}
function isDeskProjection(value: unknown): value is DeskProjection {
  if (!isRecord(value) || (value.ok !== undefined && value.ok !== true) || !isText(value.desk) || !isText(value.as_of)
    || !isOptionalText(value.decision_gap) || !Array.isArray(value.sources) || !Array.isArray(value.decisions)
    || !isRecord(value.tabs) || (value.errors !== undefined && !isTextList(value.errors))) return false
  return value.sources.every(s => isRecord(s) && isText(s.id) && isText(s.label) && isOptionalText(s.as_of)
    && isTextList(s.lane_ids) && isOptionalText(s.gap) && (s.max_age_hours === undefined
      || (typeof s.max_age_hours === 'number' && Number.isFinite(s.max_age_hours) && s.max_age_hours >= 0)))
    && value.decisions.every(isDeskDecision)
    && Object.values(value.tabs).every(tab => isRecord(tab) && Array.isArray(tab.panels)
      && tab.panels.every(p => isRecord(p) && isText(p.id) && isText(p.title) && isOptionalText(p.sub)
        && isOptionalText(p.gap) && isOptionalText(p.empty) && (p.span === undefined || [1, 2, 3].includes(p.span))
        && Array.isArray(p.rows) && p.rows.every(isDeskRow)))
}
// The current agents producer uses gap for this one INFORMATIONAL note too. Exclude only that exact known ABI
// value at its source; every other source gap, including a failed registry read, means coverage is unknown.
function isRegistryClockNote(desk: string, source: DeskProjection['sources'][number]): boolean {
  return desk === 'agents' && source.id === 'summary'
    && source.gap === 'Lane counts come from config/lane_registry.json; it carries no update time.'
}
function projectionGaps(data: DeskProjection): string[] {
  const gaps = new Map((data.errors ?? []).map(gap => [gap, gap]))
  // agents_payload's failed reads are in sources[].gap, not errors[]. Keep other desks on their existing ABI.
  if (data.desk === 'agents') {
    for (const source of data.sources) {
      if (source.gap && !isRegistryClockNote(data.desk, source)) gaps.set(source.gap, `${source.label}: ${source.gap}`)
    }
    // Cases/promotions and admission-log coverage can have a panel gap without a matching source entry. Count
    // those too, deduplicating shared source/panel failures. These two exact producer notes describe known data,
    // not an unread source: insufficient calibration samples and recorded errors in successfully read run journals.
    for (const tab of Object.values(data.tabs)) for (const panel of tab.panels) {
      if (!panel.gap || (panel.id === 'calibration' && panel.gap === 'No agent has enough resolved outcomes for a Brier score.')
        || (panel.id === 'timeline' && /^\d+ of the \d+ newest runs recorded a model error\.$/.test(panel.gap))) continue
      if (!gaps.has(panel.gap)) gaps.set(panel.gap, `${panel.title}: ${panel.gap}`)
    }
  }
  return [...gaps.values()]
}

const TONE: Record<string, string> = { good: BB.green, warn: BB.amber, bad: BB.red, info: T.link }
const panelStyle: CSSProperties = { background: BB.bgPanel, border: `1px solid ${BB.border}`, borderRadius: RADIUS.lg, padding: 14, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 4 }
const rowStyle: CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, minHeight: 44, width: '100%', padding: '6px 0', borderTop: `1px solid ${BB.border}`, fontSize: TYPE.md, textAlign: 'left', background: 'transparent', color: BB.text1, boxSizing: 'border-box' }
const valueStyle: CSSProperties = { fontFamily: 'var(--font-mono)', textAlign: 'right', overflowWrap: 'anywhere', minWidth: 0 }

function RowBody({ row }: { row: DeskRow }) {
  return <>
    <span style={{ minWidth: 0, overflowWrap: 'anywhere', color: BB.text2 }}>{row.label}</span>
    <span style={{ ...valueStyle, color: row.tone ? TONE[row.tone] ?? BB.text0 : BB.text0 }}>{row.value}</span>
  </>
}

export function DeskPanels({ panels, onOpen, totalUnknown = false }: { panels: DeskPanel[]; onOpen: (panel: string, row: string) => void; totalUnknown?: boolean }) {
  return <div className="desk-board-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 12, alignItems: 'start' }}>
    <style>{`.desk-board-grid > section[data-span="2"]{grid-column:span 2}.desk-board-grid > section[data-span="3"]{grid-column:span 3}@media(max-width:1100px){.desk-board-grid{grid-template-columns:minmax(0,1fr) !important}.desk-board-grid > section[data-span]{grid-column:auto !important}}`}</style>
    {panels.map(panel => <section key={panel.id} data-span={panel.span ?? 1} aria-label={panel.title} data-testid={`desk-panel-${panel.id}`} style={panelStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, fontSize: TYPE.md, color: BB.text0 }}>{panel.title}</h3>
        {panel.sub && <span style={{ fontSize: TYPE.base, color: BB.text3, overflowWrap: 'anywhere' }}>{panel.sub}</span>}
      </div>
      {panel.rows.length === 0 && !panel.gap && <p style={{ color: BB.text3, margin: '6px 0 0', fontSize: TYPE.base }}>{totalUnknown
        ? 'Not known while some sources are unavailable.'
        : panel.empty ?? 'No rows on file.'}</p>}
      {panel.rows.map(row => row.href
        ? <Link key={row.id} to={row.href} style={{ ...rowStyle, textDecoration: 'none' }}><RowBody row={row} /></Link>
        : row.detail
          ? <button key={row.id} type="button" onClick={() => onOpen(panel.id, row.id)} style={{ ...rowStyle, border: 'none', borderTop: rowStyle.borderTop, cursor: 'pointer', font: 'inherit' }}><RowBody row={row} /></button>
          : <div key={row.id} style={rowStyle}><RowBody row={row} /></div>)}
      {panel.gap && <div role="note" style={{ marginTop: 6, padding: '8px 10px', borderRadius: RADIUS.md, border: `1px dashed ${BB.amber}`, color: BB.amber, fontSize: TYPE.base }}>{panel.gap}</div>}
    </section>)}
  </div>
}

export type DeskBoardConfig = {
  desk: string
  title: string
  purpose: string
  tabs: readonly DeskTab[]
  tabAliases?: Record<string, string>
  classicHref: string
  testId: string
  /** Retained read-only content rendered under a tab's projected panels. */
  extras?: Record<string, ReactNode>
}

/** One desk page: the board-0 frame around the server projection, one tab at a time. */
export default function DeskBoard({ desk, title, purpose, tabs, tabAliases, classicHref, testId, extras }: DeskBoardConfig) {
  const { data, error, loading, refreshing, stale, refetch } = useApi<DeskProjection>(`/api/v2/desks/${desk}`, 300_000)
  const { selected, open, close } = useW7Detail()
  // SurfaceState@v1 (BOARD row 36): ONE state decides every word this page prints about its data. `!projection` is
  // never used as a synonym for "unavailable" again — that is what put "Agents unavailable" beside "Loading the
  // desk projection." on the operator's screen.
  const shape: SurfaceShape<DeskProjection> = {
    what: `${title} page data`,
    // Read the producer's source-level completeness contract, even when errors[] is empty.
    gaps: projectionGaps,
    isEmpty: d => Object.values(d.tabs).every(t => t.panels.every(p => p.rows.length === 0)),
    usable: isDeskProjection,
  }
  const surface = deriveSurfaceState<DeskProjection>({ data, error, loading, refreshing, stale }, shape)
  useReportSurfaceState(`${title} page`, surface)
  const projection = surface.data
  const surfaceText = surfaceGap(surface, shape)
  // F1 (review, 2026-11-04): the invariant is enforced HERE, in the renderer the operator sees, not only in the
  // module. While the envelope says sources are missing (`surface.state === 'partial'`, `totalKnown === false`) this
  // page may not print a complete-looking line — "No open decisions on file" is exactly that claim.
  const decisionLine = !projection
    ? (surfaceText ? surfaceText.title : 'The desk projection has not answered.')
    : surface.totalKnown
      ? projection.decision_gap ?? 'No open decisions on file for this desk.'
      : `${surface.gaps.length} source${surface.gaps.length === 1 ? '' : 's'} did not answer (${surface.gaps.join(', ')}). The decisions list is not complete.`
  const sources: DeskSource[] = projection
    ? projection.sources.map(s => ({ id: s.id, label: s.label, asOf: s.as_of, laneIds: s.lane_ids, maxAgeHours: s.max_age_hours, gap: s.gap ?? undefined }))
    : [{ id: 'projection', label: `${title} projection`, pending: true, gap: surfaceText ? `${surfaceText.title} ${surfaceText.reason}` : undefined }]
  const [panelId, rowId] = (selected ?? '').split(':')
  const detailRow = projection && selected
    ? Object.values(projection.tabs).flatMap(t => t.panels).find(p => p.id === panelId)?.rows.find(r => r.id === rowId)
    : undefined
  return <div data-testid={testId}>
    <DeskPage title={title} purpose={purpose} tabs={tabs} tabAliases={tabAliases} sources={sources} compactSources={desk === 'agents'}
      decisions={projection?.decisions.map(decision => desk === 'agents' && decision.id === 'runs-gate-b-shadow' ? {
        ...decision, title: 'Choose how these agents should use AI',
        detail: 'These recorded runs do not contact an AI model and produce no AI findings. Decide whether to keep, reduce or pause the runs, or connect the agents to the approved CIO research service.',
        diagnostics: { title: decision.title, detail: decision.detail },
      } : decision)} decisionGap={decisionLine}>
      {(active: string) => <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <SurfaceGap state={surface} shape={shape} onRetry={refetch} />
        {projection && (projection.tabs[active]?.panels?.length
          ? <DeskPanels panels={projection.tabs[active].panels} onOpen={(p, r) => open(`${p}:${r}`)} totalUnknown={!surface.totalKnown} />
          : <DeskGap title="Nothing on file for this view" reason="The projection returned no panels for this tab." />)}
        {extras?.[active]}
        <Link to={classicHref} style={{ display: 'flex', alignItems: 'center', minHeight: 44, color: T.link, fontSize: TYPE.md }}>
          Classic {title} view — every original panel and control →
        </Link>
      </div>}
    </DeskPage>
    {selected && detailRow?.detail && <W7DetailSheet title={detailRow.detail.title} onClose={close}>
      <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 8 }}>
        {detailRow.detail.fields.map(f => <div key={f.label} style={{ borderTop: `1px solid ${BB.border}`, paddingTop: 8 }}>
          <dt style={{ color: BB.text3, fontSize: TYPE.base }}>{f.label}</dt>
          <dd style={{ margin: '2px 0 0', color: BB.text0, fontSize: TYPE.md, overflowWrap: 'anywhere' }}>{f.value}</dd>
        </div>)}
      </dl>
      {detailRow.detail.source && <p style={{ color: BB.text3, fontSize: TYPE.base }}>Source: {detailRow.detail.source}</p>}
      {detailRow.detail.href && <Link to={detailRow.detail.href} style={{ display: 'flex', alignItems: 'center', minHeight: 44, color: T.link }}>{detailRow.detail.href_label ?? 'Open →'}</Link>}
    </W7DetailSheet>}
    {selected && projection && !detailRow?.detail && <W7DetailSheet title="Detail unavailable" onClose={close}>
      <p>This row is no longer in the desk projection.</p>
    </W7DetailSheet>}
  </div>
}
