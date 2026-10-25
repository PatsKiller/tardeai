import { type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { BB, T, TYPE } from '../lib/watchTokens'
import { RADIUS } from '../lib/designTokens'
import DeskPage, { DeskGap, type DeskDecision, type DeskSource, type DeskTab } from './DeskPage'
import W7DetailSheet, { useW7Detail } from './W7DetailSheet'
import { useApi } from '../hooks/useApi'

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

export function DeskPanels({ panels, onOpen }: { panels: DeskPanel[]; onOpen: (panel: string, row: string) => void }) {
  return <div className="desk-board-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 12, alignItems: 'start' }}>
    <style>{`.desk-board-grid > section[data-span="2"]{grid-column:span 2}.desk-board-grid > section[data-span="3"]{grid-column:span 3}@media(max-width:1100px){.desk-board-grid{grid-template-columns:minmax(0,1fr) !important}.desk-board-grid > section[data-span]{grid-column:auto !important}}`}</style>
    {panels.map(panel => <section key={panel.id} data-span={panel.span ?? 1} aria-label={panel.title} data-testid={`desk-panel-${panel.id}`} style={panelStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, fontSize: TYPE.md, color: BB.text0 }}>{panel.title}</h3>
        {panel.sub && <span style={{ fontSize: TYPE.base, color: BB.text3, overflowWrap: 'anywhere' }}>{panel.sub}</span>}
      </div>
      {panel.rows.length === 0 && !panel.gap && <p style={{ color: BB.text3, margin: '6px 0 0', fontSize: TYPE.base }}>{panel.empty ?? 'No rows on file.'}</p>}
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
  const { data, error, loading, refetch } = useApi<DeskProjection>(`/api/v2/desks/${desk}`, 300_000)
  const { selected, open, close } = useW7Detail()
  const projection = data && typeof data === 'object' && 'tabs' in data ? data : null
  const sources: DeskSource[] = projection
    ? projection.sources.map(s => ({ id: s.id, label: s.label, asOf: s.as_of, laneIds: s.lane_ids, maxAgeHours: s.max_age_hours, gap: s.gap ?? undefined }))
    : [{ id: 'projection', label: `${title} projection`, gap: loading ? 'Loading the desk projection.' : 'The desk projection has not answered.' }]
  const [panelId, rowId] = (selected ?? '').split(':')
  const detailRow = projection && selected
    ? Object.values(projection.tabs).flatMap(t => t.panels).find(p => p.id === panelId)?.rows.find(r => r.id === rowId)
    : undefined
  return <div data-testid={testId}>
    <DeskPage title={title} purpose={purpose} tabs={tabs} tabAliases={tabAliases} sources={sources}
      decisions={projection?.decisions} decisionGap={projection ? projection.decision_gap ?? 'No open decisions on file for this desk.' : 'The desk projection has not answered.'}>
      {(active: string) => <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {!projection && <DeskGap title={`${title} unavailable`} reason={error ? 'The desk projection could not be read. Nothing below is current.' : 'Loading the desk projection.'}>
          {error && <button type="button" onClick={refetch} style={{ minHeight: 44, width: '100%', marginTop: 8 }}>Retry</button>}
        </DeskGap>}
        {projection && (projection.tabs[active]?.panels?.length
          ? <DeskPanels panels={projection.tabs[active].panels} onOpen={(p, r) => open(`${p}:${r}`)} />
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
