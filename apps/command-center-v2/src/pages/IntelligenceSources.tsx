import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'
import { AddYouTubeChannelModal } from '../components/shared/AddYouTubeChannelModal'

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
  category?: string
  priority?: string
  agent_tags?: string[]
  auto_promote_threshold?: number
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

interface QualifiedItem { id: number; source_type: string; symbol: string; title: string; quality_score: number; retirement_relevance: string; strategy_focus: string; discovered_at: string }
interface QualifiedResp { items: QualifiedItem[] }
interface DiscoveryEntry { id: number; discovery_type: string; title: string; summary: string; symbols_mentioned: string; intel_count: number; created_at: string }
interface DiscoveryResp { entries: DiscoveryEntry[] }

interface SearchSourceInfo { active: boolean; articles?: number; transcripts?: number; series?: number; indexed?: number; status?: string; key_present?: boolean; last?: string; model?: string; dim?: number; calls_today?: number; daily_limit?: number }
interface SearchSourcesResp { [key: string]: SearchSourceInfo }

interface NewsArticle {
  id: number; title: string; symbol: string | null; source: string
  source_url: string; strategy_type: string; retirement_relevance: string
  relevance_score: number; created_at: string
}
interface NewsResp { articles: NewsArticle[]; total: number; page: number }

interface SourcesResp { sources: Source[] }
interface TranscriptsResp { transcripts: Transcript[] }
interface ChannelsResp { channels: Channel[] }
interface SocialPostsResp { posts: SocialPost[] }

type Tab = 'screeners' | 'youtube' | 'social' | 'news' | 'qualified' | 'discovery'

const badge = (text: string, color: string) => (
  <span style={{ fontSize: 9, padding: '2px 6px', borderRadius: 4, background: `${color}22`, color, fontWeight: 700, textTransform: 'uppercase' }}>{text}</span>
)

function statusBadge(validationStatus: string, qualityScore: number) {
  if (validationStatus === 'orphan') return badge('ORPHAN', '#ff4466')
  if (validationStatus === 'ai_validated') return badge('VALIDATED', '#0ecb81')
  if (validationStatus === 'low_confidence') return badge('LOW CONF', '#ff8800')
  if (qualityScore > 0) return badge('TAGGED', '#c4a34f')
  return badge('PENDING', '#5a7fa8')
}

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
  const nav = useNavigate()
  const { data: srcData, loading: srcLoading } = useApi<SourcesResp>('/api/v2/intelligence-sources')
  const [ytCatFilter, setYtCatFilter] = useState('all')
  const ytPath = ytCatFilter !== 'all' ? `/api/v2/youtube/transcripts?limit=500&category=${ytCatFilter}` : '/api/v2/youtube/transcripts?limit=500'
  const { data: ytData, loading: ytLoading } = useApi<TranscriptsResp>(ytPath)
  const { data: chData } = useApi<ChannelsResp>('/api/v2/youtube/channels')
  const { data: socialData, loading: socialLoading } = useApi<SocialPostsResp>('/api/v2/social/posts')
  const { data: socialStatus } = useApi<SocialStatusResp>('/api/v2/social/status')
  const { data: qualData, loading: qualLoading } = useApi<QualifiedResp>('/api/v2/qualified-intelligence')
  const { data: searchSources } = useApi<SearchSourcesResp>('/api/v2/search-sources')
  const { data: discData, loading: discLoading } = useApi<DiscoveryResp>('/api/v2/discovery-log')
  const [newsStratFilter, setNewsStratFilter] = useState('')
  const [newsSourceFilter, setNewsSourceFilter] = useState('')
  const [newsRelFilter, setNewsRelFilter] = useState('')
  const [newsSearch, setNewsSearch] = useState('')
  const [newsPage, setNewsPage] = useState(0)
  const newsParams = [newsStratFilter && `strategy=${newsStratFilter}`, newsSourceFilter && `source=${newsSourceFilter}`, newsRelFilter && `relevance=${newsRelFilter}`, newsSearch && `search=${encodeURIComponent(newsSearch)}`].filter(Boolean).join('&')
  const { data: newsData, loading: newsLoading } = useApi<NewsResp>(`/api/v2/news/articles?limit=50&offset=${newsPage * 50}${newsParams ? '&' + newsParams : ''}`)
  const [tab, setTab] = useState<Tab>('screeners')
  const [filter, setFilter] = useState('')
  const [stratFilter, setStratFilter] = useState<string>('all')
  const [editing, setEditing] = useState<Source | null>(null)
  const [saving, setSaving] = useState(false)
  const [ytUrl, setYtUrl] = useState('')
  const [ytIngesting, setYtIngesting] = useState(false)
  const [ytMsg, setYtMsg] = useState('')
  const [showAddChannel, setShowAddChannel] = useState(false)
  const [ingestAllState, setIngestAllState] = useState<'idle'|'running'|'done'|'error'>('idle')
  const [ingestAllMsg, setIngestAllMsg] = useState('')
  const [ingestingChannel, setIngestingChannel] = useState<string | null>(null)
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

  // Extract distinct categories with counts from channels
  const ytCategories = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const ch of channels) {
      const cat = ch.category || 'uncategorized'
      counts[cat] = (counts[cat] || 0) + 1
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1])
  }, [channels])

  // Channel name set for category-filtered channels (for transcript filtering)
  const filteredChannelNames = useMemo(() => {
    if (ytCatFilter === 'all') return null
    return new Set(channels.filter(ch => (ch.category || 'uncategorized') === ytCatFilter).map(ch => ch.channel_name))
  }, [channels, ytCatFilter])

  const filteredChannels = useMemo(() => {
    let list = channels
    if (ytCatFilter !== 'all') list = list.filter(ch => (ch.category || 'uncategorized') === ytCatFilter)
    if (filter) {
      const q = filter.toLowerCase()
      list = list.filter(ch => ch.channel_name.toLowerCase().includes(q) || (ch.category || '').toLowerCase().includes(q))
    }
    return list
  }, [channels, ytCatFilter, filter])

  const filteredTranscripts = useMemo(() => {
    let list = transcripts
    if (filteredChannelNames) list = list.filter(t => filteredChannelNames.has(t.channel_name))
    if (filter) {
      const q = filter.toLowerCase()
      list = list.filter(t => t.title.toLowerCase().includes(q) || t.channel_name.toLowerCase().includes(q))
    }
    return list
  }, [transcripts, filter, filteredChannelNames])

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

  const handleIngestAll = async () => {
    setIngestAllState('running'); setIngestAllMsg('')
    try {
      const res = await fetch('/api/v2/youtube/ingest-all', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const d = await res.json()
      if (d.ok) {
        setIngestAllState('done'); setIngestAllMsg(d.message || 'Ingest queued')
        setTimeout(() => { setIngestAllState('idle'); setIngestAllMsg('') }, 4000)
      } else { setIngestAllState('error'); setIngestAllMsg(d.error || 'Failed') }
    } catch { setIngestAllState('error'); setIngestAllMsg('Network error') }
  }

  const handleIngestChannel = async (ch: Channel) => {
    if (!ch.channel_url && !ch.channel_name) return
    setIngestingChannel(ch.channel_id)
    try {
      const url = ch.channel_url || `https://www.youtube.com/@${ch.channel_name.replace(/\s+/g, '')}`
      const res = await fetch('/api/v2/youtube/ingest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) })
      const d = await res.json()
      if (d.ok) setYtMsg(`Ingesting ${ch.channel_name}...`)
      else setYtMsg(`Error: ${d.error}`)
    } catch { setYtMsg('Network error') }
    finally { setTimeout(() => setIngestingChannel(null), 2000) }
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

  const qualItems = qualData?.items || []
  const discEntries = discData?.entries || []
  const totalSources = sources.length + transcripts.length + channels.length + socialPosts.length + qualItems.length

  return (
    <>
      <PageHeader title="Intelligence Sources & Screeners" subtitle={`${totalSources} sources configured`} />

      {/* G13: Brave Search credit warning */}
      {searchSources && (() => {
        const brave = (searchSources as any)?.brave_search
        const eff = (searchSources as any)?._efficiency
        const braveDown = brave && (brave.active === false || (brave.status || '').includes('402') || (eff?.brave_calls_today ?? 0) >= (brave.daily_limit ?? 5))
        return braveDown ? (
          <div style={{ padding: '10px 16px', marginBottom: 12, background: 'rgba(246,70,93,0.08)', border: '2px solid rgba(246,70,93,0.3)', borderRadius: 10, fontSize: 12, color: 'var(--red)', fontWeight: 700 }}>
            ⚠️ Brave Search API depleted — {brave.status || 'credit exhausted'}. Market news coverage is reduced; system falls back to Finnhub → RSS → DB embeddings. <a href="https://brave.com/api" target="_blank" rel="noreferrer" style={{ color: 'var(--accent)', textDecoration: 'underline' }}>Add $5 credit at brave.com/api</a> to restore full search.
          </div>
        ) : null
      })()}

      {/* Search Sources Status Strip */}
      {searchSources && (
        <div style={{ display: 'flex', gap: 10, marginBottom: 10, flexWrap: 'wrap', padding: '6px 10px', background: 'var(--bg3)', borderRadius: 8 }}>
          {Object.entries(searchSources).map(([name, info]) => (
            <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 9, color: 'var(--text3)' }}>
              <div style={{ width: 6, height: 6, borderRadius: 99, background: info.active ? '#0ecb81' : '#f6465d' }} />
              <span style={{ fontWeight: 600 }}>{name.replace(/_/g, ' ')}</span>
              {info.articles != null && <span>({info.articles})</span>}
              {info.transcripts != null && <span>({info.transcripts})</span>}
              {info.series != null && <span>({info.series})</span>}
              {info.indexed != null && <span>({info.indexed})</span>}
              {info.calls_today != null && <span style={{ color: 'var(--amber)', fontSize: 8 }}>{info.calls_today}/{info.daily_limit ?? 5}</span>}
              {info.status && <span style={{ color: '#f6465d', fontSize: 8 }}>{info.status}</span>}
            </div>
          ))}
        </div>
      )}

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 12, borderBottom: '1px solid var(--border)' }}>
        {(['screeners', 'youtube', 'social', 'news', 'qualified', 'discovery'] as Tab[]).map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            padding: '8px 16px', fontSize: 11, fontWeight: 700, border: 'none',
            borderBottom: t === tab ? '2px solid #4a90f4' : '2px solid transparent',
            background: 'transparent', color: t === tab ? '#4a90f4' : 'var(--text3)',
            cursor: 'pointer', textTransform: 'uppercase',
          }}>
            {t === 'screeners' ? `Screeners (${sources.length})` : t === 'youtube' ? `YouTube (${transcripts.length})` : t === 'social' ? `Social (${socialPosts.length})` : t === 'news' ? `News (${newsData?.total ?? '...'})` : t === 'qualified' ? `Qualified (${qualItems.length})` : `Discovery (${discEntries.length})`}
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
              <button onClick={() => setShowAddChannel(true)} style={{ ...btnStyle, background: 'rgba(0,255,136,.1)', color: '#00ff88', whiteSpace: 'nowrap' }}>+ Channel</button>
              <button onClick={() => nav('/content-health')} style={{ ...btnStyle, background: 'rgba(170,85,255,.08)', color: '#aa55ff', borderColor: 'rgba(170,85,255,.3)', whiteSpace: 'nowrap' }}>Content Health</button>
              <button onClick={handleIngestAll} disabled={ingestAllState === 'running'}
                style={{ ...btnStyle, marginLeft: 'auto', whiteSpace: 'nowrap',
                  background: ingestAllState === 'done' ? 'rgba(0,255,136,.1)' : ingestAllState === 'error' ? 'rgba(255,68,102,.1)' : 'rgba(170,85,255,.1)',
                  color: ingestAllState === 'done' ? '#00ff88' : ingestAllState === 'error' ? '#ff4466' : '#aa55ff',
                  borderColor: ingestAllState === 'done' ? 'rgba(0,255,136,.3)' : ingestAllState === 'error' ? 'rgba(255,68,102,.3)' : 'rgba(170,85,255,.3)',
                }}>
                {ingestAllState === 'running' ? 'Running...' : ingestAllState === 'done' ? '\u2713 Done' : '\u25B6 Run Ingest'}
              </button>
            </div>
            {ytMsg && <div style={{ fontSize: 10, color: ytMsg.startsWith('Error') ? '#f6465d' : '#0ecb81', marginTop: 4 }}>{ytMsg}</div>}
            {ingestAllMsg && <div style={{ fontSize: 10, color: ingestAllState === 'error' ? '#f6465d' : '#0ecb81', marginTop: 4 }}>{ingestAllMsg}</div>}
          </Card>

          {/* Category filter pills */}
          {ytCategories.length > 0 && (
            <div style={{ display: 'flex', gap: 5, margin: '10px 0 8px', flexWrap: 'wrap' }}>
              <button onClick={() => setYtCatFilter('all')}
                style={{ ...btnStyle, background: ytCatFilter === 'all' ? 'rgba(0,212,255,.12)' : 'transparent', borderColor: ytCatFilter === 'all' ? 'rgba(0,212,255,.4)' : 'var(--border)', color: ytCatFilter === 'all' ? '#00d4ff' : 'var(--text3)' }}>
                All ({channels.length})
              </button>
              {ytCategories.map(([cat, cnt]) => (
                <button key={cat} onClick={() => setYtCatFilter(ytCatFilter === cat ? 'all' : cat)}
                  style={{ ...btnStyle, background: ytCatFilter === cat ? 'rgba(0,212,255,.12)' : 'transparent', borderColor: ytCatFilter === cat ? 'rgba(0,212,255,.4)' : 'var(--border)', color: ytCatFilter === cat ? '#00d4ff' : 'var(--text3)', fontSize: 10 }}>
                  {cat.replace(/_/g, ' ')} ({cnt})
                </button>
              ))}
            </div>
          )}

          {/* Tracked Channels */}
          {filteredChannels.length > 0 && (
            <div style={{ margin: '4px 0 8px', fontSize: 11, color: 'var(--text3)' }}>
              <strong style={{ color: 'var(--text2)' }}>Channels ({filteredChannels.length}):</strong>{' '}
              {filteredChannels.map((ch, i) => (
                <span key={ch.channel_id} style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                  {ch.channel_url ? (
                    <a href={ch.channel_url} target="_blank" rel="noopener noreferrer" style={{ color: '#4a90f4' }}>{ch.channel_name}</a>
                  ) : ch.channel_name}
                  <button onClick={() => handleIngestChannel(ch)} disabled={ingestingChannel === ch.channel_id}
                    title={`Ingest latest from ${ch.channel_name}`}
                    style={{ background: 'none', border: 'none', color: ingestingChannel === ch.channel_id ? 'var(--text3)' : 'var(--accent)', cursor: 'pointer', fontSize: 9, padding: '0 2px', opacity: 0.6 }}
                    onMouseEnter={e => { (e.target as HTMLElement).style.opacity = '1' }}
                    onMouseLeave={e => { (e.target as HTMLElement).style.opacity = '0.6' }}>
                    {ingestingChannel === ch.channel_id ? '\u27F3' : '\u25B6'}
                  </button>
                  {i < filteredChannels.length - 1 ? ' \u00B7 ' : ''}
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
                      <td style={td}>{statusBadge(t.validation_status, t.quality_score)}</td>
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
                      <td style={td}>{statusBadge(p.validation_status, p.quality_score)}</td>
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

      {/* News Tab */}
      {tab === 'news' && (
        <>
          {newsLoading && <div style={{ color: 'var(--text3)', fontSize: 12 }}>Loading news...</div>}
          {/* Filters */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <input placeholder="Search title or symbol..." value={newsSearch} onChange={e => { setNewsSearch(e.target.value); setNewsPage(0) }}
              style={{ ...inputStyle, width: 200 }} />
            <select value={newsStratFilter} onChange={e => { setNewsStratFilter(e.target.value); setNewsPage(0) }}
              style={{ ...inputStyle, width: 160 }}>
              <option value="">All strategies</option>
              {['investment_general','dividend_income','retirement_planning','macro_fed','etf_indexing','bond_income','tax_planning','roth_conversion','high_yield_income_bdc','disability_retirement','401k_rollover','rollover_ira','ssdi','trust_estate'].map(s => (
                <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
              ))}
            </select>
            <select value={newsSourceFilter} onChange={e => { setNewsSourceFilter(e.target.value); setNewsPage(0) }}
              style={{ ...inputStyle, width: 130 }}>
              <option value="">All sources</option>
              {['yahoo_rss','finnhub','google_news','seeking_alpha'].map(s => (
                <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
              ))}
            </select>
            {['high','medium','low'].map(r => {
              const active = newsRelFilter === r
              const color = r === 'high' ? '#00ff88' : r === 'medium' ? '#ffaa00' : '#5a7fa8'
              return (
                <button key={r} onClick={() => { setNewsRelFilter(active ? '' : r); setNewsPage(0) }}
                  style={{ ...btnStyle, background: active ? `${color}18` : 'transparent', borderColor: active ? `${color}60` : 'var(--border)', color: active ? color : 'var(--text3)', fontSize: 10 }}>
                  {r}
                </button>
              )
            })}
            <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--text3)' }}>{newsData?.total ?? 0} articles</span>
          </div>
          {/* Table */}
          <Card>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text3)', textAlign: 'left' }}>
                    <th style={th}>Source</th><th style={th}>Symbol</th><th style={th}>Title</th>
                    <th style={th}>Strategy</th><th style={th}>Relevance</th><th style={th}>Quality</th><th style={th}>Date</th>
                  </tr>
                </thead>
                <tbody>
                  {(newsData?.articles || []).map(a => {
                    const relColor = a.retirement_relevance === 'high' ? '#00ff88' : a.retirement_relevance === 'medium' ? '#ffaa00' : '#5a7fa8'
                    const srcColor = a.source?.includes('yahoo') ? '#4a90f4' : a.source?.includes('finnhub') ? '#aa55ff' : a.source?.includes('google') ? '#00cc88' : '#7a9cc8'
                    return (
                      <tr key={a.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                        <td style={td}>{badge(a.source?.replace(/_/g, ' ').slice(0, 12) || '?', srcColor)}</td>
                        <td style={{ ...td, fontFamily: 'var(--mono)', fontWeight: 700, color: '#c8daf5' }}>{a.symbol || '\u2014'}</td>
                        <td style={td}>
                          {a.source_url ? <a href={a.source_url} target="_blank" rel="noopener noreferrer" style={{ color: '#4a90f4', textDecoration: 'none' }}>{(a.title || '').slice(0, 70)}</a> : (a.title || '').slice(0, 70)}
                        </td>
                        <td style={td}>{badge((a.strategy_type || '').replace(/_/g, ' ').slice(0, 18), '#7a9cc8')}</td>
                        <td style={td}>{badge(a.retirement_relevance || 'low', relColor)}</td>
                        <td style={{ ...td, textAlign: 'right', color: '#7a9cc8' }}>{a.relevance_score ? Number(a.relevance_score).toFixed(0) : '\u2014'}</td>
                        <td style={{ ...td, color: '#5a7fa8', whiteSpace: 'nowrap' }}>{a.created_at?.slice(0, 10) || '\u2014'}</td>
                      </tr>
                    )
                  })}
                  {(newsData?.articles || []).length === 0 && !newsLoading && (
                    <tr><td colSpan={7} style={{ ...td, textAlign: 'center', color: 'var(--text3)', padding: 20 }}>No articles match filters</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            {/* Pagination */}
            {(newsData?.total || 0) > 50 && (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'center', marginTop: 12 }}>
                <button onClick={() => setNewsPage(p => Math.max(0, p - 1))} disabled={newsPage === 0}
                  style={{ ...btnStyle, color: newsPage === 0 ? 'var(--text3)' : '#4a90f4' }}>&laquo; Prev</button>
                <span style={{ fontSize: 10, color: 'var(--text3)' }}>Page {newsPage + 1} of {Math.ceil((newsData?.total || 1) / 50)}</span>
                <button onClick={() => setNewsPage(p => p + 1)} disabled={(newsPage + 1) * 50 >= (newsData?.total || 0)}
                  style={{ ...btnStyle, color: (newsPage + 1) * 50 >= (newsData?.total || 0) ? 'var(--text3)' : '#4a90f4' }}>Next &raquo;</button>
              </div>
            )}
          </Card>
        </>
      )}

      {/* Qualified Intelligence Tab */}
      {tab === 'qualified' && (
        <>
          {qualLoading && <div style={{ color: 'var(--text3)', fontSize: 12 }}>Loading...</div>}
          <Card>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text3)', textAlign: 'left' }}>
                    <th style={th}>Source</th>
                    <th style={th}>Symbol</th>
                    <th style={th}>Title</th>
                    <th style={th}>Quality</th>
                    <th style={th}>Retirement</th>
                    <th style={th}>Strategy</th>
                    <th style={th}>Discovered</th>
                  </tr>
                </thead>
                <tbody>
                  {qualItems.map(q => (
                    <tr key={q.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={td}>{badge(q.source_type?.toUpperCase() || '?', q.source_type === 'sec' ? '#f6465d' : q.source_type === 'news' ? '#0ecb81' : '#4a90f4')}</td>
                      <td style={td}><span style={{ fontWeight: 800, color: 'var(--accent)', fontSize: 12 }}>{q.symbol || '—'}</span></td>
                      <td style={{ ...td, maxWidth: 280 }}><div style={{ fontSize: 10, color: 'var(--text1)', lineHeight: 1.3 }}>{q.title}</div></td>
                      <td style={td}><span style={{ fontSize: 12, fontWeight: 700, color: qualityColor(q.quality_score) }}>{q.quality_score}</span></td>
                      <td style={td}>
                        {q.retirement_relevance === 'high'
                          ? badge('HIGH', '#f6465d')
                          : q.retirement_relevance === 'medium' ? badge('MED', '#c4a34f') : badge('LOW', 'var(--text3)')}
                      </td>
                      <td style={td}><span style={{ fontSize: 9, color: 'var(--text2)' }}>{q.strategy_focus?.replace(/_/g, ' ') || '—'}</span></td>
                      <td style={td}><span style={{ fontSize: 9, color: 'var(--text3)' }}>{q.discovered_at ? new Date(q.discovered_at).toLocaleDateString() : '—'}</span></td>
                    </tr>
                  ))}
                  {qualItems.length === 0 && (
                    <tr><td colSpan={7} style={{ ...td, textAlign: 'center', color: 'var(--text3)' }}>No qualified intelligence yet. The engine promotes high-quality items daily at 7 PM.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}

      {/* Discovery Log Tab */}
      {tab === 'discovery' && (
        <>
          {discLoading && <div style={{ color: 'var(--text3)', fontSize: 12 }}>Loading...</div>}
          {discEntries.length === 0 ? (
            <Card><div style={{ color: 'var(--text3)', fontSize: 11, padding: 16, textAlign: 'center' }}>No discovery summaries yet. The engine generates daily at 7 PM.</div></Card>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {discEntries.map(d => (
                <Card key={d.id}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                    {badge(d.discovery_type?.replace(/_/g, ' ') || 'daily', '#4a90f4')}
                    <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', fontFamily: 'var(--sans)' }}>{d.title}</span>
                    <span style={{ marginLeft: 'auto', fontSize: 9, color: 'var(--text3)' }}>{d.created_at ? new Date(d.created_at).toLocaleDateString() : ''}</span>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.6, whiteSpace: 'pre-wrap', maxHeight: 200, overflowY: 'auto' }}>
                    {d.summary}
                  </div>
                  <div style={{ display: 'flex', gap: 12, marginTop: 8, fontSize: 9, color: 'var(--text3)' }}>
                    {d.intel_count > 0 && <span>{d.intel_count} intel items</span>}
                    {d.symbols_mentioned && <span>Symbols: {d.symbols_mentioned}</span>}
                  </div>
                </Card>
              ))}
            </div>
          )}
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
      <AddYouTubeChannelModal isOpen={showAddChannel} onClose={() => setShowAddChannel(false)} />
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
