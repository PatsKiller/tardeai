import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { useTerminalUi } from '../lib/terminalUi'
import { hubTitle, hubSubtitle, hubTab, hubPanel, hubStrip } from '../lib/terminalHubChrome'

type Tab = 'events' | 'deliveries' | 'subjects' | 'retention' | 'agents'

const MUTED = 'var(--text3)'
const TEXT = 'var(--text0)'
const AMBER = 'var(--amber)'
const GREEN = 'var(--green)'
const BORDER = 'var(--border)'

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

export default function CommunicationsHub() {
  const [terminalUi] = useTerminalUi()
  const [tab, setTab] = useState<Tab>('events')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [subjectFilter, setSubjectFilter] = useState('')

  const eventsPath = useMemo(() => {
    const q = new URLSearchParams({ limit: '100' })
    if (subjectFilter.trim()) q.set('subject_key', subjectFilter.trim())
    return `/api/v2/communications/events?${q.toString()}`
  }, [subjectFilter])

  const { data: health, loading: healthLoading } = useApi<any>('/api/v2/communications/health', 60_000)
  const { data: eventsPayload, loading: eventsLoading, error: eventsError } = useApi<any>(eventsPath, 30_000)
  const { data: deliveriesPayload, loading: deliveriesLoading } = useApi<any>(
    '/api/v2/communications/deliveries?limit=200',
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

  const retentionCounts = useMemo(() => {
    const byClass: Record<string, number> = {}
    for (const e of events) {
      const rc = e.retention_class || 'unknown'
      byClass[rc] = (byClass[rc] || 0) + 1
    }
    return byClass
  }, [events])

  return (
    <div style={{ maxWidth: 1200 }}>
      <div className="hub-title-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={hubTitle()}>Communications</div>
          <div style={hubSubtitle(terminalUi)}>
            CommunicationEvent ledger · ChannelDelivery stubs · subject threads
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

      <div
        className="cc-panel"
        style={{
          ...hubStrip(terminalUi),
          marginTop: 12,
          marginBottom: 14,
          borderColor: deliveryOwned ? GREEN : AMBER,
          color: TEXT,
          fontWeight: 700,
        }}
        role="status"
      >
        Ledger-backed · gateway does not own delivery while OFF/SHADOW
        {!deliveryOwned && (
          <span style={{ color: MUTED, fontWeight: 600 }}>
            {' '}
            · delivery_owned=false · mode={mode}
          </span>
        )}
      </div>

      {tab === 'events' && (
        <div style={{ display: 'grid', gridTemplateColumns: selectedId ? '1fr 340px' : '1fr', gap: 12 }}>
          <div className="cc-panel" style={hubPanel(terminalUi)}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 10, color: MUTED, fontWeight: 800, letterSpacing: '.06em', textTransform: 'uppercase' }}>
                Events ({events.length})
              </span>
              <input
                value={subjectFilter}
                onChange={(e) => setSubjectFilter(e.target.value)}
                placeholder="Filter subject_key"
                style={{
                  fontSize: 10,
                  padding: '3px 8px',
                  background: 'var(--bg1)',
                  border: `1px solid ${BORDER}`,
                  borderRadius: 2,
                  color: TEXT,
                  minWidth: 180,
                }}
              />
              {eventsError && <span style={{ color: 'var(--red)', fontSize: 10 }}>{eventsError}</span>}
              {eventsLoading && <span style={{ color: MUTED, fontSize: 10 }}>Loading…</span>}
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                <thead>
                  <tr style={{ color: MUTED, textAlign: 'left' }}>
                    <th style={{ padding: '4px 6px' }}>event_id</th>
                    <th style={{ padding: '4px 6px' }}>type</th>
                    <th style={{ padding: '4px 6px' }}>subject_key</th>
                    <th style={{ padding: '4px 6px' }}>severity</th>
                    <th style={{ padding: '4px 6px' }}>producer</th>
                    <th style={{ padding: '4px 6px' }}>created_at</th>
                    <th style={{ padding: '4px 6px' }}>curation</th>
                  </tr>
                </thead>
                <tbody>
                  {events.length === 0 && !eventsLoading && (
                    <tr>
                      <td colSpan={7} style={{ padding: 12, color: MUTED }}>
                        No ledger events ({source}). Portal never scrapes providers.
                      </td>
                    </tr>
                  )}
                  {events.map((e) => {
                    const active = e.event_id === selectedId
                    return (
                      <tr
                        key={e.event_id}
                        onClick={() => setSelectedId(e.event_id)}
                        style={{
                          cursor: 'pointer',
                          background: active ? 'rgba(245,158,11,0.12)' : 'transparent',
                          borderTop: `1px solid ${BORDER}`,
                        }}
                      >
                        <td style={{ padding: '5px 6px', fontFamily: 'ui-monospace, monospace', color: TEXT }} title={e.event_id}>
                          {shortId(e.event_id)}
                        </td>
                        <td style={{ padding: '5px 6px', color: TEXT }}>{e.event_type || e.type || '—'}</td>
                        <td style={{ padding: '5px 6px', color: MUTED }} title={e.subject_key}>{shortId(e.subject_key, 18)}</td>
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
                <button
                  type="button"
                  onClick={() => setSelectedId(null)}
                  style={{ fontSize: 10, border: `1px solid ${BORDER}`, background: 'transparent', color: MUTED, cursor: 'pointer', padding: '2px 6px' }}
                >
                  Close
                </button>
              </div>
              {!detail ? (
                <div style={{ color: MUTED, fontSize: 10 }}>Loading {shortId(selectedId)}…</div>
              ) : (
                <dl style={{ margin: 0, fontSize: 10, lineHeight: 1.55 }}>
                  {(
                    [
                      ['event_id', detail.event_id],
                      ['type', detail.event_type || detail.type],
                      ['message_class', detail.message_class],
                      ['subject_key', detail.subject_key],
                      ['severity', detail.severity],
                      ['producer', detail.producer],
                      ['direction', detail.direction],
                      ['curation_mode', detail.curation_mode],
                      ['retention_class', detail.retention_class],
                      ['knowledge_status', detail.knowledge_status],
                      ['created_at', fmtWhen(detail.created_at)],
                      ['short_summary', detail.short_summary],
                      ['source', detail.source],
                    ] as [string, any][]
                  ).map(([k, v]) => (
                    <div key={k} style={{ display: 'grid', gridTemplateColumns: '110px 1fr', gap: 6, borderBottom: `1px solid ${BORDER}`, padding: '4px 0' }}>
                      <dt style={{ color: MUTED }}>{k}</dt>
                      <dd style={{ margin: 0, color: TEXT, wordBreak: 'break-word' }}>{v == null || v === '' ? '—' : String(v)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          )}
        </div>
      )}

      {tab === 'deliveries' && (
        <div className="cc-panel" style={hubPanel(terminalUi)}>
          <div style={{ fontSize: 10, color: MUTED, fontWeight: 800, marginBottom: 10, letterSpacing: '.06em', textTransform: 'uppercase' }}>
            Deliveries ({deliveries.length}){deliveriesLoading ? ' · loading…' : ''} · source {deliveriesPayload?.source || '—'}
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
              <thead>
                <tr style={{ color: MUTED, textAlign: 'left' }}>
                  <th style={{ padding: '4px 6px' }}>delivery_id</th>
                  <th style={{ padding: '4px 6px' }}>event_id</th>
                  <th style={{ padding: '4px 6px' }}>channel</th>
                  <th style={{ padding: '4px 6px' }}>status</th>
                  <th style={{ padding: '4px 6px' }}>reserved_at</th>
                </tr>
              </thead>
              <tbody>
                {deliveries.length === 0 && !deliveriesLoading && (
                  <tr>
                    <td colSpan={5} style={{ padding: 12, color: MUTED }}>
                      No delivery rows (RESERVED stubs appear after publish).
                    </td>
                  </tr>
                )}
                {deliveries.map((d) => (
                  <tr key={d.delivery_id || `${d.event_id}-${d.channel}`} style={{ borderTop: `1px solid ${BORDER}` }}>
                    <td style={{ padding: '5px 6px', fontFamily: 'ui-monospace, monospace' }} title={d.delivery_id}>{shortId(d.delivery_id)}</td>
                    <td style={{ padding: '5px 6px', fontFamily: 'ui-monospace, monospace', cursor: 'pointer', color: AMBER }} onClick={() => { setSelectedId(d.event_id); setTab('events') }} title={d.event_id}>{shortId(d.event_id)}</td>
                    <td style={{ padding: '5px 6px' }}>{d.channel || '—'}</td>
                    <td style={{ padding: '5px 6px' }}>{d.status || '—'}</td>
                    <td style={{ padding: '5px 6px', color: MUTED }}>{fmtWhen(d.reserved_at)}</td>
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
                  <th style={{ padding: '4px 6px' }}>subject_key</th>
                  <th style={{ padding: '4px 6px' }}>domain</th>
                  <th style={{ padding: '4px 6px' }}>events</th>
                  <th style={{ padding: '4px 6px' }}>last_activity</th>
                </tr>
              </thead>
              <tbody>
                {subjects.length === 0 && !subjectsLoading && (
                  <tr>
                    <td colSpan={4} style={{ padding: 12, color: MUTED }}>No subjects yet.</td>
                  </tr>
                )}
                {subjects.map((s) => (
                  <tr
                    key={s.subject_key}
                    style={{ borderTop: `1px solid ${BORDER}`, cursor: 'pointer' }}
                    onClick={() => { setSubjectFilter(s.subject_key || ''); setTab('events') }}
                  >
                    <td style={{ padding: '5px 6px', color: TEXT }}>{s.subject_key}</td>
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
            Retention (placeholder counts from visible ledger window)
          </div>
          <p style={{ fontSize: 10, color: MUTED, marginTop: 0, lineHeight: 1.5 }}>
            Librarian execution is Phase 6 — this tab shows retention_class rollups only. No purge from the UI.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 8 }}>
            {Object.keys(retentionCounts).length === 0 && (
              <div style={{ fontSize: 10, color: MUTED }}>No events in current projection.</div>
            )}
            {Object.entries(retentionCounts).map(([k, n]) => (
              <div key={k} style={{ padding: 10, border: `1px solid ${BORDER}`, borderRadius: 2 }}>
                <div style={{ fontSize: 10, color: MUTED, textTransform: 'uppercase', fontWeight: 800 }}>{k}</div>
                <div style={{ fontSize: 18, fontWeight: 900, color: TEXT, marginTop: 4 }}>{n}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'agents' && (
        <div className="cc-panel" style={hubPanel(terminalUi)}>
          <div style={{ fontSize: 10, fontWeight: 800, color: MUTED, letterSpacing: '.06em', textTransform: 'uppercase', marginBottom: 8 }}>
            Agent consumption (placeholder)
          </div>
          <p style={{ fontSize: 10, color: MUTED, lineHeight: 1.5, margin: 0 }}>
            Phase 8 consumption receipts are not wired into this workspace yet. This page remains ledger-read-only and does not call providers.
          </p>
        </div>
      )}
    </div>
  )
}
