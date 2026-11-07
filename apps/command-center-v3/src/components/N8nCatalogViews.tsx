import { useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { FONT, RADIUS, TOKENS, TYPE, toneVars, type Tone } from '../lib/designTokens'
import { etTime } from '../lib/jobRunHistory'
import {
  MODES, MODE_LABEL, MODE_TIP, MODE_TONE, N8N_CATALOG_API, catalogStats, categoryLanes, laneChips, laneHref, notInRelay, scheduleText,
  type CatalogCategory, type CatalogLane, type N8nCatalogWire,
} from '../lib/n8nCatalog'
import { mountApproved, resolveSub, type Nav, type SubKey } from '../lib/n8nCatalogApproved'

// Ops › Jobs & n8n › n8n catalog (LQ-20261107-150). Read-only. Phone first: stacked cards, 44 px targets, every
// mode chip / verdict chip / top stat explains itself: a tap opens the text inline (phone), hover or keyboard focus
// shows it (desktop), and title= carries it as a fallback.

const panel: CSSProperties = { padding: 12, border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, background: TOKENS.bg[1], minWidth: 0 }
const muted: CSSProperties = { color: TOKENS.text[2], fontSize: TYPE.sm, margin: 0 }
const wrap: CSSProperties = { overflowWrap: 'anywhere', minWidth: 0 }
const chipBtn = (tone: Tone, open: boolean): CSSProperties => ({
  display: 'inline-flex', alignItems: 'center', gap: 4, minHeight: 32, padding: '2px 10px', borderRadius: RADIUS.pill, fontSize: TYPE.sm, fontWeight: 600,
  color: toneVars(tone).color, background: toneVars(tone).bg, border: `1px solid ${open ? toneVars(tone).color : toneVars(tone).border}`, cursor: 'pointer',
  font: 'inherit', whiteSpace: 'nowrap', maxWidth: '100%',
})
const tipBox: CSSProperties = {
  flexBasis: '100%', gridColumn: '1 / -1', display: 'block', boxSizing: 'border-box', padding: '8px 10px', borderRadius: RADIUS.sm,
  background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, color: TOKENS.text[1], fontSize: TYPE.base, lineHeight: 1.45, ...wrap,
}

/** A chip (or any trigger) whose explanation opens inline on tap and on hover/focus. The tip text is required. */
export function TipChip({ tip, tone, children, testId, style }: { tip: string; tone: Tone; children: ReactNode; testId?: string; style?: CSSProperties }) {
  const id = useId()
  const [pinned, setPinned] = useState(false)
  const [hover, setHover] = useState(false)
  const open = pinned || hover
  return <span style={{ display: 'contents' }}>
    <button type="button" data-testid={testId} data-tip={tip} title={tip} aria-expanded={open} aria-describedby={open ? id : undefined}
      onClick={e => { e.preventDefault(); e.stopPropagation(); setPinned(p => !p) }}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)} onFocus={() => setHover(true)} onBlur={() => setHover(false)}
      onKeyDown={e => { if (e.key === 'Escape') { setPinned(false); setHover(false) } }}
      style={{ ...chipBtn(tone, open), ...style }}>{children}<span aria-hidden="true" style={{ opacity: 0.7, fontSize: TYPE.xs }}>ⓘ</span></button>
    {open && <span id={id} role="tooltip" data-testid="n8n-catalog-tip" style={tipBox}>{tip}</span>}
  </span>
}

function StatTiles({ data }: { data: N8nCatalogWire | null }) {
  const stats = catalogStats(data)
  return <div role="group" aria-label="n8n catalog summary — tap a number for what it means" data-testid="n8n-catalog-stats"
    style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 112px), 1fr))', gap: 6 }}>
    {stats.map(s => <TipChip key={s.key} tip={s.tip} tone={s.value ? s.tone : 'neutral'} testId="n8n-catalog-stat"
      style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2, minHeight: 56, width: '100%', borderRadius: RADIUS.md,
        padding: '8px 10px', whiteSpace: 'normal', textAlign: 'left', boxSizing: 'border-box' }}>
      <strong style={{ fontFamily: FONT.mono, fontSize: TYPE.lg }}>{s.value ?? '—'}</strong>
      <span style={{ fontSize: TYPE.xs, textTransform: 'uppercase', letterSpacing: '.04em', color: TOKENS.text[1] }}>{s.label}</span>
    </TipChip>)}
  </div>
}

export function LaneRow({ lane }: { lane: CatalogLane }) {
  const failing = lane.verdict_class === 'fail' || lane.verdict_class === 'not_provable'
  return <li data-testid="n8n-catalog-lane" data-lane={lane.lane_id} data-mode={lane.mode} style={{ ...panel, padding: 10, listStyle: 'none', display: 'grid', gap: 6 }}>
    <Link to={laneHref(lane.lane_id)} style={{ color: TOKENS.text[0], textDecoration: 'none', display: 'grid', gap: 2, minHeight: 44, ...wrap }}>
      <strong style={{ fontSize: TYPE.md }}>{lane.title || lane.lane_id}</strong>
      <span style={{ ...muted, fontFamily: FONT.mono }}>{lane.lane_id} · {scheduleText(lane)}</span>
      {lane.does ? <span style={{ fontSize: TYPE.base, color: TOKENS.text[1] }}>{lane.does}</span> : <span style={muted}>No description yet</span>}
    </Link>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', minWidth: 0 }}>
      {laneChips(lane).map(c => <TipChip key={c.kind} tip={c.tip} tone={c.tone} testId={`n8n-catalog-${c.kind}-chip`}>{c.label}</TipChip>)}
      {notInRelay(lane) && <span data-testid="n8n-catalog-not-in-relay" style={{ ...muted, color: TOKENS.warning }}>not in the relay live list</span>}
      {lane.paused_on_n8n && <span style={{ ...muted, color: TOKENS.warning }}>paused on n8n (Ops Controls)</span>}
      {lane.work_item && <span style={muted}>fix {lane.work_item}</span>}
    </div>
    {failing && lane.defect && <p data-testid="n8n-catalog-defect" style={{ ...muted, color: TOKENS.text[1], ...wrap }}>{lane.defect}</p>}
  </li>
}

export function CategorySection({ cat, data, defaultOpen }: { cat: CatalogCategory; data: N8nCatalogWire | null; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const lanes = categoryLanes(data, cat)
  const bodyId = useId()
  return <section data-testid="n8n-catalog-category" data-category={cat.key} style={{ ...panel, display: 'grid', gap: 8 }}>
    <h3 style={{ margin: 0, fontSize: TYPE.md }}>{cat.label}</h3>
    {cat.blurb && <p style={muted}>{cat.blurb}</p>}
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, minWidth: 0 }}>
      {MODES.map(m => <TipChip key={m} tip={MODE_TIP[m]} tone={cat.modes?.[m] ? MODE_TONE[m] : 'neutral'} testId="n8n-catalog-mode-count">{cat.modes?.[m] ?? 0} · {MODE_LABEL[m]}</TipChip>)}
    </div>
    {lanes.length
      ? <button type="button" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen(o => !o)}
          style={{ minHeight: 44, borderRadius: RADIUS.sm, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[2], color: TOKENS.info, fontSize: TYPE.base, cursor: 'pointer' }}>
          {open ? 'Hide' : 'Show'} {lanes.length} {lanes.length === 1 ? 'lane' : 'lanes'} on n8n</button>
      : <p style={muted}>Nothing in this category is on n8n. {cat.modes?.none ? `All ${cat.modes.none} jobs run on cron or systemd.` : ''}</p>}
    {open && lanes.length > 0 && <ul id={bodyId} style={{ margin: 0, padding: 0, display: 'grid', gap: 8 }}>{lanes.map(l => <LaneRow key={l.lane_id} lane={l} />)}</ul>}
  </section>
}

export function N8nCatalogView({ data, loading, error }: { data: N8nCatalogWire | null; loading: boolean; error: string | null }) {
  const cats = data?.categories ?? []
  const audit = data?.audit
  return <section aria-label="n8n catalog" data-testid="n8n-catalog" style={{ display: 'grid', gap: 10, minWidth: 0 }}>
    <p style={muted}>What n8n is configured to handle, by category: each lane's mode, whether it is in the relay live list, and its audit verdict.
      {' '}Only an audit PASS means a lane is working. Tap any chip or number for what it means; tap a lane for its details.</p>
    <p style={muted} data-testid="n8n-catalog-asof">
      {data?.computed_at ? `Jobs as of ${etTime(data.computed_at)}. ` : ''}
      {audit?.written_at ? `Audit written ${etTime(audit.written_at)}${audit.by ? ` by ${audit.by}` : ''} (${audit.rows ?? 0} lanes). ` : ''}
      {typeof data?.relay?.lanes === 'number' ? `Relay live list: ${data.relay.lanes} lanes.` : ''}
    </p>
    {error && <div role="alert" style={{ ...panel, color: TOKENS.warning }}>The n8n catalog could not be read: {error}.{data ? ' The last read remains below.' : ''}</div>}
    {(data?.notes ?? []).map(n => <div key={n} role="status" data-testid="n8n-catalog-note" style={{ ...panel, color: TOKENS.warning, ...wrap }}>{n}</div>)}
    <StatTiles data={data} />
    {cats.map((c, i) => <CategorySection key={c.key} cat={c} data={data} defaultOpen={i < 3 && (c.lanes?.length ?? 0) > 0} />)}
    {!cats.length && <p style={{ ...panel, ...muted }}>{loading && !data ? 'Loading the n8n catalog…' : 'No categories are reported.'}</p>}
  </section>
}

/** The operator-approved design (artifact "n8n Lane Configuration"), rendered verbatim in a shadow root so its CSS
 *  matches the approved page exactly and cannot leak into the app. Fed by the same live read-only GET. Subtabs
 *  (LQ-20261107-180) live in the URL: ?tab=catalog&sub=overview|lanes|audit[&verdict=FAIL_DATA]. */
export function N8nCatalogApprovedView({ data, sub, filter, onNav }: { data: N8nCatalogWire; sub: SubKey; filter: string; onNav: (n: Nav) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const navRef = useRef(onNav)
  navRef.current = onNav
  const query = useRef('')
  useEffect(() => {
    const box = ref.current
    if (!box) return
    const host = document.createElement('div')
    const theme = document.documentElement.dataset.theme
    if (theme) host.dataset.theme = theme
    box.replaceChildren(host)
    const shadow = host.attachShadow({ mode: 'open' })
    mountApproved(shadow, data, sub, { filter, q: query.current }, n => navRef.current(n))
    // The search survives the minute refresh: remember what was typed.
    const input = shadow.querySelector<HTMLInputElement>('[data-search]')
    input?.addEventListener('input', () => { query.current = input.value })
  }, [data, sub, filter])
  return <div ref={ref} data-testid="n8n-catalog-approved" data-sub={sub} style={{ minWidth: 0 }} />
}

export function N8nCatalogTab() {
  const api = useApi<N8nCatalogWire>(N8N_CATALOG_API, 60_000)
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const sub = resolveSub(params.get('sub'))
  const filter = params.get('verdict') ?? ''
  const onNav = (n: Nav) => {
    if (n.lane) { navigate(laneHref(n.lane)); return }
    const next = new URLSearchParams(params)
    next.set('tab', 'catalog')
    if (n.sub && n.sub !== 'overview') next.set('sub', n.sub); else next.delete('sub')
    if (n.filter) next.set('verdict', n.filter); else next.delete('verdict')
    setParams(next)
  }
  if (api.data) return <N8nCatalogApprovedView data={api.data} sub={sub} filter={sub === 'audit' ? filter : ''} onNav={onNav} />
  return <N8nCatalogView data={null} loading={api.loading} error={api.error ?? null} />
}
