import { useState, useEffect, useCallback } from 'react'
import AdminConfirmModal, { type PendingAction } from './AdminConfirmModal'

// Research Topic Registry management modal (2026-06-04).
// Manages topic_monitor as the system-of-record: add/edit/delete/pause topics + keywords, and
// map each to an owner (tradeai | hermes | shared). All writes route through the guarded
// admin_write path (preview -> confirm -> admin_audit_log) via AdminConfirmModal.

interface Topic {
  topic_id: string; display_name: string; owner: string; priority: number; enabled: boolean
  search_queries: string[]; video_queries: string[]; max_age_days: number; min_articles: number
  last_searched: string | null; last_found_count: number
}

const OWNER_COLOR: Record<string, string> = { tradeai: '#60a5fa', hermes: '#a855f7', shared: '#22c55e' }
const OWNER_LABEL: Record<string, string> = { tradeai: 'TradeAI', hermes: 'Hermes', shared: 'Shared (both)' }
const blank = (): Topic => ({ topic_id: '', display_name: '', owner: 'shared', priority: 5, enabled: true,
  search_queries: [], video_queries: [], max_age_days: 30, min_articles: 3, last_searched: null, last_found_count: 0 })

const ageDays = (iso: string | null) => iso ? Math.floor((Date.now() - new Date(iso).getTime()) / 86400000) : null

export default function ResearchTopicsModal({ onClose }: { onClose: () => void }) {
  const [topics, setTopics] = useState<Topic[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<Topic | null>(null)
  const [isNew, setIsNew] = useState(false)
  const [pending, setPending] = useState<PendingAction | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetch('/api/v2/research-topics/registry')
      const d = await r.json()
      if (d.ok) setTopics(d.data.topics || [])
    } catch { /* */ }
    setLoading(false)
  }, [])
  useEffect(() => { load() }, [load])

  const saveTopic = (t: Topic) => {
    if (!t.topic_id.trim()) return
    setPending({
      path: '/api/v2/admin/topic/upsert',
      label: `${isNew ? 'Add' : 'Edit'} topic "${t.topic_id}"`,
      body: { topic_id: t.topic_id, display_name: t.display_name, owner: t.owner, priority: t.priority,
        enabled: t.enabled, search_queries: t.search_queries, video_queries: t.video_queries,
        max_age_days: t.max_age_days, min_articles: t.min_articles },
    })
  }
  const toggle = (t: Topic) => setPending({ path: '/api/v2/admin/topic/toggle',
    label: `${t.enabled ? 'Pause' : 'Enable'} "${t.topic_id}"`, body: { topic_id: t.topic_id, enabled: !t.enabled } })
  const del = (t: Topic) => setPending({ path: '/api/v2/admin/topic/delete',
    label: `DELETE topic "${t.topic_id}"`, body: { topic_id: t.topic_id } })

  const overlay: React.CSSProperties = { position: 'fixed', inset: 0, zIndex: 9990, display: 'flex',
    alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.7)' }
  const panel: React.CSSProperties = { background: 'rgba(16,20,28,0.97)', backdropFilter: 'blur(16px)',
    border: '1px solid rgba(255,255,255,0.08)', borderRadius: 12, width: '95vw', maxWidth: 920,
    maxHeight: '90vh', overflow: 'auto', padding: 22 }
  const input: React.CSSProperties = { width: '100%', background: 'var(--bg2)', border: '1px solid var(--border)',
    borderRadius: 6, padding: '6px 9px', color: 'var(--text0)', fontSize: 12, boxSizing: 'border-box' }
  const lbl: React.CSSProperties = { fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 3 }

  return (
    <div style={overlay} onClick={onClose}>
      <div style={panel} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
          <div style={{ fontSize: 17, fontWeight: 800, color: 'var(--text0)' }}>Research Topic Registry</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text2)', fontSize: 20, cursor: 'pointer' }}>×</button>
        </div>
        <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 14 }}>
          System-of-record over <code>topic_monitor</code>. Owner routes which engine researches the topic.
          Edits are guarded (preview → confirm → audit log).
        </div>

        {/* ── EDIT / ADD FORM ── */}
        {editing ? (
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 14 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 12 }}>
              {isNew ? 'Add topic' : `Edit: ${editing.display_name || editing.topic_id}`}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
              <div>
                <div style={lbl}>topic_id (key)</div>
                <input style={{ ...input, opacity: isNew ? 1 : 0.6 }} value={editing.topic_id} disabled={!isNew}
                  onChange={e => setEditing({ ...editing, topic_id: e.target.value.toLowerCase().replace(/\s+/g, '_') })} />
              </div>
              <div>
                <div style={lbl}>Display name</div>
                <input style={input} value={editing.display_name} onChange={e => setEditing({ ...editing, display_name: e.target.value })} />
              </div>
              <div>
                <div style={lbl}>Owner (maps to engine)</div>
                <select style={input} value={editing.owner} onChange={e => setEditing({ ...editing, owner: e.target.value })}>
                  <option value="tradeai">TradeAI only</option>
                  <option value="hermes">Hermes only</option>
                  <option value="shared">Shared (both)</option>
                </select>
              </div>
              <div style={{ display: 'flex', gap: 10 }}>
                <div style={{ flex: 1 }}>
                  <div style={lbl}>Priority (1=top)</div>
                  <input type="number" style={input} value={editing.priority} onChange={e => setEditing({ ...editing, priority: parseInt(e.target.value) || 5 })} />
                </div>
                <div style={{ flex: 1 }}>
                  <div style={lbl}>Min articles</div>
                  <input type="number" style={input} value={editing.min_articles} onChange={e => setEditing({ ...editing, min_articles: parseInt(e.target.value) || 3 })} />
                </div>
                <label style={{ display: 'flex', alignItems: 'flex-end', gap: 4, fontSize: 11, color: 'var(--text2)', paddingBottom: 6 }}>
                  <input type="checkbox" checked={editing.enabled} onChange={e => setEditing({ ...editing, enabled: e.target.checked })} /> enabled
                </label>
              </div>
            </div>
            {editing.owner === 'hermes' && (
              <div style={{ fontSize: 10, color: '#a855f7', marginBottom: 10 }}>
                Hermes-only: researched by Hermes (via the topic bridge → hermes_research_intelligence), not TradeAI's topic_ingestion.
              </div>
            )}
            {editing.owner === 'shared' && (
              <div style={{ fontSize: 10, color: '#22c55e', marginBottom: 10 }}>
                Shared: researched by BOTH — TradeAI (topic_ingestion) and Hermes (topic bridge).
              </div>
            )}
            <div style={{ marginBottom: 10 }}>
              <div style={lbl}>Search queries (one per line)</div>
              <textarea style={{ ...input, minHeight: 64, fontFamily: 'var(--mono)' }} value={editing.search_queries.join('\n')}
                onChange={e => setEditing({ ...editing, search_queries: e.target.value.split('\n') })} />
            </div>
            <div style={{ marginBottom: 12 }}>
              <div style={lbl}>Video queries (one per line)</div>
              <textarea style={{ ...input, minHeight: 48, fontFamily: 'var(--mono)' }} value={editing.video_queries.join('\n')}
                onChange={e => setEditing({ ...editing, video_queries: e.target.value.split('\n') })} />
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={() => setEditing(null)} style={{ background: 'var(--bg2)', color: 'var(--text2)', border: '1px solid var(--border)', borderRadius: 6, padding: '7px 14px', fontSize: 12, cursor: 'pointer' }}>Cancel</button>
              <button onClick={() => saveTopic({ ...editing, search_queries: editing.search_queries.filter(Boolean), video_queries: editing.video_queries.filter(Boolean) })}
                disabled={!editing.topic_id.trim()} style={{ background: editing.topic_id.trim() ? '#1d4ed8' : 'var(--bg2)', color: '#fff', border: 0, borderRadius: 6, padding: '7px 16px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>Save (guarded)</button>
            </div>
          </div>
        ) : (
          <button onClick={() => { setEditing(blank()); setIsNew(true) }}
            style={{ background: 'rgba(96,165,250,.15)', color: '#60a5fa', border: '1px solid rgba(96,165,250,.3)', borderRadius: 6, padding: '6px 14px', fontSize: 12, cursor: 'pointer', marginBottom: 14 }}>+ Add topic</button>
        )}

        {/* ── TOPIC LIST ── */}
        {loading ? <div style={{ color: 'var(--text3)', fontSize: 12 }}>Loading…</div> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ fontSize: 11, color: 'var(--text3)' }}>{topics.length} topics</div>
            {topics.map(t => {
              const age = ageDays(t.last_searched)
              const stale = age === null || age > 3
              return (
                <div key={t.topic_id} style={{ display: 'flex', alignItems: 'center', gap: 10, background: 'var(--bg1)',
                  border: '1px solid var(--border)', borderRadius: 8, padding: '8px 12px', opacity: t.enabled ? 1 : 0.55 }}>
                  <span style={{ width: 7, height: 7, borderRadius: 4, background: t.enabled ? '#22c55e' : '#6b7280', flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text0)' }}>{t.display_name || t.topic_id}</div>
                    <div style={{ fontSize: 10, color: 'var(--text3)' }}>
                      {t.topic_id} · {t.search_queries?.length || 0} queries · last {age === null ? 'never' : `${age}d ago`}
                      {stale && <span style={{ color: '#f59e0b' }}> · stale</span>}
                    </div>
                  </div>
                  <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 10,
                    background: `${OWNER_COLOR[t.owner] || '#888'}22`, color: OWNER_COLOR[t.owner] || '#888' }}>{OWNER_LABEL[t.owner] || t.owner}</span>
                  <button onClick={() => { setEditing({ ...t, search_queries: t.search_queries || [], video_queries: t.video_queries || [] }); setIsNew(false) }}
                    style={{ background: 'var(--bg2)', color: 'var(--text2)', border: '1px solid var(--border)', borderRadius: 5, padding: '3px 9px', fontSize: 10, cursor: 'pointer' }}>Edit</button>
                  <button onClick={() => toggle(t)} style={{ background: 'var(--bg2)', color: 'var(--text2)', border: '1px solid var(--border)', borderRadius: 5, padding: '3px 9px', fontSize: 10, cursor: 'pointer' }}>{t.enabled ? 'Pause' : 'Enable'}</button>
                  <button onClick={() => del(t)} style={{ background: 'rgba(239,68,68,.12)', color: '#ef4444', border: '1px solid rgba(239,68,68,.3)', borderRadius: 5, padding: '3px 9px', fontSize: 10, cursor: 'pointer' }}>Del</button>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Guarded write — preview → confirm → audit (reuses the proven admin_write path) */}
      <AdminConfirmModal action={pending} onClose={() => setPending(null)}
        onDone={() => { setPending(null); setEditing(null); load() }} />
    </div>
  )
}
