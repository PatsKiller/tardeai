import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { useTerminalUi } from '../lib/terminalUi'
import { hubTitle, hubSubtitle, hubTab, hubPanel, hubStrip } from '../lib/terminalHubChrome'

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

  const eventsPath = useMemo(() => {
    const q = new URLSearchParams({ limit: '250' })
    if (subjectFilter.trim()) q.set('subject_key', subjectFilter.trim())
    return `/api/v2/communications/events?${q.toString()}`
  }, [subjectFilter])

  const { data: health, loading: healthLoading } = useApi<any>('/api/v2/communications/health', 60_000)
  const { data: eventsPayload, loading: eventsLoading, error: eventsError } = useApi<any>(eventsPath, 30_000)
  const { data: deliveriesPayload, loading: deliveriesLoading } = useApi<any>(
    '/api/v2/communications/deliveries?limit=500',
    60_000,
  )
  const { data: subjectsPayload, loading: subjectsLoading } = useApi<any>(
    '/api/v2/communications/subjects?limit=50',
    60_000,
  )
  const detailPath = selectedId
    ? `/api/v2/communications/events/${encodeURIComponent(selectedId)}`
    : ''
  const { data: detailPayload } = useApi<any>(detailPath || '/api/v2/communications/health', 0, {
    enabled: Boolean(selectedId),
  })

  const events: any[] = eventsPayload?.events || []
  const deliveries: any[] = deliveriesPayload?.deliveries || []
  const subjects: any[] = subjectsPayload?.subjects || []
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

      {tab === 'events' && (
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
                style={{ fontSize: 10, padding: '3px 8px', background: 'var(--bg1)', border: `1px solid ${BORDER}`, borderRadius: 2, color: TEXT, minWidth: 200 }}
              />
              <select value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)} style={{ fontSize: 10, padding: '3px 6px', background: 'var(--bg1)', border: `1px solid ${BORDER}`, borderRadius: 2, color: TEXT }}>
                <option value="">severity: all</option>
                <option value="info">info</option>
                <option value="warning">warning</option>
                <option value="critical">critical</option>
              </select>
              <select value={dirFilter} onChange={(e) => setDirFilter(e.target.value)} style={{ fontSize: 10, padding: '3px 6px', background: 'var(--bg1)', border: `1px solid ${BORDER}`, borderRadius: 2, color: TEXT }}>
                <option value="">direction: all</option>
                <option value="INBOUND">INBOUND</option>
                <option value="OUTBOUND">OUTBOUND</option>
              </select>
              <input
                value={subjectFilter}
                onChange={(e) => setSubjectFilter(e.target.value)}
                placeholder="Filter subject_key (server)"
                style={{ fontSize: 10, padding: '3px 8px', background: 'var(--bg1)', border: `1px solid ${BORDER}`, borderRadius: 2, color: TEXT, minWidth: 160 }}
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
            Retention (read-only — no purge from this UI)
          </div>
          <p style={{ fontSize: 10, color: MUTED, marginTop: 0, lineHeight: 1.5 }}>
            Librarian expiry is not scheduled in production yet; this tab shows retention_class and knowledge-status
            rollups over the loaded window. Expiry is not deletion — a knowledge-gated event is governed separately.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 8, marginBottom: 12 }}>
            {Object.keys(retentionCounts.byClass).length === 0 && (
              <div style={{ fontSize: 10, color: MUTED }}>No events in current projection.</div>
            )}
            {Object.entries(retentionCounts.byClass).map(([k, n]) => (
              <div key={k} style={{ padding: 10, border: `1px solid ${BORDER}`, borderRadius: 2 }}>
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
              <div key={k} style={{ padding: 10, border: `1px solid ${BORDER}`, borderRadius: 2 }}>
                <div style={{ fontSize: 10, color: MUTED, textTransform: 'uppercase', fontWeight: 800 }}>{k}</div>
                <div style={{ fontSize: 18, fontWeight: 900, color: k === 'accepted' ? GREEN : TEXT, marginTop: 4 }}>{n}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'agents' && (
        <div className="cc-panel" style={hubPanel(terminalUi)}>
          <div style={{ fontSize: 10, fontWeight: 800, color: MUTED, letterSpacing: '.06em', textTransform: 'uppercase', marginBottom: 8 }}>
            Agent consumption
          </div>
          <p style={{ fontSize: 10, color: MUTED, lineHeight: 1.5, margin: 0 }}>
            Consumption receipts (AgentConsumptionReceipt@v1) are not yet exposed through this workspace — the
            CIO/Hermes/Advisory subscription wiring is a later wave. This page remains ledger-read-only and never
            calls providers.
          </p>
        </div>
      )}
    </div>
  )
}
