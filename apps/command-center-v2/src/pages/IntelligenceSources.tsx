import { useState, useMemo } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

interface Source {
  screener_id: string
  display_name: string
  strategy_type: string
  finviz_url: string
  description: string
  keywords: string
  sources: string[] | null
  added_by: string
  schedule: string
  active: boolean
  last_run: string | null
  results_count: number
  created_at: string
  updated_at: string | null
}

interface Transcript {
  id: number
  video_id: string
  title: string
  channel_name: string
  publish_date: string | null
  url: string
  duration_seconds: number
  quality_score: number
  relevance_score: number
  validation_status: string
  matched_keywords: string[]
  added_by: string
  ingested_at: string
}

interface Channel {
  id: number
  channel_id: string
  channel_name: string
  channel_url: string
  strategy_focus: string
  added_by: string
  active: boolean
  created_at: string
}

interface SocialPost {
  id: number
  platform: string
  post_id: string
  username: string
  display_name: string
  text: string
  post_date: string
  url: string
  followers: number
  verified: boolean
  likes: number
  retweets: number
  replies: number
  quality_score: number
  relevance_score: number
  validation_status: string
  matched_keywords: string[]
  sentiment: string
  sentiment_score: number
  added_by: string
  ingested_at: string
}

interface SocialStatusResp { apis: Record<string, { configured: boolean; env_var: string; label: string }>; total_posts: number }

interface SourcesResp { sources: Source[] }
interface TranscriptsResp { transcripts: Transcript[] }
interface ChannelsResp { channels: Channel[] }
interface SocialPostsResp { posts: SocialPost[] }

type Tab = 'screeners' | 'youtube' | 'social'

const badge = (text: string, color: string) => (
  <span style={{ fontSize: 9, padding: '2px 6px', borderRadius: 4, background: `${color}22`, color, fontWeight: 700, textTransform: 'uppercase' }}>{text}</span>
)

function qualityColor(score: number) {
  if (score >= 70) return '#0ecb81'
  if (score >= 40) return '#c4a34f'
  return '#f6465d'
}

function fmtDuration(sec: number) {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

export default function IntelligenceSources() {
  const { data: srcData, loading: srcLoading } = useApi<SourcesResp>('/api/v2/intelligence-sources')
  const { data: ytData, loading: ytLoading } = useApi<TranscriptsResp>('/api/v2/youtube/transcripts')
  const { data: chData } = useApi<ChannelsResp>('/api/v2/youtube/channels')
  const { data: socialData, loading: socialLoading } = useApi<SocialPostsResp>('/api/v2/social/posts')
  const { data: socialStatus } = useApi<SocialStatusResp>('/api/v2/social/status')
  const [tab, setTab] = useState<Tab>('screeners')
  const [filter, setFilter] = useState('')
  const [stratFilter, setStratFilter] = useState<string>('all')
  const [editing, setEditing] = useState<Source | null>(null)
  const [saving, setSaving] = useState(false)
  const [ytUrl, setYtUrl] = useState('')
  const [ytIngesting, setYtIngesting] = useState(false)
  const [ytMsg, setYtMsg] = useState('')
  const [socialText, setSocialText] = useState('')
  const [socialUser, setSocialUser] = useState('')
  const [socialSaving, setSocialSaving] = useState(false)
  const [socialMsg, setSocialMsg] = useState('')

  // Screeners data
  const sources = srcData?.sources || []
  const strategies = useMemo(() => ['all', ...Array.from(new Set(sources.map(s => s.strategy_type).filter(Boolean))).sort()], [sources])
  const filteredSources = useMemo(() => {
    let list = sources
    if (stratFilter !== 'all') list = list.filter(s => s.strategy_type === stratFilter)
    if (filter) {
      const q = filter.toLowerCase()
      list = list.filter(s =>
        s.display_name.toLowerCase().includes(q) ||
        s.keywords?.toLowerCase().includes(q) ||
        s.strategy_type.toLowerCase().includes(q) ||
        s.screener_id.toLowerCase().includes(q)
      )
    }
    return list
  }, [sources, filter, stratFilter])

  // YouTube data
  const transcripts = ytData?.transcripts || []
  const channels = chData?.channels || []
  const filteredTranscripts = useMemo(() => {
    if (!filter) return transcripts
    const q = filter.toLowerCase()
    return transcripts.filter(t =>
      t.title.toLowerCase().includes(q) ||
      t.channel_name.toLowerCase().includes(q)
    )
  }, [transcripts, filter])

  // Social data
  const socialPosts = socialData?.posts || []
  const filteredPosts = useMemo(() => {
    if (!filter) return socialPosts
    const q = filter.toLowerCase()
    return socialPosts.filter(p =>
      p.text.toLowerCase().includes(q) ||
      p.username.toLowerCase().includes(q)
    )
  }, [socialPosts, filter])

  const handleSave = async (src: Source) => {
    setSaving(true)
    try {
      await fetch('/api/v2/intelligence-sources', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          screener_id: src.screener_id, display_name: src.display_name,
          strategy_type: src.strategy_type, finviz_url: src.finviz_url,
          description: src.description, keywords: src.keywords,
          sources: src.sources || [], added_by: src.added_by,
          schedule: src.schedule, active: src.active,
        })
      })
      setEditing(null)
      window.location.reload()
    } finally { setSaving(false) }
  }

  const handleYtIngest = async () => {
    if (!ytUrl.trim()) return
    setYtIngesting(true)
    setYtMsg('')
    try {
      const resp = await fetch('/api/v2/youtube/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: ytUrl.trim(), added_by: 'user' })
      })
      const data = await resp.json()
      if (data.ok) {
        setYtMsg(`Ingested: ${data.title || data.video_id} (Q:${data.quality_score} R:${data.relevance_score})`)
        setYtUrl('')
        setTimeout(() => window.location.reload(), 1500)
      } else {
        setYtMsg(`Error: ${data.error}`)
      }
    } catch (e: unknown) {
      setYtMsg(`Failed: ${e instanceof Error ? e.message : String(e)}`)
    } finally { setYtIngesting(false) }
  }

  const handleSocialIngest = async () => {
    if (!socialText.trim()) return
    setSocialSaving(true)
    setSocialMsg('')
    try {
      const resp = await fetch('/api/v2/social/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: socialText.trim(), username: socialUser.trim(), platform: 'x', added_by: 'user' })
      })
      const data = await resp.json()
      if (data.ok) {
        setSocialMsg(`Scored: Q:${data.quality_score} R:${data.relevance_score} [${data.validation_status}] ${data.sentiment}`)
        setSocialText('')
        setSocialUser('')
        setTimeout(() => window.location.reload(), 1500)
      } else {
        setSocialMsg(`Error: ${data.error}`)
      }
    } catch (e: unknown) {
      setSocialMsg(`Failed: ${e instanceof Error ? e.message : String(e)}`)
    } finally { setSocialSaving(false) }
  }

  const totalSources = sources.length + transcripts.length + channels.length + socialPosts.length

  return (
    <>
      <PageHeader title="Intelligence Sources & Screeners" subtitle={`${totalSources} sources configured`} />

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 12, borderBottom: '1px solid var(--border)' }}>
        {(['screeners', 'youtube', 'social'] as Tab[]).map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            padding: '8px 16px', fontSize: 11, fontWeight: 700, border: 'none',
            borderBottom: t === tab ? '2px solid #4a90f4' : '2px solid transparent',
            background: 'transparent', color: t === tab ? '#4a90f4' : 'var(--text3)',
            cursor: 'pointer', textTransform: 'uppercase',
          }}>
            {t === 'screeners' ? `Screeners (${sources.length})` : t === 'youtube' ? `YouTube (${transcripts.length})` : `Social (${socialPosts.length})`}
          </button>
        ))}
      </div>

      {/* Shared filter */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <input placeholder="Search..." value={filter} onChange={e => setFilter(e.target.value)} style={inputStyle} />
        {tab === 'screeners' && (
          <select value={stratFilter} onChange={e => setStratFilter(e.target.value)} style={{ ...inputStyle, width: 180 }}>
            {strategies.map(s => <option key={s} value={s}>{s === 'all' ? 'All Strategies' : s.replace(/_/g, ' ')}</option>)}
          </select>
        )}
      </div>

      {/* Screeners Tab */}
      {tab === 'screeners' && (
        <>
          {srcLoading && <div style={{ color: 'var(--text3)', fontSize: 12 }}>Loading...</div>}
          <Card>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text3)', textAlign: 'left' }}>
                    <th style={th}>Name</th>
                    <th style={th}>Strategy</th>
                    <th style={th}>Finviz URL</th>
                    <th style={th}>Keywords</th>
                    <th style={th}>Sources</th>
                    <th style={th}>Added By</th>
                    <th style={th}>Schedule</th>
                    <th style={th}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredSources.map(s => (
                    <tr key={s.screener_id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={td}>
                        <div style={{ fontWeight: 700, color: 'var(--text1)' }}>{s.display_name}</div>
                        <div style={{ fontSize: 9, color: 'var(--text3)' }}>{s.screener_id}</div>
                      </td>
                      <td style={td}>{badge(s.strategy_type?.replace(/_/g, ' ') || '—', '#4a90f4')}</td>
                      <td style={td}>
                        {s.finviz_url ? (
                          <a href={s.finviz_url} target="_blank" rel="noopener noreferrer" style={{ color: '#0ecb81', fontSize: 10 }}>Open Screener</a>
                        ) : '—'}
                      </td>
                      <td style={{ ...td, maxWidth: 180 }}>
                        <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.4 }}>{s.keywords || '—'}</div>
                      </td>
                      <td style={td}>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
                          {(s.sources || []).map((src, i) => (
                            <span key={i} style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, background: 'rgba(255,255,255,.06)', color: 'var(--text2)' }}>{src}</span>
                          ))}
                          {(!s.sources || s.sources.length === 0) && <span style={{ color: 'var(--text3)', fontSize: 9 }}>—</span>}
                        </div>
                      </td>
                      <td style={td}>
                        {s.added_by === 'ai' ? badge('AI', '#f6465d') : badge('User', '#0ecb81')}
                        {s.created_at && <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 2 }}>{new Date(s.created_at).toLocaleDateString()}</div>}
                      </td>
                      <td style={td}>{badge(s.schedule || 'daily', '#c4a34f')}</td>
                      <td style={td}>
                        <button onClick={() => setEditing({ ...s })} style={btnStyle}>Edit</button>
                      </td>
                    </tr>
                  ))}
                  {filteredSources.length === 0 && (
                    <tr><td colSpan={8} style={{ ...td, textAlign: 'center', color: 'var(--text3)' }}>No sources match filter</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}

      {/* YouTube Tab */}
      {tab === 'youtube' && (
        <>
          {ytLoading && <div style={{ color: 'var(--text3)', fontSize: 12 }}>Loading...</div>}

          {/* Ingest form */}
          <Card>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 0' }}>
              <input
                placeholder="Paste YouTube URL to ingest..."
                value={ytUrl}
                onChange={e => setYtUrl(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleYtIngest()}
                style={{ ...inputStyle, flex: 1 }}
              />
              <button onClick={handleYtIngest} disabled={ytIngesting || !ytUrl.trim()} style={{ ...btnStyle, background: 'rgba(74,144,244,.15)', color: '#4a90f4', whiteSpace: 'nowrap' }}>
                {ytIngesting ? 'Ingesting...' : 'Ingest'}
              </button>
            </div>
            {ytMsg && <div style={{ fontSize: 10, color: ytMsg.startsWith('Error') ? '#f6465d' : '#0ecb81', marginTop: 4 }}>{ytMsg}</div>}
          </Card>

          {/* Tracked Channels */}
          {channels.length > 0 && (
            <div style={{ margin: '12px 0 8px', fontSize: 11, color: 'var(--text3)' }}>
              <strong style={{ color: 'var(--text2)' }}>Tracked Channels:</strong>{' '}
              {channels.map((ch, i) => (
                <span key={ch.channel_id}>
                  {ch.channel_url ? (
                    <a href={ch.channel_url} target="_blank" rel="noopener noreferrer" style={{ color: '#4a90f4' }}>{ch.channel_name}</a>
                  ) : ch.channel_name}
                  {ch.strategy_focus ? ` (${ch.strategy_focus.replace(/_/g, ' ')})` : ''}
                  {i < channels.length - 1 ? ' · ' : ''}
                </span>
              ))}
            </div>
          )}

          {/* Transcripts table */}
          <Card>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text3)', textAlign: 'left' }}>
                    <th style={th}>Channel</th>
                    <th style={th}>Title</th>
                    <th style={th}>Duration</th>
                    <th style={th}>Quality</th>
                    <th style={th}>Relevance</th>
                    <th style={th}>Status</th>
                    <th style={th}>Keywords</th>
                    <th style={th}>Added By</th>
                    <th style={th}>Ingested</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTranscripts.map(t => (
                    <tr key={t.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={td}>
                        <div style={{ fontWeight: 700, color: 'var(--text1)', fontSize: 10 }}>{t.channel_name || '—'}</div>
                      </td>
                      <td style={{ ...td, maxWidth: 220 }}>
                        <a href={t.url} target="_blank" rel="noopener noreferrer" style={{ color: '#4a90f4', fontSize: 10, lineHeight: 1.3, display: 'block' }}>
                          {t.title}
                        </a>
                      </td>
                      <td style={td}><span style={{ fontSize: 10, color: 'var(--text2)' }}>{fmtDuration(t.duration_seconds)}</span></td>
                      <td style={td}>
                        <span style={{ fontSize: 11, fontWeight: 700, color: qualityColor(t.quality_score) }}>{t.quality_score}</span>
                      </td>
                      <td style={td}>
                        <span style={{ fontSize: 11, fontWeight: 700, color: qualityColor(t.relevance_score * 100) }}>{(t.relevance_score * 100).toFixed(0)}%</span>
                      </td>
                      <td style={td}>{badge(t.validation_status, t.validation_status === 'ai_validated' ? '#0ecb81' : t.validation_status === 'low_confidence' ? '#f6465d' : '#c4a34f')}</td>
                      <td style={td}>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
                          {(t.matched_keywords || []).slice(0, 5).map((kw, i) => (
                            <span key={i} style={{ fontSize: 8, padding: '1px 4px', borderRadius: 3, background: 'rgba(74,144,244,.1)', color: '#4a90f4' }}>{kw}</span>
                          ))}
                        </div>
                      </td>
                      <td style={td}>{t.added_by === 'ai' ? badge('AI', '#f6465d') : badge('User', '#0ecb81')}</td>
                      <td style={td}><span style={{ fontSize: 9, color: 'var(--text3)' }}>{new Date(t.ingested_at).toLocaleDateString()}</span></td>
                    </tr>
                  ))}
                  {filteredTranscripts.length === 0 && (
                    <tr><td colSpan={9} style={{ ...td, textAlign: 'center', color: 'var(--text3)' }}>
                      No transcripts ingested yet. Paste a YouTube URL above to get started.
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}

      {/* Social Media Tab */}
      {tab === 'social' && (
        <>
          {socialLoading && <div style={{ color: 'var(--text3)', fontSize: 12 }}>Loading...</div>}

          {/* API Status */}
          {socialStatus && (
            <Card>
              <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 8 }}>
                <strong style={{ color: 'var(--text2)' }}>API Status:</strong>{' '}
                {Object.entries(socialStatus.apis || {}).map(([name, info]) => (
                  <span key={name} style={{ marginRight: 12 }}>
                    {info.label}: {info.configured ? badge('ACTIVE', '#0ecb81') : badge('NOT SET', '#f6465d')}
                  </span>
                ))}
              </div>
              {/* Manual ingest form */}
              <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
                <div style={{ flex: 1 }}>
                  <input placeholder="Paste post text..." value={socialText} onChange={e => setSocialText(e.target.value)} style={inputStyle} />
                </div>
                <div style={{ width: 120 }}>
                  <input placeholder="@username" value={socialUser} onChange={e => setSocialUser(e.target.value)} style={inputStyle} />
                </div>
                <button onClick={handleSocialIngest} disabled={socialSaving || !socialText.trim()} style={{ ...btnStyle, background: 'rgba(74,144,244,.15)', color: '#4a90f4', whiteSpace: 'nowrap' }}>
                  {socialSaving ? 'Scoring...' : 'Score & Save'}
                </button>
              </div>
              {socialMsg && <div style={{ fontSize: 10, color: socialMsg.startsWith('Error') ? '#f6465d' : '#0ecb81', marginTop: 4 }}>{socialMsg}</div>}
            </Card>
          )}

          {/* Posts table */}
          <Card>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text3)', textAlign: 'left' }}>
                    <th style={th}>Platform</th>
                    <th style={th}>User</th>
                    <th style={th}>Post</th>
                    <th style={th}>Quality</th>
                    <th style={th}>Relevance</th>
                    <th style={th}>Sentiment</th>
                    <th style={th}>Status</th>
                    <th style={th}>Engagement</th>
                    <th style={th}>Added By</th>
                    <th style={th}>Date</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredPosts.map(p => (
                    <tr key={p.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={td}>{badge(p.platform.toUpperCase(), '#4a90f4')}</td>
                      <td style={td}>
                        <div style={{ fontWeight: 700, color: 'var(--text1)', fontSize: 10 }}>@{p.username || '—'}</div>
                        {p.verified && <span style={{ fontSize: 8, color: '#4a90f4' }}>verified</span>}
                      </td>
                      <td style={{ ...td, maxWidth: 260 }}>
                        {p.url ? (
                          <a href={p.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--text2)', fontSize: 10, lineHeight: 1.3, display: 'block' }}>
                            {p.text.slice(0, 120)}{p.text.length > 120 ? '...' : ''}
                          </a>
                        ) : (
                          <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.3 }}>
                            {p.text.slice(0, 120)}{p.text.length > 120 ? '...' : ''}
                          </div>
                        )}
                        {(p.matched_keywords || []).length > 0 && (
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 2, marginTop: 3 }}>
                            {p.matched_keywords.slice(0, 4).map((kw, i) => (
                              <span key={i} style={{ fontSize: 8, padding: '1px 4px', borderRadius: 3, background: 'rgba(74,144,244,.1)', color: '#4a90f4' }}>{kw}</span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td style={td}><span style={{ fontSize: 11, fontWeight: 700, color: qualityColor(p.quality_score) }}>{p.quality_score}</span></td>
                      <td style={td}><span style={{ fontSize: 11, fontWeight: 700, color: qualityColor(p.relevance_score * 100) }}>{(p.relevance_score * 100).toFixed(0)}%</span></td>
                      <td style={td}>
                        {badge(p.sentiment, p.sentiment === 'positive' ? '#0ecb81' : p.sentiment === 'negative' ? '#f6465d' : '#c4a34f')}
                      </td>
                      <td style={td}>{badge(p.validation_status, p.validation_status === 'ai_validated' ? '#0ecb81' : p.validation_status === 'low_confidence' ? '#f6465d' : '#c4a34f')}</td>
                      <td style={td}>
                        <div style={{ fontSize: 9, color: 'var(--text3)', lineHeight: 1.6 }}>
                          {p.likes > 0 && <span>{p.likes} likes</span>}
                          {p.retweets > 0 && <span> · {p.retweets} RT</span>}
                          {p.replies > 0 && <span> · {p.replies} replies</span>}
                          {!p.likes && !p.retweets && !p.replies && '—'}
                        </div>
                      </td>
                      <td style={td}>{p.added_by === 'ai' ? badge('AI', '#f6465d') : badge('User', '#0ecb81')}</td>
                      <td style={td}><span style={{ fontSize: 9, color: 'var(--text3)' }}>{new Date(p.ingested_at).toLocaleDateString()}</span></td>
                    </tr>
                  ))}
                  {filteredPosts.length === 0 && (
                    <tr><td colSpan={10} style={{ ...td, textAlign: 'center', color: 'var(--text3)' }}>
                      No social posts yet. Configure API keys or paste posts manually above.
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}

      {/* Edit Modal (screeners) */}
      {editing && (
        <div style={overlay} onClick={() => setEditing(null)}>
          <div style={modal} onClick={e => e.stopPropagation()}>
            <h3 style={{ margin: '0 0 12px', fontSize: 14, color: 'var(--text1)' }}>Edit: {editing.display_name}</h3>
            <div style={{ display: 'grid', gap: 8 }}>
              <label style={labelStyle}>Display Name
                <input value={editing.display_name} onChange={e => setEditing({ ...editing, display_name: e.target.value })} style={inputStyle} />
              </label>
              <label style={labelStyle}>Strategy Type
                <input value={editing.strategy_type} onChange={e => setEditing({ ...editing, strategy_type: e.target.value })} style={inputStyle} />
              </label>
              <label style={labelStyle}>Finviz URL
                <input value={editing.finviz_url} onChange={e => setEditing({ ...editing, finviz_url: e.target.value })} style={inputStyle} />
              </label>
              <label style={labelStyle}>Keywords
                <input value={editing.keywords || ''} onChange={e => setEditing({ ...editing, keywords: e.target.value })} style={inputStyle} placeholder="dividend growth, yield >2%, payout <60%" />
              </label>
              <label style={labelStyle}>Sources (comma-separated)
                <input value={(editing.sources || []).join(', ')} onChange={e => setEditing({ ...editing, sources: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })} style={inputStyle} placeholder="Finviz, FMP API, Seeking Alpha" />
              </label>
              <label style={labelStyle}>Added By
                <select value={editing.added_by || 'user'} onChange={e => setEditing({ ...editing, added_by: e.target.value })} style={inputStyle}>
                  <option value="user">User</option>
                  <option value="ai">AI</option>
                </select>
              </label>
              <label style={labelStyle}>Schedule
                <select value={editing.schedule || 'daily'} onChange={e => setEditing({ ...editing, schedule: e.target.value })} style={inputStyle}>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="manual">Manual</option>
                </select>
              </label>
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 14, justifyContent: 'flex-end' }}>
              <button onClick={() => setEditing(null)} style={{ ...btnStyle, color: 'var(--text3)' }}>Cancel</button>
              <button onClick={() => handleSave(editing)} disabled={saving} style={{ ...btnStyle, background: 'rgba(74,144,244,.15)', color: '#4a90f4' }}>
                {saving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

const inputStyle: React.CSSProperties = {
  fontSize: 11, padding: '6px 10px', borderRadius: 6,
  border: '1px solid var(--border)', background: 'var(--bg-card)',
  color: 'var(--text1)', width: '100%', boxSizing: 'border-box',
}
const th: React.CSSProperties = { padding: '8px 6px', fontSize: 10, fontWeight: 700, whiteSpace: 'nowrap' }
const td: React.CSSProperties = { padding: '8px 6px', verticalAlign: 'top' }
const btnStyle: React.CSSProperties = {
  fontSize: 10, padding: '4px 10px', borderRadius: 4,
  border: '1px solid var(--border)', background: 'transparent',
  color: 'var(--text2)', cursor: 'pointer',
}
const overlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
}
const modal: React.CSSProperties = {
  background: 'var(--bg-card)', borderRadius: 12, padding: 20,
  width: 440, maxHeight: '80vh', overflowY: 'auto',
  border: '1px solid var(--border)', boxShadow: '0 20px 60px rgba(0,0,0,.4)',
}
const labelStyle: React.CSSProperties = { fontSize: 10, color: 'var(--text3)', display: 'flex', flexDirection: 'column', gap: 3 }
