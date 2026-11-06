import { Link } from 'react-router-dom'
import { BB, T, TYPE } from '../../lib/watchTokens'
import DeskPage, { DeskGap, type DeskSource } from '../../components/DeskPage'
import { DeskPanels, type DeskProjection } from '../../components/DeskBoard'
import W7DetailSheet, { useW7Detail } from '../../components/W7DetailSheet'
import DefenseEngineView, { EngineSheetBody, SHEET_TITLES } from '../../components/defense/engine/DefenseEngine'
import { useApi } from '../../hooks/useApi'
import { unwrapProjection } from '../../lib/defenseEngine'

/**
 * Approved board 3, redesigned per design defense/v001. Sector momentum is owned by Watch › Sectors
 * (board 13): linked, not repeated. The engine view (GET /api/v2/defense/engine) leads "Where to act";
 * every original desk panel (GET /api/v2/desks/defense) stays under its tab, and the classic page keeps
 * every original panel and control. Read-only: GET only, no order control on this page.
 */
export const DEFENSE_TABS = [
  { id: 'where-to-act', label: 'Where to act' },
  { id: 'your-book', label: 'Your book' },
  { id: 'hedges', label: 'Hedges & short side' },
  { id: 'review-log', label: 'Review log' },
] as const

const ENGINE_PREFIX = 'engine:'

export default function DefenseDesk() {
  const desk = useApi<DeskProjection>('/api/v2/desks/defense', 300_000)
  const engine = useApi<unknown>('/api/v2/defense/engine', 300_000)
  const { selected, open, close } = useW7Detail()
  const projection = desk.data && typeof desk.data === 'object' && 'tabs' in desk.data ? desk.data : null
  const ep = unwrapProjection(engine.data)
  const sources: DeskSource[] = [
    ...(ep ? [{ id: 'defense-engine', label: 'Defense engine', asOf: ep.generated_at, laneIds: ['defense-engine-build'], gap: ep.served?.stale ? ep.served.fallback_reason ?? 'served stale' : undefined }]
      : [{ id: 'defense-engine', label: 'Defense engine', gap: engine.loading ? 'Loading the defense projection.' : 'The defense projection has not answered.' }]),
    ...(projection
      ? projection.sources.map(s => ({ id: s.id, label: s.label, asOf: s.as_of, laneIds: s.lane_ids, maxAgeHours: s.max_age_hours, gap: s.gap ?? undefined }))
      : [{ id: 'projection', label: 'Defense desk projection', gap: desk.loading ? 'Loading the desk projection.' : 'The desk projection has not answered.' }]),
  ]
  const openEngine = (k: string) => open(`${ENGINE_PREFIX}${k}`)
  const engineSheet = selected?.startsWith(ENGINE_PREFIX) ? selected.slice(ENGINE_PREFIX.length) : null
  const [panelId, rowId] = !engineSheet && selected ? selected.split(':') : []
  const detailRow = projection && panelId
    ? Object.values(projection.tabs).flatMap(t => t.panels).find(p => p.id === panelId)?.rows.find(r => r.id === rowId)
    : undefined

  return <div data-testid="defense-desk">
    <DeskPage title="Defense" purpose="How exposed is the book if the market turns — and what hedges are ready?"
      tabs={DEFENSE_TABS} tabAliases={{ act: 'where-to-act', book: 'your-book', 'short-side': 'hedges', review: 'review-log' }}
      sources={sources} decisions={projection?.decisions}
      decisionGap={projection ? projection.decision_gap ?? 'No open decisions on file for this desk.' : 'The desk projection has not answered.'}>
      {(active: string) => <div style={{ display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 }}>
        {active === 'where-to-act' && (ep
          ? <DefenseEngineView p={ep} onOpen={openEngine} />
          : <DeskGap title="Defense engine unavailable" reason={engine.error ? 'The defense projection could not be read. The desk panels below are unchanged.' : 'Loading the defense projection.'}>
            {engine.error && <button type="button" onClick={engine.refetch} style={{ minHeight: 44, width: '100%', marginTop: 8 }}>Retry</button>}
          </DeskGap>)}
        {!projection && <DeskGap title="Defense desk unavailable" reason={desk.error ? 'The desk projection could not be read. Nothing below is current.' : 'Loading the desk projection.'}>
          {desk.error && <button type="button" onClick={desk.refetch} style={{ minHeight: 44, width: '100%', marginTop: 8 }}>Retry</button>}
        </DeskGap>}
        {projection && (projection.tabs[active]?.panels?.length
          ? <DeskPanels panels={projection.tabs[active].panels} onOpen={(p, r) => open(`${p}:${r}`)} />
          : <DeskGap title="Nothing on file for this view" reason="The projection returned no panels for this tab." />)}
        <Link to="/defense/classic" style={{ display: 'flex', alignItems: 'center', minHeight: 44, color: T.link, fontSize: TYPE.md }}>
          Classic Defense view — every original panel and control →
        </Link>
      </div>}
    </DeskPage>
    {engineSheet && <W7DetailSheet title={SHEET_TITLES[engineSheet] ?? 'Detail unavailable'} onClose={close}>
      {ep ? <EngineSheetBody p={ep} sheet={engineSheet} /> : <p>The defense projection has not answered.</p>}
    </W7DetailSheet>}
    {!engineSheet && selected && detailRow?.detail && <W7DetailSheet title={detailRow.detail.title} onClose={close}>
      <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 8 }}>
        {detailRow.detail.fields.map(f => <div key={f.label} style={{ borderTop: `1px solid ${BB.border}`, paddingTop: 8 }}>
          <dt style={{ color: BB.text3, fontSize: TYPE.base }}>{f.label}</dt>
          <dd style={{ margin: '2px 0 0', color: BB.text0, fontSize: TYPE.md, overflowWrap: 'anywhere' }}>{f.value}</dd>
        </div>)}
      </dl>
      {detailRow.detail.source && <p style={{ color: BB.text3, fontSize: TYPE.base }}>Source: {detailRow.detail.source}</p>}
      {detailRow.detail.href && <Link to={detailRow.detail.href} style={{ display: 'flex', alignItems: 'center', minHeight: 44, color: T.link }}>{detailRow.detail.href_label ?? 'Open →'}</Link>}
    </W7DetailSheet>}
    {!engineSheet && selected && projection && !detailRow?.detail && <W7DetailSheet title="Detail unavailable" onClose={close}>
      <p>This row is no longer in the desk projection.</p>
    </W7DetailSheet>}
  </div>
}
