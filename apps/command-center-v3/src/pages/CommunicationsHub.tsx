import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { BoardCards, FeedCard } from '../components/decision/FeedCards'
import { useApi } from '../hooks/useApi'
import { useTerminalUi } from '../lib/terminalUi'
import { hubTitle, hubSubtitle, hubTab, hubPanel, hubStrip } from '../lib/terminalHubChrome'
import { RADIUS, TOKENS } from '../lib/designTokens'
import AdminConfirmModal, { type PendingAction } from '../components/AdminConfirmModal'
import { CommsFilterModal, ItemBadges, ttlLabel, labelOf, CATEGORY_COLOR, PANEL_PRESET, REENTRY_COLOR, tint, type HubFilters } from '../components/comms/CommsHubParts'

type Tab = 'events' | 'deliveries' | 'subjects' | 'retention' | 'agents'

const MUTED = 'var(--text3)'
const TEXT = 'var(--text0)'
const TEXT2 = 'var(--text2)'
const AMBER = 'var(--amber)'
const GREEN = 'var(--green)'
const RED = 'var(--red)'
const BORDER = 'var(--border)'
const MONO = "'JetBrains Mono', ui-monospace, Consolas, monospace"

function fmtWhen(s?: string | null) {
  if (!s) return '—'
  try {
    return new Date(s).toLocaleString()
  } catch {
    return String(s)
  }
}

function shortId(id?: string | null, n = 10) {
  if (!id) return '—'
  return id.length > n + 2 ? `${id.slice(0, n)}…` : id
}

/** Delivery status → terminal color. Un-settled states read amber so a stuck
 *  RESERVED/SENDING stub (the F1 phantom-row defect) is visible, not hidden. */
function deliveryStatusColor(s?: string | null): string {
  switch (s) {
    case 'SENT':
    case 'DELIVERED':
    case 'ACKNOWLEDGED':
      return GREEN
    case 'RESERVED':
    case 'SENDING':
      return AMBER
    case 'FAILED':
    case 'BOUNCED':
    case 'EXPIRED':
    case 'CANCELLED':
      return RED
    case 'LEGACY_DELIVERED':
    case 'SUPPRESSED':
      return MUTED
    default:
      return TEXT2
  }
}

/** A subject_key like `telegram:operator_alert:⚠️ <b>…</b>` is a DB key, not a
 *  title. Prefer the event's own short_summary; if absent, strip the channel/
 *  class prefix so what remains is the message, not the key. */
function humanizeSubject(subjectKey?: string | null): string {
  if (!subjectKey) return '—'
  const raw = subjectKey.replace(/\s+/g, ' ').trim()
  if (raw.startsWith('telegram:')) {
    // telegram:<class>:<body-derived tail>
    const rest = raw.split(':').slice(2).join(':')
    if (rest) return rest.slice(0, 120)
    return raw
  }
  // domain:<key> — the domain is the legible part; keep the key on hover.
  return raw
}

function dirLabel(d?: string | null): string {
  if (!d) return '—'
  return d === 'INBOUND' ? 'IN' : 'OUT'
}

export default function CommunicationsHub() {
  const [terminalUi] = useTerminalUi()
  const [tab, setTab] = useState<Tab>('events')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [subjectFilter, setSubjectFilter] = useState('')
  const [severityFilter, setSeverityFilter] = useState('')
  const [dirFilter, setDirFilter] = useState('')
  const [textFilter, setTextFilter] = useState('')

  // Communications hub (2026-10-07): server-side filters / sort / paging; decision board; bulk actions.
  const [hubFilters, setHubFilters] = useState<HubFilters>({})
  const [sort, setSort] = useState('priority_score')
  const [order, setOrder] = useState('desc')
  const [offset, setOffset] = useState(0)
  const [filterOpen, setFilterOpen] = useState(false)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [pending, setPending] = useState<PendingAction | null>(null)
  const PAGE = 100

  const eventsPath = useMemo(() => {
    const q = new URLSearchParams({ limit: String(PAGE), hub: '1', sort, order, offset: String(offset) })
    if (subjectFilter.trim()) q.set('subject_key', subjectFilter.trim())
    for (const [k, v] of Object.entries(hubFilters)) {
      if (!v) continue
      if (k === 'within_h') q.set('since', new Date(Date.now() - Number(v) * 3600_000).toISOString())
      else q.set(k, v)
    }
    return `/api/v2/communications/events?${q.toString()}`
  }, [subjectFilter, hubFilters, sort, order, offset])
  const { data: boardPayload, refetch: refetchBoard } = useApi<any>('/api/v2/communications/board?limit=5', 60_000)

  const { data: health, loading: healthLoading } = useApi<any>('/api/v2/communications/health', 60_000)
  const { data: eventsPayload, loading: eventsLoading, error: eventsError, refetch: refetchEvents } = useApi<any>(eventsPath, 30_000)
  const { data: deliveriesPayload, loading: deliveriesLoading } = useApi<any>(
    '/api/v2/communications/deliveries?limit=500',
    60_000,
  )
  const { data: subjectsPayload, loading: subjectsLoading } = useApi<any>(
    '/api/v2/communications/subjects?limit=50',
    60_000,
  )
  const { data: agentsPayload, loading: agentsLoading } = useApi<any>(
    '/api/v2/communications/agents?limit=200',
    60_000,
  )
  const detailPath = selectedId
    ? `/api/v2/communications/events/${encodeURIComponent(selectedId)}`
    : ''
  const { data: detailPayload } = useApi<any>(detailPath || '/api/v2/communications/health', 0, {
    enabled: Boolean(selectedId),
  })

  const events: any[] = eventsPayload?.events || []
  const hubMode = eventsPayload?.hub === true
  const board = boardPayload?.data ?? boardPayload
  const applyPreset = (preset: Record<string, string>) => {
    const { sort: so, order: or, ...rest } = preset
    setHubFilters(rest); setSort(so || 'priority_score'); setOrder(or || 'desc'); setOffset(0); setPicked(new Set())
  }
  // ?preset=attention|reward|reentry|risk|expiring|recent — Home "Review now" lands on the matching view.
  const [sp] = useSearchParams()
  const presetParam = sp.get('preset')
  // ?event=<id> opens one message; ?q=<ticker or text> filters the feed (advice-digest links, 2026-10-08).
  const eventParam = sp.get('event')
  const qParam = sp.get('q')
  useEffect(() => { if (eventParam) setSelectedId(eventParam) }, [eventParam])
  useEffect(() => {
    if (qParam) { setHubFilters((p) => ({ ...p, q: qParam })); setOffset(0) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qParam])
  useEffect(() => {
    if (presetParam && PANEL_PRESET[presetParam]) applyPreset(PANEL_PRESET[presetParam])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presetParam])
  const bulk = (action: string, extra: Record<string, any> = {}, label?: string) => {
    if (!picked.size) return
    setPending({ path: '/api/v2/communications/events/bulk', body: { event_ids: Array.from(picked), action, ...extra },
      label: label || `${labelOf(action)} ${picked.size} message(s)` })
  }
  const deliveries: any[] = deliveriesPayload?.deliveries || []
  const subjects: any[] = subjectsPayload?.subjects || []
  const agentSubscriptions: any[] = agentsPayload?.subscriptions || []
  const agentReceipts: any[] = agentsPayload?.receipts || []
  const detail = detailPayload?.event ?? null
  const mode = health?.mode || 'OFF'
  const source = eventsPayload?.source || health?.ledger?.source || 'empty'
  const deliveryOwned = health?.delivery_owned === true
  const ownedClasses = health?.owned_classes || []

  // P0 — delivery settlement health. A RESERVED/SENDING row with no settlement
  // is the signature of the F1 phantom-row defect; surface the count, don't
  // bury it in a table the operator has to read row-by-row.
  const deliveryHealth = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const d of deliveries) {
      const s = d.status || 'UNKNOWN'
      counts[s] = (counts[s] || 0) + 1
    }
    const unsettled = (counts.RESERVED || 0) + (counts.SENDING || 0)
    const failed = (counts.FAILED || 0) + (counts.BOUNCED || 0) + (counts.EXPIRED || 0)
    return { counts, unsettled, failed }
  }, [deliveries])

  // P2 — retention rollup from the visible window, by class × knowledge status.
  const retentionCounts = useMemo(() => {
    const byClass: Record<string, number> = {}
    const byKnowledge: Record<string, number> = {}
    for (const e of events) {
      const rc = e.retention_class || 'unknown'
      byClass[rc] = (byClass[rc] || 0) + 1
      const ks = e.knowledge_status || 'none'
      byKnowledge[ks] = (byKnowledge[ks] || 0) + 1
    }
    return { byClass, byKnowledge }
  }, [events])

  // P2 — client-side filters (server already handles subject_key; severity /
  // direction / free-text are applied over the loaded window).
  const visibleEvents = useMemo(() => {
    let rows = events
    if (severityFilter) rows = rows.filter((e) => (e.severity || '') === severityFilter)
    if (dirFilter) rows = rows.filter((e) => e.direction === dirFilter)
    if (textFilter.trim()) {
      const q = textFilter.trim().toLowerCase()
      rows = rows.filter((e) =>
        [e.short_summary, e.subject_key, e.incident_id, e.correlation_id, e.producer]
          .filter(Boolean)
          .some((v: string) => String(v).toLowerCase().includes(q)),
      )
    }
    return rows
  }, [events, severityFilter, dirFilter, textFilter])

  return (
    <div style={{ maxWidth: 1280 }}>
      <div className="hub-title-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={hubTitle()}>Communications</div>
          <div style={hubSubtitle(terminalUi)}>
            CommunicationEvent ledger · ChannelDelivery · subject threads
            {healthLoading ? '' : <> · mode <span style={{ color: AMBER }}>{mode}</span></>}
            <> · source <span style={{ color: TEXT }}>{source}</span></>
          </div>
        </div>
        <div className="hub-tabs" style={{ display: 'flex', gap: terminalUi ? 4 : 6, flexWrap: 'wrap' }}>
          {(
            [
              ['events', 'Live / Events'],
              ['deliveries', 'Deliveries'],
              ['subjects', 'Subjects / Threads'],
              ['retention', 'Retention'],
              ['agents', 'Agent consumption'],
            ] as const
          ).map(([id, label]) => (
            <button key={id} type="button" onClick={() => setTab(id)} style={hubTab(tab === id, terminalUi)}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* P0 — delivery health strip: ownership + un-settled/failed counts are the
          operator's "is anything not reaching me?" signal. */}
      <div
        className="cc-panel"
        style={{
          ...hubStrip(terminalUi),
          marginTop: 12,
          marginBottom: 14,
          borderColor: deliveryOwned ? GREEN : AMBER,
          color: TEXT,
          fontWeight: 700,
          display: 'flex',
          flexWrap: 'wrap',
          gap: 14,
          alignItems: 'baseline',
        }}
        role="status"
      >
        <span>
          {deliveryOwned
            ? `gateway owns Telegram: ${ownedClasses.join(', ') || '(none)'}`
            : 'gateway does not own delivery while OFF/SHADOW'}
        </span>
        <span style={{ color: MUTED, fontWeight: 600 }}>
          deliveries {deliveries.length} · un-settled{' '}
          <span style={{ color: deliveryHealth.unsettled > 0 ? AMBER : TEXT2, fontWeight: 800 }}>
            {deliveryHealth.unsettled}
          </span>{' '}
          · failed{' '}
          <span style={{ color: deliveryHealth.failed > 0 ? RED : TEXT2, fontWeight: 800 }}>
            {deliveryHealth.failed}
          </span>
          {deliveriesLoading ? ' · loading…' : ''}
        </span>
        {!deliveryOwned && (
          <span style={{ color: MUTED, fontWeight: 600 }}>· delivery_owned=false · mode={mode}</span>
        )}
      </div>

      <AdminConfirmModal action={pending} onClose={() => setPending(null)} onDone={() => { setPicked(new Set()); refetchEvents?.(); refetchBoard?.() }} />
      <CommsFilterModal open={filterOpen} initial={hubFilters} meta={eventsPayload} onApply={(f) => { setHubFilters(f); setOffset(0) }} onClose={() => setFilterOpen(false)} />

      {tab === 'events' && hubMode && (
        <div>
          <BoardCards board={board} onPick={applyPreset} />
          <div className="cc-panel" style={hubPanel(terminalUi)}>
            {/* Re-entry focus + category chips + sort + filters */}
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
              <span style={{ fontSize: 10, color: TOKENS.success, fontWeight: 800 }}>RE-ENTRY</span>
              {['confirmed', 'opportunity', 'potential', 'expired', 'invalidated'].map((r) => {
                const on = hubFilters.reentry_status === r
                const n = eventsPayload?.facets?.reentry_status?.[r]
                return (
                  <button key={r} type="button" onClick={() => applyPreset(on ? {} : { category: 're_entry', reentry_status: r, sort: 'priority_score' })}
                    style={{ fontSize: 10, padding: '2px 7px', borderRadius: RADIUS.sm, cursor: 'pointer', border: `1px solid ${REENTRY_COLOR[r]}`, background: on ? tint(REENTRY_COLOR[r], 20) : 'transparent', color: TEXT }}>
                    {labelOf(r)}{n != null ? ` · ${n}` : ''}
                  </button>
                )
              })}
            </div>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
              {(eventsPayload?.categories || []).map((c: any) => {
                const on = (hubFilters.category || '') === c.id
                const n = eventsPayload?.facets?.category?.[c.id] || 0
                return (
                  <button key={c.id} type="button" onClick={() => { setHubFilters((p) => { const x = { ...p }; if (on) delete x.category; else x.category = c.id; return x }); setOffset(0) }}
                    style={{ fontSize: 10, padding: '2px 7px', borderRadius: RADIUS.sm, cursor: 'pointer', border: `1px solid ${on ? CATEGORY_COLOR[c.id] || BORDER : BORDER}`, background: on ? tint(CATEGORY_COLOR[c.id] || 'var(--info-color)', 20) : 'transparent', color: n ? TEXT : MUTED }}
                    title={`TTL ${c.ttl_hours}h`}>
                    {c.label} · {n}
                  </button>
                )
              })}
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
              <span style={{ fontSize: 10, color: MUTED, fontWeight: 800, letterSpacing: '.06em', textTransform: 'uppercase' }}>
                Feed ({eventsPayload?.total ?? 0})
              </span>
              <input value={hubFilters.q || ''} onChange={(e) => { const v = e.target.value; setHubFilters((p) => { const x = { ...p }; if (v) x.q = v; else delete x.q; return x }); setOffset(0) }}
                placeholder="Search messages, symbols, sources" style={{ fontSize: 10, padding: '3px 8px', background: 'var(--bg1)', border: `1px solid ${BORDER}`, borderRadius: RADIUS.sm, color: TEXT, minWidth: 220 }} />
              <button type="button" onClick={() => setFilterOpen(true)} style={{ fontSize: 10, padding: '3px 10px', border: `1px solid ${TOKENS.info}`, background: tint(TOKENS.info), color: TEXT, cursor: 'pointer', fontWeight: 700 }}>
                Filters{Object.keys(hubFilters).length ? ` (${Object.keys(hubFilters).length})` : ''}
              </button>
              {Object.keys(hubFilters).length > 0 && (
                <button type="button" onClick={() => applyPreset({})} style={{ fontSize: 10, padding: '3px 8px', border: `1px solid ${BORDER}`, background: 'transparent', color: MUTED, cursor: 'pointer' }}>Clear</button>
              )}
              <span style={{ fontSize: 10, color: MUTED }}>sort</span>
              <select value={sort} onChange={(e) => { setSort(e.target.value); setOffset(0) }} style={{ fontSize: 10, padding: '3px 6px', background: 'var(--bg1)', border: `1px solid ${BORDER}`, color: TEXT }}>
                {[['priority_score', 'Priority score'], ['confidence', 'Confidence'], ['risk_score', 'Risk'], ['reward_score', 'Reward'], ['time_sensitivity', 'Time sensitivity'], ['expires_at', 'Expiry'], ['actionable_since', 'Became actionable'], ['created_at', 'Newest']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              <button type="button" onClick={() => setOrder((o) => (o === 'desc' ? 'asc' : 'desc'))} style={{ fontSize: 10, padding: '3px 6px', border: `1px solid ${BORDER}`, background: 'transparent', color: TEXT2, cursor: 'pointer' }}>{order === 'desc' ? '↓' : '↑'}</button>
              {eventsLoading && <span style={{ color: MUTED, fontSize: 10 }}>Loading…</span>}
              {eventsError && <span style={{ color: RED, fontSize: 10 }}>{eventsError}</span>}
            </div>
            {picked.size > 0 && (
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8, fontSize: 10 }}>
                <b style={{ color: TEXT }}>{picked.size} selected</b>
                {[['acknowledge', {}, 'Acknowledge'], ['retain', { retain_hours: 24 }, 'Keep +24h'], ['retain', { retain_hours: 168 }, 'Keep +7d'], ['retain', {}, 'Keep (no expiry)'], ['release', {}, 'Release hold'], ['expire', {}, 'Expire now']].map(([a, x, l]: any) => (
                  <button key={l} type="button" onClick={() => bulk(a, x, `${l}: ${picked.size} message(s)`)} style={{ fontSize: 10, padding: '2px 8px', border: `1px solid ${BORDER}`, background: 'transparent', color: TEXT, cursor: 'pointer' }}>{l}</button>
                ))}
                <button type="button" onClick={() => setPicked(new Set())} style={{ fontSize: 10, padding: '2px 8px', border: 'none', background: 'transparent', color: MUTED, cursor: 'pointer' }}>clear</button>
              </div>
            )}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, fontSize: 10, color: MUTED }}>
              <input type="checkbox" checked={events.length > 0 && events.every((e) => picked.has(e.event_id))}
                onChange={(ev) => setPicked(ev.target.checked ? new Set(events.map((e) => e.event_id)) : new Set())} aria-label="select all" />
              select all on this page · click a card for the full message, scores and source
            </div>
            <div data-testid="comms-feed-cards" style={{ display: 'grid', gap: 6 }}>
              {events.length === 0 && !eventsLoading && <div style={{ padding: 12, color: MUTED }}>Nothing matches these filters.</div>}
              {events.map((e) => (
                <FeedCard key={e.event_id} e={e} selected={e.event_id === selectedId} picked={picked.has(e.event_id)}
                  onPick={() => setPicked((p) => { const n = new Set(p); if (n.has(e.event_id)) n.delete(e.event_id); else n.add(e.event_id); return n })}
                  onOpen={() => setSelectedId(e.event_id)} />
              ))}
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'flex-end', marginTop: 8, fontSize: 10, color: MUTED }}>
              <span>{eventsPayload?.total ? `${offset + 1}–${Math.min(offset + PAGE, eventsPayload.total)} of ${eventsPayload.total}` : ''}</span>
              <button type="button" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - PAGE))} style={{ fontSize: 10, padding: '2px 8px', border: `1px solid ${BORDER}`, background: 'transparent', color: TEXT2, cursor: 'pointer' }}>Prev</button>
              <button type="button" disabled={!eventsPayload?.total || offset + PAGE >= eventsPayload.total} onClick={() => setOffset((o) => o + PAGE)} style={{ fontSize: 10, padding: '2px 8px', border: `1px solid ${BORDER}`, background: 'transparent', color: TEXT2, cursor: 'pointer' }}>Next</button>
            </div>
          </div>
        </div>
      )}

      {tab === 'events' && hubMode && selectedId && (() => {
        const e = events.find((x) => x.event_id === selectedId)
          || Object.values(board?.panels || {}).flatMap((p: any) => p.items || []).find((x: any) => x.event_id === selectedId)
          || detail
        return (
          <div onClick={() => setSelectedId(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.45)', zIndex: 900 }}>
            <div onClick={(ev) => ev.stopPropagation()} style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: 520, maxWidth: '96vw', background: 'var(--bg1)', borderLeft: `1px solid ${BORDER}`, padding: 16, overflowY: 'auto' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <b style={{ color: TEXT, fontSize: 12 }}>{e?.headline || e?.short_summary || shortId(selectedId)}</b>
                <button type="button" onClick={() => setSelectedId(null)} style={{ fontSize: 10, border: `1px solid ${BORDER}`, background: 'transparent', color: MUTED, cursor: 'pointer', padding: '2px 6px' }}>Close</button>
              </div>
              {e && (
                <>
                  <div style={{ marginBottom: 8 }}><ItemBadges e={e} /></div>
                  <div style={{ fontSize: 10, color: TEXT2, lineHeight: 1.6, marginBottom: 10 }}>
                    {[
                      ['Symbols', (e.symbols || []).join(', ') || '—'],
                      ['Priority score', e.priority_score ?? '—'],
                      ['Confidence · Risk · Reward · Time', [e.confidence, e.risk_score, e.reward_score, e.time_sensitivity].map((v: any) => (v == null ? '—' : Number(v).toFixed(2))).join(' · ')],
                      ['Status', e.lifecycle_status || '—'],
                      ['TTL', `${ttlLabel(e.ttl_remaining_s, e.legal_hold)} · expires ${fmtWhen(e.expires_at)}`],
                      ['Actionable', e.actionable ? `yes — ${e.action_hint || ''} (since ${fmtWhen(e.actionable_since)})` : 'no'],
                      ['Source', e.producer || '—'],
                      ['Created', fmtWhen(e.created_at)],
                      ['Rule', e.classified_by || '—'],
                    ].map(([k, v]) => (
                      <div key={String(k)}><span style={{ color: MUTED }}>{k}: </span><span style={{ color: TEXT }}>{String(v)}</span></div>
                    ))}
                  </div>
                  <pre style={{ fontSize: 10, color: TEXT, whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'var(--bg0, transparent)', border: `1px solid ${BORDER}`, padding: 8, borderRadius: RADIUS.sm, fontFamily: MONO }}>
                    {e.sanitized_body || e.short_summary || ''}
                  </pre>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
                    {[['acknowledge', {}, 'Acknowledge'], ['retain', { retain_hours: 168 }, 'Keep +7d'], ['retain', {}, 'Keep (no expiry)'], ['expire', {}, 'Expire now']].map(([a, x, l]: any) => (
                      <button key={l} type="button" onClick={() => setPending({ path: '/api/v2/communications/events/bulk', body: { event_ids: [selectedId], action: a, ...x }, label: `${l}: 1 message` })}
                        style={{ fontSize: 10, padding: '2px 8px', border: `1px solid ${BORDER}`, background: 'transparent', color: TEXT, cursor: 'pointer' }}>{l}</button>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        )
      })()}

      {tab === 'events' && !hubMode && (
        <div style={{ display: 'grid', gridTemplateColumns: selectedId ? '1fr 360px' : '1fr', gap: 12 }}>
          <div className="cc-panel" style={hubPanel(terminalUi)}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 10, color: MUTED, fontWeight: 800, letterSpacing: '.06em', textTransform: 'uppercase' }}>
                Events ({visibleEvents.length})
              </span>
              <input
                value={textFilter}
                onChange={(e) => setTextFilter(e.target.value)}
                placeholder="Search summary / subject / incident"
                style={{ fontSize: 10, padding: '3px 8px', background: 'var(--bg1)', border: `1px solid ${BORDER}`, borderRadius: RADIUS.sm, color: TEXT, minWidth: 200 }}
              />
              <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)} style={{ fontSize: 10, padding: '3px 6px', background: 'var(--bg1)', border: `1px solid ${BORDER}`, borderRadius: RADIUS.sm, color: TEXT }}>
                <option value="">severity: all</option>
                <option value="info">info</option>
                <option value="warning">warning</option>
                <option value="critical">critical</option>
              </select>
              <select value={dirFilter} onChange={(e) => setDirFilter(e.target.value)} style={{ fontSize: 10, padding: '3px 6px', background: 'var(--bg1)', border: `1px solid ${BORDER}`, borderRadius: RADIUS.sm, color: TEXT }}>
                <option value="">direction: all</option>
                <option value="INBOUND">INBOUND</option>
                <option value="OUTBOUND">OUTBOUND</option>
              </select>
              <input
                value={subjectFilter}
                onChange={(e) => setSubjectFilter(e.target.value)}
                placeholder="Filter subject_key (server)"
                style={{ fontSize: 10, padding: '3px 8px', background: 'var(--bg1)', border: `1px solid ${BORDER}`, borderRadius: RADIUS.sm, color: TEXT, minWidth: 160 }}
              />
              {eventsError && <span style={{ color: RED, fontSize: 10 }}>{eventsError}</span>}
              {eventsLoading && <span style={{ color: MUTED, fontSize: 10 }}>Loading…</span>}
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                <thead>
                  <tr style={{ color: MUTED, textAlign: 'left' }}>
                    <th style={{ padding: '4px 6px' }}>dir</th>
                    <th style={{ padding: '4px 6px' }}>message</th>
                    <th style={{ padding: '4px 6px' }}>class</th>
                    <th style={{ padding: '4px 6px' }}>severity</th>
                    <th style={{ padding: '4px 6px' }}>producer</th>
                    <th style={{ padding: '4px 6px' }}>when</th>
                    <th style={{ padding: '4px 6px' }}>curation</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleEvents.length === 0 && !eventsLoading && (
                    <tr>
                      <td colSpan={7} style={{ padding: 12, color: MUTED }}>
                        No ledger events ({source}). Portal never scrapes providers.
                      </td>
                    </tr>
                  )}
                  {visibleEvents.map((e) => {
                    const active = e.event_id === selectedId
                    const headline = e.short_summary || humanizeSubject(e.subject_key) || '—'
                    return (
                      <tr
                        key={e.event_id}
                        onClick={() => setSelectedId(e.event_id)}
                        style={{ cursor: 'pointer', background: active ? 'rgba(245,158,11,0.12)' : 'transparent', borderTop: `1px solid ${BORDER}`, verticalAlign: 'top' }}
                      >
                        <td style={{ padding: '5px 6px', color: e.direction === 'INBOUND' ? AMBER : MUTED, fontWeight: 800, fontFamily: MONO }}>{dirLabel(e.direction)}</td>
                        <td style={{ padding: '5px 6px', color: TEXT, maxWidth: 360 }}>
                          <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={e.sanitized_body || e.subject_key || ''}>{headline}</div>
                          <div style={{ color: MUTED, fontFamily: MONO }} title={e.subject_key}>{shortId(e.event_id)}</div>
                        </td>
                        <td style={{ padding: '5px 6px', color: TEXT2 }}>{e.message_class || '—'}</td>
                        <td style={{ padding: '5px 6px' }}>{e.severity || '—'}</td>
                        <td style={{ padding: '5px 6px', color: MUTED }}>{e.producer || '—'}</td>
                        <td style={{ padding: '5px 6px', color: MUTED }}>{fmtWhen(e.created_at)}</td>
                        <td style={{ padding: '5px 6px' }}>{e.curation_mode || '—'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {selectedId && (
            <div className="cc-panel" style={{ ...hubPanel(terminalUi), position: 'sticky', top: 8, alignSelf: 'start' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <span style={{ fontSize: 10, fontWeight: 800, color: MUTED, letterSpacing: '.06em', textTransform: 'uppercase' }}>
                  Event detail
                </span>
                <button type="button" onClick={() => setSelectedId(null)} style={{ fontSize: 10, border: `1px solid ${BORDER}`, background: 'transparent', color: MUTED, cursor: 'pointer', padding: '2px 6px' }}>
                  Close
                </button>
              </div>
              {!detail ? (
                <div style={{ color: MUTED, fontSize: 10 }}>Loading {shortId(selectedId)}…</div>
              ) : (
                <div style={{ fontSize: 10, lineHeight: 1.55 }}>
                  {detail.short_summary && (
                    <div style={{ color: TEXT, fontWeight: 700, marginBottom: 8, wordBreak: 'break-word' }}>{detail.short_summary}</div>
                  )}
                  {detail.sanitized_body && (
                    <div style={{ color: TEXT2, marginBottom: 8, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{detail.sanitized_body}</div>
                  )}
                  <dl style={{ margin: 0 }}>
                    {(
                      [
                        ['event_id', detail.event_id],
                        ['direction', detail.direction],
                        ['type', detail.event_type || detail.type],
                        ['message_class', detail.message_class],
                        ['subject_key', detail.subject_key],
                        ['severity', detail.severity],
                        ['producer', detail.producer],
                        ['incident_id', detail.incident_id],
                        ['correlation_id', detail.correlation_id],
                        ['curation_mode', detail.curation_mode],
                        ['retention_class', detail.retention_class],
                        ['knowledge_status', detail.knowledge_status],
                        ['knowledge_eligibility', detail.knowledge_eligibility],
                        ['created_at', fmtWhen(detail.created_at)],
                        ['source', detail.source],
                      ] as [string, any][]
                    ).map(([k, v]) => (
                      <div key={k} style={{ display: 'grid', gridTemplateColumns: '130px 1fr', gap: 6, borderBottom: `1px solid ${BORDER}`, padding: '4px 0' }}>
                        <dt style={{ color: MUTED }}>{k}</dt>
                        <dd style={{ margin: 0, color: TEXT, wordBreak: 'break-word', fontFamily: k.endsWith('_id') ? MONO : 'inherit' }}>{v == null || v === '' ? '—' : String(v)}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {tab === 'deliveries' && (
        <div className="cc-panel" style={hubPanel(terminalUi)}>
          <div style={{ fontSize: 10, color: MUTED, fontWeight: 800, marginBottom: 10, letterSpacing: '.06em', textTransform: 'uppercase' }}>
            Deliveries ({deliveries.length}){deliveriesLoading ? ' · loading…' : ''} · source {deliveriesPayload?.source || '—'} ·{' '}
            <span style={{ color: AMBER }}>un-settled {deliveryHealth.unsettled}</span> ·{' '}
            <span style={{ color: RED }}>failed {deliveryHealth.failed}</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
              <thead>
                <tr style={{ color: MUTED, textAlign: 'left' }}>
                  <th style={{ padding: '4px 6px' }}>status</th>
                  <th style={{ padding: '4px 6px' }}>event_id</th>
                  <th style={{ padding: '4px 6px' }}>channel</th>
                  <th style={{ padding: '4px 6px' }}>provider msg id</th>
                  <th style={{ padding: '4px 6px' }}>reserved</th>
                  <th style={{ padding: '4px 6px' }}>sent / completed</th>
                </tr>
              </thead>
              <tbody>
                {deliveries.length === 0 && !deliveriesLoading && (
                  <tr>
                    <td colSpan={6} style={{ padding: 12, color: MUTED }}>
                      No delivery rows (RESERVED stubs appear after publish).
                    </td>
                  </tr>
                )}
                {deliveries.map((d) => (
                  <tr key={d.delivery_id || `${d.event_id}-${d.channel}`} style={{ borderTop: `1px solid ${BORDER}` }}>
                    <td style={{ padding: '5px 6px', color: deliveryStatusColor(d.status), fontWeight: 800 }}>{d.status || '—'}</td>
                    <td style={{ padding: '5px 6px', fontFamily: MONO, cursor: 'pointer', color: AMBER }} onClick={() => { setSelectedId(d.event_id); setTab('events') }} title={d.event_id}>{shortId(d.event_id)}</td>
                    <td style={{ padding: '5px 6px' }}>{d.channel || '—'}</td>
                    <td style={{ padding: '5px 6px', fontFamily: MONO, color: d.provider_message_id ? TEXT : MUTED }} title={d.provider_message_id || undefined}>{d.provider_message_id ? shortId(d.provider_message_id, 14) : '—'}</td>
                    <td style={{ padding: '5px 6px', color: MUTED }}>{fmtWhen(d.reserved_at)}</td>
                    <td style={{ padding: '5px 6px', color: MUTED }}>
                      {d.sent_at ? fmtWhen(d.sent_at) : '—'}
                      {d.completed_at && d.completed_at !== d.sent_at ? ` / ${fmtWhen(d.completed_at)}` : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === 'subjects' && (
        <div className="cc-panel" style={hubPanel(terminalUi)}>
          <div style={{ fontSize: 10, color: MUTED, fontWeight: 800, marginBottom: 10, letterSpacing: '.06em', textTransform: 'uppercase' }}>
            Subjects / Threads ({subjects.length}){subjectsLoading ? ' · loading…' : ''} · source {subjectsPayload?.source || '—'}
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
              <thead>
                <tr style={{ color: MUTED, textAlign: 'left' }}>
                  <th style={{ padding: '4px 6px' }}>subject</th>
                  <th style={{ padding: '4px 6px' }}>domain</th>
                  <th style={{ padding: '4px 6px' }}>events</th>
                  <th style={{ padding: '4px 6px' }}>last activity</th>
                </tr>
              </thead>
              <tbody>
                {subjects.length === 0 && !subjectsLoading && (
                  <tr>
                    <td colSpan={4} style={{ padding: 12, color: MUTED }}>No subjects yet.</td>
                  </tr>
                )}
                {subjects.map((s) => (
                  <tr key={s.subject_key} style={{ borderTop: `1px solid ${BORDER}`, cursor: 'pointer' }} onClick={() => { setSubjectFilter(s.subject_key || ''); setTab('events') }}>
                    <td style={{ padding: '5px 6px', color: TEXT }} title={s.subject_key}>{humanizeSubject(s.subject_key)}</td>
                    <td style={{ padding: '5px 6px', color: MUTED }}>{s.domain || '—'}</td>
                    <td style={{ padding: '5px 6px' }}>{s.event_count ?? '—'}</td>
                    <td style={{ padding: '5px 6px', color: MUTED }}>{fmtWhen(s.last_activity_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === 'retention' && (
        <div className="cc-panel" style={hubPanel(terminalUi)}>
          <div style={{ fontSize: 10, fontWeight: 800, color: MUTED, letterSpacing: '.06em', textTransform: 'uppercase', marginBottom: 8 }}>
            Retention · TTL by category
          </div>
          <p style={{ fontSize: 10, color: MUTED, marginTop: 0, lineHeight: 1.5 }}>
            Every message has a TTL by category (config/comms_categories.yaml). When it runs out the message leaves every
            active view; it stays under the "include expired" filter for the grace period, then the hourly lifecycle pass
            (scripts/comms_lifecycle.py) archives it to jsonl.gz and removes it. A newer message on the same symbol or topic
            supersedes older ones. Use "Keep" in the feed to hold a message past its TTL.
          </p>
          {hubMode && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))', gap: 8, marginBottom: 12 }}>
              {(eventsPayload?.categories || []).map((c: any) => (
                <div key={c.id} style={{ border: `1px solid ${BORDER}`, borderLeft: `3px solid ${CATEGORY_COLOR[c.id] || BORDER}`, padding: 6, fontSize: 10 }}>
                  <div style={{ color: TEXT, fontWeight: 700 }}>{c.label}</div>
                  <div style={{ color: MUTED }}>TTL {c.ttl_hours >= 48 ? `${c.ttl_hours / 24}d` : `${c.ttl_hours}h`}</div>
                </div>
              ))}
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 8, marginBottom: 12 }}>
            {Object.keys(retentionCounts.byClass).length === 0 && (
              <div style={{ fontSize: 10, color: MUTED }}>No events in current projection.</div>
            )}
            {Object.entries(retentionCounts.byClass).map(([k, n]) => (
              <div key={k} style={{ padding: 10, border: `1px solid ${BORDER}`, borderRadius: RADIUS.sm }}>
                <div style={{ fontSize: 10, color: MUTED, textTransform: 'uppercase', fontWeight: 800 }}>retention · {k}</div>
                <div style={{ fontSize: 18, fontWeight: 900, color: TEXT, marginTop: 4 }}>{n}</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 10, color: MUTED, fontWeight: 800, marginBottom: 6, letterSpacing: '.06em', textTransform: 'uppercase' }}>
            Knowledge status (a Hermes hypothesis is not a verified fact)
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(120px,1fr))', gap: 8 }}>
            {Object.entries(retentionCounts.byKnowledge).map(([k, n]) => (
              <div key={k} style={{ padding: 10, border: `1px solid ${BORDER}`, borderRadius: RADIUS.sm }}>
                <div style={{ fontSize: 10, color: MUTED, textTransform: 'uppercase', fontWeight: 800 }}>{k}</div>
                <div style={{ fontSize: 18, fontWeight: 900, color: k === 'accepted' ? GREEN : TEXT, marginTop: 4 }}>{n}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'agents' && (
        <div className="cc-panel" style={hubPanel(terminalUi)}>
          <div style={{ fontSize: 10, fontWeight: 800, color: MUTED, letterSpacing: '.06em', textTransform: 'uppercase', marginBottom: 10 }}>
            Agent consumption · {agentReceipts.length} receipts · {agentSubscriptions.length} subscriptions{agentsLoading ? ' · loading…' : ''} · source {agentsPayload?.source || '—'}
          </div>

          <div style={{ fontSize: 10, color: MUTED, fontWeight: 800, marginBottom: 6, letterSpacing: '.06em', textTransform: 'uppercase' }}>
            Consumption receipts (what each agent read + what it derived)
          </div>
          {agentReceipts.length === 0 && !agentsLoading ? (
            <p style={{ fontSize: 10, color: MUTED, margin: '0 0 12px', lineHeight: 1.5 }}>
              No consumption receipts recorded yet. CIO/Advisory/Hermes emit a receipt when they read a
              policy-eligible event — until then this is empty by design, not a failure.
            </p>
          ) : (
            <div style={{ overflowX: 'auto', marginBottom: 14 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                <thead>
                  <tr style={{ color: MUTED, textAlign: 'left' }}>
                    <th style={{ padding: '4px 6px' }}>agent</th>
                    <th style={{ padding: '4px 6px' }}>version</th>
                    <th style={{ padding: '4px 6px' }}>event_id</th>
                    <th style={{ padding: '4px 6px' }}>purpose</th>
                    <th style={{ padding: '4px 6px' }}>derived</th>
                    <th style={{ padding: '4px 6px' }}>influence</th>
                    <th style={{ padding: '4px 6px' }}>retrieved</th>
                  </tr>
                </thead>
                <tbody>
                  {agentReceipts.map((r) => (
                    <tr key={r.receipt_id} style={{ borderTop: `1px solid ${BORDER}`, verticalAlign: 'top' }}>
                      <td style={{ padding: '5px 6px', color: TEXT, fontWeight: 800 }}>{r.agent_id || '—'}</td>
                      <td style={{ padding: '5px 6px', color: MUTED, fontFamily: MONO }}>{r.agent_version || '—'}</td>
                      <td style={{ padding: '5px 6px', fontFamily: MONO, cursor: 'pointer', color: AMBER }} onClick={() => { setSelectedId(r.event_id); setTab('events') }} title={r.event_id}>{shortId(r.event_id)}</td>
                      <td style={{ padding: '5px 6px', color: TEXT2 }}>{r.purpose || '—'}</td>
                      <td style={{ padding: '5px 6px', color: MUTED }}>{(r.derived_artifact_ids || []).length || '—'}</td>
                      <td style={{ padding: '5px 6px', color: MUTED, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.influence_declaration || undefined}>{r.influence_declaration || '—'}</td>
                      <td style={{ padding: '5px 6px', color: MUTED }}>{fmtWhen(r.retrieved_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div style={{ fontSize: 10, color: MUTED, fontWeight: 800, marginBottom: 6, letterSpacing: '.06em', textTransform: 'uppercase' }}>
            Subscriptions
          </div>
          {agentSubscriptions.length === 0 ? (
            <p style={{ fontSize: 10, color: MUTED, margin: 0, lineHeight: 1.5 }}>
              No agent subscriptions registered. Agents subscribe to message-class / severity / subject-domain
              scopes; a receipt requires a matching enabled subscription.
            </p>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                <thead>
                  <tr style={{ color: MUTED, textAlign: 'left' }}>
                    <th style={{ padding: '4px 6px' }}>agent</th>
                    <th style={{ padding: '4px 6px' }}>version</th>
                    <th style={{ padding: '4px 6px' }}>filter</th>
                    <th style={{ padding: '4px 6px' }}>enabled</th>
                  </tr>
                </thead>
                <tbody>
                  {agentSubscriptions.map((s) => (
                    <tr key={s.subscription_id} style={{ borderTop: `1px solid ${BORDER}` }}>
                      <td style={{ padding: '5px 6px', color: TEXT, fontWeight: 800 }}>{s.agent_id || '—'}</td>
                      <td style={{ padding: '5px 6px', color: MUTED, fontFamily: MONO }}>{s.agent_version || '—'}</td>
                      <td style={{ padding: '5px 6px', color: MUTED, fontFamily: MONO, maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={JSON.stringify(s.filter || {})}>{JSON.stringify(s.filter || {})}</td>
                      <td style={{ padding: '5px 6px', color: s.enabled === false ? MUTED : GREEN, fontWeight: 800 }}>{s.enabled === false ? 'off' : 'on'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
