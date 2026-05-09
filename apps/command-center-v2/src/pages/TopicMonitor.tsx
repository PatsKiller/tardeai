import { useState, useEffect, useCallback } from 'react'

interface Topic {
  id: number
  topic_id: string
  display_name: string
  search_queries: string[]
  video_queries: string[]
  saved_search_urls: string[]
  priority: number
  agent_owner: string
  agent_tags: string[]
  strategy_tags: string[]
  personal_context: string
  enabled: boolean
  last_searched: string | null
  last_found_count: number
  max_age_days: number
  min_articles: number
  article_count: number
  transcript_count: number
  blocked_count: number
}

interface Transcript {
  id: number
  video_id: string
  title: string
  channel_name: string
  url: string
  quality_score: number
  relevance_score: number
  rag_status: string
  rag_reason: string
  summary: string
  preview: string
  ingested_at: string
  strategy_tags: string[]
}

interface GapFill {
  topic_id: string
  source: string
  query_used: string
  results_found: number
  articles_saved: number
  transcripts_saved: number
  created_at: string
}

const COLORS = {
  bg: '#1A202C', card: '#2D3748', border: '#4A5568',
  text: '#E2E8F0', muted: '#A0AEC0', accent: '#4A90F4',
  green: '#48BB78', red: '#FC8181', orange: '#F6AD55', yellow: '#ECC94B',
}

const cardStyle: React.CSSProperties = {
  background: COLORS.card, borderRadius: 8, padding: 20,
  border: `1px solid ${COLORS.border}`, marginBottom: 16,
}

const btnStyle: React.CSSProperties = {
  background: COLORS.accent, color: '#fff', border: 'none',
  borderRadius: 6, padding: '6px 14px', cursor: 'pointer', fontSize: 13,
}

const inputStyle: React.CSSProperties = {
  background: '#1A202C', color: COLORS.text, border: `1px solid ${COLORS.border}`,
  borderRadius: 6, padding: '8px 12px', fontSize: 13, width: '100%',
}

function StatusBadge({ count, min, label }: { count: number; min: number; label: string }) {
  const ok = count >= min
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 4, fontSize: 12, fontWeight: 600,
      background: ok ? '#2F855A' : '#C53030', color: '#fff', marginRight: 4,
    }}>
      {count} {label}
    </span>
  )
}

function RagBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    approved: '#2F855A', blocked: '#C53030', low_quality: '#C05621', pending: '#4A5568',
  }
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 4, fontSize: 11,
      background: colors[status] || '#4A5568', color: '#fff',
    }}>
      {status}
    </span>
  )
}

export default function TopicMonitor() {
  const [topics, setTopics] = useState<Topic[]>([])
  const [transcripts, setTranscripts] = useState<Transcript[]>([])
  const [gapFills, setGapFills] = useState<GapFill[]>([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<'topics' | 'transcripts' | 'history'>('topics')
  const [selectedTopic, setSelectedTopic] = useState<string>('')
  const [showAddModal, setShowAddModal] = useState(false)
  const [showUrlModal, setShowUrlModal] = useState<string | null>(null)
  const [msg, setMsg] = useState('')

  const loadData = useCallback(() => {
    setLoading(true)
    Promise.all([
      fetch('/api/v2/topics').then(r => r.json()),
      fetch('/api/v2/topics/transcripts').then(r => r.json()),
      fetch('/api/v2/topics/gap-fills').then(r => r.json()),
    ]).then(([t, tr, gf]) => {
      setTopics((t.data || []).filter((x: Topic) => x.enabled !== false))
      setTranscripts(tr.data || [])
      setGapFills(gf.data || [])
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  useEffect(() => { loadData() }, [loadData])

  const runIngestion = (topicId?: string, curate?: boolean) => {
    fetch('/api/v2/topics/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic_id: topicId, curate }),
    }).then(r => r.json()).then(d => {
      setMsg(d.message || 'Started')
      setTimeout(() => setMsg(''), 5000)
    })
  }

  const reviewTranscript = (videoId: string, ragStatus: string, reason: string = '') => {
    fetch('/api/v2/topics/transcripts/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_id: videoId, rag_status: ragStatus, rag_reason: reason }),
    }).then(() => loadData())
  }

  const totalArticles = topics.reduce((s, t) => s + (t.article_count || 0), 0)
  const totalTranscripts = topics.reduce((s, t) => s + (t.transcript_count || 0), 0)
  const gapCount = topics.filter(t => (t.article_count + t.transcript_count) < t.min_articles).length

  if (loading) return <div style={{ padding: 24, color: COLORS.text }}>Loading topics...</div>

  return (
    <div style={{ padding: 24, color: COLORS.text, maxWidth: 1400 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, margin: 0 }}>Topic Monitor</h1>
          <p style={{ color: COLORS.muted, margin: '4px 0 0', fontSize: 13 }}>
            Research topics, saved URLs, transcript quality, gap remediation
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button style={btnStyle} onClick={() => setShowAddModal(true)}>+ Add Topic</button>
          <button style={{ ...btnStyle, background: '#2F855A' }} onClick={() => runIngestion(undefined, true)}>
            Run All (Curated)
          </button>
        </div>
      </div>

      {msg && <div style={{ ...cardStyle, background: '#2F855A', padding: 12, marginBottom: 16 }}>{msg}</div>}

      {/* KPI tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
        {[
          { label: 'Topics', value: topics.length, color: COLORS.accent },
          { label: 'Articles', value: totalArticles, color: COLORS.green },
          { label: 'Transcripts', value: totalTranscripts, color: COLORS.green },
          { label: 'Gaps', value: gapCount, color: gapCount > 0 ? COLORS.red : COLORS.green },
        ].map(kpi => (
          <div key={kpi.label} style={{ ...cardStyle, textAlign: 'center', padding: 16 }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: kpi.color }}>{kpi.value}</div>
            <div style={{ fontSize: 12, color: COLORS.muted }}>{kpi.label}</div>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 16, borderBottom: `1px solid ${COLORS.border}` }}>
        {(['topics', 'transcripts', 'history'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            background: 'none', border: 'none', color: tab === t ? COLORS.accent : COLORS.muted,
            borderBottom: tab === t ? `2px solid ${COLORS.accent}` : '2px solid transparent',
            padding: '10px 20px', cursor: 'pointer', fontSize: 14, fontWeight: tab === t ? 600 : 400,
          }}>
            {t === 'topics' ? 'Topics' : t === 'transcripts' ? 'Transcripts' : 'Search History'}
          </button>
        ))}
      </div>

      {/* TOPICS TAB */}
      {tab === 'topics' && (
        <div>
          {topics.map(topic => (
            <div key={topic.topic_id} style={cardStyle}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <span style={{ fontSize: 16, fontWeight: 600 }}>{topic.display_name}</span>
                    <span style={{ fontSize: 11, color: COLORS.muted, background: COLORS.bg, padding: '2px 6px', borderRadius: 4 }}>
                      P{topic.priority}
                    </span>
                    <span style={{ fontSize: 11, color: COLORS.muted }}>
                      Owner: {topic.agent_owner}
                    </span>
                  </div>
                  <StatusBadge count={topic.article_count || 0} min={topic.min_articles} label="articles" />
                  <StatusBadge count={topic.transcript_count || 0} min={1} label="transcripts" />
                  {(topic.blocked_count || 0) > 0 && (
                    <span style={{ fontSize: 11, color: COLORS.red, marginLeft: 8 }}>
                      {topic.blocked_count} blocked
                    </span>
                  )}
                  <div style={{ fontSize: 12, color: COLORS.muted, marginTop: 6 }}>
                    Queries: {(topic.search_queries || []).slice(0, 2).join(' | ')}
                  </div>
                  {(topic.saved_search_urls || []).length > 0 && (
                    <div style={{ fontSize: 12, color: COLORS.accent, marginTop: 2 }}>
                      {topic.saved_search_urls.length} saved search URLs
                    </div>
                  )}
                  {topic.last_searched && (
                    <div style={{ fontSize: 11, color: COLORS.muted, marginTop: 2 }}>
                      Last searched: {new Date(topic.last_searched).toLocaleDateString()} (found {topic.last_found_count})
                    </div>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                  <button style={{ ...btnStyle, fontSize: 12, padding: '4px 10px' }}
                    onClick={() => runIngestion(topic.topic_id)}>
                    Run
                  </button>
                  <button style={{ ...btnStyle, fontSize: 12, padding: '4px 10px', background: '#6B46C1' }}
                    onClick={() => runIngestion(topic.topic_id, true)}>
                    Curate
                  </button>
                  <button style={{ ...btnStyle, fontSize: 12, padding: '4px 10px', background: '#4A5568' }}
                    onClick={() => setShowUrlModal(topic.topic_id)}>
                    + URL
                  </button>
                  <button style={{ ...btnStyle, fontSize: 12, padding: '4px 10px', background: '#4A5568' }}
                    onClick={() => { setSelectedTopic(topic.topic_id); setTab('transcripts') }}>
                    View
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* TRANSCRIPTS TAB */}
      {tab === 'transcripts' && (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <select value={selectedTopic} onChange={e => setSelectedTopic(e.target.value)}
              style={{ ...inputStyle, width: 200 }}>
              <option value="">All Topics</option>
              {topics.map(t => <option key={t.topic_id} value={t.topic_id}>{t.display_name}</option>)}
            </select>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${COLORS.border}` }}>
                <th style={{ textAlign: 'left', padding: '8px 6px', color: COLORS.muted }}>Title</th>
                <th style={{ textAlign: 'left', padding: '8px 6px', color: COLORS.muted }}>Channel</th>
                <th style={{ textAlign: 'center', padding: '8px 6px', color: COLORS.muted }}>Quality</th>
                <th style={{ textAlign: 'center', padding: '8px 6px', color: COLORS.muted }}>RAG</th>
                <th style={{ textAlign: 'left', padding: '8px 6px', color: COLORS.muted }}>Summary</th>
                <th style={{ textAlign: 'center', padding: '8px 6px', color: COLORS.muted }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {transcripts
                .filter(t => !selectedTopic || (t.strategy_tags || []).toString().includes(selectedTopic)
                  || t.title.toLowerCase().includes(selectedTopic.replace(/_/g, ' ')))
                .map(t => (
                  <tr key={t.video_id} style={{ borderBottom: `1px solid ${COLORS.border}` }}>
                    <td style={{ padding: '8px 6px', maxWidth: 280 }}>
                      <a href={t.url} target="_blank" rel="noopener" style={{ color: COLORS.accent, textDecoration: 'none' }}>
                        {t.title?.substring(0, 60)}
                      </a>
                      <div style={{ fontSize: 11, color: COLORS.muted }}>
                        {t.ingested_at ? new Date(t.ingested_at).toLocaleDateString() : ''}
                      </div>
                    </td>
                    <td style={{ padding: '8px 6px', fontSize: 12, color: COLORS.muted }}>{t.channel_name}</td>
                    <td style={{ padding: '8px 6px', textAlign: 'center' }}>{t.quality_score}</td>
                    <td style={{ padding: '8px 6px', textAlign: 'center' }}>
                      <RagBadge status={t.rag_status || 'pending'} />
                    </td>
                    <td style={{ padding: '8px 6px', fontSize: 12, color: COLORS.muted, maxWidth: 250 }}>
                      {(t.summary || t.preview || '').substring(0, 100)}
                    </td>
                    <td style={{ padding: '8px 6px', textAlign: 'center' }}>
                      <div style={{ display: 'flex', gap: 4, justifyContent: 'center' }}>
                        <button onClick={() => reviewTranscript(t.video_id, 'approved')}
                          style={{ ...btnStyle, padding: '2px 8px', fontSize: 11, background: '#2F855A' }}>RAG</button>
                        <button onClick={() => reviewTranscript(t.video_id, 'blocked', 'Not relevant')}
                          style={{ ...btnStyle, padding: '2px 8px', fontSize: 11, background: '#C53030' }}>Block</button>
                      </div>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          {transcripts.length === 0 && (
            <div style={{ padding: 40, textAlign: 'center', color: COLORS.muted }}>No transcripts yet</div>
          )}
        </div>
      )}

      {/* SEARCH HISTORY TAB */}
      {tab === 'history' && (
        <div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${COLORS.border}` }}>
                <th style={{ textAlign: 'left', padding: '8px 6px', color: COLORS.muted }}>Topic</th>
                <th style={{ textAlign: 'left', padding: '8px 6px', color: COLORS.muted }}>Source</th>
                <th style={{ textAlign: 'left', padding: '8px 6px', color: COLORS.muted }}>Query</th>
                <th style={{ textAlign: 'center', padding: '8px 6px', color: COLORS.muted }}>Found</th>
                <th style={{ textAlign: 'center', padding: '8px 6px', color: COLORS.muted }}>Saved</th>
                <th style={{ textAlign: 'left', padding: '8px 6px', color: COLORS.muted }}>When</th>
              </tr>
            </thead>
            <tbody>
              {gapFills.map((gf, i) => (
                <tr key={i} style={{ borderBottom: `1px solid ${COLORS.border}` }}>
                  <td style={{ padding: '8px 6px' }}>{gf.topic_id}</td>
                  <td style={{ padding: '8px 6px', fontSize: 12 }}>{gf.source}</td>
                  <td style={{ padding: '8px 6px', fontSize: 12, color: COLORS.muted, maxWidth: 300 }}>
                    {gf.query_used?.substring(0, 80)}
                  </td>
                  <td style={{ padding: '8px 6px', textAlign: 'center' }}>{gf.results_found}</td>
                  <td style={{ padding: '8px 6px', textAlign: 'center' }}>
                    {gf.articles_saved}a / {gf.transcripts_saved}t
                  </td>
                  <td style={{ padding: '8px 6px', fontSize: 11, color: COLORS.muted }}>
                    {gf.created_at ? new Date(gf.created_at).toLocaleString() : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ADD URL MODAL */}
      {showUrlModal && (
        <UrlModal topicId={showUrlModal} onClose={() => setShowUrlModal(null)} onSaved={loadData} />
      )}

      {/* ADD TOPIC MODAL */}
      {showAddModal && (
        <AddTopicModal onClose={() => setShowAddModal(false)} onSaved={loadData} />
      )}
    </div>
  )
}

function UrlModal({ topicId, onClose, onSaved }: { topicId: string; onClose: () => void; onSaved: () => void }) {
  const [url, setUrl] = useState('')
  const [saving, setSaving] = useState(false)

  const save = () => {
    setSaving(true)
    fetch('/api/v2/topics/add-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic_id: topicId, url }),
    }).then(r => r.json()).then(() => {
      setSaving(false)
      onSaved()
      onClose()
    })
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div style={{ background: COLORS.card, borderRadius: 12, padding: 24, width: 500, border: `1px solid ${COLORS.border}` }}>
        <h3 style={{ margin: '0 0 16px', color: COLORS.text }}>Add Search URL to "{topicId}"</h3>
        <p style={{ fontSize: 13, color: COLORS.muted, marginBottom: 12 }}>
          Paste a Google Video search URL (udm=7). The query will be extracted and used for YouTube API search.
        </p>
        <input style={inputStyle} placeholder="https://www.google.com/search?udm=7&q=..." value={url}
          onChange={e => setUrl(e.target.value)} />
        <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
          <button style={{ ...btnStyle, background: COLORS.border }} onClick={onClose}>Cancel</button>
          <button style={btnStyle} onClick={save} disabled={saving || !url.trim()}>
            {saving ? 'Saving...' : 'Add URL'}
          </button>
        </div>
      </div>
    </div>
  )
}

function AddTopicModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    topic_id: '', display_name: '', priority: 5, agent_owner: 'Alex',
    search_queries: '', video_queries: '', personal_context: '',
  })
  const [saving, setSaving] = useState(false)

  const save = () => {
    setSaving(true)
    const body = {
      ...form,
      search_queries: form.search_queries.split('\n').filter(Boolean),
      video_queries: form.video_queries.split('\n').filter(Boolean),
    }
    fetch('/api/v2/topics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => r.json()).then(() => {
      setSaving(false)
      onSaved()
      onClose()
    })
  }

  const f = (field: string, value: string | number) => setForm(prev => ({ ...prev, [field]: value }))

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div style={{ background: COLORS.card, borderRadius: 12, padding: 24, width: 550, border: `1px solid ${COLORS.border}`, maxHeight: '80vh', overflowY: 'auto' }}>
        <h3 style={{ margin: '0 0 16px', color: COLORS.text }}>Add Research Topic</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <label style={{ fontSize: 12, color: COLORS.muted }}>Topic ID (lowercase, underscores)</label>
            <input style={inputStyle} placeholder="ssdi_ny_trusts" value={form.topic_id}
              onChange={e => f('topic_id', e.target.value)} />
          </div>
          <div>
            <label style={{ fontSize: 12, color: COLORS.muted }}>Display Name</label>
            <input style={inputStyle} placeholder="SSDI NY Trusts" value={form.display_name}
              onChange={e => f('display_name', e.target.value)} />
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: 12, color: COLORS.muted }}>Priority (1=highest)</label>
              <input style={inputStyle} type="number" value={form.priority}
                onChange={e => f('priority', parseInt(e.target.value) || 5)} />
            </div>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: 12, color: COLORS.muted }}>Agent Owner</label>
              <select style={inputStyle} value={form.agent_owner} onChange={e => f('agent_owner', e.target.value)}>
                <option>Alex</option><option>Steph</option><option>Maria</option><option>Aegis</option>
              </select>
            </div>
          </div>
          <div>
            <label style={{ fontSize: 12, color: COLORS.muted }}>Search Queries (one per line)</label>
            <textarea style={{ ...inputStyle, height: 80, fontFamily: 'monospace' }}
              placeholder={"SSDI trust asset protection NY\nspecial needs trust New York medicaid"}
              value={form.search_queries} onChange={e => f('search_queries', e.target.value)} />
          </div>
          <div>
            <label style={{ fontSize: 12, color: COLORS.muted }}>YouTube Queries (one per line)</label>
            <textarea style={{ ...inputStyle, height: 80, fontFamily: 'monospace' }}
              placeholder={"SSDI trust protection explained\nspecial needs trust NY planning"}
              value={form.video_queries} onChange={e => f('video_queries', e.target.value)} />
          </div>
          <div>
            <label style={{ fontSize: 12, color: COLORS.muted }}>Personal Context (for LLM curation)</label>
            <input style={inputStyle} placeholder="Age 58, SSDI, NY resident, MFS filing..."
              value={form.personal_context} onChange={e => f('personal_context', e.target.value)} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 20, justifyContent: 'flex-end' }}>
          <button style={{ ...btnStyle, background: COLORS.border }} onClick={onClose}>Cancel</button>
          <button style={btnStyle} onClick={save} disabled={saving || !form.topic_id.trim()}>
            {saving ? 'Saving...' : 'Add Topic'}
          </button>
        </div>
      </div>
    </div>
  )
}
