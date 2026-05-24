import { useState, useEffect, useCallback } from 'react'

interface ResearchTopic {
  id: number
  topic: string
  priority: string
  status: string
  latest_findings: string | null
  latest_finding_at: string | null
  research_count: number
  last_researched_at: string | null
  original_message: string | null
  source: string | null
  created_at: string
  updated_at: string
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

function PriorityBadge({ priority }: { priority: string }) {
  const bg = priority === 'high' ? '#C53030' : priority === 'normal' ? '#2B6CB0' : '#4A5568'
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 4, fontSize: 11,
      fontWeight: 600, background: bg, color: '#fff', textTransform: 'uppercase',
    }}>
      {priority}
    </span>
  )
}

function timeAgo(iso: string | null): string {
  if (!iso) return 'never'
  const diff = Date.now() - new Date(iso).getTime()
  const hrs = Math.floor(diff / 3600000)
  if (hrs < 1) return `${Math.floor(diff / 60000)}m ago`
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

function FindingsBlock({ findings }: { findings: string }) {
  const [expanded, setExpanded] = useState(false)
  const isLong = findings.length > 600
  const display = !isLong || expanded ? findings : findings.slice(0, 600) + '…'

  // Parse sections from the findings text
  const sections = display.split(/\n{2,}/)

  return (
    <div style={{ marginTop: 12 }}>
      {sections.map((section, i) => {
        const isHeading = /^#+\s|^\d+\.\s+(What|Specific|Account)/i.test(section.trim())
        return (
          <p key={i} style={{
            margin: '8px 0', fontSize: 13, lineHeight: 1.6,
            color: isHeading ? COLORS.text : COLORS.muted,
            fontWeight: isHeading ? 600 : 400,
          }}>
            {section.trim()}
          </p>
        )
      })}
      {isLong && (
        <button
          onClick={() => setExpanded(v => !v)}
          style={{
            background: 'none', border: 'none', color: COLORS.accent,
            cursor: 'pointer', fontSize: 12, padding: 0, marginTop: 4,
          }}
        >
          {expanded ? 'Show less' : 'Show full findings'}
        </button>
      )}
    </div>
  )
}

export default function ResearchTopics() {
  const [topics, setTopics] = useState<ResearchTopic[]>([])
  const [monitorTopics, setMonitorTopics] = useState<any[]>([])
  const [gaps, setGaps] = useState<any[]>([])
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'high' | 'normal'>('all')

  const fetchTopics = useCallback(async () => {
    try {
      const res = await fetch('/api/v2/research-topics')
      if (!res.ok) throw new Error(`API ${res.status}`)
      const data = await res.json()
      const d = data.data || data
      setTopics(d.user_topics || d.topics || [])
      setMonitorTopics(d.monitor_topics || [])
      setGaps(d.research_gaps || [])
      setNote(d.note || '')
      setError(null)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchTopics()
    const iv = setInterval(fetchTopics, 60000)
    return () => clearInterval(iv)
  }, [fetchTopics])

  const filtered = filter === 'all' ? topics : topics.filter(t => t.priority === filter)
  const highCount = topics.filter(t => t.priority === 'high').length
  const totalIterations = topics.reduce((s, t) => s + (t.research_count || 0), 0)

  return (
    <div style={{ padding: 24, maxWidth: 1100, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h1 style={{ color: COLORS.text, fontSize: 22, margin: 0 }}>Research Topics</h1>
          <p style={{ color: COLORS.muted, fontSize: 13, margin: '4px 0 0' }}>
            Persistent research advisories — iterated daily by LLM
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ color: COLORS.muted, fontSize: 12 }}>
            {topics.length} advisories &middot; {monitorTopics.length} monitor topics &middot; {gaps.length} gaps
            {highCount > 0 && <> &middot; <span style={{ color: COLORS.orange }}>{highCount} high priority</span></>}
          </span>
        </div>
      </div>

      {/* Filter bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {(['all', 'high', 'normal'] as const).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{
              background: filter === f ? COLORS.accent : COLORS.card,
              color: '#fff', border: `1px solid ${filter === f ? COLORS.accent : COLORS.border}`,
              borderRadius: 6, padding: '5px 14px', cursor: 'pointer', fontSize: 12,
              textTransform: 'capitalize',
            }}
          >
            {f === 'all' ? `All (${topics.length})` : `${f} (${topics.filter(t => t.priority === f).length})`}
          </button>
        ))}
        <button
          onClick={fetchTopics}
          style={{
            marginLeft: 'auto', background: 'none', border: `1px solid ${COLORS.border}`,
            color: COLORS.muted, borderRadius: 6, padding: '5px 14px', cursor: 'pointer', fontSize: 12,
          }}
        >
          Refresh
        </button>
      </div>

      {loading && <p style={{ color: COLORS.muted }}>Loading research topics...</p>}
      {error && <p style={{ color: COLORS.red }}>Error: {error}</p>}

      {filtered.map(topic => (
        <div key={topic.id} style={cardStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                <h2 style={{ color: COLORS.text, fontSize: 16, margin: 0 }}>{topic.topic}</h2>
                <PriorityBadge priority={topic.priority || 'normal'} />
                <span style={{
                  fontSize: 11, color: COLORS.accent, fontWeight: 600,
                  background: 'rgba(74,144,244,0.12)', padding: '2px 8px', borderRadius: 4,
                }}>
                  Iteration #{topic.research_count || 0}
                </span>
              </div>

              <div style={{ display: 'flex', gap: 16, fontSize: 12, color: COLORS.muted }}>
                <span>Last researched: <strong style={{ color: COLORS.text }}>{timeAgo(topic.last_researched_at)}</strong></span>
                <span>Updated: <strong style={{ color: COLORS.text }}>{timeAgo(topic.updated_at)}</strong></span>
                {topic.source && <span>Source: <strong style={{ color: COLORS.text }}>{topic.source}</strong></span>}
              </div>
            </div>
          </div>

          {topic.latest_findings ? (
            <FindingsBlock findings={topic.latest_findings} />
          ) : (
            <p style={{ color: COLORS.muted, fontSize: 13, marginTop: 12, fontStyle: 'italic' }}>
              No findings yet — next iteration pending.
            </p>
          )}

          {topic.latest_finding_at && (
            <div style={{
              marginTop: 12, paddingTop: 8, borderTop: `1px solid ${COLORS.border}`,
              fontSize: 11, color: COLORS.muted,
            }}>
              Finding generated: {new Date(topic.latest_finding_at).toLocaleString()}
            </div>
          )}
        </div>
      ))}

      {!loading && filtered.length === 0 && (
        <div style={{ ...cardStyle, textAlign: 'center', padding: 40 }}>
          <p style={{ color: COLORS.muted, fontSize: 14 }}>
            {filter !== 'all' ? `No ${filter}-priority topics found.` : 'No active research advisories. Send "research <topic>" via Telegram to create one.'}
          </p>
        </div>
      )}

      {/* Topic Monitor Library */}
      {monitorTopics.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <h2 style={{ color: COLORS.text, fontSize: 16, marginBottom: 12 }}>
            Topic Monitor Library ({monitorTopics.length} topics)
          </h2>
          <p style={{ color: COLORS.muted, fontSize: 11, marginBottom: 12 }}>{note}</p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 10 }}>
            {monitorTopics.map((t: any) => (
              <div key={t.topic_id} style={{ ...cardStyle, padding: 12, marginBottom: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: COLORS.text, fontSize: 12, fontWeight: 600 }}>{t.display_name}</span>
                  <span style={{ fontSize: 10, color: COLORS.muted }}>{t.article_count} articles / {t.transcript_count} transcripts</span>
                </div>
                <div style={{ fontSize: 10, color: COLORS.muted, marginTop: 4 }}>
                  Last searched: {t.last_searched ? timeAgo(t.last_searched) : 'never'}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Research Gaps */}
      {gaps.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <h2 style={{ color: COLORS.red, fontSize: 16, marginBottom: 12 }}>
            Research Gaps ({gaps.length})
          </h2>
          {gaps.map((g: any, i: number) => (
            <div key={i} style={{ ...cardStyle, padding: 12, marginBottom: 8, borderColor: COLORS.red + '44' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ color: COLORS.text, fontSize: 12, fontWeight: 600 }}>{g.display_name}</span>
                <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 3, background: COLORS.red + '22', color: COLORS.red }}>{g.reason}</span>
              </div>
              <div style={{ fontSize: 10, color: COLORS.muted, marginTop: 4 }}>
                Last searched: {g.last_searched ? timeAgo(g.last_searched) : 'never'}
                {g.age_days && <> — {g.age_days} days stale</>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
